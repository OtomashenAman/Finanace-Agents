"""Evidence pack: one ZIP with everything an auditor needs for a run.

Contains the run (input, result, findings, AI explanation, approvals), the text extracted
from each document (with the original file's SHA-256), the data source snapshot, the run's
audit timeline, a readable summary and a manifest with every file's SHA-256.
"""

import hashlib
import io
import json
import re
import zipfile
from typing import Any

from src.app.agent_catalog.runs.schemas import RunDetail
from src.app.audit.schemas import AuditEventOut
from src.app.common.clock import utcnow


def _dumps(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, default=str, ensure_ascii=False).encode()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "document"


def _summary(run: RunDetail, timeline: list[AuditEventOut]) -> str:
    output = run.narrative.output if run.narrative else None
    draft = output.draft_message if output else None
    lines = [
        f"Evidence pack · {run.reference} · {run.agent_name}",
        "",
        f"Business reference: {run.business_reference or '-'}",
        f"Legal entity: {f'{run.entity.code} · {run.entity.name}' if run.entity else '-'}",
        f"Preparer: {run.preparer.full_name}",
        f"Status: {run.status_label}",
        f"Policy: {run.policy_version or '-'}",
        f"Result hash (what was approved): {run.result_hash or '-'}",
        "",
        f"Result: {run.headline or '-'}",
        f"Proposed decision: {run.proposed_decision or '-'}",
        "",
        "Calculations:",
        *[f"  {c.label}: {c.value}" for c in run.calculations],
        "",
        "Findings:",
        *[f"  [{f.severity.value}] {f.message}" for f in run.flags],
        "",
        "AI explanation:",
        f"  {output.summary}" if output else "  (none)",
        *(
            ["", "Draft for review (not sent):", *[f"  {line}" for line in draft.splitlines()]]
            if draft
            else []
        ),
        "",
        "Decisions:",
        *[
            f"  {r.created_at:%Y-%m-%d %H:%M} UTC  {r.decision.value} by {r.reviewer.full_name}: "
            f"{r.comment}"
            for r in run.reviews
        ],
        "",
        "Activity:",
        *[
            f"  {e.created_at:%Y-%m-%d %H:%M} UTC  {e.actor.full_name if e.actor else '-'}: "
            f"{e.summary}"
            for e in timeline
        ],
    ]
    return "\n".join(lines) + "\n"


def build(
    run: RunDetail,
    documents: list[tuple[str, str, str]],
    timeline: list[AuditEventOut],
    exported_by: str,
) -> bytes:
    """`documents`: (filename, original sha256, extracted text)."""
    files: dict[str, bytes] = {
        "summary.txt": _summary(run, timeline).encode(),
        "run.json": _dumps(run.model_dump(mode="json")),
        "audit-trail.json": _dumps([e.model_dump(mode="json") for e in timeline]),
    }
    sources: dict[str, str] = {}
    for i, (filename, sha256, text) in enumerate(documents, start=1):
        name = f"documents/D{i}-{_safe(filename)}.txt"
        files[name] = text.encode()
        sources[name] = sha256
    if run.source:
        files["data-source-snapshot.json"] = _dumps(run.source.model_dump(mode="json"))

    manifest = {
        "run": run.reference,
        "agent": run.agent_key,
        "status": run.status.value,
        "result_hash": run.result_hash,
        "exported_at": utcnow().isoformat(),
        "exported_by": exported_by,
        "note": "Documents are the text extracted on upload; the original files are not stored. "
        "source_sha256 identifies the original file.",
        "files": [
            {
                "name": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                **({"source_sha256": sources[name]} if name in sources else {}),
            }
            for name, data in sorted(files.items())
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", _dumps(manifest))
        for name, data in files.items():
            zf.writestr(name, data)
    return buffer.getvalue()
