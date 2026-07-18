"""Generate the WhatsApp onboarding invite for a new field tester (build: field-test kit).

A tiny sibling of sync_starter_kit: it assembles the one message the maintainer sends over
WhatsApp to onboard a new trusted tester, from the same repo brain, deterministically and with
no model call. Output goes to docs/invite-message.txt and stdout, and — like the other sync
artefacts — the CI freshness gate regenerates it and fails on any drift.

Design constraints (from the invite brief):
  * Plain text only. No markdown syntax (no #, *, backticks, link brackets) — WhatsApp renders
    none of it, and asterisks would turn into stray bold. Links are bare URLs. Short lines.
  * A hard character budget (INVITE_CHAR_BUDGET) so the message stays WhatsApp-friendly; over
    budget, generation FAILS rather than silently shipping a wall of text.
  * The public repo URL is taken from ONE config constant (PUBLIC_REPO_URL) and both doc links
    are derived from it, so it is set in exactly one place.
  * The message carries the deterministic Domestique version stamp at the end, so the maintainer
    can tell which kit an invitee was sent (and so regeneration is byte-identical for CI).

Athlete-agnostic like the rest of the kit, and enforced the same mechanical way: generation
runs the personal-data leak gate (sync_starter_kit.personal_data_leaks) over the message and
raises PersonalDataLeak if any of this repo's real profile values appear. The invite carries no
athlete facts by construction; the gate is the backstop that proves it.
"""

from __future__ import annotations

from pathlib import Path

from domestique import version
from domestique.sync_starter_kit import PersonalDataLeak, personal_data_leaks

REPO_ROOT = Path(__file__).resolve().parents[2]
INVITE_PATH = REPO_ROOT / "docs" / "invite-message.txt"

# The public showcase repo URL — the SINGLE place it is defined. Both doc links in the invite
# are built from it (blob/main/docs/...), so pointing invitees at a different host or fork is a
# one-line change here. (The private working repo lives elsewhere; this is the copy testers see.)
PUBLIC_REPO_URL = "https://github.com/whitet-ai/domestique-public"

# WhatsApp-friendly ceiling. The brief asks for "under ~900 characters"; generation fails over
# this so the message can never quietly bloat past a comfortable single send.
INVITE_CHAR_BUDGET = 900


def _blob_url(doc: str) -> str:
    """A stable link to a doc on the public repo's main branch (blob/main/docs/<doc>)."""
    return f"{PUBLIC_REPO_URL}/blob/main/docs/{doc}"


def build_invite(ver: str) -> str:
    """Assemble the plain-text WhatsApp onboarding message, stamped with the kit version."""
    starter = _blob_url("starter-kit.md")
    report = _blob_url("field-report.md")
    return (
        "Domestique: an AI cycling coach I built — you run your own copy, "
        "it never sends me your data.\n"
        "\n"
        "To set it up (about 5 min):\n"
        "1. 📱 In the Claude app, create a project called Domestique.\n"
        f"2. 📋 Open {starter} — copy the whole file, paste it into the project's "
        "instructions, and save.\n"
        "3. 🔗 Connect the Strava connector in Claude's settings.\n"
        '4. 🚴 Start a chat and say "hi coach" — it reads your recent riding and '
        "interviews you.\n"
        "\n"
        f"📝 Once a week, run the field-report prompt ({report}) and send me what it "
        "produces — that's the feedback.\n"
        "\n"
        "⚠️ Advice, not medicine: skip this if you have heart or serious health issues, "
        "and illness always means rest.\n"
        "\n"
        f"Kit version: {ver}\n"
    )


class InviteOverBudget(RuntimeError):
    """Raised when the assembled invite exceeds the WhatsApp character budget."""


def generate() -> str:
    """Build the invite and enforce the leak gate and the character budget. Returns the text.

    Raises PersonalDataLeak if this athlete's profile data leaks into the message (the same
    mechanical guarantee the starter kit uses), or InviteOverBudget if it runs past
    INVITE_CHAR_BUDGET.
    """
    ver = version.domestique_version()
    text = build_invite(ver)

    leaks = personal_data_leaks(text)
    if leaks:
        raise PersonalDataLeak(
            "Refusing to generate — personal profile data leaked into the invite "
            f"({', '.join(leaks)}). The invite must carry no athlete-specific facts."
        )

    if len(text) > INVITE_CHAR_BUDGET:
        raise InviteOverBudget(
            f"Invite is {len(text):,} chars, over the WhatsApp budget "
            f"({INVITE_CHAR_BUDGET:,}). Tighten build_invite() until it fits."
        )
    return text


def write_output(text: str) -> Path:
    """Write the invite message to docs/invite-message.txt; return the path."""
    INVITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    INVITE_PATH.write_text(text, encoding="utf-8")
    return INVITE_PATH
