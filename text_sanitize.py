"""Shared text hygiene for anything that ends up as user-facing content in
Supabase (trending_reason, summaries, headlines, ...), regardless of how it
was produced -- an LLM call, or a hand-written Python string in this repo.

llm/client.py already strips real em dashes from LLM API responses, but
that guard has zero effect on deterministic template strings written
directly in code (pipeline/enricher.py, pipeline/holiday_dates.py, etc.) --
those never pass through the LLM client at all. A double-hyphen "--" used
as a manual em-dash substitute is exactly as unwanted in shipped copy as a
real em dash, and just as easy to type by habit without noticing.

This is applied at the DB-write boundary (db/saver.py, db/daily_summary_saver.py)
rather than only at the LLM client, so it catches both kinds of source at
the one place everything must pass through before persistence -- no future
call site can reintroduce this by omission.
"""
import re

_DASH_ARTIFACT_RE = re.compile(r"\s*(?:--|—)\s*")


def strip_dash_artifacts(text: str) -> str:
    if not text:
        return text
    return _DASH_ARTIFACT_RE.sub(" - ", text)
