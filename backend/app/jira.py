import logging
import time
from datetime import datetime
from typing import Iterator

import requests

from .config import Settings

log = logging.getLogger("ghost.jira")

RETRY_STATUSES = (502, 503, 504)


def parse_jira_time(value: str) -> datetime:
    """Jira timestamps look like 2026-10-13T01:51:43.000+0530."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(value)


class JiraClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None,
                 attempts: int = 4, backoff: float = 2.0, sleep=time.sleep):
        self.attempts = attempts
        self.backoff = backoff
        self._sleep = sleep
        self.base = settings.jira_base_url
        self.verify = settings.jira_verify  # CA bundle path or bool; never forced to False
        self.session = session or requests.Session()
        if settings.jira_client_cert:  # mutual TLS: server demands a client certificate
            self.session.cert = (
                (settings.jira_client_cert, settings.jira_client_key)
                if settings.jira_client_key else settings.jira_client_cert
            )
        if settings.jira_token:  # optional: the client certificate alone can authenticate
            self.session.headers["Authorization"] = "Bearer %s" % settings.jira_token
        self.session.headers["Accept"] = "application/json"

    def _get(self, path: str, **params):
        """GET with a few retries for dropped connections, timeouts and 502/503/504."""
        for attempt in range(1, self.attempts + 1):
            try:
                r = self.session.get(
                    self.base + path, params=params or None, verify=self.verify, timeout=60
                )
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError,
                    requests.HTTPError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                transient = not isinstance(exc, requests.HTTPError) or status in RETRY_STATUSES  # not 401/403/404
                if not transient or attempt == self.attempts:
                    raise
                delay = self.backoff * 2 ** (attempt - 1)
                log.warning("Jira request failed (%s), retry %d/%d in %.0fs: %s", path, attempt,
                            self.attempts - 1, delay, str(exc)[:120])
                self._sleep(delay)

    def iter_comments(self, ticket: str, page_size: int = 100) -> Iterator[dict]:
        start = 0
        while True:
            data = self._get(
                "/rest/api/2/issue/%s/comment" % ticket,
                expand="renderedBody", startAt=start, maxResults=page_size,
            )
            comments = data.get("comments", [])
            yield from comments
            start += len(comments)
            if not comments or start >= data.get("total", 0):
                return

    def get_issue(self, key: str) -> dict:
        return self._get("/rest/api/2/issue/%s" % key)

    def discover_owner_fields(self) -> tuple[str | None, str | None]:
        """Find the custom-field ids whose name is SQA / DevQA."""
        sqa = devqa = None
        for f in self._get("/rest/api/2/field"):
            name = (f.get("name") or "").strip().lower()
            if name in ("sqa", "sqa owner", "assigned sqa") and sqa is None:
                sqa = f["id"]
            elif name in ("devqa", "dev qa", "devqa owner", "assigned devqa") and devqa is None:
                devqa = f["id"]
        return sqa, devqa
