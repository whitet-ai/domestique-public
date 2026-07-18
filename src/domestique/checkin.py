"""Terminal check-in: three questions -> structured state (BUILD_SPEC §4.2, step 2).

One question at a time, free-text answers passed to the model raw — the LLM does the
interpretation (that is the point). A non-interactive mode (--sleep/--body/--yesterday
or --answers file) supports phone-driven cloud sessions. A simple keyword pass sets an
illness/injury flag that guardrails.py will consume in build step 3 (BUILD_SPEC §6);
step 2 records the flags but does not yet enforce them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import typer

QUESTIONS: tuple[tuple[str, str], ...] = (
    ("sleep", "How did you sleep, and how do you feel this morning?"),
    ("body", "Anything sore, run down, or on your mind that affects training?"),
    ("yesterday", "How hard did yesterday feel, if you trained?"),
)

# Keyword passes (BUILD_SPEC §6). These SET flags the guardrail layer enforces; they
# never soften advice here. Deliberately broad — guardrails.py decides what to do.

# General illness signals → rest/recovery only.
_ILLNESS_KEYWORDS = (
    "ill",
    "sick",
    "unwell",
    "fever",
    "feverish",
    "temperature",
    "cold",
    "flu",
    "cough",
    "sore throat",
    "chesty",
    "run down",
    "rundown",
    "run-down",
    "rough",
    "nauseous",
    "nausea",
    "sniffle",
    "man flu",
)
# Cardiac / neurological red flags → see a doctor, full stop (superset routed separately).
_MEDICAL_RED_FLAGS = (
    "chest pain",
    "chest tight",
    "tight chest",
    "tightness in my chest",
    "tightness in the chest",
    "chest tightness",
    "dizzy",
    "dizziness",
    "light-headed",
    "lightheaded",
    "light headed",
    "faint",
    "short of breath",
    "shortness of breath",
    "breathless",
    "palpitation",
    "heart racing",
)
# Words that turn a body-part mention into a symptom (vs a bare, symptom-free mention).
_PAIN_WORDS = (
    "pain",
    "sore",
    "ache",
    "aching",
    "hurt",
    "tender",
    "niggle",
    "flare",
    "tight",
    "stiff",
    "twinge",
    "strain",
)
_PERSISTENT_WORDS = ("persistent", "ongoing", "weeks", "chronic", "still", "again", "recurring")
# "progressive" is handled separately so "non-progressive" does not read as worsening.
_WORSENING_WORDS = ("worse", "worsening", "getting worse", "sharp", "sharper")
# Poor / absent fuelling → fuelling penalty (next prescription capped at endurance).
_FUELLING_POOR_KEYWORDS = (
    "bonk",
    "bonked",
    "hit the wall",
    "hunger flat",
    "ran out of fuel",
    "ran out of gels",
    "no fuel",
    "under-fuel",
    "underfuel",
    "under fuel",
    "didn't eat",
    "didnt eat",
    "did not eat",
    "forgot to eat",
    "skipped breakfast",
    "skipped fuel",
    "no breakfast",
    "empty stomach",
    "nothing to eat",
    "no food",
    "undereat",
    "under-eat",
)


@dataclass
class CheckinState:
    """Raw check-in answers plus flags derived by a keyword pass (BUILD_SPEC §6)."""

    sleep: str = ""
    body: str = ""
    yesterday: str = ""
    flags: dict[str, bool] = field(default_factory=dict)

    def as_block(self) -> str:
        """Render the answers as a labelled context block for the agent."""
        return (
            "THIS MORNING'S CHECK-IN (athlete's own words — interpret these):\n"
            f"  Sleep / feel: {self.sleep or '(no answer)'}\n"
            f"  Soreness / illness / stress: {self.body or '(no answer)'}\n"
            f"  Yesterday's effort: {self.yesterday or '(no answer)'}"
        )


def _has_kw(text: str, keywords: tuple[str, ...]) -> bool:
    """Whole-word/phrase keyword match — avoids 'ill' matching inside a longer word etc."""
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)


def _protocol_triggered(text: str, protocol: dict) -> bool:
    """Whether one profile-defined personal protocol is triggered by the check-in text.

    A protocol (from athlete/profile.md's `personal_protocols`) names a `trigger` keyword,
    a `severity` rule, and an `action`. The condition keywords live in the profile, never
    here, so this module carries no athlete-specific medical vocabulary. Severity rules:
      * ``symptom``     — fires on any reported symptom (pain or a persistence word). A
                          hard-stop protocol: any signal above 0/10 removes intensity.
      * ``significant`` — fires only when the symptom is >1/10 or progressive/worsening; a
                          rating ≤1/10 that is explicitly stable/non-progressive does NOT
                          fire (trainable). A bare pain mention defaults to significant.
    """
    trigger = str(protocol.get("trigger", "")).lower().strip()
    if not trigger or not re.search(rf"\b{re.escape(trigger)}\b", text):
        return False
    severity = str(protocol.get("severity", "symptom")).lower()
    if severity == "symptom":
        return _has_kw(text, _PAIN_WORDS) or _has_kw(text, _PERSISTENT_WORDS)
    # 'significant' (and any other value): require an actual pain word, then grade it.
    if not _has_kw(text, _PAIN_WORDS):
        return False
    progressive = bool(re.search(r"\bprogressive\b", text)) and not re.search(
        r"non-?\s*progressive|not\s+progressive", text
    )
    if _has_kw(text, _WORSENING_WORDS) or progressive:
        return True
    rating = re.search(r"(\d+)\s*/\s*10", text)
    if rating:
        return int(rating.group(1)) > 1
    if _has_kw(text, ("non-progressive", "not progressive", "stable", "quiet", "settled")):
        return False
    return True


def _load_protocols() -> list[dict]:
    """Personal protocols from the athlete's profile frontmatter (empty list if none).

    Imported lazily to avoid a module cycle. The profile (private) owns the condition
    keywords and severity thresholds; the export ships only the fictional example's.
    """
    from domestique import context

    protocols = context.load_profile_frontmatter().get("personal_protocols") or []
    return [p for p in protocols if isinstance(p, dict)]


def _scan_flags(state: CheckinState, protocols: list[dict]) -> dict[str, bool]:
    """Whole-word keyword pass over all answers -> the guardrail flag set (BUILD_SPEC §6).

    `personal_protocol` is true when any profile-defined protocol is triggered — the
    generic replacement for the old per-condition flags, so no named condition lives here.
    """
    text = " ".join((state.sleep, state.body, state.yesterday)).lower()
    return {
        "illness": _has_kw(text, _ILLNESS_KEYWORDS),
        "red_flag_medical": _has_kw(text, _MEDICAL_RED_FLAGS),
        "personal_protocol": any(_protocol_triggered(text, p) for p in protocols),
        "fuelling_poor": _has_kw(text, _FUELLING_POOR_KEYWORDS),
    }


def _parse_answers_file(path: str | Path) -> dict[str, str]:
    """Parse an --answers markdown file with 'sleep:', 'body:', 'yesterday:' lines."""
    answers: dict[str, str] = {}
    current: str | None = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip().lstrip("#-* ").strip()
        matched = False
        for key in ("sleep", "body", "yesterday"):
            for prefix in (f"{key}:", f"{key} -", f"{key} —"):
                if line.lower().startswith(prefix):
                    answers[key] = line[len(prefix) :].strip()
                    current = key
                    matched = True
                    break
            if matched:
                break
        if not matched and current and line:
            answers[current] = (answers.get(current, "") + " " + line).strip()
    if not answers:
        raise ValueError(
            f"Could not parse any answers from {path}. Expected lines like "
            "'sleep: ...', 'body: ...', 'yesterday: ...'."
        )
    return answers


def run_checkin(
    *,
    sleep: str | None = None,
    body: str | None = None,
    yesterday: str | None = None,
    answers_path: str | None = None,
    protocols: list[dict] | None = None,
) -> CheckinState:
    """Collect the three answers interactively, or accept them non-interactively.

    Non-interactive if any of --sleep/--body/--yesterday or --answers is supplied;
    otherwise prompt one question at a time in the terminal (BUILD_SPEC §4.2).
    `protocols` overrides the profile's personal protocols (defaults to loading them).
    """
    provided = {"sleep": sleep, "body": body, "yesterday": yesterday}
    if answers_path:
        from_file = _parse_answers_file(answers_path)
        for key, value in from_file.items():
            provided[key] = provided[key] or value

    non_interactive = any(v is not None for v in provided.values())
    if non_interactive:
        state = CheckinState(
            sleep=provided["sleep"] or "",
            body=provided["body"] or "",
            yesterday=provided["yesterday"] or "",
        )
    else:
        collected: dict[str, str] = {}
        for key, question in QUESTIONS:
            collected[key] = typer.prompt(question).strip()
        state = CheckinState(**collected)

    state.flags = _scan_flags(state, _load_protocols() if protocols is None else protocols)
    return state
