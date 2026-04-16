# Daily Brief Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated daily tech news briefing agent that crawls sources, summarizes with a free LLM, generates an MP3, commits Markdown to GitHub, and serves a GitHub Pages web archive with audio playback.

**Architecture:** A single Python script (`generate_brief.py`) runs in GitHub Actions on a daily cron. It crawls HN, Reddit, GitHub Trending, and RSS feeds; deduplicates and ranks stories; summarizes via Groq API; generates audio via Kokoro TTS; commits the brief Markdown; uploads the MP3 as a GitHub Release asset; and regenerates a static `docs/index.html` for GitHub Pages.

**Tech Stack:** Python 3.11+, uv, feedparser, beautifulsoup4, requests, groq, kokoro, soundfile, pydub, markdown, GitHub Actions, GitHub Pages, GitHub Releases API

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | uv-managed dependencies and project metadata |
| `generate_brief.py` | Main orchestration script — crawl, rank, summarize, TTS, write MD, generate HTML |
| `briefs/.issue_count` | Persisted integer counter, one line, incremented each run |
| `briefs/MM-DD-YYYY/daily-brief.md` | Generated brief for that day |
| `docs/index.html` | Generated GitHub Pages web archive, rebuilt every run |
| `.github/workflows/daily-brief.yml` | GitHub Actions cron workflow |
| `tests/test_crawler.py` | Unit tests for crawl/rank/deduplicate logic |
| `tests/test_formatter.py` | Unit tests for Markdown formatting and word count |
| `tests/test_html_generator.py` | Unit tests for HTML generation |

---

## Task 1: Project scaffold + dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `briefs/.issue_count`
- Create: `briefs/.gitkeep`
- Create: `docs/.gitkeep`
- Create: `.gitignore`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "daily-brief"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "feedparser>=6.0",
    "beautifulsoup4>=4.12",
    "requests>=2.31",
    "groq>=0.9",
    "kokoro>=0.9",
    "soundfile>=0.12",
    "pydub>=0.25",
    "markdown>=3.5",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create `briefs/.issue_count` with initial value**

```
0
```

- [ ] **Step 3: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
uv.lock
*.wav
*.mp3
.env
```

- [ ] **Step 4: Create placeholder dirs**

```bash
mkdir -p briefs docs tests
touch docs/.gitkeep
```

- [ ] **Step 5: Install dependencies with uv**

```bash
uv sync --extra dev
```

Expected: `.venv/` created, all packages installed without errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml briefs/.issue_count .gitignore docs/.gitkeep
git commit -m "chore: project scaffold and dependencies"
```

---

## Task 2: Crawler module (HN + Reddit + GitHub Trending + RSS)

**Files:**
- Create: `generate_brief.py` (crawl functions only for now)
- Create: `tests/test_crawler.py`

A `Story` is a plain dataclass used throughout the pipeline:

```python
@dataclass
class Story:
    title: str
    url: str
    source: str          # "hn", "reddit", "github", "rss"
    score: float         # normalized 0–1 for ranking
    published_at: datetime
    text: str            # raw snippet/body for summarization input
    section: str = ""    # filled later by summarizer: "ai", "dev", "tech", "hits"
    summary: str = ""    # filled later by summarizer
```

- [ ] **Step 1: Write failing tests for `fetch_hn()`**

Create `tests/test_crawler.py`:

```python
from unittest.mock import patch, MagicMock
from generate_brief import fetch_hn, Story
from datetime import datetime, timezone

def _mock_hn_response():
    return {
        "hits": [
            {
                "objectID": "123",
                "title": "New LLM beats GPT-5",
                "url": "https://example.com/llm",
                "points": 450,
                "num_comments": 120,
                "created_at": "2026-04-14T05:00:00.000Z",
                "story_text": None,
            },
            {
                "objectID": "124",
                "title": "Ask HN: Best Rust resources?",
                "url": None,
                "points": 200,
                "num_comments": 80,
                "created_at": "2026-04-14T04:00:00.000Z",
                "story_text": "I want to learn Rust",
            },
        ]
    }

def test_fetch_hn_returns_stories():
    with patch("generate_brief.requests.get") as mock_get:
        mock_get.return_value.json.return_value = _mock_hn_response()
        mock_get.return_value.raise_for_status = MagicMock()
        stories = fetch_hn()
    assert len(stories) == 2
    assert stories[0].title == "New LLM beats GPT-5"
    assert stories[0].source == "hn"
    assert stories[0].url == "https://example.com/llm"
    assert isinstance(stories[0].score, float)

def test_fetch_hn_uses_item_url_for_ask_hn():
    with patch("generate_brief.requests.get") as mock_get:
        mock_get.return_value.json.return_value = _mock_hn_response()
        mock_get.return_value.raise_for_status = MagicMock()
        stories = fetch_hn()
    # Ask HN has no url — falls back to HN item URL
    assert stories[1].url == "https://news.ycombinator.com/item?id=124"

def test_fetch_hn_returns_empty_on_error():
    with patch("generate_brief.requests.get") as mock_get:
        mock_get.side_effect = Exception("network error")
        stories = fetch_hn()
    assert stories == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_crawler.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `generate_brief` doesn't exist yet.

- [ ] **Step 3: Implement `Story` dataclass and `fetch_hn()` in `generate_brief.py`**

```python
#!/usr/bin/env python3
"""Daily Brief Agent — generates a daily tech news briefing."""

import os
import re
import sys
import json
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import feedparser
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

CUTOFF_HOURS = 24  # only stories published within this window


@dataclass
class Story:
    title: str
    url: str
    source: str
    score: float
    published_at: datetime
    text: str
    section: str = ""
    summary: str = ""


def _within_cutoff(dt: datetime) -> bool:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=CUTOFF_HOURS)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= cutoff


def fetch_hn() -> list[Story]:
    """Fetch top HN stories from the last 24 hours via Algolia API."""
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"tags": "story", "hitsPerPage": 30, "numericFilters": "points>50"},
            timeout=10,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        stories = []
        for h in hits:
            pub = datetime.fromisoformat(h["created_at"].replace("Z", "+00:00"))
            if not _within_cutoff(pub):
                continue
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
            score = min((h.get("points", 0) + h.get("num_comments", 0) * 2) / 1000, 1.0)
            stories.append(Story(
                title=h["title"],
                url=url,
                source="hn",
                score=score,
                published_at=pub,
                text=h.get("story_text") or h["title"],
            ))
        return stories
    except Exception as e:
        log.warning(f"HN fetch failed: {e}")
        return []
```

- [ ] **Step 4: Run HN tests to verify they pass**

```bash
uv run pytest tests/test_crawler.py::test_fetch_hn_returns_stories tests/test_crawler.py::test_fetch_hn_uses_item_url_for_ask_hn tests/test_crawler.py::test_fetch_hn_returns_empty_on_error -v
```

Expected: 3 PASSED

- [ ] **Step 5: Write failing tests for `fetch_reddit()`**

Add to `tests/test_crawler.py`:

```python
from generate_brief import fetch_reddit

def _mock_reddit_response():
    now_utc = datetime.now(timezone.utc).timestamp()
    return {
        "data": {
            "children": [
                {"data": {
                    "title": "Llama 4 released",
                    "url": "https://reddit.com/r/MachineLearning/123",
                    "permalink": "/r/MachineLearning/comments/123/llama_4",
                    "score": 1200,
                    "num_comments": 300,
                    "created_utc": now_utc - 3600,
                    "selftext": "Meta just dropped Llama 4",
                    "subreddit": "MachineLearning",
                }},
            ]
        }
    }

def test_fetch_reddit_returns_stories():
    with patch("generate_brief.requests.get") as mock_get:
        mock_get.return_value.json.return_value = _mock_reddit_response()
        mock_get.return_value.raise_for_status = MagicMock()
        stories = fetch_reddit()
    assert len(stories) >= 1
    assert stories[0].source == "reddit"
    assert stories[0].title == "Llama 4 released"

def test_fetch_reddit_returns_empty_on_error():
    with patch("generate_brief.requests.get") as mock_get:
        mock_get.side_effect = Exception("rate limited")
        stories = fetch_reddit()
    assert stories == []
```

- [ ] **Step 6: Implement `fetch_reddit()`**

Add to `generate_brief.py` after `fetch_hn()`:

```python
REDDIT_SUBS = [
    "MachineLearning", "LocalLLaMA", "artificial",
    "programming", "Python", "golang", "rust",
]

def fetch_reddit() -> list[Story]:
    """Fetch top posts from tech subreddits (unauthenticated JSON API)."""
    stories = []
    headers = {"User-Agent": "daily-brief-bot/1.0"}
    for sub in REDDIT_SUBS:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/top.json",
                params={"limit": 10, "t": "day"},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
            for child in children:
                d = child["data"]
                pub = datetime.fromtimestamp(d["created_utc"], tz=timezone.utc)
                if not _within_cutoff(pub):
                    continue
                score = min((d.get("score", 0) + d.get("num_comments", 0) * 2) / 5000, 1.0)
                text = d.get("selftext") or d["title"]
                stories.append(Story(
                    title=d["title"],
                    url=f"https://reddit.com{d['permalink']}",
                    source="reddit",
                    score=score,
                    published_at=pub,
                    text=text[:500],
                ))
            time.sleep(0.5)  # be polite to Reddit
        except Exception as e:
            log.warning(f"Reddit r/{sub} fetch failed: {e}")
    return stories
```

- [ ] **Step 7: Run Reddit tests**

```bash
uv run pytest tests/test_crawler.py::test_fetch_reddit_returns_stories tests/test_crawler.py::test_fetch_reddit_returns_empty_on_error -v
```

Expected: 2 PASSED

- [ ] **Step 8: Write failing test for `fetch_github_trending()`**

Add to `tests/test_crawler.py`:

```python
from generate_brief import fetch_github_trending

GITHUB_TRENDING_HTML = """
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/astral-sh/uv">astral-sh / uv</a>
  </h2>
  <p class="col-9 color-fg-muted my-1 pr-4">An extremely fast Python package installer</p>
  <span class="d-inline-block float-sm-right">
    <span>★ 1,234 stars today</span>
  </span>
</article>
"""

def test_fetch_github_trending_returns_stories():
    with patch("generate_brief.requests.get") as mock_get:
        mock_get.return_value.text = GITHUB_TRENDING_HTML
        mock_get.return_value.raise_for_status = MagicMock()
        stories = fetch_github_trending()
    assert len(stories) == 1
    assert "uv" in stories[0].title
    assert stories[0].source == "github"
    assert stories[0].url == "https://github.com/astral-sh/uv"

def test_fetch_github_trending_returns_empty_on_error():
    with patch("generate_brief.requests.get") as mock_get:
        mock_get.side_effect = Exception("timeout")
        stories = fetch_github_trending()
    assert stories == []
```

- [ ] **Step 9: Implement `fetch_github_trending()`**

Add to `generate_brief.py`:

```python
def fetch_github_trending() -> list[Story]:
    """Scrape GitHub Trending page for today's trending repos."""
    try:
        resp = requests.get(
            "https://github.com/trending",
            headers={"User-Agent": "daily-brief-bot/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        stories = []
        for article in soup.select("article.Box-row"):
            a = article.select_one("h2 a")
            if not a:
                continue
            path = a["href"].strip("/")
            title = path.replace("/", " / ")
            desc_el = article.select_one("p")
            desc = desc_el.get_text(strip=True) if desc_el else title
            stories.append(Story(
                title=f"{title} — {desc}" if desc != title else title,
                url=f"https://github.com/{path}",
                source="github",
                score=0.5,
                published_at=datetime.now(timezone.utc),
                text=desc,
            ))
        return stories
    except Exception as e:
        log.warning(f"GitHub Trending fetch failed: {e}")
        return []
```

- [ ] **Step 10: Write failing test for `fetch_rss()`**

Add to `tests/test_crawler.py`:

```python
from generate_brief import fetch_rss
import time as time_mod

def _mock_feed():
    entry = MagicMock()
    entry.title = "AI takes over the world"
    entry.link = "https://techcrunch.com/ai-takeover"
    entry.summary = "In a shocking turn of events..."
    entry.published_parsed = time_mod.gmtime()  # now
    return MagicMock(entries=[entry])

def test_fetch_rss_returns_stories():
    with patch("generate_brief.feedparser.parse") as mock_parse:
        mock_parse.return_value = _mock_feed()
        stories = fetch_rss()
    assert any(s.title == "AI takes over the world" for s in stories)
    assert all(s.source == "rss" for s in stories)

def test_fetch_rss_returns_empty_on_error():
    with patch("generate_brief.feedparser.parse") as mock_parse:
        mock_parse.side_effect = Exception("connection refused")
        stories = fetch_rss()
    assert stories == []
```

- [ ] **Step 11: Implement `fetch_rss()`**

Add to `generate_brief.py`:

```python
RSS_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://www.theregister.com/software/ai_ml/headlines.atom",
    "https://www.infoq.com/feed/",
]

def fetch_rss() -> list[Story]:
    """Fetch stories from RSS feeds."""
    stories = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                try:
                    pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    pub = datetime.now(timezone.utc)
                if not _within_cutoff(pub):
                    continue
                stories.append(Story(
                    title=entry.title,
                    url=entry.link,
                    source="rss",
                    score=0.4,
                    published_at=pub,
                    text=BeautifulSoup(entry.summary, "html.parser").get_text()[:500],
                ))
        except Exception as e:
            log.warning(f"RSS feed {url} failed: {e}")
    return stories
```

- [ ] **Step 12: Run all crawler tests**

```bash
uv run pytest tests/test_crawler.py -v
```

Expected: All tests PASSED

- [ ] **Step 13: Commit**

```bash
git add generate_brief.py tests/test_crawler.py
git commit -m "feat: crawler — HN, Reddit, GitHub Trending, RSS"
```

---

## Task 3: Deduplication and ranking

**Files:**
- Modify: `generate_brief.py` (add `deduplicate()` and `rank_and_select()`)
- Modify: `tests/test_crawler.py` (add dedup/rank tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_crawler.py`:

```python
from generate_brief import deduplicate, rank_and_select

def _make_story(title, url, score=0.5, source="hn"):
    return Story(
        title=title, url=url, source=source, score=score,
        published_at=datetime.now(timezone.utc), text=title,
    )

def test_deduplicate_removes_exact_url_duplicates():
    stories = [
        _make_story("Rust 2.0 released", "https://blog.rust-lang.org/2.0"),
        _make_story("Rust 2.0 released", "https://blog.rust-lang.org/2.0"),
    ]
    result = deduplicate(stories)
    assert len(result) == 1

def test_deduplicate_removes_similar_titles():
    stories = [
        _make_story("OpenAI releases GPT-5", "https://openai.com/gpt5"),
        _make_story("OpenAI Releases GPT-5 Model", "https://techcrunch.com/gpt5"),
    ]
    result = deduplicate(stories)
    assert len(result) == 1

def test_deduplicate_keeps_distinct_stories():
    stories = [
        _make_story("Rust 2.0 released", "https://rust-lang.org"),
        _make_story("Python 4.0 released", "https://python.org"),
    ]
    result = deduplicate(stories)
    assert len(result) == 2

def test_rank_and_select_returns_top_n():
    stories = [_make_story(f"Story {i}", f"https://ex.com/{i}", score=i/10) for i in range(20)]
    result = rank_and_select(stories, n=10)
    assert len(result) == 10
    # highest scores first
    assert result[0].score >= result[-1].score
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_crawler.py::test_deduplicate_removes_exact_url_duplicates -v
```

Expected: FAIL — `ImportError: cannot import name 'deduplicate'`

- [ ] **Step 3: Implement `deduplicate()` and `rank_and_select()`**

Add to `generate_brief.py`:

```python
def _title_key(title: str) -> str:
    """Normalize title for fuzzy dedup: lowercase, strip punctuation, sort words."""
    words = re.sub(r"[^a-z0-9 ]", "", title.lower()).split()
    return " ".join(sorted(words))


def deduplicate(stories: list[Story]) -> list[Story]:
    """Remove duplicate stories by URL and near-duplicate titles."""
    seen_urls: set[str] = set()
    seen_title_keys: set[str] = set()
    result = []
    for s in stories:
        if s.url in seen_urls:
            continue
        tkey = _title_key(s.title)
        if tkey in seen_title_keys:
            continue
        seen_urls.add(s.url)
        seen_title_keys.add(tkey)
        result.append(s)
    return result


def rank_and_select(stories: list[Story], n: int = 12) -> list[Story]:
    """Sort by score descending and return top n."""
    return sorted(stories, key=lambda s: s.score, reverse=True)[:n]
```

- [ ] **Step 4: Run dedup/rank tests**

```bash
uv run pytest tests/test_crawler.py -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add generate_brief.py tests/test_crawler.py
git commit -m "feat: deduplication and ranking"
```

---

## Task 4: Summarization via Groq API

**Files:**
- Modify: `generate_brief.py` (add `summarize_and_categorize()`)
- Create: `tests/test_summarizer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_summarizer.py`:

```python
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from generate_brief import summarize_and_categorize, Story

def _make_story(title, text="Some content about the topic."):
    return Story(
        title=title, url="https://example.com", source="hn",
        score=0.8, published_at=datetime.now(timezone.utc), text=text,
    )

def _mock_groq_response(summary: str, section: str):
    msg = MagicMock()
    msg.content = f'{{"summary": "{summary}", "section": "{section}"}}'
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp

def test_summarize_sets_summary_and_section():
    stories = [_make_story("New LLM model beats all benchmarks")]
    with patch("generate_brief.Groq") as MockGroq:
        client = MockGroq.return_value
        client.chat.completions.create.return_value = _mock_groq_response(
            "A new LLM model has beaten all benchmarks.", "ai"
        )
        result = summarize_and_categorize(stories, api_key="fake-key")
    assert result[0].summary == "A new LLM model has beaten all benchmarks."
    assert result[0].section == "ai"

def test_summarize_falls_back_on_json_parse_error():
    stories = [_make_story("Rust 2.0 released")]
    with patch("generate_brief.Groq") as MockGroq:
        client = MockGroq.return_value
        client.chat.completions.create.return_value = _mock_groq_response("not json {{", "")
        result = summarize_and_categorize(stories, api_key="fake-key")
    # fallback: summary is the story text, section defaults to "tech"
    assert result[0].summary != ""
    assert result[0].section in ("ai", "dev", "tech", "hits")

def test_summarize_falls_back_on_api_error():
    stories = [_make_story("Python 4.0 ships")]
    with patch("generate_brief.Groq") as MockGroq:
        client = MockGroq.return_value
        client.chat.completions.create.side_effect = Exception("rate limited")
        result = summarize_and_categorize(stories, api_key="fake-key")
    assert result[0].summary == stories[0].text[:300]
    assert result[0].section in ("ai", "dev", "tech", "hits")
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_summarizer.py -v
```

Expected: FAIL — `ImportError: cannot import name 'summarize_and_categorize'`

- [ ] **Step 3: Implement `summarize_and_categorize()`**

Add to `generate_brief.py`:

```python
from groq import Groq

SECTION_KEYWORDS = {
    "ai": ["llm", "gpt", "claude", "gemini", "ai", "model", "agent", "ml", "neural", "openai", "anthropic", "mistral", "llama"],
    "dev": ["python", "rust", "golang", "java", "typescript", "javascript", "framework", "library", "github", "open source", "release", "uv", "npm", "cargo"],
    "tech": ["security", "cloud", "kubernetes", "aws", "startup", "funding", "hardware", "chip", "quantum", "browser", "linux"],
}

def _guess_section(title: str, text: str) -> str:
    combined = (title + " " + text).lower()
    scores = {s: sum(combined.count(kw) for kw in kws) for s, kws in SECTION_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "hits"


SUMMARIZE_PROMPT = """\
You are a tech news editor writing a concise daily brief.

Given the story title and snippet below, write a JSON response with:
- "summary": 3-5 sentence summary in plain English. Include key facts, numbers, and why it matters.
- "section": one of "ai", "dev", "tech", or "hits"
  - "ai" = AI, LLMs, models, agents, ML
  - "dev" = programming languages, tools, frameworks, open source
  - "tech" = general software/internet/hardware/security/startups
  - "hits" = anything else interesting

Respond ONLY with valid JSON, no markdown fences.

Title: {title}
Snippet: {text}
"""

def summarize_and_categorize(stories: list[Story], api_key: str) -> list[Story]:
    """Call Groq API to summarize each story and assign a section."""
    client = Groq(api_key=api_key)
    for story in stories:
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": SUMMARIZE_PROMPT.format(
                    title=story.title, text=story.text[:800]
                )}],
                temperature=0.3,
                max_tokens=300,
            )
            raw = resp.choices[0].message.content.strip()
            data = json.loads(raw)
            story.summary = data.get("summary", story.text[:300])
            story.section = data.get("section", _guess_section(story.title, story.text))
        except json.JSONDecodeError:
            log.warning(f"JSON parse error for story: {story.title}")
            story.summary = story.text[:300]
            story.section = _guess_section(story.title, story.text)
        except Exception as e:
            log.warning(f"Groq API error for '{story.title}': {e}")
            story.summary = story.text[:300]
            story.section = _guess_section(story.title, story.text)
    return stories
```

- [ ] **Step 4: Run summarizer tests**

```bash
uv run pytest tests/test_summarizer.py -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add generate_brief.py tests/test_summarizer.py
git commit -m "feat: summarization and section categorization via Groq"
```

---

## Task 5: Markdown formatter

**Files:**
- Modify: `generate_brief.py` (add `format_markdown()` and `get_next_issue_number()`)
- Create: `tests/test_formatter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_formatter.py`:

```python
from datetime import datetime, timezone
from pathlib import Path
import tempfile, os
from generate_brief import format_markdown, get_next_issue_number, Story

def _make_story(title, summary, section, url="https://example.com"):
    return Story(
        title=title, url=url, source="hn", score=0.9,
        published_at=datetime.now(timezone.utc),
        text="text", section=section, summary=summary,
    )

def test_format_markdown_contains_all_sections():
    stories = [
        _make_story("GPT-6 released", "OpenAI dropped GPT-6 today.", "ai"),
        _make_story("Rust 2.0 ships", "Rust 2.0 is out with major changes.", "dev"),
        _make_story("AWS outage", "AWS had a major outage.", "tech"),
        _make_story("Cool new font", "Someone made a cool font.", "hits"),
    ]
    date = datetime(2026, 4, 14, tzinfo=timezone.utc)
    md = format_markdown(stories, date=date, issue_number=42)
    assert "## 01 AI / LLM / Agents" in md
    assert "## 02 Dev Tooling & Languages" in md
    assert "## 03 Software & Internet Tech" in md
    assert "## 04 Quick Hits" in md
    assert "GPT-6 released" in md
    assert "Issue #042" in md
    assert "April 14, 2026" in md

def test_format_markdown_story_has_source_link():
    stories = [_make_story("GPT-6", "Summary.", "ai", url="https://openai.com")]
    md = format_markdown(stories, date=datetime.now(timezone.utc), issue_number=1)
    assert "https://openai.com" in md

def test_get_next_issue_number_increments():
    with tempfile.TemporaryDirectory() as tmpdir:
        count_file = Path(tmpdir) / ".issue_count"
        count_file.write_text("5\n")
        n = get_next_issue_number(count_file)
        assert n == 6
        assert count_file.read_text().strip() == "6"

def test_get_next_issue_number_starts_at_1_if_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        count_file = Path(tmpdir) / ".issue_count"
        n = get_next_issue_number(count_file)
        assert n == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_formatter.py -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `get_next_issue_number()` and `format_markdown()`**

Add to `generate_brief.py`:

```python
SECTION_LABELS = {
    "ai":   ("01", "AI / LLM / Agents"),
    "dev":  ("02", "Dev Tooling & Languages"),
    "tech": ("03", "Software & Internet Tech"),
    "hits": ("04", "Quick Hits"),
}

def get_next_issue_number(count_file: Path) -> int:
    """Read, increment, and persist the issue counter."""
    n = int(count_file.read_text().strip()) + 1 if count_file.exists() else 1
    count_file.write_text(f"{n}\n")
    return n


def _estimate_read_time(text: str) -> int:
    """Estimate reading time in minutes (avg 200 wpm)."""
    return max(1, len(text.split()) // 200)


def format_markdown(stories: list[Story], date: datetime, issue_number: int) -> str:
    date_str = date.strftime("%B %-d, %Y")
    lines = [
        f"# Daily Brief — {date_str}  //  Issue #{issue_number:03d}",
        "",
        f"> Automated daily tech briefing covering AI, dev tooling, and software news.",
        "",
    ]
    for section_key in ("ai", "dev", "tech", "hits"):
        num, label = SECTION_LABELS[section_key]
        section_stories = [s for s in stories if s.section == section_key]
        if not section_stories:
            continue
        lines.append(f"## {num} {label}")
        lines.append("")
        for s in section_stories:
            lines.append(f"### {s.title}")
            lines.append("")
            lines.append(s.summary)
            lines.append("")
            lines.append(f"*Source: [{s.source.upper()}]({s.url})*")
            lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run formatter tests**

```bash
uv run pytest tests/test_formatter.py -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add generate_brief.py tests/test_formatter.py
git commit -m "feat: Markdown formatter and issue counter"
```

---

## Task 6: HTML web archive generator

**Files:**
- Modify: `generate_brief.py` (add `generate_index_html()`)
- Create: `tests/test_html_generator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_html_generator.py`:

```python
from datetime import datetime, timezone
from generate_brief import generate_index_html, BriefMeta

def _make_meta(date_str="2026-04-14", issue=42, word_count=700, mp3_url="https://github.com/releases/mp3"):
    return BriefMeta(
        date=datetime(2026, 4, 14, tzinfo=timezone.utc),
        date_str=date_str,
        issue_number=issue,
        word_count=word_count,
        mp3_url=mp3_url,
        md_url="https://github.com/blob/main/briefs/04-14-2026/daily-brief.md",
        html_content="<p>Story content here</p>",
    )

def test_generate_index_html_contains_meta():
    meta = _make_meta()
    html = generate_index_html([meta])
    assert "April 14, 2026" in html
    assert "#042" in html
    assert "~3 min" in html  # 700 words / 200 wpm = 3.5 → 3
    assert "▶ Play" in html
    assert "📄 Read" in html

def test_generate_index_html_no_play_button_when_no_mp3():
    meta = _make_meta(mp3_url="")
    html = generate_index_html([meta])
    assert "▶ Play" not in html

def test_generate_index_html_has_theme_toggle():
    html = generate_index_html([_make_meta()])
    assert "theme-toggle" in html
    assert "prefers-color-scheme" in html

def test_generate_index_html_newest_first():
    m1 = _make_meta(date_str="2026-04-13", issue=41)
    m2 = _make_meta(date_str="2026-04-14", issue=42)
    html = generate_index_html([m1, m2])
    assert html.index("#042") < html.index("#041")
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_html_generator.py -v
```

Expected: FAIL — `ImportError: cannot import name 'generate_index_html'`

- [ ] **Step 3: Implement `BriefMeta` dataclass and `generate_index_html()`**

Add to `generate_brief.py`:

```python
import markdown as md_lib

@dataclass
class BriefMeta:
    date: datetime
    date_str: str          # "2026-04-14"
    issue_number: int
    word_count: int
    mp3_url: str           # empty string if TTS failed
    md_url: str            # link to raw .md on GitHub
    html_content: str      # rendered HTML of the brief


def generate_index_html(briefs: list[BriefMeta]) -> str:
    """Generate the full GitHub Pages index.html from all briefs, newest first."""
    briefs_sorted = sorted(briefs, key=lambda b: b.date, reverse=True)

    rows = []
    for i, b in enumerate(briefs_sorted):
        date_display = b.date.strftime("%B %-d, %Y")
        read_min = max(1, b.word_count // 200)
        play_btn = (
            f'<button class="btn btn-play" onclick="toggleAudio(this, \'{b.mp3_url}\')" aria-label="Play audio">▶ Play</button>'
            if b.mp3_url else ""
        )
        expanded = "expanded" if i == 0 else ""
        rows.append(f"""
        <tr class="brief-row {expanded}" data-index="{i}">
          <td class="col-date">{date_display}</td>
          <td class="col-issue">#{b.issue_number:03d}</td>
          <td class="col-tags">
            <span class="tag tag-ai">AI</span>
            <span class="tag tag-dev">Dev</span>
            <span class="tag tag-tech">Tech</span>
          </td>
          <td class="col-time">~{read_min} min read</td>
          <td class="col-actions">
            <a class="btn btn-read" href="{b.md_url}" target="_blank">📄 Read</a>
            {play_btn}
          </td>
        </tr>
        <tr class="brief-content {expanded}" id="content-{i}">
          <td colspan="5">
            <div class="audio-player" id="audio-{i}"></div>
            <div class="brief-body">{b.html_content}</div>
          </td>
        </tr>""")

    rows_html = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Brief</title>
  <style>
    :root {{
      --bg: #ffffff;
      --bg2: #f6f8fa;
      --border: #d0d7de;
      --text: #1f2328;
      --text-muted: #636c76;
      --accent: #0969da;
      --tag-ai-bg: #ddf4ff;
      --tag-ai-text: #0550ae;
      --tag-dev-bg: #d1f0db;
      --tag-dev-text: #1a7f37;
      --tag-tech-bg: #fff0b3;
      --tag-tech-text: #7d4e00;
      --btn-play-bg: #0969da;
      --btn-play-text: #ffffff;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #0d1117;
        --bg2: #161b22;
        --border: #30363d;
        --text: #e6edf3;
        --text-muted: #7d8590;
        --accent: #58a6ff;
        --tag-ai-bg: #0c2d6b;
        --tag-ai-text: #79c0ff;
        --tag-dev-bg: #0c3322;
        --tag-dev-text: #56d364;
        --tag-tech-bg: #3d2b00;
        --tag-tech-text: #e3b341;
        --btn-play-bg: #1f6feb;
        --btn-play-text: #ffffff;
      }}
    }}
    [data-theme="light"] {{
      --bg: #ffffff; --bg2: #f6f8fa; --border: #d0d7de; --text: #1f2328;
      --text-muted: #636c76; --accent: #0969da;
      --tag-ai-bg: #ddf4ff; --tag-ai-text: #0550ae;
      --tag-dev-bg: #d1f0db; --tag-dev-text: #1a7f37;
      --tag-tech-bg: #fff0b3; --tag-tech-text: #7d4e00;
      --btn-play-bg: #0969da; --btn-play-text: #ffffff;
    }}
    [data-theme="dark"] {{
      --bg: #0d1117; --bg2: #161b22; --border: #30363d; --text: #e6edf3;
      --text-muted: #7d8590; --accent: #58a6ff;
      --tag-ai-bg: #0c2d6b; --tag-ai-text: #79c0ff;
      --tag-dev-bg: #0c3322; --tag-dev-text: #56d364;
      --tag-tech-bg: #3d2b00; --tag-tech-text: #e3b341;
      --btn-play-bg: #1f6feb; --btn-play-text: #ffffff;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 15px; line-height: 1.6; }}
    header {{ background: var(--bg2); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 10; }}
    header h1 {{ font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }}
    header .subtitle {{ font-size: 12px; color: var(--text-muted); font-family: "SFMono-Regular", Consolas, monospace; }}
    .theme-toggle {{ background: none; border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; cursor: pointer; font-size: 16px; color: var(--text); }}
    main {{ max-width: 960px; margin: 0 auto; padding: 24px 16px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; font-size: 12px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; padding: 8px 12px; border-bottom: 1px solid var(--border); }}
    td {{ padding: 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
    .brief-row:hover td {{ background: var(--bg2); cursor: pointer; }}
    .brief-row.expanded td {{ background: var(--bg2); }}
    .col-date {{ font-weight: 600; white-space: nowrap; }}
    .col-issue {{ font-family: monospace; color: var(--text-muted); white-space: nowrap; }}
    .col-time {{ color: var(--text-muted); font-size: 13px; white-space: nowrap; }}
    .col-actions {{ white-space: nowrap; }}
    .tag {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-right: 4px; }}
    .tag-ai {{ background: var(--tag-ai-bg); color: var(--tag-ai-text); }}
    .tag-dev {{ background: var(--tag-dev-bg); color: var(--tag-dev-text); }}
    .tag-tech {{ background: var(--tag-tech-bg); color: var(--tag-tech-text); }}
    .btn {{ display: inline-block; padding: 5px 12px; border-radius: 6px; font-size: 13px; font-weight: 500; text-decoration: none; border: 1px solid var(--border); cursor: pointer; margin-right: 6px; color: var(--text); background: var(--bg); }}
    .btn:hover {{ background: var(--bg2); }}
    .btn-play {{ background: var(--btn-play-bg); color: var(--btn-play-text); border-color: transparent; }}
    .btn-play:hover {{ opacity: 0.88; }}
    .brief-content {{ display: none; }}
    .brief-content.expanded {{ display: table-row; }}
    .brief-body {{ padding: 16px; max-width: 720px; }}
    .brief-body h1 {{ font-size: 20px; margin-bottom: 16px; }}
    .brief-body h2 {{ font-size: 16px; margin: 20px 0 8px; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 4px; }}
    .brief-body h3 {{ font-size: 14px; margin: 12px 0 4px; }}
    .brief-body p {{ margin-bottom: 10px; color: var(--text); }}
    .brief-body a {{ color: var(--accent); }}
    .brief-body em {{ color: var(--text-muted); font-size: 12px; }}
    .audio-player {{ padding: 12px 16px 0; }}
    .audio-player audio {{ width: 100%; max-width: 480px; }}
    footer {{ text-align: center; padding: 32px 16px; color: var(--text-muted); font-size: 13px; border-top: 1px solid var(--border); margin-top: 32px; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Daily Brief</h1>
      <div class="subtitle">$ ./daily_brief.sh — automated · curated · daily</div>
    </div>
    <button class="theme-toggle" id="theme-toggle" onclick="toggleTheme()" aria-label="Toggle theme">🌙</button>
  </header>
  <main>
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Issue</th>
          <th>Topics</th>
          <th>Length</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </main>
  <footer>
    Automated daily tech briefing · AI · Dev · Security · Open Source
  </footer>
  <script>
    // Theme toggle
    (function() {{
      const saved = localStorage.getItem('theme');
      if (saved) document.documentElement.setAttribute('data-theme', saved);
      updateToggleIcon();
    }})();

    function toggleTheme() {{
      const current = document.documentElement.getAttribute('data-theme');
      const isDark = current === 'dark' || (!current && window.matchMedia('(prefers-color-scheme: dark)').matches);
      const next = isDark ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      updateToggleIcon();
    }}

    function updateToggleIcon() {{
      const current = document.documentElement.getAttribute('data-theme');
      const isDark = current === 'dark' || (!current && window.matchMedia('(prefers-color-scheme: dark)').matches);
      document.getElementById('theme-toggle').textContent = isDark ? '☀️' : '🌙';
    }}

    // Row expand/collapse
    document.querySelectorAll('.brief-row').forEach(function(row) {{
      row.addEventListener('click', function(e) {{
        if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON') return;
        const idx = this.dataset.index;
        const content = document.getElementById('content-' + idx);
        const isExpanded = content.classList.contains('expanded');
        // collapse all
        document.querySelectorAll('.brief-content').forEach(function(c) {{ c.classList.remove('expanded'); }});
        document.querySelectorAll('.brief-row').forEach(function(r) {{ r.classList.remove('expanded'); }});
        if (!isExpanded) {{
          content.classList.add('expanded');
          this.classList.add('expanded');
        }}
      }});
    }});

    // Audio player — one at a time
    let currentAudio = null;
    function toggleAudio(btn, url) {{
      // pause any playing
      if (currentAudio && !currentAudio.paused) {{
        currentAudio.pause();
        if (currentAudio.dataset.url === url) {{
          currentAudio = null;
          btn.textContent = '▶ Play';
          return;
        }}
      }}
      const row = btn.closest('tr');
      const idx = row.dataset.index;
      const container = document.getElementById('content-' + idx);
      const audioDiv = document.getElementById('audio-' + idx);
      // expand row if not already
      if (!container.classList.contains('expanded')) {{
        document.querySelectorAll('.brief-content').forEach(function(c) {{ c.classList.remove('expanded'); }});
        document.querySelectorAll('.brief-row').forEach(function(r) {{ r.classList.remove('expanded'); }});
        container.classList.add('expanded');
        row.classList.add('expanded');
      }}
      let audio = audioDiv.querySelector('audio');
      if (!audio) {{
        audio = document.createElement('audio');
        audio.controls = true;
        audio.src = url;
        audio.dataset.url = url;
        audioDiv.appendChild(audio);
      }}
      audio.play();
      currentAudio = audio;
      btn.textContent = '⏸ Pause';
      audio.onended = function() {{ btn.textContent = '▶ Play'; }};
    }}
  </script>
</body>
</html>"""
```

- [ ] **Step 4: Run HTML generator tests**

```bash
uv run pytest tests/test_html_generator.py -v
```

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add generate_brief.py tests/test_html_generator.py
git commit -m "feat: GitHub Pages HTML archive generator"
```

---

## Task 7: TTS audio generation

**Files:**
- Modify: `generate_brief.py` (add `generate_mp3()`)

No unit tests for TTS — it requires the Kokoro model weights and audio hardware. It's tested via integration in the Actions workflow.

- [ ] **Step 1: Implement `generate_mp3()`**

Add to `generate_brief.py`:

```python
def _strip_markdown(text: str) -> str:
    """Strip Markdown syntax for clean TTS input."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)           # bold/italic
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)              # links
    text = re.sub(r"`{1,3}.+?`{1,3}", "", text)                   # code
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)         # blockquotes
    text = re.sub(r"\n{3,}", "\n\n", text)                        # extra newlines
    return text.strip()


def generate_mp3(markdown_text: str, output_path: Path) -> bool:
    """Generate MP3 from brief text using Kokoro TTS. Returns True on success."""
    try:
        import kokoro
        import soundfile as sf
        from pydub import AudioSegment

        plain_text = _strip_markdown(markdown_text)
        pipeline = kokoro.KPipeline(lang_code="a")  # American English

        wav_path = output_path.with_suffix(".wav")
        samples = []
        sample_rate = 24000

        for _, _, audio in pipeline(plain_text, voice="af_heart", speed=1.0):
            import numpy as np
            samples.append(audio)

        if not samples:
            log.warning("Kokoro produced no audio samples")
            return False

        import numpy as np
        combined = np.concatenate(samples)
        sf.write(str(wav_path), combined, sample_rate)

        AudioSegment.from_wav(str(wav_path)).export(str(output_path), format="mp3", bitrate="128k")
        wav_path.unlink(missing_ok=True)
        log.info(f"MP3 generated: {output_path}")
        return True
    except Exception as e:
        log.warning(f"TTS generation failed: {e}")
        return False
```

- [ ] **Step 2: Commit**

```bash
git add generate_brief.py
git commit -m "feat: Kokoro TTS MP3 generation"
```

---

## Task 8: GitHub Release upload

**Files:**
- Modify: `generate_brief.py` (add `create_github_release()`)

- [ ] **Step 1: Implement `create_github_release()`**

Add to `generate_brief.py`:

```python
def create_github_release(
    repo: str,       # "owner/repo-name"
    tag: str,        # "2026-04-14"
    title: str,      # "Daily Brief — April 14, 2026"
    mp3_path: Path,
    token: str,
) -> str:
    """Create a GitHub Release and upload the MP3. Returns the asset download URL."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Create the release
    release_resp = requests.post(
        f"https://api.github.com/repos/{repo}/releases",
        headers=headers,
        json={
            "tag_name": tag,
            "name": title,
            "body": f"Automated daily brief for {tag}.",
            "draft": False,
            "prerelease": False,
        },
        timeout=15,
    )
    release_resp.raise_for_status()
    upload_url = release_resp.json()["upload_url"].replace("{?name,label}", "")
    release_id = release_resp.json()["id"]

    # Upload the MP3
    with open(mp3_path, "rb") as f:
        upload_resp = requests.post(
            upload_url,
            headers={**headers, "Content-Type": "audio/mpeg"},
            params={"name": "daily-brief.mp3"},
            data=f,
            timeout=120,
        )
    upload_resp.raise_for_status()
    asset_url = upload_resp.json()["browser_download_url"]
    log.info(f"MP3 uploaded to GitHub Release: {asset_url}")
    return asset_url
```

- [ ] **Step 2: Commit**

```bash
git add generate_brief.py
git commit -m "feat: GitHub Release creation and MP3 upload"
```

---

## Task 9: Main orchestration + `collect_existing_briefs()`

**Files:**
- Modify: `generate_brief.py` (add `collect_existing_briefs()` and `main()`)

- [ ] **Step 1: Implement `collect_existing_briefs()`**

Add to `generate_brief.py`:

```python
def collect_existing_briefs(briefs_dir: Path, repo: str) -> list[BriefMeta]:
    """
    Walk briefs/*/daily-brief.md and reconstruct BriefMeta for each.
    MP3 URL is derived from GitHub Releases — we check if a matching release exists.
    """
    metas = []
    for md_path in sorted(briefs_dir.glob("*/daily-brief.md")):
        date_str = md_path.parent.name  # "04-14-2026"
        try:
            date = datetime.strptime(date_str, "%m-%d-%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        content = md_path.read_text()
        # extract issue number from first heading
        m = re.search(r"Issue #(\d+)", content)
        issue = int(m.group(1)) if m else 0
        word_count = len(content.split())
        tag = date.strftime("%Y-%m-%d")
        md_url = f"https://github.com/{repo}/blob/main/{md_path}"
        mp3_url = f"https://github.com/{repo}/releases/download/{tag}/daily-brief.mp3"
        html_content = md_lib.markdown(content)
        metas.append(BriefMeta(
            date=date,
            date_str=date_str,
            issue_number=issue,
            word_count=word_count,
            mp3_url=mp3_url,
            md_url=md_url,
            html_content=html_content,
        ))
    return metas
```

- [ ] **Step 2: Implement `main()`**

Add to `generate_brief.py`:

```python
def main():
    # ── Config from environment ──────────────────────────────────────────────
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    github_repo  = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo"

    today = datetime.now(timezone.utc)
    date_dir_name = today.strftime("%m-%d-%Y")     # "04-14-2026"
    tag = today.strftime("%Y-%m-%d")               # "2026-04-14"

    root = Path(__file__).parent
    briefs_dir = root / "briefs"
    out_dir = briefs_dir / date_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path  = out_dir / "daily-brief.md"
    mp3_path = out_dir / "daily-brief.mp3"
    count_file = briefs_dir / ".issue_count"
    docs_dir = root / "docs"
    docs_dir.mkdir(exist_ok=True)

    # ── 1. Crawl ─────────────────────────────────────────────────────────────
    log.info("Crawling sources...")
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(fetch_hn): "hn",
            ex.submit(fetch_reddit): "reddit",
            ex.submit(fetch_github_trending): "github",
            ex.submit(fetch_rss): "rss",
        }
        all_stories: list[Story] = []
        for future in as_completed(futures):
            result = future.result()
            log.info(f"  {futures[future]}: {len(result)} stories")
            all_stories.extend(result)

    # ── 2. Rank + deduplicate ─────────────────────────────────────────────────
    stories = rank_and_select(deduplicate(all_stories), n=12)
    log.info(f"Selected {len(stories)} stories after dedup+rank")

    # ── 3. Summarize ─────────────────────────────────────────────────────────
    if groq_api_key:
        log.info("Summarizing via Groq...")
        stories = summarize_and_categorize(stories, api_key=groq_api_key)
    else:
        log.warning("GROQ_API_KEY not set — skipping summarization")
        for s in stories:
            s.summary = s.text[:300]
            s.section = _guess_section(s.title, s.text)

    # ── 4. Format Markdown ───────────────────────────────────────────────────
    issue_number = get_next_issue_number(count_file)
    markdown_text = format_markdown(stories, date=today, issue_number=issue_number)
    md_path.write_text(markdown_text)
    log.info(f"Brief written: {md_path}")

    # ── 5. Generate MP3 ──────────────────────────────────────────────────────
    log.info("Generating MP3 via Kokoro TTS...")
    tts_ok = generate_mp3(markdown_text, mp3_path)

    # ── 6. Upload MP3 as GitHub Release ─────────────────────────────────────
    mp3_url = ""
    if tts_ok and github_token and github_repo:
        title = f"Daily Brief — {today.strftime('%B %-d, %Y')}"
        try:
            mp3_url = create_github_release(
                repo=github_repo, tag=tag, title=title,
                mp3_path=mp3_path, token=github_token,
            )
        except Exception as e:
            log.warning(f"GitHub Release upload failed: {e}")

    # ── 7. Regenerate index.html ─────────────────────────────────────────────
    log.info("Regenerating docs/index.html...")
    all_metas = collect_existing_briefs(briefs_dir, github_repo)
    index_html = generate_index_html(all_metas)
    (docs_dir / "index.html").write_text(index_html)
    log.info("docs/index.html updated")

    log.info("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: All PASSED

- [ ] **Step 4: Commit**

```bash
git add generate_brief.py
git commit -m "feat: main orchestration — crawl, summarize, write, TTS, release, deploy"
```

---

## Task 10: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/daily-brief.yml`

- [ ] **Step 1: Create workflow file**

```bash
mkdir -p .github/workflows
```

Create `.github/workflows/daily-brief.yml`:

```yaml
name: Daily Brief

on:
  schedule:
    - cron: '0 6 * * *'   # 6:00 AM UTC daily
  workflow_dispatch:        # manual trigger anytime

permissions:
  contents: write           # push commits
  id-token: write

jobs:
  generate:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          fetch-depth: 0

      - name: Install system dependencies
        run: sudo apt-get update && sudo apt-get install -y ffmpeg

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "latest"

      - name: Install Python dependencies
        run: uv sync

      - name: Cache Kokoro model weights
        uses: actions/cache@v4
        with:
          path: ~/.cache/huggingface
          key: kokoro-models-v1

      - name: Generate daily brief
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
        run: uv run python generate_brief.py

      - name: Commit and push brief + index.html
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add briefs/ docs/index.html
          git diff --cached --quiet || git commit -m "brief: $(date -u +%Y-%m-%d)"
          git push
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/daily-brief.yml
git commit -m "ci: GitHub Actions daily brief workflow"
```

---

## Task 11: README and GitHub Pages setup instructions

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create README**

```bash
cat > README.md << 'EOF'
# Daily Brief

Automated daily tech news briefing — AI, LLMs, dev tooling, software & internet tech.

## Setup

### 1. Fork / clone this repo and push to GitHub

### 2. Add repository secrets

In your repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Where to get it |
|--------|----------------|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free account |

`GITHUB_TOKEN` is provided automatically by Actions.

### 3. Enable GitHub Pages

Repo → Settings → Pages → Source: **Deploy from a branch** → Branch: `main` → Folder: `/docs` → Save.

Your archive will be live at `https://<your-username>.github.io/daily-brief/`

### 4. Trigger manually (first run)

Actions → Daily Brief → Run workflow

### 5. Automatic schedule

Runs automatically at **6:00 AM UTC** every day.

## Local development

```bash
uv sync --extra dev
GROQ_API_KEY=your_key uv run python generate_brief.py
uv run pytest tests/ -v
```
EOF
```

- [ ] **Step 2: Run full test suite one final time**

```bash
uv run pytest tests/ -v
```

Expected: All PASSED

- [ ] **Step 3: Final commit**

```bash
git add README.md
git commit -m "docs: README with setup instructions"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|-----------------|-----------|
| Crawl HN, Reddit, GitHub Trending, RSS | Task 2 |
| Rank + deduplicate | Task 3 |
| Summarize via Groq (Llama 3.3 70B) | Task 4 |
| Format `briefs/MM-DD-YYYY/daily-brief.md` | Task 5 |
| Issue counter (`briefs/.issue_count`) | Task 5 |
| Kokoro TTS → MP3 | Task 7 |
| GitHub Release asset upload | Task 8 |
| `docs/index.html` GitHub Pages archive | Task 6 |
| Light/dark theme + toggle | Task 6 (HTML generator) |
| Table: date, issue#, tags, read time, play/read buttons | Task 6 |
| Inline audio player, one at a time | Task 6 (JS) |
| Most recent brief expanded by default | Task 6 |
| GitHub Actions cron + manual trigger | Task 10 |
| uv dependency management | Task 1 |
| `pyproject.toml` | Task 1 |
| Error handling (skip failing sources, TTS fallback) | Tasks 2–7 |

**No gaps found.** All spec requirements are covered.
