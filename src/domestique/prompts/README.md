# prompts/

Versioned prompt assets — part of the agent's brain (PRD §5).

- `coach.md` — the master coaching prompt, stored **verbatim**. It seeds the
  production system prompt (PRD §2) and is assembled with the athlete context by
  `context.py` before every agent call. Edited only deliberately; changes here are
  regression-tested by the eval harness (PRD §F3) once step 5 lands.
- `coach.starter.md` — the **athlete-agnostic** edition, for the external field-test kit.
  Same structure as `coach.md` but with every athlete-specific fact removed: the universal
  §8 safety rules travel verbatim, while personal injury thresholds are replaced by a
  per-athlete injury-protocol pattern the coach builds at onboarding (§0a). It also carries
  the medical disclaimer (§0). `sync-starter-kit` assembles it into `docs/starter-kit.md` and
  **greps the output for this repo's real profile values, failing generation on any leak** —
  keep it clean. It is a deliberate sibling of `coach.md`; when you change coaching behaviour
  in one, consider whether the other should track it.
