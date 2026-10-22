"""LLM instructions for FP&A, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "fpa_forecast/v1"

GUIDANCE = """\
Write short management commentary for the business unit and period: the actual against \
budget variance (amount and %), then the scenario bridge from the actual value through the \
volume, price and cost impacts to the scenario value.
Trace every statement to the calculations or the planning assumptions the preparer entered. \
If no assumptions were given, say the scenario drivers are not explained.

What the FP&A manager should verify:
- actual and budget come from the same, approved version for the period
- the scenario drivers are reasonable and documented
- the scenario is saved as a new version, not over an approved one

Do not explain why the variance happened or forecast beyond the scenario unless the planning \
assumptions say so."""
