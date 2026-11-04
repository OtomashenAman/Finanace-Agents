from functools import lru_cache
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Finance Agent Command Center"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "info"
    log_format: Literal["text", "json"] = "text"  # json: one object per line, for log shippers
    # Bearer token for GET /metrics. Unset: open outside production, disabled in production
    metrics_token: SecretStr | None = None
    # Several server processes (WEB_CONCURRENCY > 1): a directory they share (tmpfs) where
    # each keeps its HTTP counters, summed on every scrape. Unset: per-process counters
    metrics_dir: str | None = None

    database_url: str
    secret_key: SecretStr
    cors_origins: list[str] = []

    # Auth
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    refresh_reuse_grace_seconds: int = 30  # concurrent refreshes from several tabs
    cookie_secure: bool = False  # true whenever served over HTTPS
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # Overview
    review_sla_hours: int = 24

    # LLM (pluggable provider; "none" disables narratives but runs still work)
    llm_provider: Literal["azure_openai", "none"] = "none"
    llm_timeout_seconds: float = 60
    llm_max_output_tokens: int = 1500
    azure_openai_api_key: SecretStr | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2025-01-01-preview"
    azure_openai_deployment: str | None = None

    # Uploads: only extracted text (+ SHA-256) is kept, never the file
    upload_max_bytes: int = 10 * 1024 * 1024
    upload_max_files_per_run: int = 10
    extracted_text_max_chars: int = 200_000

    # Where browsers reach the app (SPA + /api proxy): OAuth redirect URIs and return pages
    public_base_url: str = "http://localhost:8081"
    # Fernet key for data source credentials (OAuth tokens, client secrets). Optional outside
    # production, where a key derived from SECRET_KEY is used instead
    data_encryption_key: SecretStr | None = None
    data_sync_timeout_seconds: float = 30
    upload_max_rows: int = 20_000

    # Background jobs: "queue" = a worker process runs them (python -m src.app.cli.worker);
    # "inline" = run inside the request that queued them (tests, single-process setups)
    jobs_mode: Literal["queue", "inline"] = "queue"
    jobs_poll_seconds: float = 1.0
    jobs_lock_timeout_seconds: int = 600  # a running job older than this is retried
    # Queue mode on hosts without a separate worker service: the API process runs the worker
    jobs_worker_in_app: bool = False

    # Audit trail: events older than this are removed by `python -m src.app.cli.audit purge`
    audit_retention_days: int = 7 * 365

    # Service POD: read-only source snapshots
    pod_snapshot_max_bytes: int = 5 * 1024 * 1024
    pod_bank_csv_max_bytes: int = 2 * 1024 * 1024
    pod_qbxml_max_bytes: int = 10 * 1024 * 1024
    pod_max_rows_per_collection: int = 10_000
    # Snapshots labelled SYNTHETIC_DEMO (or from a QuickBooks sandbox). Unset: allowed outside
    # production only, so a client installation never shows demo figures as its books
    pod_allow_demo_snapshots: bool | None = None

    # Service POD: email. "outbox" records approved messages without sending anything
    # (labelled as simulated); "brevo" sends through Brevo's transactional API; "microsoft"
    # sends from a Microsoft 365 mailbox through Microsoft Graph (an Entra app with Mail.Send)
    email_provider: Literal["outbox", "brevo", "microsoft"] = "outbox"
    # The From address (a sender verified in the provider; for Microsoft, the mailbox itself
    # unless the app may "Send As" this address)
    email_sender: str | None = Field(
        default=None, validation_alias=AliasChoices("EMAIL_SENDER", "AGENT_EMAIL_FROM")
    )
    email_sender_name: str = "Finance"
    brevo_api_key: SecretStr | None = None
    email_timeout_seconds: float = 20
    ms_tenant_id: str | None = Field(
        default=None, validation_alias=AliasChoices("MS_TENANT_ID", "AGENT_MS_TENANT_ID")
    )
    ms_client_id: str | None = Field(
        default=None, validation_alias=AliasChoices("MS_CLIENT_ID", "AGENT_MS_CLIENT_ID")
    )
    ms_client_secret: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("MS_CLIENT_SECRET", "AGENT_MS_CLIENT_SECRET")
    )
    ms_mailbox: str | None = Field(
        default=None, validation_alias=AliasChoices("MS_MAILBOX", "AGENT_MS_MAILBOX")
    )
    # Seconds between reads of the Microsoft mailbox for customer replies (needs Mail.Read);
    # unset: replies are imported by hand
    mailbox_poll_seconds: int | None = Field(
        default=None,
        ge=30,
        validation_alias=AliasChoices("MAILBOX_POLL_SECONDS", "AGENT_POLL_INTERVAL"),
    )
    # While set, every email goes to this address instead of the customer (the subject names
    # the real recipient). Mail from demo / sandbox data can only go out this way
    email_test_recipient: str | None = None
    # Demo / sandbox data may also mail real addresses, but only each customer's own email
    # as the source states it (never an edited one). The test recipient, when set, wins
    email_sandbox_to_quickbooks_contacts: bool = False
    # The only addresses internal reports may be distributed to
    pod_internal_recipients: list[str] = []

    # Finance POD: where approved vendors and POs are created. "local": the Finance POD's
    # own records (default); "workday": Workday, once the tenant connection below is set up
    finance_pod_erp: Literal["local", "workday"] = "local"
    workday_base_url: str | None = None  # e.g. https://wd2-impl-services1.workday.com
    workday_tenant: str | None = None
    workday_client_id: str | None = None
    workday_client_secret: SecretStr | None = None
    workday_refresh_token: SecretStr | None = None
    # Vendor onboarding portal links stay valid this long, and work once
    vendor_portal_days: int = 14
    # OFAC's Specially Designated Nationals list (CSV) for sanctions screening
    ofac_sdn_url: str = "https://www.treasury.gov/ofac/downloads/sdn.csv"

    # Demo seed user (uv run poe seed)
    demo_admin_email: str = "finance.admin@example.com"
    demo_admin_name: str = "Finance Admin"
    demo_admin_password: SecretStr | None = None

    @field_validator(
        "data_encryption_key",
        "metrics_token",
        "metrics_dir",
        "brevo_api_key",
        "email_sender",
        "ms_tenant_id",
        "ms_client_id",
        "ms_client_secret",
        "ms_mailbox",
        "mailbox_poll_seconds",
        "email_test_recipient",
        "pod_allow_demo_snapshots",
        "workday_base_url",
        "workday_tenant",
        "workday_client_id",
        "workday_client_secret",
        "workday_refresh_token",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def demo_snapshots_allowed(self) -> bool:
        if self.pod_allow_demo_snapshots is None:
            return not self.is_production
        return self.pod_allow_demo_snapshots

    @model_validator(mode="after")
    def _check_email_config(self) -> Self:
        if self.email_provider == "brevo" and not (self.brevo_api_key and self.email_sender):
            raise ValueError("EMAIL_PROVIDER=brevo requires BREVO_API_KEY and EMAIL_SENDER")
        if self.email_provider == "microsoft":
            missing = [
                name
                for name, value in (
                    ("AGENT_MS_TENANT_ID", self.ms_tenant_id),
                    ("AGENT_MS_CLIENT_ID", self.ms_client_id),
                    ("AGENT_MS_CLIENT_SECRET", self.ms_client_secret),
                    ("AGENT_MS_MAILBOX", self.ms_mailbox),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"EMAIL_PROVIDER=microsoft requires {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def _check_llm_config(self) -> Self:
        if self.llm_provider == "azure_openai":
            missing = [
                name
                for name, value in (
                    ("AZURE_OPENAI_API_KEY", self.azure_openai_api_key),
                    ("AZURE_OPENAI_ENDPOINT", self.azure_openai_endpoint),
                    ("AZURE_OPENAI_DEPLOYMENT", self.azure_openai_deployment),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"LLM_PROVIDER=azure_openai requires {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def _check_production_secrets(self) -> Self:
        if self.is_production:
            key = self.secret_key.get_secret_value()
            if len(key) < 32 or key == "change-me":
                raise ValueError("SECRET_KEY must be a random value of at least 32 characters")
            if self.data_encryption_key is None:
                raise ValueError("DATA_ENCRYPTION_KEY is required in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment / .env
