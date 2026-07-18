"""DOMESTIQUE_VERSION — a deterministic fingerprint of the coaching "brain".

The version stamps every generated artefact (Claude-app instructions, field-test kit) and,
via the coach prompt's output contract, every briefing and field report — so any output can be
traced to the exact brain that produced it, and so CI can *prove* the committed artefacts are
in sync with their sources (regenerate → diff → must be byte-identical).

Format: ``{date}+{hash8}`` where
  * ``hash8`` — first 8 hex of a SHA-256 over the brain fingerprint: prompts/coach.md,
    prompts/coach.starter.md, the guardrails bounds table, and the profile schema contract;
  * ``date``  — the date (YYYY-MM-DD) of the most recent git commit touching a brain source
    file.

Both components are pure functions of committed repo state, so regeneration is byte-identical
across machines and CI runs — the property the freshness gate depends on. This is why the old
non-deterministic ``Source commit: <hash>-dirty`` stamp was dropped from the artefacts in
favour of this. (An uncommitted edit to a brain file changes ``hash8`` but not ``date`` — that
is exactly what lets the freshness check demonstrate a stale artefact without a commit.)
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = Path(__file__).parent / "prompts"
COACH_PROMPT_PATH = PROMPTS_DIR / "coach.md"
COACH_STARTER_PATH = PROMPTS_DIR / "coach.starter.md"

# Source files whose most-recent commit date gives the version's date component. These are the
# brain's home in the tree; the hash (below) captures their *content* semantically.
_BRAIN_SOURCE_FILES = (
    COACH_PROMPT_PATH,
    COACH_STARTER_PATH,
    Path(__file__).parent / "guardrails.py",
    Path(__file__).parent / "context.py",
)

_MISSING_DATE = "0000-00-00"


def _bounds_repr() -> str:
    """Stable serialisation of the guardrail bounds table (imported lazily to avoid a cycle)."""
    from domestique import guardrails

    return repr(
        (
            guardrails.STEADY_MAX_FTP,
            guardrails.THRESHOLD_MAX_FTP,
            guardrails.ABSOLUTE_MAX_FTP,
            guardrails.A_RACE_TAPER_DAYS,
        )
    )


def _schema_repr() -> str:
    """Stable serialisation of the profile schema contract (imported lazily to avoid a cycle)."""
    from domestique import context

    return repr((tuple(context.ALLOWED_FRONTMATTER_KEYS), tuple(context.REQUIRED_H2_SECTIONS)))


def brain_fingerprint() -> str:
    """Full SHA-256 hex over the brain: both coach prompts + the bounds table + the schema."""
    digest = hashlib.sha256()
    for path in (COACH_PROMPT_PATH, COACH_STARTER_PATH):
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    digest.update(_bounds_repr().encode("utf-8"))
    digest.update(b"\x00")
    digest.update(_schema_repr().encode("utf-8"))
    return digest.hexdigest()


def brain_hash8() -> str:
    """The short (8-hex) brain hash used in the version string."""
    return brain_fingerprint()[:8]


def brain_date() -> str:
    """Date (YYYY-MM-DD) of the most recent commit touching a brain source file.

    Deterministic in any committed checkout; falls back to a sentinel if git is unavailable or
    the files have no history. An uncommitted edit does not move this (no new commit exists).
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "log",
                "-1",
                "--format=%cd",
                "--date=short",
                "--",
                *[str(p) for p in _BRAIN_SOURCE_FILES],
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return _MISSING_DATE
    return result.stdout.strip() or _MISSING_DATE


def domestique_version() -> str:
    """The stamp embedded in every generated artefact and echoed by briefings: ``date+hash8``."""
    return f"{brain_date()}+{brain_hash8()}"
