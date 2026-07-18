"""Generate the field-test kit from the repo brain (build step: field-test kit).

Same pattern as sync_claude_app.py, but for *external* testers: it produces the artefacts a
trusted tester needs to run their own Domestique in their own Claude project against their own
Strava connector — with no fact about this repo's athlete carried across.

Two generated artefacts:
  * docs/starter-kit.md    — the athlete-AGNOSTIC coaching brain to paste into a Claude
                             project: the agnostic coach prompt (prompts/coach.starter.md,
                             which carries the medical disclaimer and the data-first onboarding
                             flow), the blank profile schema the coach fills in, and a short
                             "staying in sync" note (re-paste when the version changes).
  * docs/field-report.md   — the weekly report prompt: the tester pastes it into their coach
                             project once a week and the coach returns a structured field report
                             under fixed headings (Coaching Moments with GOOD/BAD CALL verdicts,
                             Feature Gaps, Behaviour Notes, One Change). It is the feedback the
                             field test runs on.

Athlete-agnostic is enforced MECHANICALLY, not by trust: `personal_data_leaks()` greps each
generated artefact for this repo's real profile frontmatter values and constraint strings, and
`generate()` raises `PersonalDataLeak` — failing generation — if any appear. The agnostic
prompt is a reviewed asset; the gate is the backstop proving it (and the assembly) stay clean.

The kit's blank schema adds one section beyond the private profile's four-section contract
(BUILD_SPEC §5): `## Injury protocols`, where onboarding records each athlete's own
symptom→action rules as personal guardrails. That is the field-test design (per the build
brief), not a change to athlete/profile.md's schema.
"""

from __future__ import annotations

import re
from pathlib import Path

from domestique import context, version
from domestique.sync_claude_app import PROJECT_INSTRUCTIONS_CHAR_BUDGET

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = Path(__file__).parent / "prompts"
COACH_STARTER_PATH = PROMPTS_DIR / "coach.starter.md"

STARTER_KIT_PATH = REPO_ROOT / "docs" / "starter-kit.md"
FIELD_REPORT_PATH = REPO_ROOT / "docs" / "field-report.md"

_SECTION_RULE = "\n\n---\n\n"

# The blank-schema field/section descriptions. Frontmatter keys are taken from the schema
# contract in context.py so the template can never drift from it; `## Injury protocols` is the
# kit-only section (see module docstring).
_FIELD_HELP = {
    "ftp_w": "current FTP in watts — the confirmed estimate from onboarding",
    "ftp_date": "when that FTP was set/estimated (YYYY-MM)",
    "weight_kg": "optional — enables W/kg and fuelling maths",
    "weekly_hours_typical": "typical training hours in a normal week",
    "constraints": (
        'recurring scheduling limits, e.g. ["long ride Sat", "no hard efforts on work nights"]'
    ),
}
_SECTION_HELP = (
    (
        "Goals",
        "Season targets and any races with dates and priority (A/B/C). An A-race puts "
        "the coach in event mode.",
    ),
    (
        "Patterns",
        "Evidence-backed observations only, each tied to a date or activity. The "
        "coach fills these in from your data over time — leave blank at the start.",
    ),
    (
        "Injury protocols",
        "Your personal, non-negotiable safety rules. One line per current or "
        'recurring injury: symptom → what the coach must do, e.g. "a recurring '
        'tendon symptom above 0/10 → remove intensity". The coach enforces these '
        "as hard as the universal safety rules.",
    ),
    (
        "History",
        "Brief training background: years riding, structured or not, typical weekly "
        "load, relevant injury history.",
    ),
    ("Preferences", "Session types you like and dislike, indoor vs outdoor, coaching tone."),
)


class PersonalDataLeak(RuntimeError):
    """Raised when a generated field-test artefact contains this athlete's personal data."""


def load_starter_prompt() -> str:
    """Return the athlete-agnostic coach prompt (prompts/coach.starter.md), verbatim."""
    return COACH_STARTER_PATH.read_text(encoding="utf-8")


def blank_profile_schema() -> str:
    """The empty profile template a tester's coach fills in during onboarding.

    Frontmatter keys come from the schema contract (context.ALLOWED_FRONTMATTER_KEYS); the H2
    sections are the four contract sections plus the kit-only `## Injury protocols`.
    `personal_protocols` is surfaced to testers as that prose section (the kit is LLM-driven,
    so it needs no machine-readable frontmatter for them), so it is omitted from the
    frontmatter block here — still derived from the contract, minus that one field.
    """
    frontmatter_keys = [k for k in context.ALLOWED_FRONTMATTER_KEYS if k != "personal_protocols"]
    lefts = {
        key: f"{key}: {'[]' if key == 'constraints' else ''}".rstrip() for key in frontmatter_keys
    }
    width = max(len(left) for left in lefts.values())
    lines = ["---"]
    for key in frontmatter_keys:
        lines.append(f"{lefts[key].ljust(width)}  # {_FIELD_HELP[key]}")
    lines.append("---")
    body = "\n\n".join(f"## {name}\n<!-- {help_} -->" for name, help_ in _SECTION_HELP)
    return "\n".join(lines) + "\n\n" + body


def _banner(title: str, ver: str, purpose: str) -> str:
    """The generated / do-not-hand-edit banner shared by both artefacts.

    Stamped with the deterministic DOMESTIQUE_VERSION so regeneration is byte-identical to the
    committed file (the CI freshness gate) and testers can tell when to re-paste the kit.
    """
    comment = (
        "<!--\n"
        "GENERATED FILE — DO NOT HAND-EDIT.\n"
        f"Produced by `domestique sync-starter-kit` from the repo's brain. {purpose}\n"
        f"Domestique version: {ver}\n"
        "To change it, edit the source assets (prompts/coach.starter.md et al.) and re-run "
        "sync-starter-kit; edits made directly here are overwritten (CI fails on any drift).\n"
        "Athlete-agnostic by construction: generation greps for this repo's real profile "
        "values and fails if any leak. Safe to share with external testers.\n"
        "-->"
    )
    notice = (
        f"# {title}\n\n"
        f"> **Generated — do not hand-edit.** `Domestique {ver}`. Assembled by `domestique "
        "sync-starter-kit` from the repo's versioned assets."
    )
    return comment + "\n\n" + notice


def build_starter_kit(ver: str) -> str:
    """Assemble docs/starter-kit.md: agnostic coach prompt + blank profile schema."""
    banner = _banner(
        "Domestique — Field-Test Starter Kit",
        ver,
        "Paste the whole file into a Claude project's custom instructions.",
    )
    prompt_block = (
        "**Coaching brain** — paste everything below into your Claude project's custom "
        "instructions. It carries the medical disclaimer (§0) and the data-first onboarding "
        "flow (§0a) the coach runs on first contact.\n\n" + load_starter_prompt().strip()
    )
    schema_block = (
        "**Blank profile schema** — the coach writes your profile into this shape during "
        "onboarding and keeps it updated. You don't fill it in by hand; it's here so you can "
        "see what the coach is building and check it back.\n\n```markdown\n"
        + blank_profile_schema().strip()
        + "\n```"
    )
    sync_block = (
        "**Staying in sync (versions).** This kit carries a version in its header (e.g. "
        f"`Domestique {ver}`) — a fingerprint of the coaching brain. **When the version "
        "changes, re-paste this whole file** into your project's custom instructions; until "
        "you do, your project is running the old brain. Your briefings and weekly field "
        "reports state the version they ran under, so any output traces back to the exact kit."
    )
    return (
        banner
        + _SECTION_RULE
        + prompt_block
        + _SECTION_RULE
        + schema_block
        + _SECTION_RULE
        + sync_block
        + "\n"
    )


def build_field_report(ver: str) -> str:
    """Assemble docs/field-report.md: the weekly report prompt testers paste into their coach.

    Athlete-agnostic (no facts about this repo's athlete), so it passes the personal-data gate
    like the other artefacts. It instructs the tester's coach to return a structured report
    under fixed headings, and instructs the tester to generalise anything medical, keep
    scenarios anonymised, delete anything they'd rather not share, and stamp the kit version.
    """
    banner = _banner("Domestique — Weekly Field Report", ver, "Weekly report prompt for testers.")
    body = """\
**Privacy — non-negotiable.** No personal, medical, or identifying details in this report, ever.
Describe coaching behaviour generically ("handled a recurring niggle well"), never the condition.

**Weekly field report.** Once a week (a quiet evening works well), paste everything below the
line into your Domestique coach project — or just say yes when the coach offers it, which it
does at any contact once 7+ days have passed since your last report ("two minutes, then your
briefing"). Onboarding helps you pick a day and set a recurring phone reminder, so the cadence
holds. The coach returns a structured report you can skim, trim, and send back — it is the
signal the whole field test runs on. Keep it honest over polished: the bad calls are worth more
than the good ones. When the report is done, the coach signs off by asking you to copy the whole
thing and send it to Tom (project maintainer) — that hand-off is the feedback.

---

Produce my Domestique field report for the past week. Use **exactly these four headings**, in
this order, and nothing else. Be specific; "nothing to report" is a valid entry under any
heading. Start the report with a single line — `Domestique <version>` — copying the version
from the header of this project's instructions, so the report can be traced to the exact kit
that produced it.

## Coaching Moments
The 3–6 moments that actually mattered this week — a briefing, a readiness call, a session, a
watch-out. For each: one line describing it, then a verdict in bold — **GOOD CALL** or **BAD
CALL** — and one line of why. Include the bad calls first; they are the most useful.

## Feature Gaps
Where the coach hit a wall: something it couldn't do, data it lacked, a question it couldn't
answer, a workflow that was clumsy.

## Behaviour Notes
How it behaved, separate from whether the advice was right: tone, over- or under-caution,
repetition, anything that felt off or untrustworthy.

## One Change
The single highest-value change that would most improve next week. Exactly one.

---

Before you send it back:
- **Generalise anything medical.** Refer to health, illness or injury in general terms — "a
  lower-limb niggle", not a diagnosis or the specifics — this report is about the coach, not
  your medical record.
- **Keep any scenarios anonymised.** No names, exact locations, or dates that identify you or
  anyone else; describe the situation, not the people.
- **Delete anything you'd rather not share.** The report is yours — cut any line freely before
  you send it. Less, shared honestly, beats more held back.
"""
    return banner + _SECTION_RULE + body


def personal_data_leaks(text: str) -> list[str]:
    """Return any of this repo's personal profile tokens found verbatim in `text` (empty = ok).

    Tokens are the real profile's distinctive frontmatter values (ftp_w, ftp_date, weight_kg)
    and every constraint string, matched with word/token boundaries. `weekly_hours_typical` is
    deliberately excluded: a bare small integer legitimately appears in generic training
    prescriptions (rep schemes, gram counts) and carries no identifying signal, so scanning for
    it would only produce false failures.
    """
    front = context.load_profile_frontmatter()
    tokens: list[str] = []
    for key in ("ftp_w", "ftp_date", "weight_kg"):
        val = front.get(key)
        if val is not None and str(val).strip():
            tokens.append(str(val).strip())
    for constraint in front.get("constraints", []) or []:
        token = str(constraint).strip()
        if token:
            tokens.append(token)

    found: list[str] = []
    for token in tokens:
        if token.isdigit():
            # Digit boundaries: catch a unit-suffixed leak like "362W" or "75 kg", but not a
            # different number that merely contains the digits (3620, 1362).
            pattern = rf"(?<!\d){re.escape(token)}(?!\d)"
        elif re.fullmatch(r"[\d-]+", token):
            # Date-like (e.g. ftp_date "2026-07"): a leak only when it stands alone, not when
            # it is a prefix of a longer date — otherwise the generated version stamp
            # "2026-07-13+…" would trip its own gate. Forbid an adjacent digit or hyphen.
            pattern = rf"(?<![\d-]){re.escape(token)}(?![\d-])"
        else:
            # Word/phrase boundaries for single-word tokens and multi-word constraint strings —
            # a leak regardless of the unit or punctuation that trails them.
            pattern = rf"(?<!\w){re.escape(token)}(?!\w)"
        if re.search(pattern, text, re.IGNORECASE):
            found.append(token)
    return found


def generate() -> dict[Path, str]:
    """Build both artefacts and enforce the personal-data gate. Returns {path: text}.

    Raises PersonalDataLeak (failing generation) if either artefact carries this athlete's
    profile data — the mechanical guarantee that the kit is athlete-agnostic.
    """
    ver = version.domestique_version()
    artefacts = {
        STARTER_KIT_PATH: build_starter_kit(ver),
        FIELD_REPORT_PATH: build_field_report(ver),
    }
    leaks = {path.name: personal_data_leaks(text) for path, text in artefacts.items()}
    offenders = {name: found for name, found in leaks.items() if found}
    if offenders:
        detail = "; ".join(f"{name}: {', '.join(found)}" for name, found in offenders.items())
        raise PersonalDataLeak(
            "Refusing to generate — personal profile data leaked into the field-test kit "
            f"({detail}). Scrub prompts/coach.starter.md (and the assembly) until the kit "
            "carries no athlete-specific facts."
        )
    return artefacts


def oversize_artefacts(artefacts: dict[Path, str]) -> dict[str, int]:
    """Names→length of any artefact over the project-instructions budget (for a caller warning).

    Nothing in the kit is droppable (prompt, schema and onboarding are all load-bearing), so
    this reports rather than trims — the caller warns and the source is tightened by hand.
    """
    return {
        path.name: len(text)
        for path, text in artefacts.items()
        if len(text) > PROJECT_INSTRUCTIONS_CHAR_BUDGET
    }


def write_outputs(artefacts: dict[Path, str]) -> list[Path]:
    """Write each artefact to disk; return the paths written."""
    for path, text in artefacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return list(artefacts)
