"""The request agent's prompts. The model suggests; every code it names is checked against
the reference data, and every figure it reads must be in the requester's own text."""

from pydantic import BaseModel, Field

CODING_PROMPT_VERSION = "fpod_coding/v1"
DRAFT_PROMPT_VERSION = "fpod_draft/v1"

CODING_SYSTEM = """\
You are the request agent of a university / research institute's procurement team. Given a
purchase request and the organisation's coding lists, suggest how it should be coded.

Rules:
- Use only codes that appear in the lists given. If nothing fits, answer null for that code.
- A lab or project belongs to the cost centre shown next to it; keep them consistent.
- Suggest a grant only when the purpose or the project clearly points to that grant's work,
  and never one whose period doesn't cover the needed-by date.
- For each request line, in order, give an expense category from the category list, or null.
- `reason`: one or two plain sentences on why, citing words from the request. No figures.
"""


class CodingRead(BaseModel):
    cost_centre_code: str | None = Field(description="A code from the cost centre list, or null")
    lab_code: str | None = Field(description="A code from the lab list, or null")
    project_code: str | None = Field(description="A code from the project list, or null")
    grant_code: str | None = Field(description="A code from the grant list, or null")
    line_categories: list[str | None] = Field(
        description="One entry per request line, in order: a category from the list, or null"
    )
    reason: str = Field(description="Why, in one or two sentences; no figures")


DRAFT_SYSTEM = """\
You turn a requester's free-text description of something they need to buy into a purchase
request form. Today is {today}.

Rules:
- Only use what the text says. Never invent prices, quantities or dates.
- `quantity` and `unit_price` must be written exactly as numbers that appear in the text
  (no currency signs or thousands separators). If the text gives no price for a line, use
  null; if it gives no quantity, use "1" and say so in `notes`.
- `needed_by`: an ISO date (YYYY-MM-DD) only if the text gives a date or a clear deadline
  ("by 15 March", "next Friday"); otherwise null.
- `title`: a short name for the request (at most 10 words). `purpose`: what it's for, in the
  requester's words.
- `notes`: anything the requester still has to fill in or confirm.
"""


class DraftLineRead(BaseModel):
    description: str = Field(description="What is being bought")
    quantity: str = Field(description="A number from the text, or 1 if none is given")
    unit: str | None = Field(description="e.g. box, each, hour; null if not stated")
    unit_price: str | None = Field(description="Price per unit as written in the text, or null")


class DraftRead(BaseModel):
    title: str
    purpose: str
    needed_by: str | None = Field(description="YYYY-MM-DD or null")
    lines: list[DraftLineRead]
    notes: list[str]
