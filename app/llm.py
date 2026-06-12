"""Unified Claude call layer with two interchangeable backends:

  "api"          — Anthropic API key / auth token (pay-per-use, platform.claude.com)
  "subscription" — your claude.ai Pro/Max account, via the Claude Agent SDK
                   (uses Claude Code's login; covered by the subscription)

The app picks automatically: an API key wins if present; otherwise the
Claude Agent SDK is used if installed and logged in.
"""

import importlib.util
import json
import os
import re


def mode() -> str:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "api"
    if importlib.util.find_spec("claude_agent_sdk") is not None:
        return "subscription"
    return "none"


# Subscription plans expose model families rather than pinned versions.
_SUBSCRIPTION_ALIAS = {"opus": "opus", "sonnet": "sonnet", "haiku": "haiku"}


def _subscription_model(model: str) -> str:
    for family, alias in _SUBSCRIPTION_ALIAS.items():
        if family in model:
            return alias
    return model


def complete(*, system: str, user: str, model: str, max_tokens: int = 8000) -> str:
    """One system+user turn -> assistant text, on whichever backend is connected."""
    m = mode()
    if m == "api":
        return _complete_api(system, user, model, max_tokens)
    if m == "subscription":
        return _complete_subscription(system, user, model)
    raise RuntimeError(
        "No Claude account connected. Either put ANTHROPIC_API_KEY in .env "
        "(platform.claude.com), or install Claude Code + the Claude Agent SDK "
        "and log in with your claude.ai subscription (see README).")


def _complete_api(system: str, user: str, model: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic()
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    return "".join(b.text for b in msg.content if b.type == "text")


def _complete_subscription(system: str, user: str, model: str) -> str:
    import asyncio

    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                  TextBlock, query)

    options = ClaudeAgentOptions(
        system_prompt=system,
        model=_subscription_model(model),
        allowed_tools=[],
        max_turns=1,
    )

    async def run() -> str:
        parts: list[str] = []
        async for message in query(prompt=user, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
        return "".join(parts)

    return asyncio.run(run())


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply (subscription mode has
    no structured-output guarantee, so tagging parses defensively)."""
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None
