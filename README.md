# Daily Brief

Automated daily tech news briefing — AI, LLMs, dev tooling, software & internet tech.

Powered by GitHub Actions, Groq (Llama 3.3 70B), and Kokoro TTS.

## Setup

### 1. Fork / clone this repo and push to GitHub

### 2. Add repository secrets

Repo → Settings → Secrets and variables → Actions → New repository secret:

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
uv sync
GROQ_API_KEY=your_key uv run python generate_brief.py
uv run pytest tests/ -v
```

## Structure

```
daily-brief/
├── .github/workflows/daily-brief.yml  # Cron workflow
├── generate_brief.py                  # Main script
├── pyproject.toml                     # uv dependencies
├── docs/index.html                    # Generated GitHub Pages archive
└── briefs/
    └── MM-DD-YYYY/
        └── daily-brief.md             # Daily brief Markdown
```
