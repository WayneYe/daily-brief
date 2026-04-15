from unittest.mock import patch, MagicMock
from generate_brief import fetch_hn, Story
from datetime import datetime, timezone, timedelta
import time as time_mod

def _mock_hn_response():
    now = datetime.now(timezone.utc)
    one_hour_ago = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    two_hours_ago = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "hits": [
            {
                "objectID": "123",
                "title": "New LLM beats GPT-5",
                "url": "https://example.com/llm",
                "points": 450,
                "num_comments": 120,
                "created_at": one_hour_ago,
                "story_text": None,
            },
            {
                "objectID": "124",
                "title": "Ask HN: Best Rust resources?",
                "url": None,
                "points": 200,
                "num_comments": 80,
                "created_at": two_hours_ago,
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
    assert stories[1].url == "https://news.ycombinator.com/item?id=124"

def test_fetch_hn_returns_empty_on_error():
    with patch("generate_brief.requests.get") as mock_get:
        mock_get.side_effect = Exception("network error")
        stories = fetch_hn()
    assert stories == []

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

GITHUB_TRENDING_HTML = """
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/astral-sh/uv">astral-sh / uv</a>
  </h2>
  <p class="col-9 color-fg-muted my-1 pr-4">An extremely fast Python package installer</p>
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

def _mock_feed():
    entry = MagicMock()
    entry.title = "AI takes over the world"
    entry.link = "https://techcrunch.com/ai-takeover"
    entry.summary = "In a shocking turn of events..."
    entry.published_parsed = time_mod.gmtime()
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

# Import the other functions needed by later tasks
from generate_brief import fetch_reddit, fetch_github_trending, fetch_rss

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
    assert result[0].score >= result[-1].score
