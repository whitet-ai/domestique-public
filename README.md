# Domestique

**A personal agentic cycling coach that briefs you each morning on what to ride and why — grounded only in your own Strava data, and hard-stopped by deterministic safety guardrails.**

It rebuilds the problem behind US patent application [US-2022-0040532-A1](https://patents.google.com/patent/US20220040532A1/en) — "Utilizing machine learning and cognitive state analysis to track user performance", on which I'm a named co-inventor — which was filed with British Triathlon, assigned to Accenture, and **abandoned** (never granted). What took an R&D team, a PhD sports scientist, and six-to-eight weeks of AWS engineering in 2020 is rebuilt here solo with Claude Code and a hosted Strava MCP server: the modelling layer collapsed into a prompt.

[![acceptance](https://github.com/whitet-ai/domestique-public/actions/workflows/ci.yml/badge.svg)](https://github.com/whitet-ai/domestique-public/actions/workflows/ci.yml)
[![evals](https://img.shields.io/badge/golden%20set-24%2F24%20passing-brightgreen)](evals/)
![python](https://img.shields.io/badge/python-3.12-blue)
![status](https://img.shields.io/badge/scope-MVP-informational)

> A *domestique* is the rider who works for the team leader — fetches bottles, shelters them from the wind, sets pace on the climbs. The right metaphor for an agent.

---

## What it does

Run `domestique brief` in the morning. It:

1. Pulls your last 28 days from the **Strava MCP server** (activities, power, HR — zero integration code);
2. Runs a three-question conversational **check-in** (sleep, soreness/stress, yesterday's effort);
3. Loads your versioned **athlete profile** (FTP, training patterns, injury history);
4. Calls Claude with all three as context and prints a briefing: **🟢 Green / 🟡 Amber / 🔴 Red readiness** → today's session with exact watt targets → *why*, grounded in your real recent rides → *watch-outs*;
5. Saves it to `briefings/YYYY-MM-DD.md`, after it clears the guardrails.

The briefing output format is specified in [`BUILD_SPEC` §5](docs/BUILD_SPEC.md) — real briefings live in the private working instance, not this public copy.

---

## Quickstart

Tested from a clean clone on Python 3.12 with [`uv`](https://docs.astral.sh/uv/).

### 60-second proof — no secrets required

The guardrails and the generated "brain" run entirely offline, so you can verify the core of the system with no API key:

```bash
uv sync --extra dev

# 1. The deterministic guardrail suite — 24 golden scenarios, no model call.
uv run python evals/run.py
#   → Pass rate: 24/24 (100%)

# 2. Watch the one brain assemble itself: coach prompt + profile + guardrails,
#    exactly what the phone (Claude app) runs.
uv run domestique sync-claude-app --stdout-only
```

### Full briefing — needs credentials

```bash
uv run domestique brief \
  --sleep "8h, feel good" \
  --body  "nothing sore" \
  --yesterday "easy Z2, felt fine" \
  --activities strava.json      # raw Strava MCP JSON (list_activities/zones/performance)
```

**Required env vars** (secrets live only as env vars — never in files):

| Variable | When it's needed | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Standalone CLI (`brief`) | Normal API auth. Inside the Claude Code platform the model is authenticated via `ANTHROPIC_AUTH_TOKEN` (platform OAuth) instead — no key needed. |
| `STRAVA_MCP_URL` + `STRAVA_MCP_TOKEN` | To attach the hosted Strava connector | **Optional.** With the hosted connector attached (as in the Claude Code environment), *no Strava secret exists here at all* — OAuth is held and refreshed server-side. Without it, pass `--activities <file>` with raw Strava MCP JSON. |

`evals/run.py` and both `sync-*` commands need **no** credentials — they read only committed repo state.

---

## Architecture — one brain, thin skins

The product is the agent plus its context; every interface is a thin skin over that one brain. The brain lives in the repo, is versioned, and is regression-tested.

```
                       ┌──────────────────  THE BRAIN (versioned)  ──────────────────┐
                       │                                                             │
   prompts/coach.md ───┤  coach prompt   +   athlete/profile.md   +   guardrails.py  │
   (system prompt)     │  (voice, rules)     (FTP, patterns,          (deterministic │
                       │                      injury protocols)        bounds table) │
                       └───────────────┬─────────────────────┬───────────────────────┘
                                       │                     │
         context.py assembles ─────────┤                     │ same sources feed
         → agent.py (Claude call) ─────┤                     │ every generated artefact
                                       ▼                     ▼
                          ┌───────────────────┐   ┌────────────────────────────────────┐
       Strava MCP ──────► │  CLI  `brief`     │   │  sync-claude-app → Claude app       │
       (28d activities)   │  guardrail pass   │   │      (daily driver, on the phone)   │
                          │  → briefing.md    │   │  sync-starter-kit → field-test kit  │
                          └───────────────────┘   │      (athlete-agnostic, for testers)│
                                                   └────────────────────────────────────┘

   version.py  ──►  DOMESTIQUE_VERSION = {date}+{hash8}, a fingerprint of the four brain
                    sources. Stamped on every artefact & briefing.  Current: 2026-07-14+0051417b

   CI freshness gate  ──►  on every PR: evals pass, then artefacts are regenerated and must be
                           byte-identical to what's committed — a stale phone/kit fails the build.
```

- **One brain, two consequences.** Because the CLI, the Claude-app instructions, and the tester starter kit are all *generated from the same coach prompt + profile + guardrails*, the phone can't drift from the terminal. Editing a source and forgetting to re-sync doesn't silently rot — CI catches it.
- **The version stamp is deterministic** — a pure function of the four committed brain sources — so regenerating an artefact produces byte-identical output. That's what lets the freshness gate *prove* sync rather than guess it.

---

## Why you can trust it

Advice you'll follow on a five-hour mountain ride, where pacing and fuelling must be spot on, needs to be an engineering property, not a vibe. Two layers back that up:

**Eval suite — 24 golden scenarios, deterministic, in CI.** Each scenario is a fixed (check-in + candidate briefing) case with a known-good or known-bad expectation, scored by the *real* guardrails in [`src/domestique/guardrails.py`](src/domestique/guardrails.py) — no model call, fully reproducible. Seeded from eight weeks of real coaching conversations (the prototype that became the [PRD](docs/PRD.md)), and grown from field-test feedback. The suite runs on every PR; a regression fails the build. → [`evals/`](evals/)

**Guardrails — hard rules the agent cannot override.** Every briefing is checked before it's shown; on failure the flow retries once with the violation fed back, then falls back to a safe rest-day message. Two kinds:

- **Universal rules** (every athlete): illness → rest only; chest pain / dizziness → see a doctor, full stop; power ceilings anchored to FTP (endurance ≤80%, threshold ≤105%, nothing ≥120% for 5-min+ efforts); within 7 days of an A-race → taper only; poor/absent fuelling → capped at endurance until nutrition is fixed; never prescribe aggressive weight loss.
- **Per-athlete personal protocols** (defined in the profile): e.g. a recurring tendon symptom → intensity removed; a joint ache ≤1/10 and non-progressive → training acceptable. Enforced with exactly the same non-negotiable force as the universal rules.

The design tension is deliberate and it *is* the whole trust story: the coach is instructed to be bold and **not** overcautious when symptoms are stable — and the guardrails overrule it at defined thresholds. Bold by default, hard-stopped at the limits.

---

## Field test

The same brain is exported athlete-agnostic so trusted testers can run their own Domestique in their own Claude project against their own Strava. `domestique sync-starter-kit` generates two artefacts and **fails generation if any of this athlete's real profile values leak** — agnostic by construction, not by trust:

- [`docs/starter-kit.md`](docs/starter-kit.md) — the coach prompt + medical disclaimer + a data-first onboarding flow + a blank profile schema, to paste into a Claude project's custom instructions.
- [`docs/field-report.md`](docs/field-report.md) — the weekly report prompt testers paste back.

**Why it differs from `prompts/coach.md`.** The starter prompt and the fictional [`profile.example.md`](athlete/profile.example.md) are kept deliberately generic — a general-fitness/event two-mode template any athlete can adopt — whereas `prompts/coach.md` is the maintainer's own personalised build (currently a race-performance `[PERF]` mode for crit and chain-gang racing): same architecture, different athlete.

**Report cadence.** The weekly report is a ritual the coach runs, not a form to remember. Onboarding ends by asking which day suits your report and suggesting a recurring phone reminder; from then on the coach tracks when you last reported and, once 7+ days pass, offers it before your briefing ("two minutes, then your briefing"). Every finished report closes by asking you to copy the whole thing and send it to the maintainer — that hand-off is the feedback loop.

**Want to test it?** Open an issue, or reach the maintainer. You'll get the starter kit, stand up a project against your own connector, and send a weekly field report ("including the bad calls — they're worth more"). Feedback from the field now sets the roadmap.

---

## Privacy model

**This is the public showcase of a private working instance** — the real athlete data lives
there, not here. The private working repo is where the daily tool actually runs: it commits the
real `athlete/profile.md`, `athlete/races.yaml` and `briefings/` because build containers are
disposable and a gitignored profile would be lost every session. **None of that real data
crosses into this public copy.** What ships here is the code, the docs, and the fictional
[`athlete/profile.example.md`](athlete/profile.example.md) — everything needed to understand and
run the architecture, with no real health or home-location data. `.gitignore` still excludes
secrets (`.env`), ride files (`*.gpx`/`*.fit`/`*.tcx`) and
token-like files; secrets exist only as env vars, and Strava's OAuth is held server-side by the
hosted connector, never on disk.

### About this export

This repository is a **clean, single-commit export by design.** It is generated from the private
working instance by an export script that copies an explicit allow-list — excluding the real
profile, races, briefings, phone instructions and the build log — and then verifies
no real personal data survives. It intentionally carries **no upstream git history**; the single
`Initial public release` commit is the whole record.

## Docs

- [`docs/PRD.md`](docs/PRD.md) — the product: story, IP position, features, success criteria.
- [`docs/BUILD_SPEC.md`](docs/BUILD_SPEC.md) — exactly how it's built: the `brief` flow, the profile schema contract, the guardrail table, the acceptance tests.

## Stack

Python 3.12 · [`uv`](https://docs.astral.sh/uv/) · [`ruff`](https://docs.astral.sh/ruff/) · [`typer`](https://typer.tiangolo.com/) CLI · [`anthropic`](https://github.com/anthropics/anthropic-sdk-python) SDK (`claude-sonnet-4-6`) · hosted **Strava MCP** connector. Flat files only — no database, no server.

> Scope note: single-user personal tool, MVP. Named co-inventor on a patent *application* — never "patent" or "patented". Not medical advice.
</content>
