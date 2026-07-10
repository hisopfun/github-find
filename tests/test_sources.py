import datetime as dt
import pathlib

from github_find.sources import (
    Repo,
    combine,
    merge,
    parse_search,
    parse_trending,
    search_recent,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "trending.html"


def test_parse_trending_extracts_all_fields():
    repos = parse_trending(FIXTURE.read_text())

    assert len(repos) == 3
    first = repos[0]
    assert first.full_name == "wonderwhy-er/DesktopCommanderMCP"
    assert first.url == "https://github.com/wonderwhy-er/DesktopCommanderMCP"
    assert first.language == "TypeScript"
    assert first.stars == 6818
    assert first.stars_gained == 349
    assert first.description.startswith("This is MCP server for Claude")
    assert first.source == "trending"


def test_parse_trending_handles_missing_language_and_stars():
    html = """
    <article class="Box-row">
      <h2><a href="/acme/widget"> acme /
        widget </a></h2>
      <p>A thing.</p>
    </article>
    """
    (repo,) = parse_trending(html)
    assert repo.full_name == "acme/widget"  # whitespace/newlines collapsed
    assert repo.language is None
    assert repo.stars == 0
    assert repo.stars_gained is None


def test_parse_trending_ignores_unparseable_gained_text():
    html = """
    <article class="Box-row">
      <h2><a href="/a/b">a/b</a></h2>
      <span class="float-sm-right">Built by</span>
    </article>
    """
    (repo,) = parse_trending(html)
    assert repo.stars_gained is None


def test_parse_search_handles_null_description():
    payload = {
        "items": [
            {
                "full_name": "acme/tool",
                "html_url": "https://github.com/acme/tool",
                "description": None,
                "language": "Go",
                "stargazers_count": 1234,
            }
        ]
    }
    (repo,) = parse_search(payload)
    assert repo.description == ""
    assert repo.stars_gained is None
    assert repo.source == "search"


def test_search_recent_builds_query_from_date_window(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"items": []}

    class FakeSession:
        def get(self, url, params, headers, timeout):
            captured["params"] = params
            captured["headers"] = headers
            return FakeResponse()

    search_recent(
        days=7,
        min_stars=50,
        language="python",
        token="secret",
        today=dt.date(2026, 7, 10),
        session=FakeSession(),
    )

    assert captured["params"]["q"] == "created:>2026-07-03 stars:>=50 language:python"
    assert captured["params"]["sort"] == "stars"
    assert captured["headers"]["Authorization"] == "Bearer secret"


def _repo(name, stars=0, gained=None, source="trending"):
    return Repo(name, f"https://github.com/{name}", "", None, stars, gained, source)


def test_merge_prefers_first_group_and_sorts_by_gained_then_stars():
    trending = [_repo("a/a", stars=10, gained=5), _repo("b/b", stars=100, gained=50)]
    search = [
        _repo("a/a", stars=999, gained=None, source="search"),  # duplicate, must lose
        _repo("c/c", stars=500, gained=None, source="search"),
    ]

    merged = merge(trending, search)

    assert [r.full_name for r in merged] == ["b/b", "a/a", "c/c"]
    assert merged[1].source == "trending"  # trending won the dedupe
    assert merged[1].stars == 10


def test_combine_reserves_slots_for_search_results():
    trending = [_repo(f"t/{i}", stars=100, gained=100 - i) for i in range(10)]
    search = [_repo(f"s/{i}", stars=50 - i, source="search") for i in range(10)]

    picked = combine(trending, search, limit=10, search_share=0.3)

    assert len(picked) == 10
    sources = [r.source for r in picked]
    assert sources.count("trending") == 7
    assert sources.count("search") == 3
    # Without the quota, sorting by (gained, stars) would have dropped search entirely.
    assert picked[7].full_name == "s/0"


def test_combine_backfills_from_trending_when_search_is_all_duplicates():
    trending = [_repo(f"t/{i}", stars=100, gained=10 - i) for i in range(10)]
    search = [_repo("t/0", stars=999, source="search")]  # duplicate of trending[0]

    picked = combine(trending, search, limit=10, search_share=0.3)

    assert len(picked) == 10  # no short post
    assert [r.source for r in picked] == ["trending"] * 10
    assert len({r.full_name for r in picked}) == 10


def test_combine_falls_back_to_single_source():
    trending = [_repo("t/0", gained=5)]
    search = [_repo("s/0", stars=5, source="search")]

    assert combine(trending, [], limit=5) == trending
    assert combine([], search, limit=5) == search
