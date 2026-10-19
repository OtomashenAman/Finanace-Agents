import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.runs.models import AgentRun, AgentRunDetail, FlagSeverity, RunPriority

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
    narrative_guidance: ClassVar[str] = ""  # agent-specific instructions for the LLM

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

    @classmethod
    def sort_order(cls) -> int:
        return int(cls.code)

    @classmethod
    def has_workspace(cls) -> bool:
        return cls.input_schema is not None

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        """Deterministic rules and arithmetic on validated input. Never calls the LLM."""
        raise NotImplementedError(f"{cls.__name__} has no workspace yet")
