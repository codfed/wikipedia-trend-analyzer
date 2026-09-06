# CLAUDE.md — wikipedia-trends-v2

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run for today
python main.py

# Run for a specific date
TARGET_DATE=2026-04-12 python main.py

# Single article (debug)
TARGET_DATE=2026-04-12 TARGET_TITLE=Shmuel_Mikunis python main.py

# Evals on a past run
python evals/runner.py --date 2026-04-12

# Evals on flagged test fixtures
python evals/runner.py --flagged

# Check example bank size
python -c "from memory.example_bank import ExampleBank; print(ExampleBank().count())"
```

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` — used by `llm/client.py`

Optional (saves and example bank are skipped if unset):
- `SUPABASE_URL`
- `SUPABASE_KEY`

Optional (search stages are skipped and articles marked mystery if unset):
- `SERPER_API_KEY`

## Architecture

Linear pipeline with three compounding improvements over v1:

### 1. Tiered Search (`search/tiered.py`)
Each trending article is searched through sequential stages until a relevant
result is found.  Stops early:
- **Stage 1**: Serper news (past week)
- **Stage 2**: Serper web search (past week)
- **Stage 3**: Serper `site:reddit.com` search (past month) — catches grassroots
  virality (e.g. a TIL repost) that predates the article's exact title and can
  lag its source content by weeks
- **Stage 4**: Deep — LLM rewrites query (`search/query_rewriter.py`), considering
  non-news drivers (video, podcast, forum) + Serper (past month)
- **unknown**: all stages failed → `is_mystery=True`

Relevance is decided by a structured LLM call (`llm/relevance.py`) that returns
`{"relevant": bool, "confidence": float}`. Threshold: `confidence >= 0.65`.

### 2. Unified Explanation Fields
| Field | Description |
|---|---|
| `trending_reason` | 3–4 sentence explanation |
| `trending_reason_short` | 12–22 word compressed version |
| `trending_reason_source` | `"news"` \| `"search"` \| `"reddit"` \| `"deep_search"` \| `"unknown"` |

Replaces the four v1 fields (`news_relation`, `news_relation_short`,
`search_relation`, `search_relation_short`).

### 3. Self-Improving Loop
After each run, `main.py` scores the enriched articles with `LLMJudge`.
Outputs with score ≥ 4 are stored in the `example_bank` Supabase table.
Future runs pull 2 examples from the bank and inject them as few-shot context
into the generation prompt.

### 4. Versioned Prompts
All prompts live in `llm/prompts.py`.  `PROMPT_VERSION` is a string constant
(e.g. `"v2.0"`) stored with every saved article and eval result, enabling
quality tracking across prompt changes.

### 5. Daily Trend Summary (`pipeline/daily_stats.py`, `llm/daily_summary.py`)
Runs once per date after the per-article loop finishes, not per-article --
relating trends to each other requires seeing the whole day's list at once.

`compute_daily_stats` derives streak length and view-delta trajectory
(`accelerating`/`declining`/`plateauing`) for every article purely from
`trending_articles_v2` rows already saved (no LLM). It also splits titles
into `organic` vs `bot_traffic` via a hand-maintained list
(`BOT_TRAFFIC_TITLES`) -- generic/domain-name-style titles and obscure
geography stubs that persistently trend with no real driver (e.g. `Google`,
`.xyz`, `Neatsville, Kentucky`). There's no reliable numeric signature for
this (Google is also genuinely newsworthy most days), so it's curated by
hand as new offenders are spotted.

`DailySummaryGenerator` makes one LLM call per date to produce structured
rows, not narrative prose. It asks the model to judge two things: whether
two or more *new* articles share the same real-world story and should be
merged into a `new_cluster` row, and whether a new article is a purely
domestic Indian story (a state/local Indian politician, a regional
Bollywood release, a local Indian court case, a state-level Indian event)
with no significance outside India -- those get excluded from the digest
entirely rather than a row (`excluded_india_local` in the model's
response). An Indian story with real international coverage, a globally
recognized figure, or cross-border impact is unaffected and gets a normal
entry like anything else. Everything else -- whether a continuing article
is a rolling reference page (`List of ...`, `Deaths in YYYY`) vs. a real
story, and whether a title is bot-traffic -- is decided deterministically
in Python before the prompt is built, and a continuing article's title is
filtered out of any `new_rows` cluster it might have been merged into (a
defense against the model rendering the exact same trend twice).

The one continuing-article row that *is* built today is the obituary row for
`Deaths in YYYY`: `pipeline/enricher.py`'s `_enrich_deaths_article` already
scrapes that date's entries via `pipeline/deaths_scraper.py` and stores them
on `Article.death_entries`; `main.py` turns that straight into an
`ongoing_list` row (one bullet per entry) without going through the LLM --
it's a verbatim slice of Wikipedia's own list, not something that needs
synthesis. Other rolling/reference pages (`List of ...`) still get no row.

Output rows are saved to `daily_trend_rows` via `DailySummarySaver`, which
deletes-then-inserts per date rather than upserting -- clusters have no
natural unique key, and a re-run for the same date should fully replace the
prior rows, not accumulate duplicates.

| `category` | Meaning |
|---|---|
| `new` | A single article trending for the first time |
| `new_cluster` | Two+ new articles sharing the same real-world story |
| `ongoing_trend` | A continuing article with a real news arc |
| `ongoing_list` | A continuing rolling/reference page (`List of ...`, `Deaths in YYYY`) |
| `ongoing_anomaly` | A continuing article on `BOT_TRAFFIC_TITLES` |

### 6. Eval-First Design
Evals run automatically after every pipeline run.  Two fields are evaluated:
- `trending_reason` — faithfulness + format (LLM judge + deterministic checks)
- `trending_reason_short` — word count gate + faithfulness (LLM judge)

Results are printed to stdout and optionally persisted to `eval_results`.

## Key Files

| File | Purpose |
|---|---|
| `pipeline/models.py` | `Article` dataclass — single source of truth |
| `pipeline/enricher.py` | Orchestrates tiered search + explanation generation |
| `search/tiered.py` | `TieredSearcher` decision tree |
| `llm/prompts.py` | All prompts + `PROMPT_VERSION` constant |
| `llm/relevance.py` | Structured relevance gate |
| `llm/generator.py` | Explanation generator with few-shot injection |
| `memory/example_bank.py` | Read/write high-scoring examples |
| `evals/runner.py` | Run all checks; log to Supabase |
| `db/saver.py` | Upsert to `trending_articles_v2` + `eval_results` |
| `pipeline/daily_stats.py` | Streak length + view-delta trajectory + bot-traffic classification, no LLM |
| `llm/daily_summary.py` | One LLM call/date; produces structured `daily_trend_rows` |
| `db/daily_summary_saver.py` | Delete-then-insert `daily_trend_rows` per date |

## Supabase Tables Required

```sql
-- Main articles table
create table trending_articles_v2 (
  id uuid primary key default gen_random_uuid(),
  trending_date date not null,
  title text not null,
  normalized_title text,
  link text,
  thumbnail text,
  extract text,
  view_count int,
  rank int,
  mystery_rank int,
  view_history jsonb,
  is_newly_trending bool,
  view_delta_percentage int,
  summary text,
  trending_reason text,
  trending_reason_short text,
  trending_reason_source text,
  is_mystery bool default false,
  raw_search_results text,
  search_query_used text,
  prompt_version text,
  flag_for_test bool default false,
  created_at timestamptz default now(),
  unique (title, trending_date)
);

-- Eval results
create table eval_results (
  id uuid primary key default gen_random_uuid(),
  title text,
  trending_date date,
  field text,
  score int,
  reasoning text,
  passed bool,
  prompt_version text,
  created_at timestamptz default now()
);

-- Example bank
create table example_bank (
  id uuid primary key default gen_random_uuid(),
  title text,
  trending_reason_source text,
  raw_input text,
  trending_reason text,
  score int,
  created_at timestamptz default now()
);

-- Prompt run log
create table prompt_run_log (
  id uuid primary key default gen_random_uuid(),
  run_date date,
  prompt_version text,
  article_count int,
  created_at timestamptz default now()
);

-- Daily trend summary rows (see "Daily Trend Summary" above)
create table daily_trend_rows (
  id uuid primary key default gen_random_uuid(),
  trending_date date not null,
  category text not null check (category in ('new', 'new_cluster', 'ongoing_trend', 'ongoing_list', 'ongoing_anomaly')),
  titles text[] not null,
  headline text not null,
  summary text not null,
  image_url text,
  streak_days int,
  trajectory text,
  prompt_version text,
  created_at timestamptz default now()
);
create index idx_daily_trend_rows_date on daily_trend_rows (trending_date);
```

## Adding a New LLM Field

1. Add a prompt + config constants to `llm/prompts.py`
2. Add the field to `Article` in `pipeline/models.py`
3. Generate the field in `pipeline/enricher.py`
4. Map the field in `db/saver.py`
5. Add an eval rubric in `evals/judge.py`
