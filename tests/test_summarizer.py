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
