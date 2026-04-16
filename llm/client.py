"""Thin Anthropic API wrapper."""
import json
import os
from typing import Any, Optional

from anthropic import Anthropic


class LLMClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable."
            )
        self._client = Anthropic(api_key=self.api_key)

    def generate(
        self,
        prompt: str,
        model: str = "claude-haiku-4-5-20251001",
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        """Send a plain text prompt; return stripped text response."""
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        return text.strip() if text else ""

    def generate_json(
        self,
        prompt: str,
        model: str = "claude-haiku-4-5-20251001",
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> dict[str, Any]:
        """Send a prompt that expects a JSON response; parse and return dict.

        Raises ValueError if the response cannot be parsed as JSON.
        """
        raw = self.generate(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # Strip markdown code fences if the model wraps the JSON
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()
        return json.loads(cleaned)
