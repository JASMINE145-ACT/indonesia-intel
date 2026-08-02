from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReviewCandidate(Base):
    __tablename__ = "review_candidates"
    __table_args__ = (UniqueConstraint("url_hash", name="uq_review_candidates_url_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(String(512))
    original_url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(1024))
    snippet: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # discovered|pending_review|watching|confirmed|ignored|merged|fetch_failed|pdf_queued
    status: Mapped[str] = mapped_column(String(32), default="discovered", index=True)
    # not_attempted|ok|failed|pdf_queued — soft-pending keeps status=pending_review when failed
    fetch_status: Mapped[str] = mapped_column(
        String(32), default="not_attempted", server_default="not_attempted"
    )
    fetch_error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Discovery provenance (multi-adapter L1)
    discovery_method: Mapped[str] = mapped_column(
        String(32), default="rss", server_default="rss"
    )
    resolved_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_status: Mapped[str] = mapped_column(
        String(32), default="not_required", server_default="not_required"
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_search_json: Mapped[str] = mapped_column(Text, default="{}")
    object_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PRD §4.4 人工投喂：来源属性 + 是否可对外使用（防止非公开信息误入公开文章）。
    source_attribution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_public_source: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # Merge pointer → formal_events.id (logical FK; no Alembic CASCADE).
    duplicate_of_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentJob(Base):
    """Async PDF download + native text extract — WANd.INTEL.FETCH_PDF_QUEUE.001."""

    __tablename__ = "document_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, index=True)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    # queued|processing|done|failed
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    storage_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(64), default="api-key")
    before_status: Mapped[str] = mapped_column(String(32))
    after_status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Company(Base):
    """企业档案 — PRD §5.1. Supports 母公司 → 印尼子公司 via parent_company_id."""

    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("name_cn", name="uq_companies_name_cn"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_cn: Mapped[str] = mapped_column(String(255), index=True)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True, index=True
    )
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    cn_hq: Mapped[str | None] = mapped_column(String(255), nullable=True)
    id_presence: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_listed: Mapped[bool] = mapped_column(Boolean, default=False)
    first_entry_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_business_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Project(Base):
    """项目档案 — PRD §5.3. 多条动态归一条时间线，避免拆成互不相关的多个项目。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(512))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    investment_amount: Mapped[str | None] = mapped_column(String(255), nullable=True)
    planned_capacity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    partners: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FormalEvent(Base):
    """企业动态 — PRD §5.2. Confirmed formal row; provenance required."""

    __tablename__ = "formal_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(1024))
    canonical_url: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    project_stage: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    occurred_date: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    published_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    investment_amount: Mapped[str | None] = mapped_column(String(255), nullable=True)
    planned_capacity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    partners: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    credibility: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EventSource(Base):
    """信息来源 — PRD §5.4. 同一 formal_event 可挂多条来源，全部保留供可信度评估与写作引用。"""

    __tablename__ = "event_sources"
    __table_args__ = (UniqueConstraint("event_id", "url", name="uq_event_sources_event_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("formal_events.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    source_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SourceWatchState(Base):
    """Page-change watch cursor — WANd.INTEL.WATCH_ADAPTER.001."""

    __tablename__ = "source_watch_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    watch_url: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
