# Daily Brief Agent — Design Spec
**Date:** 2026-04-14  
**Status:** Approved

---

## Overview

An automated personal daily briefing agent that crawls tech news sources, summarizes the top stories using a free LLM, generates an audio MP3, commits a Markdown brief to a GitHub repo, uploads the MP3 as a GitHub Release asset, and deploys a GitHub Pages web archive — all triggered by a GitHub Actions cron job at 6:00 AM UTC daily.

Topics covered: AI/LLM/Agents, Programming Languages (Python, Rust, Go, Java, etc.), Software & Internet Tech.

---

## Architecture

```
GitHub Actions (cron: 6:00 AM UTC daily)
    └── generate_brief.py
        ├── 1. Crawl phase (parallel where possible)
        │   ├── Hacker News API
        │   ├── Reddit JSON API
        │   ├── GitHub Trending (scrape)
        │   └── RSS feeds (feedparser)
        ├── 2. Rank + deduplicate
        ├── 3. Summarize top stories via Groq API (Llama 3.3 70B)
        ├── 4. Format → briefs/MM-DD-YYYY/daily-brief.md
        ├── 5. Generate MP3 via Kokoro TTS
        ├── 6. Commit + push daily-brief.md to repo
        ├── 7. Upload MP3 as GitHub Release asset (tag: YYYY-MM-DD)
        └── 8. Regenerate docs/index.html → push → GitHub Pages auto-deploys
```

---

## Content Structure

The generated `daily-brief.md` follows this section layout (matching the visual mockup):

```
# Daily Brief — Month DD, YYYY  //  Issue #NNN

## 01 AI / LLM / Agents
## 02 Dev Tooling & Languages
## 03 Software & Internet Tech
## 04 Quick Hits
```

**Per section:** 2–4 stories  
**Per story:** Title + 3–6 sentence summary + source URL  
**Target length:** 600–900 words  
**Estimated listen time:** 5–8 minutes

Issue numbers are tracked via a counter file (`briefs/.issue_count`) committed to the repo, incremented on each run.

---

## News Sources

| Source | Method | API Key Required | Topics |
|--------|--------|-----------------|--------|
| Hacker News | Official Algolia API (free) | No | All tech |
| Reddit | JSON API (`/r/sub.json`, no auth) | No | r/MachineLearning, r/programming, r/golang, r/rust, r/Python, r/LocalLLaMA, r/artificial |
| GitHub Trending | HTML scrape (BeautifulSoup) | No | All languages |
| TechCrunch AI | RSS via feedparser | No | AI/LLM |
| Ars Technica | RSS via feedparser | No | General tech |
| The Register | RSS via feedparser | No | General tech |
| InfoQ | RSS via feedparser | No | Dev/engineering |

**Crawl window:** Past 24 hours  
**Story pool:** Top 30 candidates per source, ranked by score/upvotes/recency, deduplicated by URL and semantic title similarity, top 10–15 selected for summarization.

---

## Summarization

- **Provider:** Groq API (free tier)
- **Model:** `llama-3.3-70b-versatile`
- **Prompt:** Each story's title + source text is sent individually. The model returns a 3–6 sentence summary in plain English, maintaining the story's key facts, numbers, and significance.
- **Section assignment:** Stories are categorized into sections by the LLM based on topic.
- **Groq free tier limits:** 14,400 requests/day, 500K tokens/day — well within budget for ~15 stories/day.

---

## TTS — Audio Generation

- **Library:** Kokoro TTS (open-source, neural quality)
- **Runs in:** GitHub Actions (model auto-downloads on first run, ~500MB, cached between runs via Actions cache)
- **Input:** Full brief text (Markdown stripped to plain text)
- **Output:** `briefs/MM-DD-YYYY/daily-brief.mp3`
- **Voice:** Default Kokoro English voice (natural, not robotic)
- **Estimated runtime:** 1–2 minutes in Actions

The MP3 is uploaded as a GitHub Release asset (tag `YYYY-MM-DD`). The release asset URL streams natively in Safari on iOS and desktop browsers — no download required.

---

## Delivery

### GitHub Commit
- File: `briefs/MM-DD-YYYY/daily-brief.md`
- Committed with message: `brief: YYYY-MM-DD`
- Pushed to `main` branch

### GitHub Release
- Tag: `YYYY-MM-DD`
- Title: `Daily Brief — Month DD, YYYY`
- Asset: `daily-brief.mp3`
- Created via GitHub API using `GITHUB_TOKEN` (auto-provided by Actions, no extra secret needed)

### GitHub Pages Web Archive
See dedicated section below. Email delivery is replaced by the web archive.

---

## Web Archive (GitHub Pages)

A static single-page app hosted at `https://<username>.github.io/daily-brief/`.

### How it works
- After each brief is generated, `generate_brief.py` also regenerates `docs/index.html` by reading all `briefs/*/daily-brief.md` files and building a fresh static HTML file
- The `docs/` folder is configured as the GitHub Pages source in repo settings
- GitHub Pages auto-deploys on every push to `main` — no separate deploy step needed

### Table layout (one row per day)

| Column | Content |
|--------|---------|
| Date | `April 14, 2026` |
| Issue | `#042` |
| Topics | Tag pills: `AI` · `Dev` · `Tech` |
| Read time | `~6 min read` (estimated from word count) |
| Actions | `📄 Read` (opens `.md` on GitHub) · `▶ Play` (streams MP3 from Release asset) |

Rows are sorted newest-first. The most recent brief is expanded by default showing its full Markdown content rendered as HTML inline.

### Theme
- **Default:** auto-matches device OS preference via `prefers-color-scheme` CSS media query
- **Toggle:** sun/moon icon button in the top-right corner persists preference to `localStorage`
- **Dark theme:** dark background (`#0d1117`), muted text, accent color for tags and buttons — matches the terminal aesthetic of the mockup
- **Light theme:** clean white background, same layout, softer tag colors

### Audio player
Clicking `▶ Play` on any row:
1. Expands an inline `<audio>` element in that row pointing to the GitHub Release MP3 URL
2. Auto-plays
3. Clicking again collapses it
Only one row plays at a time — opening a new one pauses any currently playing audio.

### Tech
- Pure static HTML + vanilla CSS + vanilla JS — no build step, no framework, no npm
- Single file: `docs/index.html` (generated by Python, not hand-edited)
- All brief metadata (date, issue, word count, MP3 URL) embedded directly in the HTML at generation time

---

## Secrets & Configuration

All secrets stored in GitHub Actions repository secrets:

| Secret | Description |
|--------|-------------|
| `GROQ_API_KEY` | Free at console.groq.com |
| `GITHUB_TOKEN` | Auto-provided by Actions — no setup needed |

---

## Repo Structure

```
daily-brief/
├── .github/
│   └── workflows/
│       └── daily-brief.yml       # Actions cron workflow
├── generate_brief.py             # Main script (single file)
├── pyproject.toml                # uv-managed dependencies
├── docs/
│   └── index.html                # Generated web archive (GitHub Pages source)
├── briefs/
│   ├── .issue_count              # Incremented each run
│   └── MM-DD-YYYY/
│       └── daily-brief.md        # Committed to repo (MP3 as Release asset)
└── README.md
```

**Dependency management:** `uv` — `uv sync` in the Actions workflow installs from `pyproject.toml`.

---

## Python Dependencies

```toml
[project]
dependencies = [
    "feedparser",          # RSS parsing
    "beautifulsoup4",      # GitHub Trending scrape + HTML generation
    "requests",            # HTTP calls
    "groq",                # Groq API client
    "kokoro",              # TTS
    "soundfile",           # WAV output from Kokoro
    "pydub",               # WAV → MP3 conversion (requires ffmpeg system dep)
    "markdown",            # Render brief Markdown → HTML for web archive
]
```

---

## GitHub Actions Workflow

```yaml
on:
  schedule:
    - cron: '0 6 * * *'   # 6:00 AM UTC daily
  workflow_dispatch:        # Manual trigger anytime
```

Steps:
1. Checkout repo
2. Install `uv`, run `uv sync`
3. Install `ffmpeg` via `apt-get` (for pydub MP3 encoding)
4. Cache Kokoro model weights (~500MB)
5. Run `python generate_brief.py`
6. Commit + push `briefs/MM-DD-YYYY/daily-brief.md` and `docs/index.html`
7. Create GitHub Release + upload `daily-brief.mp3` as asset

---

## Error Handling

- If a source fails to crawl, skip it and log a warning — don't fail the whole run
- If Groq API fails, fall back to using raw story titles + first paragraph (no summarization)
- If Kokoro TTS fails, skip MP3 generation; `▶ Play` button is omitted from that day's row in the web archive
- Web archive is always regenerated and deployed even if TTS fails — the Markdown brief is the primary artifact

---

## Out of Scope

- No email delivery (replaced by GitHub Pages web archive)
- No Slack integration
- No local cron/launchd setup (GitHub Actions handles scheduling)
- No paid APIs
- Reddit OAuth app (using unauthenticated JSON API endpoint, sufficient for read-only access)
- No JavaScript framework or build pipeline for the web UI
