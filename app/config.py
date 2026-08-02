from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    api_key: str = "dev-local-key"
    brave_enabled: bool = False
    brave_api_key: str = ""
    exa_api_key: str = ""
    tavily_api_key: str = ""
    youtube_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "YOUTUBE_API_KEY",
            "INTEL_YOUTUBE_API_KEY",
            "youtube_api_key",
        ),
    )
    database_url: str = "sqlite:///./data/intel.db"
    blob_root: str = "./data/blobs"
    # Scrapling L2 escalation (FETCH_L2=0 or INTEL_FETCH_L2=0 to disable)
    fetch_l2: bool = Field(
        default=True,
        validation_alias=AliasChoices("FETCH_L2", "INTEL_FETCH_L2", "fetch_l2"),
    )
    # L1.5 Scrapling Fetcher / curl_cffi (INTEL_FETCH_L15=0 to disable)
    fetch_l15_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "FETCH_L15", "INTEL_FETCH_L15", "fetch_l15_enabled"
        ),
    )
    fetch_circuit_breaker_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "FETCH_CIRCUIT_BREAKER",
            "INTEL_FETCH_CIRCUIT_BREAKER",
            "fetch_circuit_breaker_enabled",
        ),
    )
    fetch_http_reclass_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "FETCH_HTTP_RECLASS",
            "INTEL_FETCH_HTTP_RECLASS",
            "fetch_http_reclass_enabled",
        ),
    )
    # Search breadth — SEARCH_UNION_ENABLED / INTEL_SEARCH_UNION (0/false to disable)
    search_union_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SEARCH_UNION_ENABLED", "INTEL_SEARCH_UNION", "search_union_enabled"
        ),
    )
    query_expand_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "QUERY_EXPAND_ENABLED", "INTEL_QUERY_EXPAND", "query_expand_enabled"
        ),
    )
    search_provider_timeout_s: float = 30.0
    # Recoverable fetch fail → pending_review (FETCH_SOFT_PENDING_ENABLED / INTEL_FETCH_SOFT_PENDING=0)
    fetch_soft_pending_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "FETCH_SOFT_PENDING_ENABLED",
            "INTEL_FETCH_SOFT_PENDING",
            "fetch_soft_pending_enabled",
        ),
    )
    discovery_sitemap_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "DISCOVERY_SITEMAP_ENABLED",
            "INTEL_DISCOVERY_SITEMAP",
            "discovery_sitemap_enabled",
        ),
    )
    discovery_listing_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "DISCOVERY_LISTING_ENABLED",
            "INTEL_DISCOVERY_LISTING",
            "discovery_listing_enabled",
        ),
    )
    discovery_gnews_resolve_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "DISCOVERY_GNEWS_RESOLVE_ENABLED",
            "INTEL_DISCOVERY_GNEWS",
            "discovery_gnews_resolve_enabled",
        ),
    )
    discovery_watch_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "DISCOVERY_WATCH_ENABLED",
            "INTEL_DISCOVERY_WATCH",
            "discovery_watch_enabled",
        ),
    )
    reach_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "REACH_ENABLED",
            "INTEL_REACH_ENABLED",
            "reach_enabled",
        ),
    )
    fetch_jina_fallback_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "FETCH_JINA_FALLBACK_ENABLED",
            "INTEL_FETCH_JINA_FALLBACK",
            "fetch_jina_fallback_enabled",
        ),
    )
    jina_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "JINA_API_KEY",
            "INTEL_JINA_API_KEY",
            "jina_api_key",
        ),
    )
    pdf_queue_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "PDF_QUEUE_ENABLED",
            "INTEL_PDF_QUEUE_ENABLED",
            "pdf_queue_enabled",
        ),
    )
    # Optional egress proxy for brittle *.go.id (Indonesian SOCKS/HTTP).
    # Also: standard HTTP_PROXY / HTTPS_PROXY are honored by httpx trust_env.
    proxy_url: str = ""

    @property
    def blob_path(self) -> Path:
        return Path(self.blob_root).resolve()

    @property
    def http_proxy(self) -> str | None:
        import os

        return (
            (self.proxy_url or "").strip()
            or os.environ.get("PROXY_URL")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
            or None
        )


settings = Settings()
