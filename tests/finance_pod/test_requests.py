import re
from typing import Any

from httpx import AsyncClient

from src.app.core.llm.base import LLMError
from tests.conftest import FakeLLM
from tests.finance_pod.conftest import request_body

BASE = "/api/v1/finance-pod/requests"


async def create(client: AsyncClient, **changes: Any) -> dict[str, Any]:
    r = await client.post(BASE, json=request_body(**changes))
    assert r.status_code == 201, r.text
    return r.json()


def problems(request: dict[str, Any], *, blocking: bool | None = None) -> list[str]:
    return [
        p["message"]
        for p in request["enrichment"]["problems"]
        if blocking is None or p["blocking"] == blocking
    ]


async def test_a_complete_request_is_checked_and_submitted(
    fpod: AsyncClient, reference: None
) -> None:
    pr = await create(fpod)
    assert re.fullmatch(r"PR-\d{4,}", pr["reference"])  # numbers never restart
    assert pr["status"] == "draft"
    assert pr["total"] == "425.00"
    assert pr["can_edit"] is True
    assert problems(pr, blocking=True) == []
    check = pr["enrichment"]["price_checks"][0]
    assert check["status"] == "matches"
    assert (check["item_code"], check["vendor_name"], check["how"]) == (
        "PIP-200",
        "Lab Supply Co",
        "description",
    )

    r = await fpod.post(f"{BASE}/{pr['id']}/submit", json={"expected_version": pr["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted"
    assert r.json()["can_edit"] is False
    # Submitted: no more edits
    r = await fpod.put(
        f"{BASE}/{pr['id']}", json={**request_body(), "expected_version": r.json()["version"]}
    )
    assert r.status_code == 409


async def test_missing_data_is_flagged_and_blocks_the_submit(
    fpod: AsyncClient, reference: None
) -> None:
    pr = await create(
        fpod,
        purpose="",
        needed_by=None,
        cost_centre_code=None,
        lab_code=None,
        project_code=None,
        grant_code=None,
        lines=[{"description": "Centrifuge rotor", "quantity": "1"}],
    )
    assert problems(pr, blocking=True) == [
        "Say what it's for: the budget and grant checks need it.",
        "Line 1: estimate the unit price.",
        "Give the date it's needed by.",
        "Choose the cost centre that pays for it.",
    ]
    assert pr["blocking_problems"] == 4
    r = await fpod.post(f"{BASE}/{pr['id']}/submit", json={"expected_version": pr["version"]})
    assert r.status_code == 422
    assert "Fix these first" in r.json()["detail"]["message"]
    assert (await fpod.get(f"{BASE}/{pr['id']}")).json()["status"] == "draft"


async def test_prices_above_contract_and_grant_rules_are_flagged(
    fpod: AsyncClient, reference: None
) -> None:
    pr = await create(
        fpod,
        lines=[
            {
                "description": "Nitrile gloves medium",
                "quantity": "20",
                "unit_price": "11.00",
                "category": "lab supplies",
                "catalogue_item_code": "GLV-M",
            },
            {
                "description": "Wine for the lab retreat",
                "quantity": "6",
                "unit_price": "30",
                "category": "alcohol",
            },
        ],
    )
    checks = pr["enrichment"]["price_checks"]
    assert checks[0]["status"] == "above_contract"
    assert checks[0]["difference"] == "40.00"  # (11.00 - 9.00) x 20
    assert checks[0]["how"] == "item_code"
    assert checks[1]["status"] == "no_match"
    assert (
        "Line 2: grant GR-22 doesn't allow 'alcohol'; the budget check will stop it."
        in problems(pr, blocking=False)
    )


async def test_coding_that_does_not_fit_the_reference_data_is_flagged(
    fpod: AsyncClient, reference: None
) -> None:
    pr = await create(fpod, cost_centre_code="CC-200", grant_code=None, project_code="PRJ-7")
    found = problems(pr)
    assert "Lab LAB-GEN belongs to cost centre CC-100, not CC-200." in found
    assert "Project PRJ-7 is funded by grant GR-22." in found
    pr = await create(fpod, grant_code="GR-404")
    assert "Grant GR-404 doesn't exist." in problems(pr, blocking=True)


async def test_above_the_threshold_sourcing_will_need_quotes(
    fpod: AsyncClient, reference: None
) -> None:
    pr = await create(
        fpod,
        lines=[
            {"description": "Sequencer service contract", "quantity": "1", "unit_price": "18000"}
        ],
    )
    assert pr["enrichment"]["quotes_needed"] == 3
    assert any("sourcing will collect 3 quotes" in m for m in problems(pr, blocking=False))


async def test_only_the_requester_changes_it_and_stale_versions_are_refused(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    pr = await create(fpod)
    seen = await other_admin.get(f"{BASE}/{pr['id']}")
    assert seen.status_code == 200
    assert seen.json()["can_edit"] is False
    r = await other_admin.put(
        f"{BASE}/{pr['id']}", json={**request_body(), "expected_version": pr["version"]}
    )
    assert r.status_code == 403

    r = await fpod.put(
        f"{BASE}/{pr['id']}",
        json={**request_body(title="Tips, more"), "expected_version": pr["version"]},
    )
    assert r.status_code == 200
    r = await fpod.put(
        f"{BASE}/{pr['id']}",
        json={**request_body(title="Lost update"), "expected_version": pr["version"]},
    )
    assert r.status_code == 409


async def test_the_agent_suggests_coding_and_the_requester_accepts_it(
    fpod: AsyncClient, reference: None, fake_llm: FakeLLM
) -> None:
    pr = await create(
        fpod,
        cost_centre_code=None,
        lab_code=None,
        project_code=None,
        grant_code=None,
        lines=[
            {"description": "Pipette tips 200ul sterile", "quantity": "10", "unit_price": "42.50"}
        ],
    )
    fake_llm.output = {
        "cost_centre_code": "CC-999",
        "lab_code": "LAB-GEN",
        "project_code": "PRJ-7",
        "grant_code": "GR-22",
        "line_categories": ["lab supplies"],
        "reason": "The purpose names the sequencing study, which is project PRJ-7.",
    }
    # A code that doesn't exist: the AI's answer is not used (and no history to fall back on)
    r = await fpod.post(f"{BASE}/{pr['id']}/suggest")
    assert r.json()["enrichment"]["suggestion"] is None
    assert "cost centre CC-999 isn't an active code" in r.json()["enrichment"]["suggestion_note"]

    fake_llm.output["cost_centre_code"] = "CC-100"
    fake_llm.output["reason"] = "Spend is about 425 dollars for PRJ-7."
    r = await fpod.post(f"{BASE}/{pr['id']}/suggest")
    assert "the reason states figures" in r.json()["enrichment"]["suggestion_note"]

    # Words quoted from the request may hold digits ("200ul"); codes too
    fake_llm.output["reason"] = "Pipette tips 200ul for the sequencing study, project PRJ-7."
    r = await fpod.post(f"{BASE}/{pr['id']}/suggest")
    suggestion = r.json()["enrichment"]["suggestion"]
    assert suggestion["source"] == "ai"
    assert suggestion["grant_code"] == "GR-22"
    assert suggestion["provenance"]["prompt_version"] == "fpod_coding/v1"
    assert "Sequencing study" in fake_llm.calls[-1][1]  # the project list was given

    r = await fpod.post(
        f"{BASE}/{pr['id']}/accept-suggestion", json={"expected_version": r.json()["version"]}
    )
    accepted = r.json()
    assert accepted["coding_source"] == "agent"
    assert (accepted["cost_centre_code"], accepted["grant_code"]) == ("CC-100", "GR-22")
    assert accepted["lines"][0]["category"] == "lab supplies"
    assert problems(accepted, blocking=True) == []


async def test_without_ai_the_agent_falls_back_to_the_requesters_usual_coding(
    fpod: AsyncClient, reference: None, fake_llm: FakeLLM
) -> None:
    first = await create(fpod)
    await fpod.post(f"{BASE}/{first['id']}/submit", json={"expected_version": first["version"]})
    fake_llm.error = LLMError("down")
    pr = await create(
        fpod, cost_centre_code=None, lab_code=None, project_code=None, grant_code=None
    )
    r = await fpod.post(f"{BASE}/{pr['id']}/suggest")
    enrichment = r.json()["enrichment"]
    assert enrichment["suggestion"]["source"] == "history"
    assert enrichment["suggestion"]["cost_centre_code"] == "CC-100"
    assert enrichment["suggestion_note"] == (
        "The AI isn't available; showing the coding you usually use."
    )


async def test_free_text_becomes_the_form_without_invented_figures(
    fpod: AsyncClient, fake_llm: FakeLLM
) -> None:
    fake_llm.output = {
        "title": "Gloves and tips",
        "purpose": "Restock the genomics lab",
        "needed_by": "2000-01-01",
        "lines": [
            {"description": "Nitrile gloves", "quantity": "20", "unit": "box", "unit_price": "9"},
            {"description": "Pipette tips", "quantity": "5", "unit": "box", "unit_price": "40"},
        ],
        "notes": [],
    }
    r = await fpod.post(
        f"{BASE}/draft-from-text",
        json={"text": "Need 20 boxes of nitrile gloves at $9 and some pipette tips asap"},
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["lines"][0] == {
        "description": "Nitrile gloves",
        "quantity": "20",
        "unit": "box",
        "unit_price": "9.00",
    }
    # 5 and 40 aren't in the text: quantity 1 to check, price left out
    assert (draft["lines"][1]["quantity"], draft["lines"][1]["unit_price"]) == ("1", None)
    assert draft["needed_by"] is None  # a past date is dropped
    assert "Line 2: the AI's price isn't in your text, so it was left out." in draft["notes"]


async def test_quotes_attach_once_and_cancel_closes_it(fpod: AsyncClient, reference: None) -> None:
    pr = await create(fpod)
    files = {"file": ("quote.pdf", b"%PDF-1.4 quote", "application/pdf")}
    r = await fpod.post(f"{BASE}/{pr['id']}/files", files=files, data={"kind": "quote"})
    assert r.status_code == 201, r.text
    assert r.json()["files"][0]["kind"] == "quote"
    again = await fpod.post(f"{BASE}/{pr['id']}/files", files=files, data={"kind": "quote"})
    assert again.status_code == 422
    file_id = r.json()["files"][0]["id"]
    download = await fpod.get(f"{BASE}/{pr['id']}/files/{file_id}")
    assert download.content == b"%PDF-1.4 quote"

    r = await fpod.post(
        f"{BASE}/{pr['id']}/cancel",
        json={"expected_version": r.json()["version"], "reason": "Bought from stock"},
    )
    assert r.json()["status"] == "cancelled"
    assert r.json()["closed_at"] is not None
    listed = await fpod.get(BASE, params={"status": "cancelled"})
    assert [p["reference"] for p in listed.json()] == [pr["reference"]]
