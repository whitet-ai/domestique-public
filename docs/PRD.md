# PRD — "Domestique": An Agentic Performance Coach
**Inspired by US patent application 2022/0040532 A1 — "Utilizing machine learning and cognitive state analysis to track user performance" (T. White, named co-inventor)**
**Rebuilt for 2026 with Claude Code and the Strava MCP server, evaluation-first**

---

## 1. The story (why this project exists)

In 2020, tracking athlete performance with ML meant an R&D programme: a team of specialists, six to eight weeks of AWS engineering, custom cognitive-state and performance models, and a PhD sports scientist designing the questions. The work became a US patent application with British Triathlon. It was never granted; the idea outlived the paperwork.

In 2026, that problem class has collapsed. Domestique is the rebuild: an agentic cycling coach, grounded in my own training data, that briefs me each morning on what to ride and why, and plans my races.

It exists to be used daily, and to explore one question seriously: what does it take for an AI agent to understand the basis of amateur sporting performance and make informed, trusted recommendations?

**Naming note:** a domestique is the rider who works for the team leader — fetches bottles, shelters them from wind, sets pace on climbs. The right metaphor for an agent.

## 2. How the requirements were made (design method)

There is no traditional spec behind this PRD. For eight weeks the MVP was a simple Claude project: a coach loaded with training history and behavioural instructions, used most days. Those conversations *are* the requirements corpus — the questions actually asked, the advice actually followed, the calls it got wrong. This document reverse-engineers the system from that usage.

Concretely, the MVP contributes three assets:
- **The instruction file** → seed for the production system prompt (tone: direct, performance-focused, exact watt targets; don't default to excessive caution when symptoms are stable)
- **Facts and rules within it** → seed for the athlete profile (FTP 362W, held stable unless data clearly supports a change) and the guardrail set (§6)
- **The conversation history** → source of golden-set evaluation scenarios with known-good and known-bad answers

The method is the point: living with a conversational prototype and then reverse-engineering the system from your own usage is faster and truer than writing requirements up front.

## 3. IP position (read first)

- The 2021 application is assigned to Accenture Global Solutions Ltd (assignment recorded 19 Nov 2021). Status confirmed via USPTO/Google Patents: **abandoned** (US and GB) — published, never granted. Domestique is **inspired by the problem space, not a reimplementation of the claims**, and is designed from the published abstract only.
- Key deliberate divergences: no media/video-based cognitive-state modelling (the core of the original's mechanism); conversational, athlete-reported state instead; LLM-agent architecture rather than trained bespoke models; single-user personal tool, non-commercial.
- All public references say: **"named co-inventor on a US patent application (US-2022-0040532-A1)"** — never "patent" or "patented".

## 4. Original system → 2026 reimagining

| Patent abstract stage (2020/21) | Domestique (2026) |
|---|---|
| Receive performance data from an activity session | **Strava MCP server**: activities, power, HR, streams — zero integration code |
| Receive media data; cognitive-state model scores the athlete's state | **Conversational check-in**: sleep, nutrition, stress, fatigue, symptoms — free-text answers, interpreted by the model. What needed a sports science PhD collaboration is now, essentially, a prompt |
| Performance model combines state + performance into a profile | **Context layer**: rolling athlete profile — FTP history, training load (CTL/ATL/TSB), climb performance, fuelling patterns, injury status — versioned context the agent reasons over |
| Generate recommendations | **Agentic coach**: morning briefing with a Green/Amber/Red readiness status, day-by-day plans, race-day elapsed-time projections, fuelling plans |
| Perform actions | Calendar entries, pre-race briefing docs |

## 5. Access & interfaces (design principle)

**The product is the agent plus its context; every interface is a thin skin over that brain.** The brain — profile, prompts, guardrails, evals — lives in the repo and is versioned. **One brain, two skins:** the **CLI** is the build target and the proof — real briefings in a terminal — and the **Claude app** is the daily driver, generated from the same profile and prompt assets with no interface code, so the phone experience and the CLI share one brain and can't drift. The interface layer collapsed just like the modelling layer did.

**Non-goals remain:** native iOS app, website, anything multi-user.

## 6. Core features

### F1 — Morning briefing (CLI)
Pulls 28 days from Strava MCP, runs the conversational check-in, loads the profile, outputs a briefing: **Green/Amber/Red readiness status** → today's session with exact watt targets (anchored to FTP 362) → why → watch-outs. In event-prep mode it also produces a conversational race-day elapsed-time projection.

### F2 — Athlete context layer
Versioned profile: FTP history (stable unless data clearly supports a change), load metrics, evidence-backed patterns, injury state. Updated after rides via an explicit flow, never silently. The same profile and prompt files also generate the Claude project instructions, so the phone experience stays in sync automatically.

### F3 — Evaluation harness
Golden set of 24 scenarios — seeded from the MVP's real conversations and grown from field-test feedback — plus deterministic checks (power within physiological bounds by duration; carbs 60–120g/hr; taper protection; load-ramp limits). Runs in CI on every prompt/context change; pass-rate badge in the README. Rationale: advice you'll follow on a mountain needs regression testing. Trust is an engineering property, not a vibe.

### F4 — Guardrails (hard rules the agent cannot override)
- **Illness**: illness signals in check-in → rest/recovery only; chest pain or dizziness → see a doctor, full stop.
- **Personal protocols** (per-athlete, defined in the profile): each names a symptom → action, e.g. a recurring tendon symptom → remove intensity; a joint ache ≤1/10 and non-progressive → acceptable to train. Enforced as hard as the universal rules; the guardrail names no condition.
- **Fuelling penalty**: poor/absent fuelling reported → next prescription capped at endurance; nutrition addressed before any load increase.
- **Race protection**: within 7 days of an A-race → taper only.
- **Never** suggest aggressive weight loss; fuelling is prioritised in build weeks.

Design tension, resolved deliberately: the coach is instructed *not* to be overcautious (the athlete handles substantial volume when symptoms are stable), and the guardrails overrule it at defined thresholds. Bold by default, hard-stopped at the limits — that is the whole trust story in one design decision.

## 7. Users

One: me. FTP 362W, gran fondo racer, years of Strava history, an existing eight-week corpus of coaching conversations. Not a product — a tool used daily, which keeps every feature honest.

## 8. Architecture

Claude Code as the build environment; agent via the Claude API with the Strava MCP server attached; flat files only (profile, golden set, briefings, plans) — no databases, no servers; a private working repo whose sanitised public showcase (built at publish time) carries README, architecture sketch, eval badge, and an honest "what didn't work" log.

**Privacy boundary:** the working repo is private and permanent, so the athlete's real data (live profile, briefings, plans) is committed there and persists across disposable build containers — the alternative, gitignoring it, loses the profile every session. A separate public showcase copy — built at publish time with clean history — carries only sanitised examples (profile.example.md, one redacted sample briefing) and never any real data; ride files (GPX/FIT) are excluded everywhere because they reveal home location. Secrets live only as environment variables or inside the attached MCP connector's own OAuth (Strava auth is held and refreshed by the hosted connector, not stored locally) — never in committed files; GitHub secret scanning and push protection are enabled.

## 9. MVP scope and build order

All features (F1–F4) ship in a single MVP, built in one continuous effort of short daily sessions with Claude Code. Versions are replaced by a build order; the rule is that every session ends with something working.

| Order | Build step | Done when |
|---|---|---|
| 1 | Repo scaffold, Strava MCP connectivity, athlete profile seeded from the prototype's instruction file | Raw activity data prints; profile facts load |
| 2 | Morning briefing CLI (check-in → context → briefing) | A real briefing generates; terminal screenshot captured |
| 3 | Deterministic guardrails + seed golden set mined from prototype conversations, wired into CI | Guardrail tests provably block unsafe advice; first eval run green |
| 4 | Context layer updates + Claude-app project instructions generated from repo | Agent cites profile facts correctly; daily use works on the phone |
| 5 | Golden set of 24 scenarios | Pass-rate badge live in README |
| 6 | README, architecture sketch, "what didn't work" log | A visiting engineer can reproduce a briefing unaided |

## 10. Success criteria
1. **Used**: 3+ briefings/week; every race planned through it.
2. **Trustworthy**: evals green in CI; guardrails demonstrably block unsafe advice; its race plan followed on an actual start line.
3. **Documented**: a visiting engineer can understand the architecture, run the evals and reproduce a briefing from the README alone.
