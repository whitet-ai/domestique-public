"""Eval harness entry point — runs the golden set and prints a pass rate.

Runs in CI on every prompt/context change (PRD §F3); the pass rate feeds the README
badge (BUILD_SPEC §3). Each golden scenario in evals/golden/ is a fixed (check-in flags
+ candidate briefing) case with a known-good/known-bad expectation, scored by the real
deterministic guardrails in src/domestique/guardrails.py — no model call, fully
reproducible. (Scenario `judge:` blocks capture behavioural criteria for a future
LLM-as-judge; the harness runs no model today.)

Scenario YAML schema:
    name: str
    description: str
    flags: {illness, red_flag_medical, personal_protocol, fuelling_poor}  # bools
    days_to_a_race: int | null
    ftp_w: int            # optional, defaults to 362
    briefing: str         # the candidate briefing text the guardrails score
    expect:
      passed: bool        # should the guardrail pass this briefing?
      violations: [str]   # optional: category substrings that MUST appear when failing

A scenario is scored correct when the guardrail's pass/fail matches `expect.passed` and
every expected violation category is present. Exit code is non-zero if any scenario is
mis-scored, so CI fails on a guardrail regression.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from domestique import context, guardrails  # noqa: E402

GOLDEN_DIR = Path(__file__).parent / "golden"
DEFAULT_FTP = 362


def check_example_profile() -> tuple[bool, str]:
    """Guard that the committed athlete/profile.example.md loads end-to-end.

    In the public showcase there is no real athlete/profile.md, so the example IS the
    profile-of-record the quickstart (`domestique sync-claude-app`) runs against. It must
    satisfy the schema contract (BUILD_SPEC §5) AND carry a numerically-parseable ``ftp_w``:
    a non-numeric placeholder such as ``<fill>`` still parses as YAML but crashes the
    quickstart at ``context.profile_ftp_w()``'s ``int(...)``. Guarded here so the example can
    never silently break the quickstart again (regression: ftp_w blanked to ``<fill>``).
    """
    text = context.PROFILE_EXAMPLE_PATH.read_text(encoding="utf-8")
    violations = context.validate_profile(text)
    if violations:
        return False, "schema contract: " + "; ".join(violations)
    match = context._FRONTMATTER_RE.match(text)
    front = yaml.safe_load(match.group(1)) if match else {}
    try:
        int(front["ftp_w"])
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"ftp_w is not loader-parseable (quickstart would crash): {exc!r}"
    return True, f"loads clean (ftp_w={front['ftp_w']}, schema valid)"


def discover_scenarios() -> list[Path]:
    """Return every golden-set scenario file."""
    return sorted(GOLDEN_DIR.glob("*.yaml"))


def score_scenario(scenario: dict) -> tuple[bool, str]:
    """Run the guardrails on one scenario; return (correct, detail)."""
    expect = scenario.get("expect", {})
    result = guardrails.check_briefing(
        scenario.get("briefing", ""),
        ftp_w=scenario.get("ftp_w", DEFAULT_FTP),
        checkin_flags=scenario.get("flags", {}) or {},
        days_to_a_race=scenario.get("days_to_a_race"),
    )

    if result.passed != expect.get("passed"):
        got = "passed" if result.passed else f"failed ({'; '.join(result.violations)})"
        return False, f"expected {'pass' if expect.get('passed') else 'fail'}, got {got}"

    joined = " || ".join(result.violations).lower()
    missing = [c for c in expect.get("violations", []) if c.lower() not in joined]
    if missing:
        return False, f"missing expected violation categor(y/ies): {', '.join(missing)}"

    if result.passed:
        return True, "correctly passed a safe briefing"
    return True, f"correctly blocked: {'; '.join(result.violations)}"


def main() -> int:
    example_ok, example_detail = check_example_profile()
    print(f"  {'✓' if example_ok else '✗'} {'profile.example loads e2e':<28} {example_detail}\n")

    scenarios = discover_scenarios()
    if not scenarios:
        print("No golden scenarios yet — seeded in build step 3 (PRD §9).")
        return 0 if example_ok else 1

    correct = 0
    for path in scenarios:
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        ok, detail = score_scenario(scenario)
        correct += ok
        mark = "✓" if ok else "✗"
        print(f"  {mark} {scenario.get('name', path.stem):<28} {detail}")

    total = len(scenarios)
    pct = 100.0 * correct / total
    print(f"\nPass rate: {correct}/{total} ({pct:.0f}%)")
    return 0 if (correct == total and example_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
