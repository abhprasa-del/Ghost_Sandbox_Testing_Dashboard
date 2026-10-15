import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.config import Settings

FIX = Path(__file__).parent / "fixtures"


def html(name):
    return (FIX / name).read_text()


def comment(cid, name, author="_sae-test", created=None, updated=None):
    created = created or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    return {"id": str(cid), "author": {"name": author}, "created": created,
            "updated": updated or created, "renderedBody": html(name)}


class FakeJira:
    def __init__(self, comments, issues=None):
        self.comments = comments
        self.issues = issues or {}
        self.fetched = []

    def iter_comments(self, ticket):
        yield from self.comments

    def get_issue(self, key):
        self.fetched.append(key)
        return self.issues.get(key, {"fields": {}})

    def discover_owner_fields(self):
        return "customfield_1", "customfield_2"


def make_settings():
    return Settings(
        jira_base_url="https://jira.example/jira", jira_browse_url="https://jira.example/jira", jira_token="t", jira_ssl_verify=True,
        jira_ca_bundle=None, jira_client_cert=None, jenkins_ca_bundle=None, jira_client_key=None, database_url=os.environ["TEST_DATABASE_URL"],
        source_ticket="GREL-799", sync_token="s", dashboard_tz="Asia/Kolkata",
        owner_refresh_days=14, jira_field_sqa=None, jira_field_devqa=None,
    )


def q(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(text(sql), p).all()
