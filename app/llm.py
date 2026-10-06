"""LLM clients with one shared interface: `chat(messages, tools)` returns a message with `.content` and
`.tool_calls` (OpenAI's shape), and `.calls` counts requests.

- `LLM`: any OpenAI-compatible endpoint (Ollama, Groq, Gemini...), switched with three env vars.
- `ClaudeLLM`: Claude through Anthropic's own SDK. It converts to and from the Messages API format, so the
  agent loop is identical for both.

`create()` picks one from `LLM_PROVIDER` (`openai`, the default, or `anthropic`).
"""

import json
import time
from types import SimpleNamespace

import openai

from app import config


class LLM:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 max_retries: int = 5, timeout: float = 120.0):
        self.model = model or config.LLM_MODEL
        if not self.model:
            raise RuntimeError("LLM_MODEL is not set. Add it to .env (see HANDOFF.md, 'Finish setup').")
        self.client = openai.OpenAI(base_url=base_url or config.LLM_BASE_URL or None,
                                    api_key=api_key or config.LLM_API_KEY or "unused",
                                    max_retries=0, timeout=timeout)
        self.max_retries = max_retries
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        """One completion at temperature 0. Returns the assistant message object."""
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                self.calls += 1
                response = self.client.chat.completions.create(
                    model=self.model, messages=messages, tools=tools or openai.NOT_GIVEN, temperature=0,
                )
                return response.choices[0].message
            except openai.RateLimitError:
                if attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay *= 2


class ClaudeLLM:
    """Claude via the Anthropic SDK, behind the same interface as `LLM`.

    Current Claude models always think and reject sampling parameters, so there is no temperature here; depth
    is set with `effort`. Inside a tool loop the API needs the assistant's full previous response (thinking
    blocks included) sent back unchanged, so the raw content of every tool-calling response is kept and
    replayed in place of the agent's simplified copy.
    """

    FALLBACK_BETA = "server-side-fallback-2026-07-01"
    REFUSAL_REPLY = "Sorry, I can't help with that request."

    def __init__(self, api_key: str | None = None, model: str | None = None, effort: str = "medium",
                 max_retries: int = 5, client=None):
        if client is None:
            import anthropic  # rate limits and 5xx are retried by the SDK with backoff

            client = anthropic.Anthropic(api_key=api_key or None, max_retries=max_retries)
        self.client = client
        self.model = model or config.LLM_MODEL
        self.effort = effort
        self.calls = 0
        self._raw: dict[str, list] = {}  # first tool_call id -> that response's content blocks
        self._tools: list[dict] | None = None

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        system, converted = self.convert_messages(messages)
        kwargs = {}
        if tools:
            self._tools = [{"name": t["function"]["name"], "description": t["function"]["description"],
                            "input_schema": t["function"]["parameters"]} for t in tools]
            kwargs["tools"] = self._tools
        elif self._tools:
            # History with tool calls still needs the definitions; "none" makes the model answer in text.
            kwargs.update(tools=self._tools, tool_choice={"type": "none"})
        self.calls += 1
        response = self.client.beta.messages.create(
            model=self.model, max_tokens=16000, system=system, messages=converted,
            output_config={"effort": self.effort},
            betas=[self.FALLBACK_BETA], fallbacks="default",  # on a refusal, the API retries on a fallback model
            **kwargs,
        )
        if response.stop_reason == "refusal":
            return SimpleNamespace(content=self.REFUSAL_REPLY, tool_calls=None)
        text = "".join(block.text for block in response.content if block.type == "text")
        calls = [SimpleNamespace(id=block.id, function=SimpleNamespace(name=block.name, arguments=json.dumps(block.input)))
                 for block in response.content if block.type == "tool_use"]
        if calls:
            self._raw[calls[0].id] = response.content
        return SimpleNamespace(content=text, tool_calls=calls or None)

    def convert_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """OpenAI-style history -> (system prompt, Messages API messages)."""
        system, out = [], []
        for message in messages:
            role = message["role"]
            if role == "system":
                system.append(message["content"])
            elif role == "tool":
                block = {"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message["content"]}
                previous = out[-1] if out else None
                if previous and previous["role"] == "user" and isinstance(previous["content"], list):
                    previous["content"].append(block)  # all results of one turn go back in a single message
                else:
                    out.append({"role": "user", "content": [block]})
            elif role == "assistant" and message.get("tool_calls"):
                raw = self._raw.get(message["tool_calls"][0]["id"])
                if raw is None:
                    raw = ([{"type": "text", "text": message["content"]}] if message.get("content") else []) + [
                        {"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                         "input": json.loads(c["function"]["arguments"] or "{}")} for c in message["tool_calls"]]
                out.append({"role": "assistant", "content": raw})
            else:
                out.append({"role": role, "content": message["content"] or "(no text)"})
        return "\n\n".join(system), out


def create(provider: str | None = None, base_url: str | None = None, api_key: str | None = None,
           model: str | None = None):
    """The configured LLM client."""
    provider = (provider or config.LLM_PROVIDER).lower()
    if provider == "anthropic":
        return ClaudeLLM(api_key=api_key or config.ANTHROPIC_API_KEY, model=model)
    if provider == "openai":
        return LLM(base_url, api_key, model)
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}; use openai or anthropic")
