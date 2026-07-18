"""Claude call: system-prompt assembly and Strava MCP wiring (BUILD_SPEC §4.4).

The agent is invoked with the assembled context as the user message and the verbatim
master coaching prompt (prompts/coach.md) as the system prompt. Model: claude-sonnet-4-6
(BUILD_SPEC §2). When a standalone Strava OAuth token is available the hosted Strava MCP
server is attached so the model can make follow-up tool calls (streams for a specific
ride, etc.); the pre-fetched activity block from strava.py remains the anchor either way.

Auth (BUILD_SPEC §2, §3a) — two paths, both env-var only, never written to disk:
  * Standalone CLI: ANTHROPIC_API_KEY (normal x-api-key auth), coach prompt as system.
  * Claude Code platform: no ANTHROPIC_API_KEY exists — the model is authenticated via
    the platform's own OAuth. If ANTHROPIC_AUTH_TOKEN is set, we use bearer auth with
    the `oauth-2025-04-20` beta; that path requires the Claude Code identity as the
    first system block, so the coach prompt is sent as the second system block.

Strava MCP attachment (the standalone step-2 auth item, BUILD_SPEC §2): set both
STRAVA_MCP_URL and STRAVA_MCP_TOKEN to attach the hosted connector via `mcp_servers`.
In the Claude Code build environment the connector is attached to the agent at the
platform layer (no URL/token exposed to a subprocess), so this is left unset and the
model reasons over the pre-fetched activity block only.
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096

PROMPTS_DIR = Path(__file__).parent / "prompts"
COACH_PROMPT_PATH = PROMPTS_DIR / "coach.md"

# Required first system block when authenticating with a platform OAuth token.
_CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
_OAUTH_BETA = "oauth-2025-04-20"
_MCP_BETA = "mcp-client-2025-04-04"


def load_coach_prompt() -> str:
    """Return the verbatim master coaching prompt used as the system prompt."""
    return COACH_PROMPT_PATH.read_text(encoding="utf-8")


def _build_client() -> tuple[anthropic.Anthropic, list[dict], list[str]]:
    """Return (client, system_blocks, betas) for whichever auth path is available.

    Prefers ANTHROPIC_API_KEY (standalone). Falls back to ANTHROPIC_AUTH_TOKEN
    (the Claude Code platform OAuth), which requires the identity system prefix
    and the oauth beta. Raises if neither credential is present.
    """
    coach_block = {"type": "text", "text": load_coach_prompt()}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return anthropic.Anthropic(api_key=api_key), [coach_block], []

    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if auth_token:
        client = anthropic.Anthropic(
            auth_token=auth_token,
            default_headers={"anthropic-beta": _OAUTH_BETA},
        )
        system = [{"type": "text", "text": _CLAUDE_CODE_IDENTITY}, coach_block]
        return client, system, [_OAUTH_BETA]

    raise RuntimeError(
        "No model credential found. Set ANTHROPIC_API_KEY for a standalone CLI, or "
        "ANTHROPIC_AUTH_TOKEN when running inside the Claude Code platform."
    )


def _strava_mcp_servers() -> list[dict]:
    """Return an mcp_servers config for the hosted Strava connector, if configured."""
    url = os.environ.get("STRAVA_MCP_URL")
    token = os.environ.get("STRAVA_MCP_TOKEN")
    if url and token:
        return [
            {
                "type": "url",
                "url": url,
                "name": "strava",
                "authorization_token": token,
            }
        ]
    return []


def _extract_text(message: anthropic.types.Message) -> str:
    """Concatenate the text blocks of a response into the briefing string."""
    return "\n".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    ).strip()


def run_briefing(context: str, *, extra_directive: str | None = None) -> str:
    """Call Claude with the assembled context; return the briefing text (BUILD_SPEC §4.4).

    `extra_directive` appends a note to the user message — used by the guardrail
    retry (BUILD_SPEC §4.6) to feed a violation back into the prompt on retry.
    """
    client, system, betas = _build_client()
    mcp_servers = _strava_mcp_servers()
    if mcp_servers:
        betas = [*betas, _MCP_BETA]

    user_content = context if not extra_directive else f"{context}\n\n{extra_directive}"
    kwargs: dict = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }
    if mcp_servers:
        kwargs["mcp_servers"] = mcp_servers

    if betas:
        message = client.beta.messages.create(betas=betas, **kwargs)
    else:
        message = client.messages.create(**kwargs)
    return _extract_text(message)
