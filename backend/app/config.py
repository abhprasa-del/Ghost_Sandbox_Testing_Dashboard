import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    jira_base_url: str
    jira_browse_url: str
    jira_token: str
    jira_ssl_verify: bool
    jira_ca_bundle: str | None
    jira_client_cert: str | None
    jenkins_ca_bundle: str | None
    jira_client_key: str | None
    database_url: str
    source_ticket: str
    sync_token: str
    dashboard_tz: str
    owner_refresh_days: int
    jira_field_sqa: str | None
    jira_field_devqa: str | None

    @property
    def jira_verify(self):
        """Value for requests verify=: CA bundle path if set, else the boolean flag."""
        return self.jira_ca_bundle or self.jira_ssl_verify


def get_settings() -> Settings:
    e = os.environ.get
    return Settings(
        jira_base_url=(e("JIRA_BASE_URL") or "").rstrip("/"),
        jira_browse_url=(e("JIRA_BROWSE_URL") or e("JIRA_BASE_URL") or "").rstrip("/"),
        jira_token=e("JIRA_TOKEN", ""),
        jira_ssl_verify=_bool(e("JIRA_SSL_VERIFY"), True),
        jira_ca_bundle=e("JIRA_CA_BUNDLE") or None,
        jira_client_cert=e("JIRA_CLIENT_CERT") or None,
        jenkins_ca_bundle=e("JENKINS_CA_BUNDLE") or None,
        jira_client_key=e("JIRA_CLIENT_KEY") or None,
        database_url=e("DATABASE_URL", ""),
        source_ticket=e("SOURCE_TICKET", "GREL-799"),
        sync_token=e("SYNC_TOKEN", ""),
        dashboard_tz=e("DASHBOARD_TZ", "Asia/Kolkata"),
        owner_refresh_days=int(e("OWNER_REFRESH_DAYS", "14")),
        jira_field_sqa=e("JIRA_FIELD_SQA") or None,
        jira_field_devqa=e("JIRA_FIELD_DEVQA") or None,
    )
