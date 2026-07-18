"""Deterministic physiological limits for the eval harness (BUILD_SPEC §3, PRD §F3).

These are the eval-side checks — power within physiological bounds by duration,
carbs 60-120 g/hr, taper protection, load-ramp limits — run over golden-set
scenarios. They share intent with src/domestique/guardrails.py but live here so the
eval harness can score briefings independently.

Scaffold only in step 1; the golden set and checks are built in build steps 3 and 5.
"""

from __future__ import annotations

# Fuelling bounds (PRD §F3, §F4): carbohydrate intake on long efforts.
CARBS_MIN_G_PER_HR = 60
CARBS_MAX_G_PER_HR = 120


def carbs_in_bounds(g_per_hr: float) -> bool:
    """True if a fuelling rate falls within the physiological window."""
    return CARBS_MIN_G_PER_HR <= g_per_hr <= CARBS_MAX_G_PER_HR
