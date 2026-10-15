"""Who started a sandbox build: read from the Jenkins build API when a run is opened.

The Jenkins server uses an internal CA, so JENKINS_CA_BUNDLE can point to its certificate. TLS
verification stays on (the certificate is trusted explicitly, hostname still checked).
"""
import logging
import ssl
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

from .config import Settings

log = logging.getLogger("ghost.jenkins")

_FOUND: dict[str, str] = {}  # the starter of a finished build request never changes
_FAILED: dict[str, float] = {}  # url -> time of last failure (retry after FAIL_TTL)
FAIL_TTL = 300.0
TIMEOUT = 5.0


class _PinnedAdapter(HTTPAdapter):
    """Trust the given certificate file even if it is a leaf (its CA is not available)."""

    def __init__(self, cafile: str):
        self._cafile = cafile
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context(cafile=self._cafile)
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _user_from_json(data: dict) -> str | None:
    for action in data.get("actions", []):
        for cause in action.get("causes", []) or []:
            if cause.get("userName"):
                return str(cause["userName"])
    return None


def fetch_started_by(build_url: str | None, settings: Settings, session: requests.Session | None = None) -> str | None:
    """User name of the "Started by user" cause of a Jenkins build, or None if unknown/unreachable."""
    if not build_url:
        return None
    u = urlparse(build_url)
    if u.scheme not in ("http", "https") or "/job/" not in u.path:
        return None
    if build_url in _FOUND:
        return _FOUND[build_url] or None
    if time.monotonic() - _FAILED.get(build_url, -FAIL_TTL) < FAIL_TTL:
        return None
    url = build_url.rstrip("/") + "/api/json?tree=actions[causes[userName]]"
    try:
        if session is None:
            session = requests.Session()
            if settings.jenkins_ca_bundle:
                session.mount("https://", _PinnedAdapter(settings.jenkins_ca_bundle))
        r = session.get(url, timeout=TIMEOUT, verify=True if settings.jenkins_ca_bundle else settings.jira_verify)
        r.raise_for_status()
        user = _user_from_json(r.json())
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read Jenkins build %s: %s", build_url, exc)
        _FAILED[build_url] = time.monotonic()
        return None
    _FOUND[build_url] = user or ""  # a build with no user cause is cached too
    return user
