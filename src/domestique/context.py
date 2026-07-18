"""Context assembly: load profile + races + recent briefings into ordered blocks.

Assembly order (BUILD_SPEC §4 step 3): system prompt -> athlete profile ->
races.yaml -> activity block -> check-in answers -> today's date/day-of-week.

The agent may *cite* the profile; only the human (or the explicit update-profile
flow) may edit it (BUILD_SPEC §5). This module reads athlete/ and owns the profile
schema contract — validation and a pure frontmatter-field transform — but never writes
files itself; the update-profile flow (cli.py) performs the actual write.

Scaffold only in step 1; wired up in build step 2 (brief) and step 4 (update-profile).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from domestique import version

REPO_ROOT = Path(__file__).resolve().parents[2]
ATHLETE_DIR = REPO_ROOT / "athlete"
PROFILE_PATH = ATHLETE_DIR / "profile.md"
PROFILE_EXAMPLE_PATH = ATHLETE_DIR / "profile.example.md"
RACES_PATH = ATHLETE_DIR / "races.yaml"
BRIEFINGS_DIR = REPO_ROOT / "briefings"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# The profile schema is a contract (BUILD_SPEC §5): exactly these frontmatter fields and
# these H2 prose sections — no others. The update-profile flow validates against this and
# refuses to add fields or drop sections (CLAUDE.md hard rule). SCALAR_FRONTMATTER_KEYS are
# the fields the non-interactive `--field KEY=VALUE` path may set; `constraints` is a list,
# edited only in the interactive editor.
SCALAR_FRONTMATTER_KEYS = ("ftp_w", "ftp_date", "weight_kg", "weekly_hours_typical")
# `personal_protocols` is a list (like `constraints`), edited only in the interactive editor:
# each entry is a mapping {trigger, severity, action} defining an enforceable personal
# injury/symptom protocol. checkin.py reads them to set the generic `personal_protocol`
# guardrail flag, so the condition keywords live in the profile, never in shipped code.
ALLOWED_FRONTMATTER_KEYS = (*SCALAR_FRONTMATTER_KEYS, "constraints", "personal_protocols")
REQUIRED_H2_SECTIONS = ("Goals", "Patterns", "History", "Preferences")


def _daily_task(ftp_w: int) -> str:
    """The [DAILY] cadence directive, with the power target anchored to the profile FTP.

    The `brief` command IS the daily morning briefing (BUILD_SPEC §4; coach prompt §3):
    select the [DAILY] cadence and its §11 contract explicitly so the coach does not slip
    into [WEEKLY] Sunday-planning just because today is a Sunday. The FTP is read from the
    profile (never hard-coded) so the prompt always tracks the single source of truth.
    """
    return (
        "=== YOUR TASK: TODAY'S MORNING BRIEFING ===\n"
        "This is the [DAILY] morning briefing (coach prompt §3). Produce ONLY the daily "
        "briefing, never a weekly plan, even if today is a Sunday. Follow the §11 [DAILY] "
        "output contract exactly, in this order:\n"
        "  1. Mode statement (one line, e.g. 'Mode: Race performance — no A-event on file').\n"
        "  2. **Green / Amber / Red readiness** with a 2–3 sentence read of the check-in "
        "against recent load.\n"
        "  3. Today's session: duration, structure, and power targets in W and %FTP "
        f"anchored to the profile FTP (currently {ftp_w}W).\n"
        "  4. Why — grounded in the profile and the real recent activities above "
        "(cite specific rides by name/date).\n"
        "  5. Watch-outs — only if earned.\n"
        "Apply the §12 readiness model and the §8 safety rules. If the athlete has already "
        "ridden today per the data, give the readiness read and the operative call for the "
        "remainder of today (and any recovery guidance), rather than prescribing a duplicate "
        "session. Never invent activity facts; if data is missing, say so."
    )


def load_profile() -> str:
    """Return athlete/profile.md, falling back to the committed example if absent."""
    if PROFILE_PATH.exists():
        return PROFILE_PATH.read_text(encoding="utf-8")
    return PROFILE_EXAMPLE_PATH.read_text(encoding="utf-8")


def load_profile_frontmatter() -> dict:
    """Parse the YAML frontmatter of the profile — the schema contract (BUILD_SPEC §5)."""
    match = _FRONTMATTER_RE.match(load_profile())
    if not match:
        return {}
    return yaml.safe_load(match.group(1)) or {}


def profile_ftp_w() -> int:
    """The athlete's FTP, read from the profile frontmatter (the single source of truth).

    Never hard-coded in live code (CLAUDE.md hard rule): every power decision reads this.
    Raises if the profile is missing ftp_w, rather than silently substituting a number.
    """
    ftp = load_profile_frontmatter().get("ftp_w")
    if ftp is None:
        raise ValueError(
            "athlete/profile.md frontmatter is missing 'ftp_w' — the FTP source of truth "
            "(BUILD_SPEC §5 schema contract)."
        )
    return int(ftp)


def validate_profile(text: str) -> list[str]:
    """Check a profile against the schema contract; return a list of violations (empty = ok).

    Enforces BUILD_SPEC §5: parseable YAML frontmatter carrying only the allowed fields
    (with ftp_w present, since it is the FTP source of truth), and all four required H2
    prose sections. The update-profile flow refuses to write a profile that fails this.
    """
    violations: list[str] = []

    match = _FRONTMATTER_RE.match(text)
    if not match:
        return ["frontmatter: missing or malformed YAML frontmatter (--- … ---) block"]
    try:
        front = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        return [f"frontmatter: not valid YAML ({exc})"]
    if not isinstance(front, dict):
        return ["frontmatter: frontmatter must be a mapping of fields"]

    unknown = [k for k in front if k not in ALLOWED_FRONTMATTER_KEYS]
    if unknown:
        violations.append(
            "frontmatter: unknown field(s) "
            + ", ".join(sorted(unknown))
            + " — the schema is a contract; do not add fields (BUILD_SPEC §5)"
        )
    if "ftp_w" not in front:
        violations.append("frontmatter: missing 'ftp_w' — the FTP source of truth")

    for section in REQUIRED_H2_SECTIONS:
        if not re.search(rf"^##\s+{re.escape(section)}\b", text, re.MULTILINE):
            violations.append(f"sections: missing required H2 section '## {section}'")

    return violations


def apply_frontmatter_fields(text: str, updates: dict[str, str]) -> str:
    """Return `text` with the given scalar frontmatter fields replaced in place.

    A pure line-level replacement inside the frontmatter block — it preserves the rest of
    the file (comments, section prose) byte-for-byte and never adds a field: a key that is
    not already present raises, so the flow cannot invent schema fields (BUILD_SPEC §5).
    Only SCALAR_FRONTMATTER_KEYS are accepted; `constraints` (a list) is editor-only.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("profile has no frontmatter block to update")
    block = match.group(1)
    lines = block.split("\n")

    for key, value in updates.items():
        if key not in SCALAR_FRONTMATTER_KEYS:
            raise ValueError(
                f"'{key}' is not an updatable scalar field; allowed: "
                + ", ".join(SCALAR_FRONTMATTER_KEYS)
                + " (edit constraints or prose in the editor)"
            )
        key_re = re.compile(rf"^(\s*{re.escape(key)}\s*:).*$")
        for i, line in enumerate(lines):
            if key_re.match(line):
                lines[i] = key_re.sub(rf"\1 {value}", line)
                break
        else:
            raise ValueError(
                f"'{key}' is not present in the profile frontmatter — refusing to add a "
                "field the schema contract does not already define (BUILD_SPEC §5)"
            )

    new_block = "\n".join(lines)
    return text[: match.start(1)] + new_block + text[match.end(1) :]


def load_races() -> str:
    """Return athlete/races.yaml verbatim (target events; source of truth, BUILD_SPEC §5)."""
    if RACES_PATH.exists():
        return RACES_PATH.read_text(encoding="utf-8")
    return "# races.yaml not found — no target events on file."


def days_to_next_a_race(today: date) -> int | None:
    """Whole days to the next upcoming A-priority race in races.yaml (None if none).

    Drives the guardrail race-protection window (BUILD_SPEC §6). Past-dated A-races and
    B/C events are ignored; only a future or same-day A-event returns a countdown.
    """
    if not RACES_PATH.exists():
        return None
    try:
        data = yaml.safe_load(RACES_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    upcoming: list[int] = []
    for race in data.get("races", []) or []:
        if str(race.get("priority", "")).upper() != "A":
            continue
        when = race.get("date")
        if isinstance(when, str):
            try:
                when = date.fromisoformat(when)
            except ValueError:
                continue
        if isinstance(when, date):
            delta = (when - today).days
            if delta >= 0:
                upcoming.append(delta)
    return min(upcoming) if upcoming else None


def assemble_context(activity_block: str, checkin_block: str, today: str) -> str:
    """Assemble the ordered context blocks passed to the agent (BUILD_SPEC §4.3).

    Order: athlete profile -> races.yaml -> activity block -> check-in answers ->
    today's date/day-of-week. The system prompt (prompts/coach.md) is passed
    separately as the model's system message by agent.py, not embedded here.
    """
    return "\n\n".join(
        (
            "=== ATHLETE PROFILE (athlete/profile.md — source of truth; you may cite, "
            "not edit) ===\n" + load_profile().strip(),
            "=== TARGET EVENTS (athlete/races.yaml) ===\n" + load_races().strip(),
            "=== " + activity_block.strip(),
            checkin_block.strip(),
            f"=== TODAY ===\n{today}\nDomestique version: {version.domestique_version()}",
            _daily_task(profile_ftp_w()),
        )
    )
