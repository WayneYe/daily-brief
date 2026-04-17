from datetime import datetime, timezone
from generate_brief import generate_index_html, BriefMeta

def _make_meta(date_str="2026-04-14", issue=42, word_count=700, mp3_url="https://github.com/releases/mp3"):
    return BriefMeta(
        date=datetime(2026, 4, 14, tzinfo=timezone.utc),
        date_str=date_str,
        issue_number=issue,
        word_count=word_count,
        mp3_url=mp3_url,
        md_url="https://github.com/blob/master/briefs/04-14-2026/daily-brief.md",
        raw_md_url="https://raw.githubusercontent.com/WayneYe/daily-brief/master/briefs/04-14-2026/daily-brief.md",
    )

def test_generate_index_html_contains_meta():
    meta = _make_meta()
    html = generate_index_html([meta])
    assert "April 14, 2026" in html
    assert "#042" in html
    assert "~3 min" in html  # 700 words / 200 wpm = 3
    assert "▶ Play" in html
    assert "📄 Read" in html
    assert "raw.githubusercontent.com" in html
    assert "data-raw-url" in html

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
