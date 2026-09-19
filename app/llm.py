"""A thin OpenAI-compatible chat client with retry on rate limits.

Any provider with an OpenAI-style /chat/completions endpoint and tool calling works (Ollama, Groq,
Gemini's compatibility endpoint...). Switching provider means changing three env vars.
"""

import time

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
