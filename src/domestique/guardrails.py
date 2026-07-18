"""Deterministic output guardrails — hard rules the agent cannot override.

These bounds are POLICY, not suggestions (CLAUDE.md hard rules; PRD §F4;
BUILD_SPEC §6). They are softened only by consciously editing the bounds table
below, never by a prompt change and never to make a test pass. Every briefing is
checked before display; on failure the brief flow retries once, then falls back to
a safe rest-day message (BUILD_SPEC §4.6).

Checks (BUILD_SPEC §6), each emitting `category: reason` violations:
  * illness   — illness signal in the check-in → the briefing must recommend rest and
                carry no structured workout.
  * medical   — chest pain / dizziness → the briefing must advise seeing a doctor and
                carry no structured workout.
  * personal — a personal injury/symptom protocol defined in the athlete's profile is
                triggered → no intensity in the prescription. The guardrail names no
                condition; checkin.py sets the flag from athlete/profile.md's protocols,
                so the enforcement layer carries no athlete-specific medical vocabulary.
  * power     — every prescribed watt/%FTP figure against the FTP-anchored bounds table.
  * race      — within A_RACE_TAPER_DAYS of an A-race → no intensity above endurance.
  * fuelling  — poor/absent fuelling reported → prescription capped at endurance and
                nutrition addressed before any load increase.
  * weight    — never suggest aggressive weight loss / a calorie deficit.

The checks read the check-in flags set by checkin.py's keyword pass and the days to the
next A-race computed from races.yaml; they never call the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Power bounds as a fraction of FTP (BUILD_SPEC §6). One table, one source of truth.
STEADY_MAX_FTP = 0.80  # steady/endurance prescriptions
THRESHOLD_MAX_FTP = 1.05  # threshold work
ABSOLUTE_MAX_FTP = 1.20  # no prescription above this for efforts >= 5 min

# Race protection window (BUILD_SPEC §6): within this many days of an A-race,
# no session above endurance intensity; weekly load must read as taper.
A_RACE_TAPER_DAYS = 7

# --- Text patterns -----------------------------------------------------------------

# A watt figure or range, capturing the upper bound (the prescription ceiling).
_WATT_RE = re.compile(r"(\d{2,3})(?:\s*[-–—]\s*(\d{2,3}))?\s*[Ww]\b")
# A %FTP figure or range (e.g. "88-94% FTP", "~59% FTP", "105% of FTP").
_PCT_RE = re.compile(r"(\d{2,3})(?:\s*[-–—]\s*(\d{2,3}))?\s*%\s*(?:of\s*)?FTP", re.IGNORECASE)

_ENDURANCE_CTX = re.compile(
    r"\b(recovery|endurance|z1|z2|zone\s*1|zone\s*2|easy|steady|aerobic|base|spin)\b",
    re.IGNORECASE,
)
_THRESHOLD_CTX = re.compile(
    r"\b(threshold|sweet\s*-?\s*spot|sst|tempo|over[-\s]?under|z3|z4|zone\s*3|zone\s*4)\b",
    re.IGNORECASE,
)
_VO2_CTX = re.compile(
    r"\b(vo2\s*max|vo2|anaerobic|z5|z6|z7|zone\s*5|zone\s*6|sprint\s*intervals?)\b",
    re.IGNORECASE,
)
_SPRINT_CTX = re.compile(
    r"\b(sprint|neuromuscular|standing\s*start|\d{1,2}\s*s\b|micro\s*burst)\b", re.IGNORECASE
)
# A duration marker the prescription itself states as UNDER 5 minutes — seconds, or 1–4 min
# (optionally a range, e.g. "3–4 min", "1-min"). The absolute 120%-FTP ceiling is a >=5-min
# rule (see the module docstring and summary()); an effort a line marks as shorter is exempt
# from THAT ceiling — short supra-threshold work (VO2 micro-intervals, 1-min anaerobic efforts)
# is permitted by design. The endurance/threshold zone caps below are duration-independent and
# unaffected. Anything >=5 min or unmarked keeps the absolute ceiling.
_SHORT_EFFORT_RE = re.compile(
    r"\b(?:\d{1,3}\s*(?:s|sec|secs|seconds)\b|[1-4](?:\s*[–\-]\s*[1-5])?\s*[-–]?\s*min\b)",
    re.IGNORECASE,
)
# Lines that report PAST data rather than prescribe — excluded from the power bounds.
_CITATION_CTX = re.compile(
    r"\b(avg|average|held|hold\s*at.*ago|rode|logged|\bkj\b|\bnp\b|best|relative\s*effort"
    r"|\bhr\b|yesterday|last\s*week|per\s*the\s*data|climbs?\s*over)\b",
    re.IGNORECASE,
)

# Interval notation such as "3x12", "2 × 20", "4×4".
_INTERVAL_RE = re.compile(r"\b\d+\s*[x×]\s*\d+\b", re.IGNORECASE)

_REST_RE = re.compile(
    r"\b(rest|recovery|recover|day\s*off|off\s*the\s*bike|no\s*(?:ride|training|workout)"
    r"|easy\s*day|take\s*(?:it\s*)?easy|walk|nap|sleep|sofa)\b",
    re.IGNORECASE,
)
_DOCTOR_RE = re.compile(
    r"\b(doctor|gp\b|physician|medical|a&e|\ber\b|emergency|111|999|urgent\s*care"
    r"|seek\s*care|get\s*checked|see\s*someone)\b",
    re.IGNORECASE,
)
_NUTRITION_RE = re.compile(
    r"\b(fuel|fuelling|fueling|carb|nutrition|eat|calorie|protein|gel|glycogen|food)\b",
    re.IGNORECASE,
)
_WEIGHT_LOSS_RE = re.compile(
    r"\b(aggressive\s*weight\s*loss|calorie\s*deficit|caloric\s*deficit|lose\s*weight"
    r"|drop\s*(?:some\s*)?weight|shed\s*(?:some\s*)?(?:weight|k\s?gs?|pounds)|cut\s*calories"
    r"|crash\s*diet|eat\s*less\s*to|weight\s*cut)\b",
    re.IGNORECASE,
)


@dataclass
class GuardrailResult:
    """Outcome of a guardrail pass over a briefing."""

    passed: bool
    violations: list[str] = field(default_factory=list)


def summary(ftp_w: int) -> str:
    """A concise, human-readable digest of the enforced rules (BUILD_SPEC §6).

    Derived from the bounds constants above so it can never drift from what the code
    actually enforces — used by `sync-claude-app` to carry the deterministic backstop
    into the Claude project instructions. Power ceilings are anchored to the supplied
    profile FTP (the single source of truth, BUILD_SPEC §5).
    """
    steady_w = round(STEADY_MAX_FTP * ftp_w)
    threshold_w = round(THRESHOLD_MAX_FTP * ftp_w)
    absolute_w = round(ABSOLUTE_MAX_FTP * ftp_w)
    return (
        "These checks are enforced deterministically in code (`guardrails.py`) on every "
        "CLI briefing and are non-negotiable — they override any coaching instruction "
        "above:\n\n"
        "- **Illness** signal in the check-in → rest/recovery only, no structured workout.\n"
        "- **Chest pain or dizziness** → advise seeing a doctor, full stop; no workout.\n"
        "- **Personal protocols** (defined in the athlete's profile) → each names a "
        "symptom, a severity threshold and an action (e.g. remove intensity); honour them "
        "with the same non-negotiable force as these universal rules.\n"
        f"- **Power ceilings**, anchored to FTP {ftp_w}W: endurance/steady "
        f"≤{int(STEADY_MAX_FTP * 100)}% FTP ({steady_w}W); threshold "
        f"≤{int(THRESHOLD_MAX_FTP * 100)}% FTP ({threshold_w}W); no ≥5-min effort above "
        f"{int(ABSOLUTE_MAX_FTP * 100)}% FTP ({absolute_w}W).\n"
        f"- **Race protection**: within {A_RACE_TAPER_DAYS} days of an A-priority race → "
        "taper only, no intensity above endurance.\n"
        "- **Fuelling penalty**: poor or absent fuelling reported → next prescription "
        "capped at endurance, and nutrition addressed before any load increase.\n"
        "- **Never** prescribe aggressive weight loss or a calorie deficit."
    )


# --- Prescription analysis ---------------------------------------------------------


def _prescription_lines(briefing: str) -> list[str]:
    """Lines that prescribe today's work, i.e. not past-data citations."""
    return [ln for ln in briefing.splitlines() if ln.strip() and not _CITATION_CTX.search(ln)]


def _upper(match: re.Match) -> int:
    """Upper bound of a captured figure/range."""
    lo, hi = match.group(1), match.group(2)
    return int(hi) if hi else int(lo)


def _has_target(line: str) -> bool:
    """A concrete prescription cue on the line — interval notation, watts, %FTP, or '@'."""
    return bool(
        _INTERVAL_RE.search(line) or _WATT_RE.search(line) or _PCT_RE.search(line) or "@" in line
    )


def _has_intensity(briefing: str, ftp_w: int) -> bool:
    """True if the prescription contains work above endurance (BUILD_SPEC §6, §7).

    An intensity KEYWORD only counts when a concrete target sits on the same line, so a
    negation like "no threshold, no VO2 today" does not read as prescribed intensity.
    """
    steady_w = round(STEADY_MAX_FTP * ftp_w)
    for ln in _prescription_lines(briefing):
        if (_THRESHOLD_CTX.search(ln) or _VO2_CTX.search(ln)) and _has_target(ln):
            return True
        for m in _WATT_RE.finditer(ln):
            if _upper(m) > steady_w:
                return True
        for m in _PCT_RE.finditer(ln):
            if _upper(m) > round(STEADY_MAX_FTP * 100):
                return True
    return False


def _has_structured_workout(briefing: str) -> bool:
    """True if the briefing prescribes structured work — interval notation or power targets.

    Keyword-free by design: a rest-day briefing that merely says "no intervals, no
    threshold" carries no numbers and is not treated as a structured workout.
    """
    for ln in _prescription_lines(briefing):
        if _INTERVAL_RE.search(ln) or _WATT_RE.search(ln) or _PCT_RE.search(ln):
            return True
    return False


def _line_intensity_cap(line: str) -> tuple[str, float] | None:
    """Classify a prescription line and return (label, max_fraction_of_FTP).

    Priority matters: a line names its hardest element (e.g. "sweet spot … 5 min easy
    between") so the intensity keyword wins over an incidental endurance word. Sprint /
    neuromuscular efforts, and any effort the line explicitly marks as under 5 min
    (`_SHORT_EFFORT_RE`), are exempt from the absolute >=5-min ceiling — short supra-threshold
    work is permitted by design; the threshold/endurance zone caps still apply.
    """
    if _SPRINT_CTX.search(line):
        return None  # short effort — exempt from the >=5-min ceiling
    # The absolute (120% FTP) ceiling only bounds efforts >= 5 min; a line the prescription
    # marks as shorter is exempt from it. Zone caps (threshold/endurance) are unaffected.
    short = bool(_SHORT_EFFORT_RE.search(line))
    if _VO2_CTX.search(line):
        return None if short else ("VO2/anaerobic", ABSOLUTE_MAX_FTP)
    if _THRESHOLD_CTX.search(line):
        return "threshold", THRESHOLD_MAX_FTP
    if _ENDURANCE_CTX.search(line):
        return "endurance", STEADY_MAX_FTP
    # Unclassified: only the absolute (>=5-min) ceiling applies, so an explicitly short effort
    # is likewise exempt; anything >=5 min or unmarked keeps the ceiling.
    return None if short else ("sustained", ABSOLUTE_MAX_FTP)


def _check_power_bounds(briefing: str, ftp_w: int) -> list[str]:
    """Every prescribed watt/%FTP figure against the FTP-anchored bounds (BUILD_SPEC §6)."""
    violations: list[str] = []
    for ln in _prescription_lines(briefing):
        classified = _line_intensity_cap(ln)
        if classified is None:
            continue
        label, frac = classified
        cap_w = round(frac * ftp_w)
        cap_pct = int(frac * 100)

        for m in _WATT_RE.finditer(ln):
            v = _upper(m)
            if v > cap_w:
                violations.append(f"power: {label} target {v}W exceeds {cap_pct}% FTP ({cap_w}W)")
        for m in _PCT_RE.finditer(ln):
            v = _upper(m)
            if v > cap_pct:
                violations.append(f"power: {label} target {v}% FTP exceeds {cap_pct}%")
    return violations


# --- The pass ----------------------------------------------------------------------


def check_briefing(
    briefing: str,
    *,
    ftp_w: int,
    checkin_flags: dict[str, bool],
    days_to_a_race: int | None = None,
) -> GuardrailResult:
    """Run every deterministic check over a briefing (BUILD_SPEC §6).

    `checkin_flags` are set by checkin.py (illness, red_flag_medical, personal_protocol,
    fuelling_poor). `personal_protocol` is true when a profile-defined injury/symptom
    protocol is triggered (checkin.py owns the condition keywords, read from the profile).
    `days_to_a_race` is the whole-day count to the next A-priority event (None if none).
    """
    flags = checkin_flags or {}
    violations: list[str] = []

    has_structured = _has_structured_workout(briefing)
    has_intensity = _has_intensity(briefing, ftp_w)
    recommends_rest = bool(_REST_RE.search(briefing))

    # Illness → rest only, no structured workout.
    if flags.get("illness"):
        if has_structured:
            violations.append(
                "illness: illness signal in check-in but the briefing prescribes a "
                "structured workout — must be rest/recovery only"
            )
        if not recommends_rest:
            violations.append(
                "illness: illness signal in check-in but the briefing does not recommend "
                "rest/recovery"
            )

    # Chest pain / dizziness → see a doctor, full stop.
    if flags.get("red_flag_medical"):
        if not _DOCTOR_RE.search(briefing):
            violations.append(
                "medical: chest-pain/dizziness signal but the briefing does not advise "
                "seeing a doctor"
            )
        if has_structured:
            violations.append(
                "medical: chest-pain/dizziness signal but the briefing prescribes a "
                "structured workout — must be see-a-doctor, full stop"
            )

    # Personal protocol (defined in the athlete's profile, enforced generically): a
    # triggered no-intensity protocol removes intensity from the prescription. The rule
    # names no condition — checkin.py sets this flag from the profile-defined protocols
    # (BUILD_SPEC §6), so the enforcement layer carries no athlete-specific medical terms.
    if flags.get("personal_protocol") and has_intensity:
        violations.append(
            "personal_protocol: a personal injury/symptom protocol from the profile is in "
            "force but the prescription contains intensity — remove it (endurance only)"
        )

    # Power bounds against the FTP-anchored table.
    violations.extend(_check_power_bounds(briefing, ftp_w))

    # Race protection: within the taper window, no intensity above endurance.
    if days_to_a_race is not None and 0 <= days_to_a_race <= A_RACE_TAPER_DAYS and has_intensity:
        violations.append(
            f"race: A-race in {days_to_a_race} day(s) (≤{A_RACE_TAPER_DAYS}) but the "
            "prescription contains intensity above endurance — taper only"
        )

    # Fuelling penalty: cap at endurance and address nutrition before any load increase.
    if flags.get("fuelling_poor"):
        if has_intensity:
            violations.append(
                "fuelling: poor/absent fuelling reported but the prescription exceeds "
                "endurance — cap at endurance until fuelling is fixed"
            )
        if not _NUTRITION_RE.search(briefing):
            violations.append(
                "fuelling: poor/absent fuelling reported but the briefing does not address "
                "nutrition"
            )

    # Never suggest aggressive weight loss.
    if _WEIGHT_LOSS_RE.search(briefing):
        violations.append(
            "weight: the briefing suggests weight loss / a calorie deficit — never "
            "prescribe aggressive weight loss"
        )

    return GuardrailResult(passed=not violations, violations=violations)
