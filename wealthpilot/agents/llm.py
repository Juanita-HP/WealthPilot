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

DEFAULT_MODEL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
FALLBACK_MODEL = "global.amazon.nova-2-lite-v1:0"   # used only if the main model declines a request (refusal)
DEFAULT_EFFORT = "medium"


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


def _to_converse_messages(messages: list) -> list[dict]:
    out = []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            blocks = [{"text": c}]
        else:
            blocks = []
            for b in c:
                if isinstance(b, dict):
                    if b.get("type") == "tool_result":
                        blocks.append({
                            "toolResult": {
                                "toolUseId": b["tool_use_id"],
                                "content": [{"text": str(b["content"])}],
                                "status": "error" if b.get("is_error") else "success",
                            }
                        })
                    elif b.get("type") == "text" and b.get("text"):
                        blocks.append({"text": b["text"]})
                else:
                    if getattr(b, "type", None) == "text" and getattr(b, "text", ""):
                        blocks.append({"text": b.text})
                    elif getattr(b, "type", None) == "tool_use":
                        blocks.append({
                            "toolUse": {
                                "toolUseId": b.id,
                                "name": b.name,
                                "input": dict(b.input or {}),
                            }
                        })
        if blocks:
            out.append({"role": m["role"], "content": blocks})
    return out


class BedrockLLM(LLM):
    """Amazon Bedrock Converse API client (boto3). Credentials come from the standard AWS chain
    (environment, ~/.aws/credentials, or the Lambda execution role)."""

    max_tokens: int = 4096

    def __init__(self, region: str | None = None, model: str | None = None, fallback: str | None = FALLBACK_MODEL):
        import boto3
        from botocore.config import Config

        self.region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        self.model = model or DEFAULT_MODEL
        self.fallback = fallback
        cfg = Config(region_name=self.region, retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=120)
        self.client = boto3.client("bedrock-runtime", config=cfg)

    def _call(self, model_id: str, system: str, messages: list, tools: list[dict]):
        kwargs = {
            "modelId": model_id,
            "system": [{"text": system}],
            "messages": _to_converse_messages(messages),
            "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": 0.2},
        }
        if tools:
            kwargs["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t["name"],
                            "description": t["description"],
                            "inputSchema": {"json": t["input_schema"]},
                        }
                    }
                    for t in tools
                ]
            }
        resp = self.client.converse(**kwargs)
        stop = resp.get("stopReason", "end_turn")
        if stop in ("guardrail_intervened", "content_filtered"):
            stop = "refusal"
        blocks = []
        for item in resp.get("output", {}).get("message", {}).get("content", []):
            if "text" in item and item["text"]:
                blocks.append(text_block(item["text"]))
            elif "toolUse" in item:
                tu = item["toolUse"]
                blocks.append(tool_block(tu["name"], dict(tu.get("input") or {}), tu["toolUseId"]))
        return SimpleNamespace(content=blocks, stop_reason=stop)

    def create(self, system: str, messages: list, tools: list[dict], effort: str | None = None):
        resp = self._call(self.model, system, messages, tools)
        if resp.stop_reason == "refusal" and self.fallback:
            return self._call(self.fallback, system, messages, tools)
        return resp


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
    model = os.environ.get("WEALTHPILOT_MODEL")
    fallback = os.environ.get("WEALTHPILOT_FALLBACK_MODEL") or FALLBACK_MODEL
    if kind == "bedrock":
        return BedrockLLM(model=model, fallback=fallback)
    if kind == "anthropic":
        return AnthropicLLM(model=model, fallback=fallback)
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
