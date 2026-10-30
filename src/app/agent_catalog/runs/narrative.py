"""Guarded LLM explanation of an analyzed run.

The instructions live in prompts.py (shared system prompt) and each agent's prompt.py.

The LLM only explains: every figure comes from the deterministic engine, the output is
schema-validated, and guard checks flag anything it cites or quotes that isn't in the payload.
"""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, create_model
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis, BaseAgent
from src.app.agent_catalog.runs import prompts
from src.app.agent_catalog.runs.models import (
    AgentRun,
    NarrativeStatus,
    RunDocument,
    RunNarrative,
    RunSourceSnapshot,
)
from src.app.agent_catalog.runs.schemas import NarrativeOutput
from src.app.core.llm.base import LLMError, LLMNotConfiguredError, LLMProvider

DOC_CHARS_PER_DOCUMENT = 15_000
DOC_CHARS_TOTAL = 40_000
MAX_SOURCE_RECORDS = 30

# A suggested action must leave money and postings to people
_MONEY_MOVEMENT = re.compile(r"\b(approve|post|pay|transfer|wire|remit|send)\b", re.IGNORECASE)

# Numbers as written in prose: 12,500.00 / -100 / 0.5. Not part of IDs like INV-2048 or dates.
_NUMBER = re.compile(r"(?<![\w.\-/])-?\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    found = set()
    for raw in _NUMBER.findall(text):
        try:
            found.add(abs(Decimal(raw.replace(",", ""))))
        except InvalidOperation:
            continue
    return found


def _worth_checking(value: Decimal, raw_has_decimals: bool) -> bool:
    # Small counts ("2 documents") and plain years are not figures worth policing
    if value < 100 and not raw_has_decimals:
        return False
    return not (value == value.to_integral() and 1900 <= value <= 2100)


def source_records(snapshot: RunSourceSnapshot | None) -> list[dict[str, Any]]:
    """The run's frozen source records as evidence the LLM may cite: S1, S2... each with its
    type, record id in the source, source name and sync time (at most MAX_SOURCE_RECORDS)."""
    if snapshot is None:
        return []
    found: list[tuple[str, dict[str, Any]]] = []
    for name, value in snapshot.records.items():
        for record in value if isinstance(value, list) else [value]:
            if isinstance(record, dict) and record.get("external_id"):
                found.append((name, record))
    synced = snapshot.source_synced_at.isoformat() if snapshot.source_synced_at else None
    return [
        {
            "id": f"S{i}",
            "type": name,
            "record_id": str(record["external_id"]),
            "source": f"{snapshot.source_kind} {snapshot.source_name}",
            "synced_at": synced,
            "data": record,
        }
        for i, (name, record) in enumerate(found[:MAX_SOURCE_RECORDS], start=1)
    ]


def build_payload(
    run: AgentRun,
    definition: type[BaseAgent],
    data: BaseModel,
    analysis: Analysis,
    documents: list[RunDocument],
    entity_name: str | None = None,
    snapshot: RunSourceSnapshot | None = None,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Payload for the LLM, map of prompt doc ids -> document ids, and notes about trimming."""
    notes: list[str] = []
    budget = DOC_CHARS_TOTAL
    docs = []
    doc_ids: dict[str, str] = {}
    for i, document in enumerate(documents, start=1):
        alias = f"D{i}"
        doc_ids[alias] = str(document.id)
        limit = min(DOC_CHARS_PER_DOCUMENT, budget)
        text = document.extracted_text[:limit]
        budget -= len(text)
        if len(text) < len(document.extracted_text):
            notes.append(f"{alias} ({document.filename}) was shortened for the LLM prompt")
        docs.append({"id": alias, "filename": document.filename, "text": text})

    payload = {
        "agent": definition.name,
        "run": run.reference,
        "legal_entity": entity_name,
        "input": data.model_dump(mode="json"),
        "calculations": [
            {"key": c.key, "label": c.label, "value": None if c.value is None else str(c.value)}
            for c in analysis.calculations
        ],
        "findings": [
            {"code": f.code, "severity": f.severity.value, "message": f.message, "field": f.field}
            for f in analysis.findings
        ],
        "headline": analysis.headline,
        "proposed_decision": analysis.proposed_decision,
        "source_records": source_records(snapshot),
        "documents": docs,
    }
    return payload, doc_ids, notes


def output_schema(payload: dict[str, Any], draft: str | None = None) -> type[NarrativeOutput]:
    """NarrativeOutput narrowed to this payload: the model can only cite keys and documents
    that exist (strict structured output enforces the enums). With `draft` (the agent's
    draft_message), it must also write that draft."""
    keys = sorted(set(payload["input"]) | {c["key"] for c in payload["calculations"]})
    overrides: dict[str, Any] = {
        "cited_fields": (
            list[StrEnum("CitedField", [(k, k) for k in keys])],  # type: ignore[misc]
            Field(description="Input or calculation keys relied on"),
        )
    }
    documents = [d["id"] for d in payload["documents"]]
    if documents:
        overrides["cited_documents"] = (
            list[StrEnum("CitedDocument", [(d, d) for d in documents])],  # type: ignore[misc]
            Field(description="Document ids relied on"),
        )
    evidence = [s["id"] for s in payload.get("source_records", [])]
    if evidence:
        overrides["evidence_ids"] = (
            list[StrEnum("EvidenceId", [(s, s) for s in evidence])],  # type: ignore[misc]
            Field(description="Source record ids relied on"),
        )
    if draft:
        overrides["draft_message"] = (
            str,
            Field(description=f"{draft}: a draft for human review, never sent automatically"),
        )
    schema: type[NarrativeOutput] = create_model(
        "NarrativeOutput", __base__=NarrativeOutput, **overrides
    )
    return schema


def check_output(output: NarrativeOutput, payload: dict[str, Any]) -> list[str]:
    """Guard checks: citations must exist, figures must appear in the source data."""
    warnings = []
    allowed_fields = set(payload["input"]) | {c["key"] for c in payload["calculations"]}
    for name in map(str, output.cited_fields):
        if name not in allowed_fields:
            warnings.append(f"Cited a field that doesn't exist: {name}")
    allowed_docs = {d["id"] for d in payload["documents"]}
    for doc in map(str, output.cited_documents):
        if doc not in allowed_docs:
            warnings.append(f"Cited a document that wasn't provided: {doc}")
    allowed_evidence = {s["id"] for s in payload.get("source_records", [])}
    for evidence_id in map(str, output.evidence_ids):
        if evidence_id not in allowed_evidence:
            warnings.append(f"Cited a source record that wasn't provided: {evidence_id}")
    if _MONEY_MOVEMENT.search(output.suggested_action):
        warnings.append(
            "The suggested action proposes approving, posting, paying or sending: "
            "a person decides that"
        )

    source_numbers = _numbers(json.dumps(payload))
    draft = getattr(output, "draft_message", None) or ""
    prose = " ".join(
        [
            output.summary,
            *output.key_points,
            *output.missing_evidence,
            *output.ambiguities,
            output.suggested_action,
            draft,
        ]
    )
    for raw in _NUMBER.findall(prose):
        try:
            value = abs(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            continue
        if _worth_checking(value, "." in raw) and value not in source_numbers:
            warnings.append(f"Figure not found in the source data: {raw}")
    return sorted(set(warnings))


def prompt_hash(system: str, user: str, schema: type[BaseModel]) -> str:
    """SHA-256 of exactly what the model was given: instructions, payload and output schema."""
    sent = json.dumps(
        {"system": system, "user": user, "schema": schema.model_json_schema()}, sort_keys=True
    )
    return hashlib.sha256(sent.encode()).hexdigest()


async def generate(
    session: AsyncSession,
    run: AgentRun,
    definition: type[BaseAgent],
    data: BaseModel,
    analysis: Analysis,
    documents: list[RunDocument],
    llm: LLMProvider,
    entity_name: str | None = None,
    snapshot: RunSourceSnapshot | None = None,
) -> RunNarrative:
    """Call the LLM and record the attempt, whatever the outcome (caller commits)."""
    payload, _, notes = build_payload(
        run, definition, data, analysis, documents, entity_name, snapshot
    )
    system = prompts.system_prompt(definition.name, definition.narrative_guidance)
    user = json.dumps(payload, ensure_ascii=False)
    schema = output_schema(payload, definition.draft_for(data))
    narrative = RunNarrative(
        run_id=run.id,
        provider=llm.name,
        model=llm.model,
        prompt_version=prompts.prompt_version(definition.prompt_version),
        prompt_hash=prompt_hash(system, user, schema),
        policy_version=run.policy_version,
        input_payload=payload,
        guard_warnings=notes,
    )
    try:
        result = await llm.generate_structured(system=system, user=user, schema=schema)
    except LLMNotConfiguredError as exc:
        narrative.status = NarrativeStatus.NOT_CONFIGURED
        narrative.error = str(exc)[:500]
    except LLMError as exc:
        narrative.status = NarrativeStatus.FAILED
        narrative.error = str(exc)[:500]
    else:
        narrative.status = NarrativeStatus.OK
        narrative.model = result.model
        narrative.output = result.output.model_dump(mode="json")
        narrative.guard_warnings = notes + check_output(result.output, payload)
        narrative.request_id = result.request_id
        narrative.input_tokens = result.usage.input_tokens
        narrative.output_tokens = result.usage.output_tokens
        narrative.cached_tokens = result.usage.cached_tokens
        narrative.latency_ms = result.latency_ms
    session.add(narrative)
    return narrative
