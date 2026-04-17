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
    "AI",
    "Claude",
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
    # AI / LLM / Agents
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theregister.com/software/ai_ml/headlines.atom",
    "https://blogs.microsoft.com/ai/feed/",
    "https://huggingface.co/blog/feed.xml",
    "https://simonwillison.net/atom/entries/",
    "https://venturebeat.com/category/ai/feed/",
    "https://bdtechtalks.com/feed/",
    # Programming languages / dev tools
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://www.infoq.com/feed/",
    "https://thenewstack.io/feed/",
    "https://engineering.fb.com/feed/",
    "https://developers.googleblog.com/feeds/posts/default",
    "https://devblogs.microsoft.com/python/feed/",
    # General tech / software
    "https://feeds.feedburner.com/ThePragmaticEngineer",
    "https://www.theverge.com/rss/index.xml",
    "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
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


@dataclass
class BriefMeta:
    date: datetime
    date_str: str          # "2026-04-14"
    issue_number: int
    word_count: int
    mp3_url: str           # empty string if TTS failed
    md_url: str            # GitHub blob URL (for 📄 Read link)
    raw_md_url: str        # raw.githubusercontent.com URL (for on-demand fetch)


def generate_index_html(briefs: list[BriefMeta]) -> str:
    """Generate the full GitHub Pages index.html from all briefs, newest first."""
    briefs_sorted = sorted(briefs, key=lambda b: (b.date, b.issue_number), reverse=True)

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
        <tr class="brief-row {expanded}" data-index="{i}" data-raw-url="{b.raw_md_url}">
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
            <div class="brief-body" id="body-{i}">{'<span class="loading">Loading...</span>' if i == 0 else ''}</div>
          </td>
        </tr>""")

    rows_html = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wayne's Daily Brief Agent</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    .loading {{ color: var(--text-muted); font-size: 13px; padding: 16px; display: block; }}
    :root {{
      --bg: #ffffff; --bg2: #f6f8fa; --border: #d0d7de; --text: #1f2328;
      --text-muted: #636c76; --accent: #0969da;
      --tag-ai-bg: #ddf4ff; --tag-ai-text: #0550ae;
      --tag-dev-bg: #d1f0db; --tag-dev-text: #1a7f37;
      --tag-tech-bg: #fff0b3; --tag-tech-text: #7d4e00;
      --btn-play-bg: #0969da; --btn-play-text: #ffffff;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #0d1117; --bg2: #161b22; --border: #30363d; --text: #e6edf3;
        --text-muted: #7d8590; --accent: #58a6ff;
        --tag-ai-bg: #0c2d6b; --tag-ai-text: #79c0ff;
        --tag-dev-bg: #0c3322; --tag-dev-text: #56d364;
        --tag-tech-bg: #3d2b00; --tag-tech-text: #e3b341;
        --btn-play-bg: #1f6feb; --btn-play-text: #ffffff;
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
      <div class="subtitle">$ ./daily_brief.sh &mdash; automated &middot; curated &middot; daily</div>
    </div>
    <button class="theme-toggle" id="theme-toggle" onclick="toggleTheme()" aria-label="Toggle theme">&#127769;</button>
  </header>
  <main>
    <table>
      <thead>
        <tr>
          <th>Date</th><th>Issue</th><th>Topics</th><th>Length</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </main>
  <footer>Automated daily tech briefing &middot; AI &middot; Dev &middot; Security &middot; Open Source</footer>
  <script>
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
      document.getElementById('theme-toggle').textContent = isDark ? '\u2600\ufe0f' : '\U0001F319';
    }}
    function loadBriefContent(row) {{
      const idx = row.dataset.index;
      const rawUrl = row.dataset.rawUrl;
      const body = document.getElementById('body-' + idx);
      if (!body || body.dataset.loaded) return;
      body.innerHTML = '<span class="loading">Loading...</span>';
      fetch(rawUrl)
        .then(function(r) {{ return r.text(); }})
        .then(function(md) {{
          body.innerHTML = marked.parse(md);
          body.dataset.loaded = '1';
        }})
        .catch(function() {{
          body.innerHTML = '<span class="loading">Failed to load content.</span>';
        }});
    }}
    document.querySelectorAll('.brief-row').forEach(function(row) {{
      row.addEventListener('click', function(e) {{
        if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON') return;
        const idx = this.dataset.index;
        const content = document.getElementById('content-' + idx);
        const isExpanded = content.classList.contains('expanded');
        document.querySelectorAll('.brief-content').forEach(function(c) {{ c.classList.remove('expanded'); }});
        document.querySelectorAll('.brief-row').forEach(function(r) {{ r.classList.remove('expanded'); }});
        if (!isExpanded) {{
          content.classList.add('expanded');
          this.classList.add('expanded');
          loadBriefContent(this);
        }}
      }});
    }});
    // Load the first (expanded) row on page load
    var firstRow = document.querySelector('.brief-row.expanded');
    if (firstRow) loadBriefContent(firstRow);
    function toggleAudio(btn, url) {{
      const row = btn.closest('tr');
      const idx = row.dataset.index;
      const container = document.getElementById('content-' + idx);
      const audioDiv = document.getElementById('audio-' + idx);
      // Expand the row if not already open
      if (!container.classList.contains('expanded')) {{
        document.querySelectorAll('.brief-content').forEach(function(c) {{ c.classList.remove('expanded'); }});
        document.querySelectorAll('.brief-row').forEach(function(r) {{ r.classList.remove('expanded'); }});
        container.classList.add('expanded');
        row.classList.add('expanded');
        loadBriefContent(row);
      }}
      // Inject native audio player once; hide the Play button
      if (!audioDiv.querySelector('audio')) {{
        var audio = document.createElement('audio');
        audio.controls = true;
        audio.preload = 'none';
        audio.src = url;
        audio.style.width = '100%';
        audio.style.maxWidth = '480px';
        audio.onerror = function() {{
          audioDiv.innerHTML = '<span style="color:red;font-size:13px">Audio unavailable</span>';
        }};
        audioDiv.appendChild(audio);
      }}
      btn.style.display = 'none';
    }}
  </script>
</body>
</html>"""


def _strip_markdown(text: str) -> str:
    """Strip Markdown syntax for clean TTS input."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    text = re.sub(r"`{1,3}.+?`{1,3}", "", text)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def generate_mp3(markdown_text: str, output_path: Path) -> bool:
    """Generate MP3 from brief text using Kokoro TTS. Returns True on success."""
    try:
        import kokoro
        import soundfile as sf
        import numpy as np
        from pydub import AudioSegment

        plain_text = _strip_markdown(markdown_text)
        pipeline = kokoro.KPipeline(lang_code="a")  # American English

        wav_path = output_path.with_suffix(".wav")
        samples = []
        sample_rate = 24000

        for _, _, audio in pipeline(plain_text, voice="af_heart", speed=1.0):
            samples.append(audio)

        if not samples:
            log.warning("Kokoro produced no audio samples")
            return False

        combined = np.concatenate(samples)
        sf.write(str(wav_path), combined, sample_rate)
        AudioSegment.from_wav(str(wav_path)).export(str(output_path), format="mp3", bitrate="128k")
        wav_path.unlink(missing_ok=True)
        log.info(f"MP3 generated: {output_path}")
        return True
    except Exception as e:
        log.warning(f"TTS generation failed: {e}")
        return False



def collect_existing_briefs(briefs_dir: Path, repo: str) -> list[BriefMeta]:
    """Walk briefs/*/daily-brief.md and reconstruct BriefMeta for each."""
    metas = []
    for md_path in sorted(briefs_dir.glob("*/daily-brief.md")):
        date_str = md_path.parent.name  # "04-14-2026"
        try:
            date = datetime.strptime(date_str, "%m-%d-%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        content = md_path.read_text()
        m = re.search(r"Issue #(\d+)", content)
        issue = int(m.group(1)) if m else 0
        word_count = len(content.split())
        md_url = f"https://github.com/{repo}/blob/master/briefs/{date_str}/daily-brief.md"
        raw_md_url = f"https://raw.githubusercontent.com/{repo}/master/briefs/{date_str}/daily-brief.md"
        mp3_exists = (md_path.parent / "daily-brief.mp3").exists()
        mp3_url = f"briefs/{date_str}/daily-brief.mp3" if mp3_exists else ""
        metas.append(BriefMeta(
            date=date,
            date_str=date_str,
            issue_number=issue,
            word_count=word_count,
            mp3_url=mp3_url,
            md_url=md_url,
            raw_md_url=raw_md_url,
        ))
    return metas


def main():
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    github_repo  = os.environ.get("GITHUB_REPOSITORY", "")

    today = datetime.now(timezone.utc)
    date_dir_name = today.strftime("%m-%d-%Y")
    tag = today.strftime("%Y-%m-%d")

    root = Path(__file__).parent
    briefs_dir = root / "briefs"
    out_dir = briefs_dir / date_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path  = out_dir / "daily-brief.md"
    mp3_path = out_dir / "daily-brief.mp3"
    count_file = briefs_dir / ".issue_count"
    docs_dir = root / "docs"
    docs_dir.mkdir(exist_ok=True)

    # 1. Crawl
    log.info("Crawling sources...")
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            ex.submit(fetch_hn): "hn",
            ex.submit(fetch_github_trending): "github",
            ex.submit(fetch_rss): "rss",
        }
        all_stories: list[Story] = []
        for future in as_completed(futures):
            result = future.result()
            log.info(f"  {futures[future]}: {len(result)} stories")
            all_stories.extend(result)

    # 2. Rank + deduplicate
    stories = rank_and_select(deduplicate(all_stories), n=12)
    log.info(f"Selected {len(stories)} stories after dedup+rank")

    # 3. Summarize
    if groq_api_key:
        log.info("Summarizing via Groq...")
        stories = summarize_and_categorize(stories, api_key=groq_api_key)
    else:
        log.warning("GROQ_API_KEY not set — skipping summarization")
        for s in stories:
            s.summary = s.text[:300]
            s.section = _guess_section(s.title, s.text)

    # 4. Format Markdown
    issue_number = get_next_issue_number(count_file)
    markdown_text = format_markdown(stories, date=today, issue_number=issue_number)
    md_path.write_text(markdown_text)
    log.info(f"Brief written: {md_path}")

    # 5. Generate MP3
    log.info("Generating MP3 via Kokoro TTS...")
    tts_ok = generate_mp3(markdown_text, mp3_path)

    # 6. MP3 is committed to the repo and served via GitHub Pages (same-origin, no CORS issues)
    if tts_ok:
        log.info(f"MP3 ready: {mp3_path}")
    else:
        log.warning("TTS failed — no audio for this brief")

    # 7. Regenerate index.html
    log.info("Regenerating docs/index.html...")
    all_metas = collect_existing_briefs(briefs_dir, github_repo)
    index_html = generate_index_html(all_metas)
    (docs_dir / "index.html").write_text(index_html)
    log.info("docs/index.html updated")

    log.info("Done.")


if __name__ == "__main__":
    main()
