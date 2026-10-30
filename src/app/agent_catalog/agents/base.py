import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.runs.models import AgentRun, AgentRunDetail, FlagSeverity, RunPriority
from src.app.data_sources.access import FinanceData
from src.app.data_sources.models import DataSource
from src.app.data_sources.records import Record, RecordType

_KEY = re.compile(r"[a-z][a-z0-9_]*")
_CODE = re.compile(r"\d{2}")


@dataclass(frozen=True)
class Calculation:
    key: str
    label: str
    value: Decimal | str | None
    kind: Literal["money", "percent", "number", "text"] = "money"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: FlagSeverity
    message: str
    field: str | None = None


@dataclass
class Analysis:
    """What the deterministic engine produced for one run."""

    headline: str
    proposed_decision: str
    calculations: list[Calculation]
    findings: list[Finding]
    # Typed values to store on the agent's run table (e.g. {"invoice_vs_po": Decimal(...)})
    computed: dict[str, Any] = field(default_factory=dict)

    @property
    def priority(self) -> RunPriority:
        high = any(f.severity == FlagSeverity.HIGH for f in self.findings)
        return RunPriority.HIGH if high else RunPriority.NORMAL


@dataclass(frozen=True)
class AnalysisContext:
    session: AsyncSession
    run: AgentRun
    document_count: int
    # The preparer's own data sources (QuickBooks, uploads): e.g. the vendor master
    data: FinanceData
    # The thresholds in force (the agent's policy_schema, current version); None if it has none
    policy: PolicySettings | None = None


@dataclass(frozen=True)
class Evidence:
    """The records an autofill used, frozen into the run's source snapshot for the reviewer
    (like a record picked by hand)."""

    source: DataSource
    record_type: str  # e.g. "bill", or "data" for figures computed over many records
    reference: str
    records: dict[str, Any]  # JSON-ready, by name


def as_of(source: DataSource | None) -> str:
    """e.g. " (data as of 21 Oct 2026 09:30 UTC)"; empty when unknown."""
    if source is None or source.last_synced_at is None:
        return ""
    return f" (data as of {source.last_synced_at:%d %b %Y %H:%M} UTC)"


@dataclass
class Autofill:
    """Empty input fields the agent completed from the preparer's data, and how (one note per
    lookup, shown to the reviewer as findings)."""

    values: dict[str, Any] = field(default_factory=dict)
    notes: list[Finding] = field(default_factory=list)
    evidence: Evidence | None = None  # the first lookup that filled something
    # Data lineage: field -> the record its value came from, e.g. "bill INV-2048"
    sources: dict[str, str] = field(default_factory=dict)

    def add(
        self,
        agent: type["BaseAgent"],
        current: dict[str, Any],
        prefill: "Prefill",
        found: str,
        evidence: Evidence | None = None,
    ) -> None:
        """Take the prefill values for fields still empty, with one note naming them."""
        new = {
            k: v
            for k, v in prefill.values.items()
            if v is not None and current.get(k) is None and k not in self.values
        }
        if not new:
            return
        self.values.update(new)
        self.sources.update(dict.fromkeys(new, found))
        if self.evidence is None:
            self.evidence = evidence
        assert agent.input_schema is not None  # noqa: S101 - only agents with a workspace
        fields = agent.input_schema.model_fields
        labels = ", ".join(fields[k].title or k for k in new if k in fields)
        source = evidence.source if evidence else None
        self.notes.append(
            Finding(
                "FILLED_FROM_DATA",
                FlagSeverity.INFO,
                f"Filled {labels} from {found}{as_of(source)}",
                next(iter(new)),
            )
        )


# How many records behind each total a snapshot keeps (the totals use all of them)
MAX_SNAPSHOT_LINES = 50
_JSON = TypeAdapter(dict[str, Any])


def record_snapshot(name: str, record: Record, related: dict[str, Record]) -> dict[str, Any]:
    """Snapshot records for one source record and the records it led to."""
    return {
        name: record.model_dump(mode="json"),
        **{n: r.model_dump(mode="json") for n, r in related.items()},
    }


def data_snapshot(params: BaseModel, prefill: "Prefill") -> dict[str, Any]:
    """Snapshot records for figures computed over many records: the parameters, the summary,
    and (up to MAX_SNAPSHOT_LINES) the records behind each total."""
    summary = dict(prefill.summary)
    lines: dict[str, Any] = {}
    for name, records in prefill.lines.items():
        lines[name] = [r.model_dump(mode="json") for r in records[:MAX_SNAPSHOT_LINES]]
        if len(records) > MAX_SNAPSHOT_LINES:
            summary[f"{name}_listed"] = f"first {MAX_SNAPSHOT_LINES} of {len(records)}"
    return {
        "parameters": params.model_dump(mode="json"),
        "summary": _JSON.dump_python(summary, mode="json"),
        **{n: r.model_dump(mode="json") for n, r in prefill.related.items()},
        **lines,
    }


@dataclass
class Prefill:
    """Input values taken from a data source, plus what they came from (frozen into the run's
    snapshot for the reviewer)."""

    values: dict[str, Any]
    # Single related records, e.g. {"purchase_order": PurchaseOrder}
    related: dict[str, Record] = field(default_factory=dict)
    # For a prefill from parameters (see BaseAgent.prefill_params): what it covers, e.g.
    # "Next 30 days", the figures it derived, and the records behind each total
    reference: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    lines: dict[str, Sequence[Record]] = field(default_factory=dict)


class BaseAgent:
    """Code definition of one finance agent.

    Catalog metadata is required. The workspace part (input_schema, run_model, analyze) is
    added when the agent is implemented; until then the agent shows "workspace coming soon".
    """

    key: ClassVar[str]  # stable id used in URLs and the DB, e.g. "ap_invoice"
    code: ClassVar[str]  # catalog order, e.g. "01"
    name: ClassVar[str]
    short_name: ClassVar[str]  # used in worklists, e.g. "AP Invoice"
    description: ClassVar[str]
    primary_user: ClassVar[str]  # preparer role label, e.g. "AP Analyst"
    reviewer: ClassVar[str]  # reviewer role label, e.g. "AP Approver"

    # --- workspace (optional until implemented) ---
    input_schema: ClassVar[type[BaseModel] | None] = None
    run_model: ClassVar[type[AgentRunDetail] | None] = None
    controls: ClassVar[tuple[str, ...]] = ()  # "Review these controls" checklist
    reference_field: ClassVar[str | None] = None  # input field shown as the run's reference
    policy_version: ClassVar[str] = "v1"  # bump when rules or thresholds change
    # LLM instructions, kept in the agent's prompt.py: appended to the shared system prompt
    narrative_guidance: ClassVar[str] = ""
    prompt_version: ClassVar[str] = ""  # e.g. "treasury_cash/v1": bump when guidance changes
    # What the LLM also drafts for the reviewer, e.g. "Payment reminder email to the customer"
    # (None: no draft). Shown as a draft for review; the app never sends it.
    draft_message: ClassVar[str | None] = None
    # Which data source records a user can pick to prefill a run (None: manual input only)
    source_record_type: ClassVar[RecordType | None] = None
    # Thresholds a Finance Admin can change (versioned); defaults are policy_version
    policy_schema: ClassVar[type[PolicySettings] | None] = None
    # What approval_amount() returns, for the approval matrix screen (e.g. "Invoice total")
    approval_amount_label: ClassVar[str | None] = None
    # Input fields (vendor, bill number, amount) to create a QuickBooks bill from an approved
    # run entered by hand (None: the agent's results aren't bills)
    bill_fields: ClassVar[tuple[str, str, str] | None] = None
    # Input field with the proposed expense account: prefills the account search for that bill
    bill_account_field: ClassVar[str | None] = None
    # Parameters for a prefill computed from many records (e.g. a forecast horizon), instead of
    # picking one record; implemented by prefill_from_data
    prefill_params: ClassVar[type[BaseModel] | None] = None
    # Input field holding the reference of a `source_record_type` record (e.g. the payment
    # reference): autofill looks that record up and prefills the empty fields from it
    lookup_field: ClassVar[str | None] = None

    _required: ClassVar[tuple[str, ...]] = (
        "key",
        "code",
        "name",
        "short_name",
        "description",
        "primary_user",
        "reviewer",
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        missing = [attr for attr in cls._required if not getattr(cls, attr, None)]
        if missing:
            raise TypeError(f"{cls.__name__} is missing: {', '.join(missing)}")
        if not _KEY.fullmatch(cls.key):
            raise TypeError(f"{cls.__name__}.key must be snake_case, got {cls.key!r}")
        if not _CODE.fullmatch(cls.code):
            raise TypeError(f"{cls.__name__}.code must be two digits, got {cls.code!r}")
        if (cls.input_schema is None) != (cls.run_model is None):
            raise TypeError(f"{cls.__name__} must define both input_schema and run_model")
        if cls.input_schema is not None:
            if not cls.narrative_guidance.strip():
                raise TypeError(f"{cls.__name__} has a workspace but no narrative_guidance")
            if not re.fullmatch(rf"{cls.key}/v\d+", cls.prompt_version):
                raise TypeError(
                    f"{cls.__name__}.prompt_version must look like '{cls.key}/v1', "
                    f"got {cls.prompt_version!r}"
                )

    @classmethod
    def sort_order(cls) -> int:
        return int(cls.code)

    @classmethod
    def has_workspace(cls) -> bool:
        return cls.input_schema is not None

    @classmethod
    async def prefill(
        cls,
        record: Record,
        source: DataSource,
        data: FinanceData,
        policy: PolicySettings | None = None,
    ) -> Prefill:
        """Map a `source_record_type` record to input values (only the fields it knows).

        `policy` is the agent's thresholds in force (e.g. expense limits per category).
        """
        raise NotImplementedError(f"{cls.__name__} can't be prefilled from a data source")

    @classmethod
    async def prefill_from_data(
        cls, params: BaseModel, data: FinanceData, policy: PolicySettings | None = None
    ) -> Prefill:
        """Input values computed from the preparer's data for `prefill_params` (e.g. cash
        position over a horizon). Sets only what the data supports."""
        raise NotImplementedError(f"{cls.__name__} has no prefill from parameters")

    @classmethod
    async def prefill_options(cls, data: FinanceData) -> dict[str, list[str]]:
        """Choices for prefill_params "choice" fields taken from the user's data (e.g. the
        accounts and periods that have balances), by field name."""
        return {}

    @classmethod
    async def autofill(
        cls, values: dict[str, Any], data: FinanceData, policy: PolicySettings | None = None
    ) -> Autofill:
        """Run before every analysis: complete the input fields still empty in `values` by
        looking them up in the preparer's data (e.g. the PO of an invoice). Never overwrites a
        value the preparer entered.

        Default: the `lookup_field` record through prefill(), and the prefill_from_data()
        figures for the parameters autofill_params() reads from the input."""
        result = Autofill()
        reference = values.get(cls.lookup_field) if cls.lookup_field else None
        if cls.source_record_type is not None and reference:
            record_type = cls.source_record_type
            what = record_type.value.replace("_", " ")
            records, source = await data.find_all(record_type, str(reference))
            if len(records) > 1 and source is not None:
                result.notes.append(
                    Finding(
                        "AMBIGUOUS_IN_DATA",
                        FlagSeverity.WARNING,
                        f"Several {what} records are numbered {reference} in {source.name}: "
                        "pick the right one from your data",
                        cls.lookup_field,
                    )
                )
            elif records and source is not None:
                record = records[0]
                prefill = await cls.prefill(record, source, data, policy)
                evidence = Evidence(
                    source,
                    record_type.value,
                    record.reference,
                    record_snapshot(record_type.value, record, prefill.related),
                )
                result.add(
                    cls, values, prefill, f"{what} {record.reference} in {source.name}", evidence
                )
        if cls.prefill_params is not None:
            raw = await cls.autofill_params(values, data)
            if raw is not None:
                try:
                    params = cls.prefill_params.model_validate(raw)
                except ValidationError:
                    return result
                prefill = await cls.prefill_from_data(params, data, policy)
                label = prefill.reference or "From your data"
                latest = await data.latest_source()
                computed = (
                    Evidence(latest, "data", label, data_snapshot(params, prefill))
                    if latest is not None
                    else None
                )
                result.add(cls, values, prefill, f"your data ({label})", computed)
        return result

    @classmethod
    async def autofill_params(
        cls, values: dict[str, Any], data: FinanceData
    ) -> dict[str, Any] | None:
        """The prefill_params to compute from the input entered so far; None: not enough yet."""
        return None

    @classmethod
    def draft_for(cls, data: BaseModel) -> str | None:
        """What the LLM drafts for this run (default: draft_message). An agent narrows it when
        the input rules a draft out, e.g. no customer reminder while a dispute is open."""
        return cls.draft_message

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        """The amount the approval matrix routes on (e.g. the invoice total); None: lowest tier."""
        return None

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        """Deterministic rules and arithmetic on validated input. Never calls the LLM."""
        raise NotImplementedError(f"{cls.__name__} has no workspace yet")
