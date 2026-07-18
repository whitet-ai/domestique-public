"""Typer CLI — the thin terminal skin over the agent (BUILD_SPEC §3, §4).

Commands (implemented across the build order in PRD §9):
  brief          — morning briefing: check-in -> context -> Claude -> briefing (step 2)
  update-profile — the explicit, human-in-the-loop context-layer update flow (step 4)
  sync-claude-app — emit Claude-app project instructions from repo assets (step 4)
  sync-starter-kit — emit the athlete-agnostic field-test kit for testers (field-test kit)
  sync-invite     — emit the WhatsApp onboarding invite for a new tester (field-test kit)

Step 1 scaffolds the command surface; brief lands in step 2, update-profile and
sync-claude-app in step 4.
"""

from __future__ import annotations

import difflib
import os
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import typer

from domestique import agent, checkin, context, guardrails, strava, version
from domestique import sync_claude_app as claude_sync
from domestique import sync_invite as invite
from domestique import sync_starter_kit as starter_kit

app = typer.Typer(
    name="domestique",
    help="Personal agentic cycling coach.",
    no_args_is_help=True,
    add_completion=False,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIEFINGS_DIR = REPO_ROOT / "briefings"

# Hoisted to a module-level singleton (ruff B008): the allowed-keys list is composed once
# at import from the schema contract in context.py, and typer reuses the OptionInfo object.
_FIELD_HELP = (
    "Non-interactive scalar frontmatter update, KEY=VALUE (e.g. -f ftp_w=365). Repeatable. "
    "Allowed keys: " + ", ".join(context.SCALAR_FRONTMATTER_KEYS) + "."
)
_FIELD_OPTION = typer.Option(None, "--field", "-f", help=_FIELD_HELP)

_SAFE_FALLBACK = (
    "Mode: Race performance.\n\n"
    "**Readiness: Red (safe fallback).**\n\n"
    "The generated briefing did not pass the output guardrails twice, so Domestique "
    "is falling back to a rest day rather than show unchecked advice. Take today easy "
    "— light spin or full rest — and re-run the briefing. (Logged for review.)"
)


@app.command()
def brief(
    sleep: str = typer.Option(None, help="Non-interactive check-in: how you slept / feel."),
    body: str = typer.Option(None, help="Non-interactive check-in: anything sore / on your mind."),
    yesterday: str = typer.Option(None, help="Non-interactive check-in: how yesterday felt."),
    answers: str = typer.Option(None, help="Path to a markdown file with the check-in answers."),
    activities: str = typer.Option(
        None,
        help="Path to raw Strava MCP JSON (activities/zones/performance). Required when the "
        "hosted connector is not attached to this process (BUILD_SPEC §4.1 auth note).",
    ),
) -> None:
    """Generate the morning briefing: check-in -> context -> Claude (BUILD_SPEC §4)."""
    # 1. Check-in (interactive, or non-interactive via flags / --answers).
    state = checkin.run_checkin(sleep=sleep, body=body, yesterday=yesterday, answers_path=answers)

    # 2. Fetch: summarise the last 28 days from Strava into a compact block (§4.1).
    if activities:
        activity_block = strava.activity_block(activities)
    elif agent._strava_mcp_servers():
        activity_block = (
            "RECENT TRAINING: the hosted Strava MCP is attached to this call — fetch "
            "the last 28 days (list_activities, get_athlete_zones, and "
            "get_activity_performance for the 3 most recent rides) before briefing."
        )
    else:
        typer.secho(
            "No Strava data source. Pass --activities <file> with raw Strava MCP JSON, "
            "or set STRAVA_MCP_URL / STRAVA_MCP_TOKEN to attach the connector.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    # 3. Context assembly (§4.3).
    today = date.today()
    today_str = today.strftime("%Y-%m-%d (%A)")
    ctx = context.assemble_context(activity_block, state.as_block(), today_str)

    # 4-6. Call Claude, run the guardrail pass, retry once on failure, else fall back.
    days_to_race = context.days_to_next_a_race(today)
    ftp_w = context.profile_ftp_w()  # single source of truth (BUILD_SPEC §5), never hard-coded
    briefing = _generate_with_guardrails(ctx, state.flags, days_to_race, ftp_w)

    # Output: stdout + briefings/YYYY-MM-DD.md (§4.5).
    typer.echo(briefing)
    out_path = BRIEFINGS_DIR / f"{today:%Y-%m-%d}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(briefing.rstrip() + "\n", encoding="utf-8")
    typer.secho(f"\nSaved to {out_path.relative_to(REPO_ROOT)}", fg=typer.colors.GREEN, err=True)


def _generate_with_guardrails(
    ctx: str, flags: dict[str, bool], days_to_race: int | None, ftp_w: int
) -> str:
    """Call the agent, run guardrails, retry once with the violation, then fall back (§4.6)."""
    briefing = agent.run_briefing(ctx)
    result = guardrails.check_briefing(
        briefing, ftp_w=ftp_w, checkin_flags=flags, days_to_a_race=days_to_race
    )
    if result.passed:
        return briefing

    violation_note = (
        "GUARDRAIL VIOLATION — your previous briefing failed these deterministic checks: "
        + "; ".join(result.violations)
        + ". Regenerate the briefing so it complies. These bounds are non-negotiable."
    )
    briefing = agent.run_briefing(ctx, extra_directive=violation_note)
    result = guardrails.check_briefing(
        briefing, ftp_w=ftp_w, checkin_flags=flags, days_to_a_race=days_to_race
    )
    if result.passed:
        return briefing

    typer.secho(
        "Guardrails failed twice — using safe fallback. Violations: "
        + "; ".join(result.violations),
        fg=typer.colors.RED,
        err=True,
    )
    return _SAFE_FALLBACK


@app.command(name="update-profile")
def update_profile(
    field: list[str] = _FIELD_OPTION,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt (for non-interactive runs)."
    ),
    sync: bool = typer.Option(
        False, "--sync", help="Run sync-claude-app after a successful update (re-sync the phone)."
    ),
) -> None:
    """Explicit context-layer update flow — never silent (build step 4, PRD §F2, §5).

    Edits athlete/profile.md either non-interactively (`--field KEY=VALUE`, scalar fields
    only) or by opening it in $EDITOR. The result is validated against the schema contract
    (BUILD_SPEC §5) before anything is written; a diff is shown and confirmed. Profile
    changes are what make the phone brain stale, so it nudges you to re-sync (or `--sync`).
    """
    if not context.PROFILE_PATH.exists():
        typer.secho(
            f"No {context.PROFILE_PATH.relative_to(REPO_ROOT)} to update.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    current = context.PROFILE_PATH.read_text(encoding="utf-8")

    if field:
        try:
            updates = _parse_field_updates(field)
            new_text = context.apply_frontmatter_fields(current, updates)
        except ValueError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc
    else:
        new_text = _edit_in_editor(current)

    if new_text == current:
        typer.secho("No changes — profile left untouched.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(0)

    violations = context.validate_profile(new_text)
    if violations:
        typer.secho(
            "Update rejected — the edited profile breaks the schema contract (BUILD_SPEC §5):",
            fg=typer.colors.RED,
            err=True,
        )
        for v in violations:
            typer.secho(f"  - {v}", fg=typer.colors.RED, err=True)
        typer.secho("Nothing written.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    rel = context.PROFILE_PATH.relative_to(REPO_ROOT)
    diff = difflib.unified_diff(
        current.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
    )
    typer.echo("".join(diff))

    if not yes and not typer.confirm(f"Write these changes to {rel}?", default=True):
        typer.secho("Aborted — nothing written.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1)

    context.PROFILE_PATH.write_text(new_text, encoding="utf-8")
    typer.secho(f"Updated {rel}.", fg=typer.colors.GREEN, err=True)

    if sync:
        doc, trimmed = claude_sync.build_instructions()
        path = claude_sync.write_output(doc)
        typer.secho(
            f"Re-synced Claude-app instructions → {path.relative_to(REPO_ROOT)}.",
            fg=typer.colors.GREEN,
            err=True,
        )
        if trimmed:
            typer.secho(
                "  (trimmed to fit: " + ", ".join(trimmed) + ")",
                fg=typer.colors.YELLOW,
                err=True,
            )
    else:
        typer.secho(
            "The Claude-app brain is now stale — run `domestique sync-claude-app` to re-sync "
            "the phone (or re-run with --sync).",
            fg=typer.colors.YELLOW,
            err=True,
        )


def _parse_field_updates(fields: list[str]) -> dict[str, str]:
    """Parse repeated `--field KEY=VALUE` options into a mapping (validated downstream)."""
    updates: dict[str, str] = {}
    for item in fields:
        if "=" not in item:
            raise ValueError(f"--field expects KEY=VALUE, got '{item}'.")
        key, _, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if not key or not value:
            raise ValueError(f"--field expects a non-empty KEY and VALUE, got '{item}'.")
        updates[key] = value
    return updates


def _edit_in_editor(initial: str) -> str:
    """Open the profile text in $EDITOR and return the edited result (BUILD_SPEC §5 flow)."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        raise typer.BadParameter(
            "No $EDITOR set for the interactive edit. Set EDITOR, or use non-interactive "
            "--field KEY=VALUE for scalar frontmatter fields."
        )
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".profile.md", encoding="utf-8", delete=False
    ) as tf:
        tf.write(initial)
        tmp_path = tf.name
    try:
        subprocess.run([*editor.split(), tmp_path], check=True)
        return Path(tmp_path).read_text(encoding="utf-8")
    finally:
        os.unlink(tmp_path)


@app.command(name="sync-claude-app")
def sync_claude_app(
    stdout_only: bool = typer.Option(
        False, "--stdout-only", help="Print to stdout only; do not write the docs file."
    ),
) -> None:
    """Emit Claude-app project instructions from repo assets (build step 4, PRD §5).

    Assembles the coach prompt, the current profile, races.yaml and a guardrail-rule
    summary into one generated markdown document (BUILD_SPEC §7.9), printed to stdout and
    written to docs/claude-app-instructions.md under a do-not-hand-edit header. Over the
    project-instructions size limit, the race calendar is dropped first and the trim is
    reported, always keeping the coach prompt, profile facts and guardrails.
    """
    doc, trimmed = claude_sync.build_instructions()
    typer.echo(doc)

    if not stdout_only:
        path = claude_sync.write_output(doc)
        typer.secho(
            f"\nWrote {path.relative_to(REPO_ROOT)} ({len(doc):,} chars, "
            f"Domestique {version.domestique_version()}).",
            fg=typer.colors.GREEN,
            err=True,
        )
    if trimmed:
        typer.secho(
            "Trimmed to fit the project-instructions size limit — dropped: "
            + ", ".join(trimmed)
            + ".",
            fg=typer.colors.YELLOW,
            err=True,
        )


@app.command(name="sync-starter-kit")
def sync_starter_kit(
    stdout_only: bool = typer.Option(
        False, "--stdout-only", help="Print the starter kit to stdout only; do not write files."
    ),
) -> None:
    """Generate the field-test kit for external testers (field-test-kit build step).

    Assembles two athlete-agnostic artefacts from the repo brain (same pattern as
    sync-claude-app): docs/starter-kit.md (the agnostic coach prompt + data-first onboarding +
    blank profile schema, to paste into a tester's Claude project) and docs/field-report.md
    (the weekly report prompt testers paste back weekly). Generation greps both for this repo's
    real profile values and FAILS if any leak, so the kit is athlete-agnostic by construction.
    """
    try:
        artefacts = starter_kit.generate()
    except starter_kit.PersonalDataLeak as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    typer.echo(artefacts[starter_kit.STARTER_KIT_PATH])

    if not stdout_only:
        written = starter_kit.write_outputs(artefacts)
        for path in written:
            rel = path.relative_to(REPO_ROOT)
            typer.secho(
                f"\nWrote {rel} ({len(artefacts[path]):,} chars).",
                fg=typer.colors.GREEN,
                err=True,
            )
    typer.secho(
        f"Personal-data scan: clean (Domestique {version.domestique_version()}).",
        fg=typer.colors.GREEN,
        err=True,
    )
    for name, size in starter_kit.oversize_artefacts(artefacts).items():
        typer.secho(
            f"Warning: {name} is {size:,} chars, over the project-instructions budget "
            f"({starter_kit.PROJECT_INSTRUCTIONS_CHAR_BUDGET:,}) — tighten the source assets.",
            fg=typer.colors.YELLOW,
            err=True,
        )


@app.command(name="sync-invite")
def sync_invite(
    stdout_only: bool = typer.Option(
        False, "--stdout-only", help="Print the invite to stdout only; do not write the file."
    ),
) -> None:
    """Generate the WhatsApp onboarding invite for a new field tester (field-test-kit step).

    Assembles the plain-text message the maintainer sends to onboard a tester, from the repo
    brain (same pattern as the other sync commands): one-line what-this-is, numbered setup
    steps, the weekly field-report loop, a plain safety line, and the kit version stamp. The
    public repo URL comes from one config constant. Generation runs the personal-data leak gate
    and a WhatsApp character budget, FAILING if the message leaks profile data or runs long. The
    message is printed to stdout exactly as it is sent and written to docs/invite-message.txt.
    """
    try:
        text = invite.generate()
    except (starter_kit.PersonalDataLeak, invite.InviteOverBudget) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    typer.echo(text)

    if not stdout_only:
        path = invite.write_output(text)
        typer.secho(
            f"\nWrote {path.relative_to(REPO_ROOT)} ({len(text):,} chars, budget "
            f"{invite.INVITE_CHAR_BUDGET:,}; Domestique {version.domestique_version()}).",
            fg=typer.colors.GREEN,
            err=True,
        )
    typer.secho("Personal-data scan: clean.", fg=typer.colors.GREEN, err=True)


if __name__ == "__main__":
    app()
