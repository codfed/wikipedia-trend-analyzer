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

Recurring calendar holidays (`Labor Day`, `Christmas`, `Diwali`, etc.) skip
tiered search entirely -- there's rarely a real news story behind why a
holiday trends (it's just the date), so search would have nothing reliable
to find and was observed flipping the same holiday between mystery and
not year to year depending on incidental press coverage. `pipeline/enricher.py`'s
`HOLIDAY_TITLES` (hand-maintained like `BOT_TRAFFIC_TITLES`) triggers
`_enrich_holiday_article`, which sets `trending_reason_source="holiday"`
and `is_mystery=False`, skipping eval/example-bank scoring the same way
`rolling_list`/`carried_forward` articles do. The reason text itself is
LLM-composed, not templated: `pipeline/holiday_dates.py`'s
`describe_holiday_date` computes the Nth-weekday-of-month schedule fact
(whether this year's occurrence is the earliest/latest possible, for
holidays that have one) and hands it to the model as optional context
rather than forcing it into the reason -- most occurrences land in the
unremarkable middle of the range, so the model only mentions it when it's
actually a notable edge case, rather than every holiday's reason reciting
"N days after the earliest it could be" whether or not that's interesting.
This is independent of the `topic="holiday"` classification (see Daily
Trend Summary below), which the per-article classifier infers from
title+extract alone with no hardcoded list needed -- `HOLIDAY_TITLES` only
exists because *that* signal can't be inferred without running (and
having) search results.

### 1b. Piggyback Cross-Reference (`pipeline/piggyback.py`)
Runs once per date, after the per-article loop finishes and every other
article already has (or lacks) a real `trending_reason` to serve as context
-- this is what makes it a whole-day pass rather than something that fits
inside per-article enrichment. Targets only `is_mystery=True` articles: an
article whose own tiered search found nothing may still be trending because
it's riding another article that trended the *same day*, not because it has
a separate cause of its own (the motivating case: `United States` trending
alongside `Labor Day`, since `Labor Day` itself skips search entirely as a
`HOLIDAY_TITLES` entry -- see Tiered Search above).

Two stages, cheapest first:
1. **LLM cross-reference** -- one call per mystery article, given its
   title+summary and a list of that date's other already-explained articles
   (`trending_reason_source` in `news`/`search`/`reddit`/`deep_search`/
   `holiday`/`rolling_list`/`carried_forward` -- other still-unresolved
   mysteries are excluded, there's nothing there to explain anything with).
   The model either names one of those titles as a `candidate_title` with a
   `confidence`, or returns `null`. At `confidence >= 0.65` the candidate's
   connection is trusted directly and the mystery article is resolved with
   `trending_reason_source="piggyback"`, no new search call.
2. **Serper fallback** -- only when the model named a real candidate but
   wasn't confident enough on its own: one targeted Serper search seeded
   with `"{mystery title} {candidate title}"`, then the same relevance gate
   (`llm/relevance.py`) and `ExplanationGenerator` used by tiered search take
   over. Resolves with `trending_reason_source="piggyback_search"`.

Articles that clear neither stage are left as mysteries. Resolved articles
are re-saved to `trending_articles_v2` immediately (upsert on
`title,trending_date`) so evals and the daily trend summary -- both of
which run after this stage -- see the real reason instead of the mystery
placeholder. `piggyback` (no real search results) skips LLM judging in
`evals/judge.py`/`evals/metrics.py` the same way `holiday`/`rolling_list`/
`carried_forward` do; `piggyback_search` has real search results behind it
and is judged normally.

### 1c. Anniversary Lead-Up (`pipeline/anniversary.py`)
Runs once per date, after piggyback resolution has had its shot at the
remaining `is_mystery` queue. Handles a different shape of mystery than
piggyback: an article trending *ahead of* a calendar anniversary of a
historical event it's closely tied to (the motivating case: `Falling Man`
trending because September 11 is a few days out), where tiered search finds
nothing because there's no current news yet, and there's no other trending
article that day to cross-reference against either -- the reference point
is the calendar, not the day's other trends.

Three stages, each gating the next:
1. **LLM world-knowledge detection** (`ANNIVERSARY_DETECT_PROMPT`) -- asks
   whether the article's subject is specifically and directly tied to a
   historical event with a fixed calendar date (not a vague thematic link,
   not a birthday or routine recurring event). This is the one place in the
   pipeline that leans on the model's own knowledge instead of search
   results or a hand-curated list -- the set of possible anniversary-
   adjacent articles is unbounded, unlike `HOLIDAY_TITLES` -- so its output
   is treated as an unverified candidate until stage 3 confirms it.
2. **Deterministic date-proximity check** (`pipeline/anniversary_dates.py`,
   `describe_anniversary_proximity`) -- pure calendar math, same spirit as
   `holiday_dates.py`. Forward-looking only: an anniversary that already
   passed this year, even by a day, is not a match. Window is 7 days
   (`LEAD_UP_WINDOW_DAYS`).
3. **Grounding search + verification** -- a real Serper search for the
   article title alongside the claimed event (wide, ~100-year time window,
   since it's confirming a historical fact rather than hunting for recent
   news), gated by a separate LLM call (`ANNIVERSARY_VERIFY_PROMPT`) that
   checks the results actually substantiate the specific connection rather
   than coincidental keyword overlap. Only a confirmed connection resolves
   the mystery, with `trending_reason_source="anniversary"`; an unconfirmed
   candidate is left as a mystery rather than guessed at. No "Nth
   anniversary" year is asserted in the generated reason unless it's
   present in the grounding search results themselves -- the detection
   step's guess at an origin year is never trusted on its own.

Like `piggyback_search`, `anniversary` has real search results behind it
and is judged normally by evals (no skip-list entry needed).

### 2. Unified Explanation Fields
| Field | Description |
|---|---|
| `trending_reason` | 3–4 sentence explanation |
| `trending_reason_short` | 12–22 word compressed version |
| `trending_reason_source` | `"news"` \| `"search"` \| `"reddit"` \| `"deep_search"` \| `"holiday"` \| `"rolling_list"` \| `"carried_forward"` \| `"piggyback"` \| `"piggyback_search"` \| `"anniversary"` \| `"unknown"` |

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
rows, not narrative prose. It asks the model to judge three things: whether
two or more *new* articles share the same real-world story and should be
merged into a `new_cluster` row; whether a new article is a purely
domestic Indian story (a state/local Indian politician, a regional
Bollywood release, a local Indian court case, a state-level Indian event)
with no significance outside India -- those get excluded from the digest
entirely rather than a row (`excluded_india_local` in the model's
response), while an Indian story with real international coverage, a
globally recognized figure, or cross-border impact gets a normal entry
like anything else; and whether an entry's story is fundamentally about
someone dying today (`is_death`), which overrides that row's `topic` (see
below) regardless of the person's profession. Everything else -- whether a
continuing article is a rolling reference page (`List of ...`, `Deaths in
YYYY`) vs. a real story, and whether a title is bot-traffic -- is decided
deterministically in Python before the prompt is built, and a continuing
article's title is filtered out of any `new_rows` cluster it might have
been merged into (a defense against the model rendering the exact same
trend twice).

The one continuing-article row that *is* built today is the obituary row for
`Deaths in YYYY`: `pipeline/enricher.py`'s `_enrich_deaths_article` already
scrapes that date's entries via `pipeline/deaths_scraper.py` and stores them
on `Article.death_entries`; `main.py` turns that straight into an
`ongoing_list` row (one bullet per entry) without going through the LLM --
it's a verbatim slice of Wikipedia's own list, not something that needs
synthesis. Other rolling/reference pages (`List of ...`) still get no row.

Recurring calendar holidays (`trending_reason_source == "holiday"`) are
**not** excluded from `DailySummaryGenerator`'s clustering call -- they're
eligible for a row like any other article, using their own already-composed
`trending_reason` (see Tiered Search above; holiday reasons are LLM-written
now too, from `pipeline/enricher.py`'s `_enrich_holiday_article`) as
context. This is what lets a holiday become a cover story: when another
article piggybacks on it (e.g. `United States` on `Labor Day`, see Piggyback
Cross-Reference above), the clustering model can recognize both as the same
underlying story and merge them into one `titles`-plural row exactly the
way it merges any other two related articles -- no separate deterministic
merge path needed. The one thing that's still forced rather than left to
the model: any row containing a holiday gets `category="holiday"` (and
`topic="holiday"`) applied after the fact in `llm/daily_summary.py`, cluster
or not, so the frontend can keep rendering holidays in their own section
rather than mixed into the regular new/cluster feed. This is independent of
the `topic="holiday"` *article*-level classification (`Article.topic`),
which the per-article classifier infers from title+extract alone -- the
digest-row override exists because the clustering model might pick a
non-holiday member as the row's "face" (e.g. `United States` over `Labor
Day`), and `topics_by_title.get(subject_title)` alone wouldn't reliably
carry "holiday" in that case.

Anniversary-driven articles (`trending_reason_source == "anniversary"`, see
Anniversary Lead-Up above) are likewise never excluded from clustering --
this matters when several independently-resolved articles converge on the
same historical anniversary (e.g. multiple September 11-adjacent articles
trending the same week): each already has its own real, LLM-written
`trending_reason` mentioning the event by name, so the clustering call can
recognize and merge them the same way it clusters any other shared story.
No `category` override is needed here (unlike holidays) -- an
anniversary-driven cluster is just a normal `new_cluster` row.

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
| `holiday` | A recurring calendar holiday (`HOLIDAY_TITLES`), its own section |

Every row also gets `topic`, `country`, and `is_mystery` -- a separate
content-classification triple for frontend iconography (distinct from
`category` above, which describes the row's structural role in the digest,
not what it's about). These are classified **per article**, not per digest
row: `main.py`'s always-run summary step (`_generate_summary_and_classify`)
bundles classification into the same Haiku call that already produces
`article.summary` for *every* processed article, so it's free (no extra
LLM call) and works even for `is_mystery` articles, since it only needs the
article's own title+extract, never why it's trending. `topic` is the single
most specific applicable label from a ~40-value controlled vocabulary
(individual sports, media types, music genres, a person's public role,
crime subtypes, etc.) -- the canonical list lives in `llm/topics.py`'s
`VALID_TOPICS` and must stay in sync with the grouped, human-readable copy
in `SUMMARY_PROMPT` (`llm/prompts.py`). A topic the model returns that
isn't in `VALID_TOPICS` is replaced with `"other"` rather than trusted
verbatim. `country` is an ISO 3166-1 alpha-2 code (nullable) when the
subject is genuinely centered on one country, letting the frontend render a
flag alongside the topic icon -- the two are independent (a story can be
`tennis` + `ES` at once).

A digest row's `topic`/`country`/`is_mystery` are just copied from its
`subject_title` article (`llm/daily_summary.py`), not re-judged -- with one
exception: article-level classification can never know "this person died
today" from title+extract alone (their Wikipedia bio reads the same
whether they're alive or not), so `DailySummaryGenerator` still asks the
digest LLM call for one narrow boolean, `is_death`, and overrides the
row's `topic` to `"death"` when true, regardless of the subject's
profession. The `Deaths in YYYY` obituary row (see above) gets
`topic="death"`, `country=None`, `is_mystery=False` deterministically in
`build_obituary_row`, not via any LLM. Rows built by the safety net (the
model dropped a title by accident) still pull `topic`/`country`/`is_mystery`
from the article's own classification, since that's independent of the
digest LLM call succeeding.

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
| `pipeline/piggyback.py` | Post-loop pass: resolves is_mystery articles that piggyback on the day's other trends |
| `pipeline/anniversary.py` | Post-loop pass: resolves is_mystery articles trending ahead of a calendar anniversary |
| `pipeline/anniversary_dates.py` | Date-math for the anniversary lead-up window |
| `search/tiered.py` | `TieredSearcher` decision tree |
| `llm/prompts.py` | All prompts + `PROMPT_VERSION` constant |
| `llm/relevance.py` | Structured relevance gate |
| `llm/generator.py` | Explanation generator with few-shot injection |
| `memory/example_bank.py` | Read/write high-scoring examples |
| `evals/runner.py` | Run all checks; log to Supabase |
| `db/saver.py` | Upsert to `trending_articles_v2` + `eval_results` |
| `pipeline/daily_stats.py` | Streak length + view-delta trajectory + bot-traffic classification, no LLM |
| `llm/topics.py` | Shared topic/country taxonomy + validators |
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
  topic text,
  country text,
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
  category text not null check (category in ('new', 'new_cluster', 'ongoing_trend', 'ongoing_list', 'ongoing_anomaly', 'holiday')),
  titles text[] not null,
  headline text not null,
  summary text not null,
  image_url text,
  topic text,
  country text,
  is_mystery boolean default false,
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
