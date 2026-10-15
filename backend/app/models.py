"""ORM mappings for the EXISTING tables and view (no DDL is ever issued from here)."""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, ForeignKey, Integer, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TS = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"
    ticket_key: Mapped[str] = mapped_column(String(20), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(50))
    assignee: Mapped[str | None] = mapped_column(String(100))
    sqa_owner: Mapped[str | None] = mapped_column(String(100))
    devqa_owner: Mapped[str | None] = mapped_column(String(100))
    jira_url: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(TS)
    updated_at: Mapped[datetime] = mapped_column(TS)

    runs: Mapped[list["TestRun"]] = relationship(back_populates="ticket")


class TestRun(Base):
    __tablename__ = "test_runs"
    __test__ = False
    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_key: Mapped[str] = mapped_column(ForeignKey("tickets.ticket_key"))
    jira_comment_id: Mapped[str] = mapped_column(String(30), unique=True)
    alsi_version: Mapped[str | None] = mapped_column(String(20))
    metadata_mode: Mapped[str] = mapped_column(String(30))
    sandbox_build_no: Mapped[int | None] = mapped_column(Integer)
    sandbox_build_url: Mapped[str | None] = mapped_column(Text)
    sandbox_status: Mapped[str | None] = mapped_column(String(20))
    ghost_version: Mapped[str | None] = mapped_column(String(100))
    not_selected_jobs: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    ghost_crashes_url: Mapped[str | None] = mapped_column(Text)
    commented_at: Mapped[datetime] = mapped_column(TS)
    comment_edited: Mapped[bool | None] = mapped_column(Boolean)
    raw_html: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(TS)

    ticket: Mapped[Ticket] = relationship(back_populates="runs")
    jobs: Mapped[list["JobResult"]] = relationship(back_populates="run")


class JobResult(Base):
    __tablename__ = "job_results"
    __table_args__ = (UniqueConstraint("run_id", "job_name"),)
    job_result_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.run_id"))
    job_name: Mapped[str] = mapped_column(String(40))
    job_status: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str | None] = mapped_column(String(20))
    result_text: Mapped[str | None] = mapped_column(Text)
    job_url: Mapped[str | None] = mapped_column(Text)
    summary_url: Mapped[str | None] = mapped_column(Text)
    analysis_url: Mapped[str | None] = mapped_column(Text)
    plots_url: Mapped[str | None] = mapped_column(Text)

    run: Mapped[TestRun] = relationship(back_populates="jobs")
    artifacts: Mapped[list["BuildArtifact"]] = relationship(back_populates="job")
    suites: Mapped[list["BaselineSuite"]] = relationship(back_populates="job")


class BuildArtifact(Base):
    __tablename__ = "build_artifacts"
    artifact_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_result_id: Mapped[int] = mapped_column(ForeignKey("job_results.job_result_id"))
    artifact_type: Mapped[str] = mapped_column(String(20))
    download_url: Mapped[str] = mapped_column(Text)
    wget_command: Mapped[str | None] = mapped_column(Text)

    job: Mapped[JobResult] = relationship(back_populates="artifacts")


class BaselineSuite(Base):
    __tablename__ = "baseline_suites"
    suite_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_result_id: Mapped[int] = mapped_column(ForeignKey("job_results.job_result_id"))
    suite_name: Mapped[str] = mapped_column(String(20))
    job_link: Mapped[str | None] = mapped_column(Text)
    report_link: Mapped[str | None] = mapped_column(Text)
    siam_link: Mapped[str | None] = mapped_column(Text)

    job: Mapped[JobResult] = relationship(back_populates="suites")


class SyncLog(Base):
    __tablename__ = "sync_log"
    sync_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    comments_seen: Mapped[int | None] = mapped_column(Integer)
    runs_upserted: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)


# Read-only view, mapped as a plain Table (selected via select(), never written).
v_dashboard = Table(
    "v_dashboard",
    Base.metadata,
    Column("ticket_key", String),
    Column("title", Text),
    Column("assignee", String),
    Column("sqa_owner", String),
    Column("devqa_owner", String),
    Column("alsi_version", String),
    Column("metadata_mode", String),
    Column("sandbox_build_no", Integer),
    Column("sandbox_status", String),
    Column("ghost_version", String),
    Column("commented_at", TS),
    Column("run_id", BigInteger, primary_key=True),
    Column("have_perf", String),
    Column("have_load", String),
    Column("have_bats", String),
    Column("have_baseline", String),
    Column("asan_status", String),
    Column("lsan_status", String),
    Column("tsan_status", String),
    Column("perf_outcome", String),
    Column("load_outcome", String),
    Column("baseline_outcome", String),
    Column("not_selected_jobs", ARRAY(Text)),
    Column("comment_edited", Boolean),
    Column("ticket_status", String),
    info={"is_view": True},
)
