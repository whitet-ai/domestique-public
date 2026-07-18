---
ftp_w: 250            # example value — the onboarding derives yours from ~90 days of Strava data
ftp_date: 2026-05-18
weight_kg: 74.5
weekly_hours_typical: 10
constraints: ["long ride Saturdays", "no intensity midweek"]
personal_protocols:
  # Fictional example protocols — the shape the coach fills in during onboarding. Each is an
  # enforceable rule read by the guardrails: a trigger keyword, a severity, and an action.
  - trigger: tendon
    severity: symptom      # any tendon symptom above 0/10 → hard stop on intensity
    action: no_intensity
  - trigger: knee
    severity: significant  # >1/10 or progressive → no intensity; ≤1/10 non-progressive trains
    action: no_intensity
---

<!--
PURPOSE — this is the template testers copy to athlete/profile.md. Real profiles stay private
and are never committed to the public repo. The starter-kit onboarding populates the copy from
~90 days of the athlete's own Strava data; the values below are fictional placeholders.
-->

<!--
SANITISED EXAMPLE — fictional data. This file is committed to keep the repo
demonstrable (BUILD_SPEC §3a). The real athlete/profile.md is gitignored and never
committed. Schema is a contract (BUILD_SPEC §5): the allowed frontmatter fields (four scalars +
constraints + personal_protocols) plus the four H2 sections below — do not add fields.
The agent may cite this file; only the human or the explicit `update-profile` flow may
edit it.
-->

## Goals

- **A-race:** a mountain gran fondo (July) — finish strong over ~140 km / ~4,000 m,
  holding power on the final climb rather than fading in the last hour.
- **B-race:** a spring gran fondo as a fitness checkpoint and pacing rehearsal.
- Season theme: durability — the fitness to still be riding well at hour five, not
  just the FTP to start fast.

## Patterns

- Gran fondo 2026 (example ride, 6h12m): held ~262 W on sustained climbs for the
  first four hours, fade began around 3,000 kJ when fuelling dropped off — a
  fuelling problem, not a fitness ceiling.
- Threshold sessions (2026-06 block): 3×12 min at 95–100% FTP completed cleanly on
  back-to-back weeks; repeatable, not a one-off.
- Long-ride HR drift (example endurance ride, 4h): stayed under 5% at ~68% FTP when
  carbs were kept above ~70 g/hr; drift climbed sharply the one time fuelling lapsed.
- Recovers well from a single hard day; a second hard day inside 48h shows up as flat
  legs and depressed power the following ride.

## History

Fictional example athlete: ~8 years riding, 4 of them structured. Endurance
background with a gran fondo focus; comfortable with 10–12 h weeks in build blocks.
Prior niggles — a manageable recurring tendon symptom and an occasional low-grade knee
ache — included here only to exercise the personal-protocol guardrails (BUILD_SPEC §6).

## Preferences

- Likes: long mountain endurance days, sweet-spot and threshold work with clear
  numeric targets, structure over "ride to feel".
- Dislikes: short max-effort sprint sets, indoor sessions over ~90 min.
- Coaching tone: direct, performance-focused, exact watt targets; not overcautious
  when symptoms are stable (PRD §2, §F4).
