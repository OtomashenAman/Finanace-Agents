"""The GIA requirement as data (see model.py). PHASES lists every phase transcribed so far;
a phase whose `workflows` is filled in is held to it by the coverage test."""

from src.app.finance_pod.requirements.ap import PHASES as AP_PHASES
from src.app.finance_pod.requirements.model import Phase

PHASES: tuple[Phase, ...] = AP_PHASES
