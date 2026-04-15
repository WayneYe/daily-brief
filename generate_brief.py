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
from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

CUTOFF_HOURS = 24  # only stories published within this window


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


def _title_words(title: str) -> frozenset[str]:
    """Normalize title to a set of significant words for fuzzy dedup."""
    stopwords = {"a", "an", "the", "and", "or", "of", "to", "in", "is", "for", "with"}
    words = re.sub(r"[^a-z0-9 ]", "", title.lower()).split()
    return frozenset(w for w in words if w not in stopwords)


def _titles_are_similar(a: frozenset[str], b: frozenset[str]) -> bool:
    """Return True if titles share enough words to be considered duplicates."""
    if not a or not b:
        return False
    intersection = len(a & b)
    shorter = min(len(a), len(b))
    return intersection >= max(2, shorter * 0.7)


def deduplicate(stories: list[Story]) -> list[Story]:
    """Remove duplicate stories by URL and near-duplicate titles."""
    seen_urls: set[str] = set()
    seen_title_word_sets: list[frozenset[str]] = []
    result = []
    for s in stories:
        if s.url in seen_urls:
            continue
        twords = _title_words(s.title)
        if any(_titles_are_similar(twords, seen) for seen in seen_title_word_sets):
            continue
        seen_urls.add(s.url)
        seen_title_word_sets.append(twords)
        result.append(s)
    return result


def rank_and_select(stories: list[Story], n: int = 12) -> list[Story]:
    """Sort by score descending and return top n."""
    return sorted(stories, key=lambda s: s.score, reverse=True)[:n]


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
            story.summary = data.get("summary") or story.text[:300]
            section = data.get("section", "")
            story.section = section if section in SECTION_KEYWORDS or section == "hits" else _guess_section(story.title, story.text)
        except json.JSONDecodeError:
            log.warning(f"JSON parse error for story: {story.title}")
            story.summary = story.text[:300]
            story.section = _guess_section(story.title, story.text)
        except Exception as e:
            log.warning(f"Groq API error for '{story.title}': {e}")
            story.summary = story.text[:300]
            story.section = _guess_section(story.title, story.text)
    return stories


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
        "> Automated daily tech briefing covering AI, dev tooling, and software news.",
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
