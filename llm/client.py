"""Thin Anthropic API wrapper."""
import json
import os
import re
from typing import Any, Optional

from anthropic import Anthropic

# Claude models default to em dashes in prose regardless of prompt wording.
# Stripped centrally here -- the one choke point every generated string
# (plain text or a JSON field parsed from it) passes through -- rather than
# relying on each prompt to ask nicely and risk missing a call site.
_EM_DASH_RE = re.compile(r"\s*—\s*")


def _strip_em_dashes(text: str) -> str:
    return _EM_DASH_RE.sub(" - ", text)


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
        # anthropic>=1.0.0 dropped `temperature` from messages.create() --
        # it's no longer forwarded to the API. Kept as a param here so
        # existing call sites (main.py, generator.py, relevance.py, etc.)
        # don't need to change.
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        text = text.strip() if text else ""
        return _strip_em_dashes(text)

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
        # raw_decode (not json.loads) so trailing text after a valid JSON
        # value -- e.g. the model second-guessing itself with "Wait, let me
        # fix that:" plus a corrected blob -- doesn't fail the whole parse.
        obj, _ = json.JSONDecoder().raw_decode(cleaned)
        return obj
