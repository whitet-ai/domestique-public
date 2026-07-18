"""Generate the Claude-app project instructions from the repo's brain (BUILD_SPEC §5, step 4).

PRD §5 design principle: *the product is the agent plus its context; every interface is a
thin skin over that brain.* The Claude app carries no interface code — the repo instead
*generates* its project instructions from the same versioned assets the CLI uses, so the
phone experience and the CLI share one brain and stay in sync. This module does that
assembly, deterministically and with no model call:

  prompts/coach.md  +  athlete/profile.md  +  athlete/races.yaml  +  a concise summary of
  the deterministic guardrail rules (guardrails.summary())

into a single markdown document, emitted to stdout and written to
docs/claude-app-instructions.md, under a header that marks it generated, records the
source commit, and forbids hand-editing (the source assets are edited instead, then this
is re-run).

Size discipline (BUILD_SPEC step-4 note): Claude project custom-instructions have a length
limit. If the assembly runs long, the lowest-priority section (the race calendar) is
dropped first, always keeping the coach prompt, the profile facts, and the guardrails; what
was trimmed is stated in the header rather than silently cut.

Privacy: the generated file embeds the real athlete profile (health/weight data), so it is
private-repo-only and must be scrubbed from the public showcase exactly like athlete/ and
briefings/ (BUILD_SPEC §3a) — it is regenerated there from profile.example.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domestique import agent, context, guardrails, version

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "docs" / "claude-app-instructions.md"

# Conservative character budget approximating the Claude project custom-instructions limit.
# It is a safety valve, not a normal-path constraint: the assembled brain is well under it.
# If the product limit changes, adjust this one number — the trimming logic follows it.
PROJECT_INSTRUCTIONS_CHAR_BUDGET = 40_000

_SECTION_RULE = "\n\n---\n\n"


@dataclass
class Section:
    """One assembled block. `droppable` sections are trimmed first when over budget."""

    name: str
    body: str
    droppable: bool = False


def _sections(ftp_w: int) -> list[Section]:
    """The ordered content blocks, each with a provenance label (source assets verbatim)."""
    return [
        Section(
            "coach prompt",
            "**Master coaching prompt** — `prompts/coach.md`, verbatim. This is the "
            "system prompt; every rule, mode and output contract below is authoritative.\n\n"
            + agent.load_coach_prompt().strip(),
        ),
        Section(
            "profile",
            "**Athlete profile** — `athlete/profile.md`, the context layer and source of "
            "truth for FTP, constraints and evidence-backed patterns. You may *cite* these "
            "facts; you may not edit them (that is the CLI's `update-profile` flow).\n\n"
            + context.load_profile().strip(),
        ),
        Section(
            "guardrails",
            "**Deterministic guardrails** — a summary of the hard rules enforced in code "
            "(`guardrails.py`) on every CLI briefing. Honour them here too:\n\n"
            + guardrails.summary(ftp_w),
        ),
        Section(
            "races",
            "**Target events** — `athlete/races.yaml`. An A-priority event is the sole "
            "trigger into event-preparation mode (coach prompt §2).\n\n```yaml\n"
            + context.load_races().strip()
            + "\n```",
            droppable=True,
        ),
    ]


def _header(ver: str, trimmed: list[str]) -> str:
    """The generated banner: an HTML maintenance comment + a visible generated notice.

    The stamp is the deterministic DOMESTIQUE_VERSION (not a git commit), so regeneration is
    byte-identical to the committed file — the property the CI freshness gate relies on.
    """
    trim_line = (
        "\nTRIMMED to fit the project-instructions size limit — dropped: "
        + ", ".join(trimmed)
        + "."
        if trimmed
        else ""
    )
    comment = (
        "<!--\n"
        "GENERATED FILE — DO NOT HAND-EDIT.\n"
        "Produced by `domestique sync-claude-app` from the repo's brain: prompts/coach.md "
        "+ athlete/profile.md + athlete/races.yaml + the guardrails.py rule summary.\n"
        f"Domestique version: {ver}\n"
        "To change these instructions, edit the source assets and re-run sync-claude-app; "
        "edits made directly here are overwritten (CI regenerates and fails on any drift).\n"
        "PRIVACY: embeds the real athlete profile — scrub from the public showcase like "
        "athlete/ and briefings/ (BUILD_SPEC §3a); regenerate there from profile.example.md."
        + trim_line
        + "\n-->"
    )
    notice = (
        "# Domestique — Claude Project Instructions\n\n"
        f"> **Generated — do not hand-edit.** `Domestique {ver}`. Assembled by `domestique "
        "sync-claude-app` from the repo's versioned assets. Paste into the Claude project's "
        "custom instructions. To change them, edit the source assets and re-run the command."
        + (f"\n>\n> _{trim_line.strip()}_" if trimmed else "")
    )
    return comment + "\n\n" + notice


def build_instructions(ftp_w: int | None = None) -> tuple[str, list[str]]:
    """Assemble the full instructions document. Returns (markdown, trimmed_section_names).

    Sections are dropped lowest-priority-first (only the race calendar is droppable) until
    the document fits PROJECT_INSTRUCTIONS_CHAR_BUDGET; the coach prompt, profile and
    guardrails are always kept. `trimmed` names what was cut, for the header and the caller.
    """
    if ftp_w is None:
        ftp_w = context.profile_ftp_w()
    ver = version.domestique_version()
    sections = _sections(ftp_w)
    trimmed: list[str] = []

    def render(secs: list[Section], trims: list[str]) -> str:
        body = _SECTION_RULE.join(s.body for s in secs)
        return _header(ver, trims) + _SECTION_RULE + body + "\n"

    doc = render(sections, trimmed)
    # Drop droppable sections (lowest priority last in the list) until within budget.
    while len(doc) > PROJECT_INSTRUCTIONS_CHAR_BUDGET and any(s.droppable for s in sections):
        victim = next(s for s in reversed(sections) if s.droppable)
        sections = [s for s in sections if s is not victim]
        trimmed.append(victim.name)
        doc = render(sections, trimmed)

    return doc, trimmed


def write_output(doc: str) -> Path:
    """Write the assembled instructions to docs/claude-app-instructions.md; return the path."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(doc, encoding="utf-8")
    return OUTPUT_PATH
