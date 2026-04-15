from datetime import datetime, timezone
from pathlib import Path
import tempfile
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
