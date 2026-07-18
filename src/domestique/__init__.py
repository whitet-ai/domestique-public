"""Domestique — a personal agentic cycling coach.

The product is the agent plus its context (PRD §5): profile, prompts, guardrails
and evals live in this repo and are versioned; every interface is a thin skin over
that brain. This package is that brain plus the CLI skin.
"""

__version__ = "0.1.0"

# The athlete's FTP is NOT defined here — it lives only in athlete/profile.md (the single
# source of truth, BUILD_SPEC §5) and is read via context.profile_ftp_w(). Deliberately no
# module-level FTP constant, so no power decision can drift from the profile.
