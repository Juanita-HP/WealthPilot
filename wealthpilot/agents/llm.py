"""Language-model clients.

* ``BedrockLLM``: Claude on Amazon Bedrock through the Anthropic SDK's Mantle
  client (Messages API on Bedrock). This is the AWS path used in the demo.
* ``AnthropicLLM``: the same calls on the first-party Claude API, for local
  development without AWS credentials.
* ``ScriptedLLM``: a deterministic stand-in for tests; it plays back tool calls
  and answers, so the whole pipeline is tested without network or cost.

All three expose ``create(system, messages, tools)`` and return an object with
``content`` (blocks with ``type``) and ``stop_reason``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from types import SimpleNamespace

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_MODEL = "claude-opus-4-8"   # used only if the main model declines a request (refusal)
DEFAULT_EFFORT = "medium"            # Opus 5.5's own default, set explicitly


class LLM:
    def create(self, system: str, messages: list, tools: list[dict], effort: str | None = None):
        raise NotImplementedError


class _AnthropicBase(LLM):
    model: str
    client: object
    max_tokens: int = 16_000

    def create(self, system, messages, tools, effort=None):
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config={"effort": effort or DEFAULT_EFFORT},
        )
        if tools:
            kwargs["tools"] = tools
        return self._send(**kwargs)

    def _send(self, **kwargs):
        raise NotImplementedError


class BedrockLLM(_AnthropicBase):
    """Claude on Amazon Bedrock (Mantle client). Credentials come from the standard AWS chain
    (environment, profile, or the Lambda execution role)."""

    def __init__(self, region: str | None = None, model: str | None = None, fallback: str | None = FALLBACK_MODEL):
        from anthropic import AnthropicBedrockMantle, BetaRefusalFallbackMiddleware

        self.model = model or f"anthropic.{DEFAULT_MODEL}"
        middleware = [BetaRefusalFallbackMiddleware([{"model": f"anthropic.{fallback}"}])] if fallback else []
        self.client = AnthropicBedrockMantle(aws_region=region or os.environ.get("AWS_REGION", "ca-central-1"),
                                             middleware=middleware)

    def _send(self, **kwargs):
        # Server-side fallbacks are not available on Bedrock; the client middleware retries refusals.
        return self.client.beta.messages.create(**kwargs)


class AnthropicLLM(_AnthropicBase):
    """First-party Claude API (local development)."""

    def __init__(self, model: str | None = None, fallback: str | None = FALLBACK_MODEL):
        import anthropic

        self.model = model or DEFAULT_MODEL
        self.fallback = fallback
        self.client = anthropic.Anthropic()

    def _send(self, **kwargs):
        if self.fallback:
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks=[{"model": self.fallback}])
        return self.client.beta.messages.create(**kwargs)


def from_env() -> LLM:
    """WEALTHPILOT_LLM = bedrock (default) | anthropic."""
    kind = os.environ.get("WEALTHPILOT_LLM", "bedrock")
    if kind == "bedrock":
        return BedrockLLM(model=os.environ.get("WEALTHPILOT_MODEL"))
    if kind == "anthropic":
        return AnthropicLLM(model=os.environ.get("WEALTHPILOT_MODEL"))
    raise ValueError(f"unknown WEALTHPILOT_LLM={kind!r}")


# ----------------------------------------------------------------------------- test double


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def tool_block(name: str, inputs: dict, id_: str):
    return SimpleNamespace(type="tool_use", name=name, input=inputs, id=id_)


@dataclass
class ScriptedLLM(LLM):
    """Plays back a script: each step is either a list of (tool_name, inputs) calls or a final text.

    A final text may contain ``{R?}`` placeholders, replaced by the receipt ids returned
    for the calls in the same script, in order, so tests can write grounded answers.
    """
    script: list
    calls: list = field(default_factory=list)

    def create(self, system, messages, tools, effort=None):
        self.calls.append({"system": system, "messages": list(messages), "tools": [t["name"] for t in tools]})
        step = self.script.pop(0)
        if isinstance(step, str):
            receipts = []
            for msg in messages:
                if msg["role"] == "user" and isinstance(msg["content"], list):
                    for block in msg["content"]:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            receipts.append(block["content"].split('"receipt":"')[1].split('"')[0]
                                            if '"receipt":"' in block["content"] else "R?")
            text = step
            for rid in receipts:
                text = text.replace("{R?}", f"[{rid}]", 1)
            return SimpleNamespace(content=[text_block(text)], stop_reason="end_turn")
        blocks = [tool_block(name, inp, f"toolu_{len(self.calls)}_{i}") for i, (name, inp) in enumerate(step)]
        return SimpleNamespace(content=blocks, stop_reason="tool_use")
