# Wikipedia Trend Analyzer

Fetches Wikipedia's daily trending articles, figures out *why* each one is trending, and stores the results. Runs on a daily schedule and gets smarter over time.

Each article is run through a tiered search pipeline (news → web → deep search), and a Claude LLM generates a plain-English explanation. High-quality outputs are stored in an example bank and injected as few-shot context into future runs.

---

## How it works

```
Wikimedia Featured Feed
        ↓
Trending status calculation (view delta, newly trending flag)
        ↓
Tiered search  →  news search → web search → deep search → unknown
        ↓
Relevance gating  (Claude Haiku — is this result actually relevant?)
        ↓
Explanation generation  (Claude Sonnet — trending_reason + trending_reason_short)
        ↓
Self-improving loop  (score output → store good examples → inject next run)
        ↓
Supabase
```

Repeat articles that have already been explained are carried forward without re-running search or LLM calls. Rolling-list articles like *Deaths in 2026* are handled as a special case — scraped directly from Wikipedia and never passed through the search pipeline.

---

## Quickstart

```bash
# 1. Clone and set up environment
git clone https://github.com/codfed/wikipedia-trend-analyzer
cd wikipedia-trend-analyzer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Copy and fill in env vars
cp .env.example .env

# 3. Run for today
python main.py

# 4. Run for a specific date
TARGET_DATE=2026-04-12 python main.py

# 5. Debug a single article
TARGET_DATE=2026-04-12 TARGET_TITLE=Shmuel_Mikunis python main.py
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Powers all LLM calls (relevance, explanation, judging) |
| `SUPABASE_URL` | No | Supabase project URL — saves and example bank are skipped if unset |
| `SUPABASE_KEY` | No | Supabase anon or service key |
| `SERPER_API_KEY` | No | Search API key — articles are marked mystery if unset |
| `WIKIPEDIA_EMAIL` | No | Added to Wikipedia API User-Agent header (good practice) |
| `TARGET_DATE` | No | Override run date (`YYYY-MM-DD`) |
| `TARGET_TITLE` | No | Run for a single article only (useful for debugging) |
| `SKIP_EVALS` | No | Set to `1` to skip the post-run eval pass |

Copy `.env.example` to `.env` and fill in the values you need.

---

## Project structure

```
main.py                  # Entry point — orchestrates the full pipeline
pipeline/
  models.py              # Article dataclass — single source of truth
  enricher.py            # Tiered search + explanation generation per article
  deaths_scraper.py      # Special case: scrapes Deaths in YYYY from Wikipedia
  fetcher.py             # Pulls trending articles from Wikimedia Featured Feed
  parser.py              # Parses feed into Article objects
  trending.py            # Calculates view delta and newly-trending flag
search/
  tiered.py              # News → web → deep search orchestration
  client.py              # Serper API wrapper
  query_rewriter.py      # LLM-powered query rewriting for deep search
llm/
  client.py              # Anthropic API wrapper
  prompts.py             # All prompts + PROMPT_VERSION constant
  relevance.py           # Structured relevance gate (Haiku)
  generator.py           # Explanation generator with few-shot injection (Sonnet)
db/
  client.py              # Supabase connection wrapper
  saver.py               # Upsert articles + eval results
memory/
  example_bank.py        # Read/write high-scoring examples for few-shot injection
  prompt_tracker.py      # Logs prompt version per run
evals/
  runner.py              # Run all checks and print report
  judge.py               # LLM-as-judge rubrics
  metrics.py             # Deterministic checks (banned phrases, sentence count)
  fixtures.py            # Load articles from Supabase for eval
```

---

## Evals

Evals run automatically after every pipeline run. Two fields are evaluated per article:

- `trending_reason` — relevance, groundedness, and format (LLM judge)
- `trending_reason_short` — faithfulness and conciseness (LLM judge)

Run evals manually against a past date:

```bash
python evals/runner.py --date 2026-04-12
python evals/runner.py --flagged   # articles flagged for testing
```

---

## Supabase schema

The full table definitions are in [`CLAUDE.md`](CLAUDE.md#supabase-tables-required).

---

## Tech stack

- **Python 3.13**
- **Anthropic API** — Claude Sonnet 4.6 for explanations, Haiku for relevance gating and judging
- **Serper** — Google News and web search
- **Supabase** — Postgres storage for articles, evals, and example bank
- **Wikimedia API** — Trending article feed and raw wikitext
