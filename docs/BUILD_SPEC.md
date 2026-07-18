# Domestique — MVP Build Spec

Companion to `docs/PRD.md`. The PRD says why and what; this says exactly how. The MVP ships all features (F1–F4) in one continuous build of short daily sessions, following the build order in PRD §9. The rule: every session ends with something working.

---

## 1. Definition of the core loop (build steps 1–2)

A CLI command, `domestique brief`, that:
1. Pulls the athlete's recent training from the Strava MCP server (last 28 days)
2. Runs a 3-question conversational check-in in the terminal
3. Loads the athlete profile from `athlete/profile.md`
4. Calls Claude with all three as context
5. Prints a morning briefing and saves it to `briefings/YYYY-MM-DD.md`

Done means: on a fresh clone with env vars set, `domestique brief` produces a briefing that cites at least 3 real recent activities by name/date, adjusts its recommendation to the check-in answers, and passes the output guardrail check.

Beyond the core loop, the MVP also includes (in build order, per PRD §9): deterministic guardrails + a seed golden set in CI (step 3); the context-layer update flow and generated Claude-app project instructions (step 4); the grown eval set with LLM-as-judge (step 5); README and docs (step 6). (A dedicated race-pacing + plan-vs-actual debrief module was previously scoped as step 6 / PRD F5; it is de-scoped pending field-test demand.)

## 2. Stack

- Python 3.12, managed with `uv`; lint/format with `ruff`
- `anthropic` SDK; model `claude-sonnet-4-6` (cost-appropriate for daily runs)
- Strava via the **hosted Strava MCP server** — a remote connector reached through the API's `mcp_servers` parameter, no bespoke Strava client. **Auth is OAuth owned by the connector, not a static token.** In the Claude Code build environment the connector is attached at the account/platform layer: its OAuth grant (Strava access + refresh tokens) lives inside the connector service and is refreshed server-side, so **no `STRAVA_MCP_TOKEN`, client ID, or client secret exists as an environment variable here** — read-only Strava calls work as soon as the connector is attached. Model access uses `ANTHROPIC_API_KEY` for a standalone CLI; inside the Claude Code environment the model is authenticated via the platform, so that variable is only required when the CLI runs on its own.
- **Open for step 2:** a standalone `domestique` CLI that calls the Anthropic API directly will need to supply its *own* Strava MCP auth (an OAuth access token in the `mcp_servers` config, with refresh handled by the CLI). This is a design decision, not yet implemented — settle it when the CLI is built.
- No database. Flat files, committed (briefings) or gitignored (anything sensitive)
- CLI via `typer`

## 3. Repo layout

```
domestique/
├── README.md              # quickstart, architecture sketch, eval badge
├── CLAUDE.md              # standing instructions for Claude Code (see §8)
├── pyproject.toml
├── docs/
│   └── PRD.md
├── src/domestique/
│   ├── cli.py             # typer app: `brief`, `update-profile`, `sync-claude-app`
│   ├── agent.py           # Claude call: system prompt assembly, MCP wiring
│   ├── checkin.py         # terminal Q&A → structured state dict
│   ├── context.py         # loads profile.md + recent briefings into context blocks
│   └── guardrails.py      # deterministic output checks (see §6)
├── athlete/               # GITIGNORED — real health/location data never committed
│   ├── profile.md         # THE context layer (see §5) — schema is a contract
│   ├── profile.example.md # sanitised copy, committed, keeps the repo demonstrable
│   └── races.yaml         # target events: name, date, priority (A/B/C)
├── briefings/             # GITIGNORED except one redacted sample briefing
└── evals/
    ├── golden/            # scenario YAMLs, seeded from prototype conversations
    ├── bounds.py          # deterministic physiological limits
    └── run.py             # CI entry point; prints pass rate for README badge
```

## 3a. Privacy and secrets: private working repo, public showcase (non-negotiable)

- **This working repo is private and permanent.** Build containers are disposable, so the real athlete data must persist in git or it is lost every session. Therefore `athlete/` (profile.md, races.yaml) and `briefings/` are **committed** here. This is safe only because the repo is private.
- **A separate public showcase copy is built at publish time** — code, docs, `profile.example.md`, one redacted `briefings/sample.md`, clean history, and **no real data**. The sanitised examples keep the architecture fully demonstrable without exposing health or home-location data. The showcase is scrubbed at creation, not held back by ignore rules.
- Rationale for the split: the profile contains health data (injury history, weight), briefings record daily health patterns, and ride files reveal home location — none of that belongs in a public repo, but all of it must persist for the private daily tool to work across sessions.
- `.gitignore` still always excludes: `.env`/`.env.*`, ride files (`*.gpx`/`*.fit`/`*.tcx`, which reveal home location), and any token-like/credential files. Secrets exist only as environment variables — never in files, never echoed into logs or briefings. Model access uses `ANTHROPIC_API_KEY` when the CLI runs standalone. **Strava has no secret in this environment:** the hosted MCP connector holds the OAuth access/refresh tokens server-side and refreshes them itself, so there is nothing Strava-related to store, echo, or leak here. If step 2's standalone CLI later needs a Strava OAuth token, it too must come from an env var, never a committed file.
- Enable GitHub push protection and secret scanning on this private repo before the first push.
- Before any commit, verify secrets and ride files stay ignored (`git check-ignore .env some.gpx`). Before publishing the showcase, verify no real `athlete/`/`briefings/` data is carried over.

## 4. The `brief` flow (exact)

1. **Fetch**: via Strava MCP — `list_activities` (28 days), `get_athlete_zones`; for the 3 most recent rides, `get_activity_performance`. Summarise into a compact block (date, name, duration, distance, avg/NP power if present, kJ, HR). Token budget for the activity block: ~2k. *Auth note:* this flow does no token handling — in the Claude Code environment the hosted Strava connector is already authenticated; a standalone CLI would instead attach the Strava MCP with its own OAuth token (open step-2 item, see §2).
2. **Check-in** (terminal, one question at a time, free-text answers). Must also support a non-interactive mode for phone-driven cloud sessions: `domestique brief --sleep "..." --body "..." --yesterday "..."` (or `--answers answers.md`), so the agent can run it end-to-end without an interactive prompt. Questions:
   - "How did you sleep, and how do you feel this morning?"
   - "Anything sore, run down, or on your mind that affects training?"
   - "How hard did yesterday feel, if you trained?"
   Answers pass to the model raw — the LLM does the interpretation (that's the point). If any answer signals illness/injury, guardrails apply (§6).
3. **Context assembly** (`context.py`), in order: system prompt → athlete profile → races.yaml → activity block → check-in answers → today's date/day-of-week.
4. **Call Claude** with the Strava MCP server attached (the model may make follow-up tool calls for detail, e.g. streams for a specific ride).
5. **Output**: briefing to stdout + `briefings/YYYY-MM-DD.md`. Structure: **Green/Amber/Red readiness status** with a 2–3 sentence read → *Today's session* (specific: duration, structure, power targets in W and %FTP, anchored to FTP 362) → *Why* (grounded in profile + recent load) → *Watch-outs* (only if warranted).
6. **Guardrail pass** (§6) runs on the output before it is shown; on failure, one retry with the violation appended to the prompt; on second failure, print the safe fallback ("rest day + reason") and log.

## 5. `athlete/profile.md` schema (contract — do not improvise fields)

YAML frontmatter + prose sections:

```yaml
---
ftp_w: <fill>         # from onboarding: an estimate, stated-not-adopted until the athlete confirms; then held stable unless data clearly supports a change
ftp_date: <fill>
weight_kg: <fill>
weekly_hours_typical: <fill>
constraints: ["long ride Saturdays", "no intensity midweek"]
personal_protocols:                    # optional — per-athlete injury/symptom protocols
  - {trigger: tendon, severity: symptom, action: no_intensity}
  - {trigger: knee, severity: significant, action: no_intensity}
---
```

`personal_protocols` are the per-athlete enforceable rules (read by `checkin.py` to set the generic `personal_protocol` guardrail flag): each names a `trigger` keyword, a `severity` (`symptom` = any signal above 0/10; `significant` = >1/10 or progressive, ≤1/10 stable trains), and an `action`. The condition keywords live in the profile, never in shipped code.

Prose sections (H2s, agent reads all): `## Goals` (season targets, from races.yaml context), `## Patterns` (evidence-backed observations only, each with a date or activity reference — e.g. "alpine gran fondo 2026: held ~265W on climbs over 6h; fade began ~3,000kJ without fuelling"), `## History` (brief training background), `## Preferences` (session types liked/hated).

Rule: the agent may *cite* the profile; only the human (or the explicit `update-profile` flow) may *edit* it.

## 6. Guardrails (deterministic, in code, from build step 3)

`guardrails.py` checks every briefing before display:
- **Illness/injury**: if check-in answers matched illness/pain patterns (simple keyword pass in `checkin.py` sets a flag), the briefing must recommend rest/recovery and must not contain a structured workout. Chest-pain or dizziness mentions → briefing must advise seeing a doctor, full stop.
- **Personal protocols** (per-athlete, defined in `profile.md` frontmatter and read by `checkin.py`): each is a symptom → action rule enforced generically — e.g. a recurring tendon symptom → intensity removed from prescriptions; a joint ache ≤1/10 and non-progressive → training acceptable. The guardrail names no condition; the profile owns them. Never suggest aggressive weight loss; fuelling prioritised in build weeks.
- **Power bounds**: extract every watt figure; steady/endurance prescriptions ≤ 80% FTP, threshold work ≤ 105% FTP, no prescription > 120% FTP for ≥ 5-min efforts. (Bounds live in one table in `guardrails.py`, cited to FTP from profile.)
- **Race protection**: within 7 days of an A-race in `races.yaml`, no session above endurance intensity and weekly load must read as taper.
- **Fuelling penalty**: if the check-in (or recent long-ride data) indicates poor or absent fuelling, the next prescription is capped at endurance intensity and the briefing must address nutrition before any load increase — under-fuelling carries a training penalty.
These are hard rules — never softened by prompt changes, only by editing the bounds table consciously.

## 7. Acceptance tests (write these first)

1. Fresh clone with model + Strava MCP auth available → `uv run domestique brief` completes without error. (Model: `ANTHROPIC_API_KEY` for a standalone CLI. Strava: the hosted MCP connector's OAuth — not a static env token; the wiring for a standalone CLI is a step-2 decision, see §2. Inside the Claude Code environment both are provided by the platform/connector, so no per-run token export is needed.)
2. Briefing cites ≥3 real activities with correct dates
3. Check-in answer "terrible sleep, feel like I'm getting ill" → rest-day briefing, no workout structure
4. Check-in reporting a triggered personal protocol (e.g. a persistent tendon symptom) → prescription contains no intensity work
5. Check-in reporting skipped fuelling on a long ride → next prescription capped at endurance, nutrition addressed
6. All watt values in 10 sample briefings pass bounds
7. A-race in 5 days in races.yaml → no threshold/VO2 prescription
8. `evals/run.py` passes in CI on the seed golden set
9. `sync-claude-app` emits project instructions containing current FTP and guardrail summary
10. In this private working repo, `athlete/profile.md`, `athlete/races.yaml` and `briefings/` are tracked and persist across sessions, while `git check-ignore .env some.gpx` still passes (secrets and ride files never committed). The public showcase copy, when built, carries no real athlete/briefing data — only `profile.example.md` and a redacted `sample.md`
11. README quickstart is accurate (test it literally)
12. Every generated artefact (`docs/claude-app-instructions.md`, `docs/starter-kit.md`, `docs/field-report.md`) carries a `DOMESTIQUE_VERSION` stamp (`{date}+{hash8}`) in its header, and briefings/field reports echo it. The version is deterministic — a pure function of the committed brain sources (`prompts/coach.md`, `prompts/coach.starter.md`, the guardrails bounds table, the profile schema) — so regenerating it produces byte-identical output. (It replaces the old non-deterministic commit stamp precisely so §7.13 can hold.)
13. **Freshness gate (CI).** The GitHub Actions workflow runs on every PR: `evals/run.py` passes (§7.8), then `sync-claude-app` and `sync-starter-kit` are regenerated and the committed artefacts must be byte-identical to the regenerated output — a stale artefact fails the build with a message to re-run the sync commands. Verify by editing a brain source (e.g. `prompts/coach.md`): regeneration now differs from the committed files (gate fails); after re-running the syncs the diff is clean (gate passes).

## 8. CLAUDE.md

The repo-root CLAUDE.md carries the standing instructions (conventions, hard rules, working style). It is committed separately at repo root; this spec defers to it.

## 9. Build order

Functionality ships in this order (PRD §9):

1. Scaffold + Strava MCP connectivity + athlete profile.
2. Morning briefing CLI.
3. Deterministic guardrails + evals in CI.
4. Context-layer updates + Claude-app sync.
5. Golden set.
6. README + docs.
