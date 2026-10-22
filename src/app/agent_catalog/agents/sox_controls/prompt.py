"""LLM instructions for SOX Controls, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "sox_controls/v1"

GUIDANCE = """\
Draft a control test workpaper summary: the control and its owner, the population, the \
sample tested, the exceptions found and the observed exception rate.
Describe missing evidence and draft a remediation request to the control owner for review.

What the SOX reviewer should verify:
- the sample was selected from the full population for the period
- the evidence for each tested item, especially the exceptions
- the test procedure matches the documented control

Do not conclude whether the exceptions are a deficiency, significant deficiency or material \
weakness: that is the SOX reviewer's judgement."""
