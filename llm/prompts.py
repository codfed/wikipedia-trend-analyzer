"""All LLM prompts and versioning constants for wikipedia-trends-v2."""

# Increment this whenever a prompt changes.  Saved articles and eval results
# include this version so quality changes can be tracked over time.
PROMPT_VERSION = "v2.5"

# ---------------------------------------------------------------------------
# Summary (always runs, Haiku)
# ---------------------------------------------------------------------------
SUMMARY_MODEL = "claude-haiku-4-5-20251001"
SUMMARY_TEMPERATURE = 0.3
SUMMARY_MAX_TOKENS = 128
SUMMARY_PROMPT = """Given the Wikipedia extract below, write a short description \
that does NOT mention or reference the article's title.

Rules:
- Focus on describing the subject's content or significance.
- Include enough context to be useful (e.g. country, medium, field).
- Length: 8–15 words (shorter is better).

Title: {title}
Extract: {extract}"""

# ---------------------------------------------------------------------------
# Relevance gate (Haiku, structured JSON output)
# ---------------------------------------------------------------------------
RELEVANCE_MODEL = "claude-haiku-4-5-20251001"
RELEVANCE_TEMPERATURE = 0.0
RELEVANCE_MAX_TOKENS = 64
RELEVANCE_PROMPT = """You are deciding whether search results are relevant to \
explaining why a Wikipedia article is suddenly trending.

A valid explanation doesn't have to be a news event — a viral reddit thread, \
forum discussion, TikTok/YouTube video, or podcast episode is just as valid a \
cause of a traffic spike as a news story, as long as the content is clearly \
about the article's subject.

Article title: {title}
Article summary: {summary}

Search results:
{results}

Does the search content directly explain or strongly relate to why "{title}" \
is receiving unusual traffic right now?

Respond with ONLY valid JSON on one line:
{{"relevant": <true|false>, "confidence": <0.0-1.0>}}"""

# ---------------------------------------------------------------------------
# Explanation generation (Sonnet, with optional few-shot examples)
# ---------------------------------------------------------------------------
EXPLANATION_MODEL = "claude-sonnet-4-6"
EXPLANATION_TEMPERATURE = 0.3
EXPLANATION_MAX_TOKENS = 512
EXPLANATION_PROMPT = """You are a concise trend analysis assistant.

Your task: explain why the Wikipedia article "{title}" is currently trending, \
using ONLY the search results below. Every substantive claim must be directly \
supported by those results—no speculation, no invented names, dates, numbers, \
or causal links that the results do not state.

Rules:
{length_rule}
- Stay direct: no filler, no meandering asides, no repeating the same point in different words.
- Do NOT hedge with "likely", "perhaps", "may have", or similar unless the search text \
uses that uncertainty explicitly.
- Light tone or whimsy is fine only if it adds no new factual claims and does not wander.
- Do NOT start with "Here is the reason why…" or "The article is trending because…"
- Avoid "spotlight" and "widespread".
{few_shot_block}
Search results ({source_type}):
{results}

Article summary: {summary}

Explanation:"""

DEFAULT_LENGTH_RULE = (
    "- One clear thread: lead with the main reason, then only what is needed for context. "
    "Use at most three short sentences; one or two is better if that fully answers it."
)

# Reddit results are the most colorful source this pipeline sees, and the
# generic 1-3 sentence rule squeezes out exactly the detail that makes them
# fun to read — which subreddits, and in whose words.
REDDIT_LENGTH_RULE = (
    "- This is Reddit-sourced — the most entertaining source type in this project, so be "
    "verbose here: 4-6 sentences is expected, not the usual one-to-three.\n"
    "- Name the specific subreddit(s) involved by their r/name (each result below is "
    "prefixed with the subreddit it came from) — never just say \"Reddit users.\"\n"
    "- Quote distinctive phrases from the results in quotation marks when they capture the "
    "tone, a repeated meme/copypasta, or a specific claim.\n"
    "- If the same odd phrase shows up across multiple unrelated subreddits, say so "
    "explicitly — that spread pattern is often the actual story.\n"
    "- Every subreddit name and quote must come verbatim from the results below — never "
    "invent one."
)

# ---------------------------------------------------------------------------
# Short summary (Haiku, condenses the full explanation)
# ---------------------------------------------------------------------------
SHORT_MODEL = "claude-haiku-4-5-20251001"
SHORT_TEMPERATURE = 0.2
SHORT_MAX_TOKENS = 128
SHORT_PROMPT = """Write a single concise sentence that identifies what "{title}" is and why it is trending.

Structure: lead with the title and a brief descriptor drawn from the summary (e.g. "AEW Dynasty, a professional wrestling event, ..." or "Dhurandhar: The Revenge, an Indian film, ..."), then state the trending reason.

Rules:
- Use the article summary below to form the descriptor — keep it short (3–6 words).
- Be concise — one tight sentence, as short as the content allows.
- Use only facts explicitly stated in the trending reason.
- Only include dates if they appear verbatim in the trending reason.

Article summary:
{summary}

Trending reason:
{trending_reason}

Short summary:"""

# ---------------------------------------------------------------------------
# Daily trend rows (Sonnet, structured JSON) -- run once per day
# ---------------------------------------------------------------------------
DAILY_SUMMARY_MODEL = "claude-sonnet-4-6"
DAILY_SUMMARY_TEMPERATURE = 0.3
DAILY_SUMMARY_MAX_TOKENS = 2048
DAILY_SUMMARY_PROMPT = """You are producing a scannable list of today's newly-trending \
Wikipedia articles -- the goal is for a reader to skim it and think "oh yeah, I heard about \
that" for anything they've seen elsewhere, with an easy path to learn more about each one.

NEW ARTICLES (first appeared today):
{new_articles_block}

Task:
1. Most articles get their own entry -- a quick one-line blurb, terse enough to skim.
2. Only when two or more articles share the same real-world story or event, group them into \
a single cluster entry instead of separate ones. A cluster gets ONE blurb that synthesizes \
why the story matters as a whole (not each article's blurb stacked together). Don't force a \
connection that isn't directly supported by the reasons given -- a shared vague theme is not \
enough, it must be the same underlying story or event.
3. Every article listed above must end up in exactly one entry, EXCEPT the India-local \
exclusions described in step 7 below.
4. Each entry also gets a headline -- a punchy, news-ticker-style headline, roughly 4-9 \
words, present tense, no filler like "is trending" or "after". Default to leading with the \
subject's name -- keep it for anyone with an established public career or profile (an actor, \
a working professional athlete, a public figure), even if they're not a household name. Only \
skip the name -- replacing it with a plain-language description of who they are (their sport, \
profession, and/or country stand in for the name) -- when the subject is genuinely obscure: \
someone with no real public profile beyond their own narrow scene (a local/regional \
politician, a first-time amateur, a niche athlete unlikely to be recognized outside their \
sport's own fanbase). Never leave a league, award, or institution acronym unexplained in a \
headline (no "NRL", no "IPL") -- spell it out or describe it in words a stranger would \
understand, or drop it if it's not essential to the headline. When an entry is fundamentally \
about a conflict or back-and-forth between two people/sides, an emoji connector can stand in \
for the relationship instead of spelling it out in prose (e.g. a boxing glove for a feud) -- \
but only when both sides clear the same recognizability bar; don't emoji-connect a well-known \
name to an obscure one. Examples \
of the target tone: "Hayden Panettiere dies from cardiac arrest", "Natalie Harp 🥊 Melania \
Trump continues", "Australian rugby league star plays final game".
5. Each entry also gets subject_title: whichever single title from its own "titles" list is \
the entry's actual face -- the one a cover image should show. For a standalone entry this is \
just that one title. For a cluster, pick whichever member the headline is really about (e.g. \
for a headline like "Dolly Parton dies at 80" covering 17 related titles, the subject is \
"Dolly Parton", not one of the tribute/filmography articles pulled in around it).
6. Each entry also gets image_worthy (true/false). This is only meaningful for standalone \
entries -- set it true when the story has real visual/narrative novelty: absurd, grisly, \
bizarre, or something that came out of nowhere. Most routine news (a transfer, a signing, a \
trailer drop, an index change) should be false. Err toward false -- this should flag a \
minority of standalone entries, not most of them. For cluster entries this field is ignored, \
set it true.
7. An article that's a purely domestic Indian story -- an Indian state/local politician, a \
regional Bollywood or regional-language release, a local Indian court case or crime story, a \
state-level Indian event -- with no significance outside India does NOT get an entry. Instead, \
list its title in excluded_india_local. Only exclude when the story is genuinely local: an \
Indian story with major international coverage, a globally recognized figure, or cross-border \
impact still gets a normal entry like anything else. When unsure, do NOT exclude it.

Rules:
- Every claim must be traceable to the reasons given below -- no speculation.
- Headline: roughly 4-9 words, punchy, present tense. Understandable to someone with zero \
context on the subject or the institutions involved -- see step 4.
- Summary: a single tight sentence for standalone articles, up to two sentences for a \
cluster synthesizing the shared story.
- These fields are JSON string values: never put a literal " character inside a headline \
or summary, even to quote someone -- use single quotes ('like this') for any quoted phrase \
instead.

Respond with ONLY valid JSON and nothing else -- no explanation before or after, no \
corrections, no markdown fences:
{{"rows": [{{"titles": ["..."], "headline": "...", "summary": "...", "subject_title": "...", "image_worthy": true}}], "excluded_india_local": ["..."]}}"""
