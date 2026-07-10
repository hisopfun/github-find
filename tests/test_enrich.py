from github_find.enrich import enrich, summarize_readme
from github_find.sources import Repo

PROSE = "Widget is a tool for building things safely and efficiently at scale."


def test_skips_headings_badges_and_logos():
    readme = f"""
<p align="center">
  <img src="logo.png" alt="Logo">
</p>
<h1 align="center">Widget</h1>

[![build](https://img.shields.io/travis/acme/widget.svg)](https://travis-ci.org/acme/widget)

# Widget

{PROSE}
"""
    assert summarize_readme(readme) == PROSE


def test_skips_link_nav_bar():
    readme = f"""
<a href="/docs">Documentation</a> &nbsp;•&nbsp; <a href="/chat">Discord</a> &nbsp;•&nbsp; <a href="/issues">Issues</a>

{PROSE}
"""
    assert summarize_readme(readme) == PROSE


def test_skips_markdown_link_nav_bar():
    readme = f"[Docs](https://a) | [Chat](https://b) | [Issues](https://c)\n\n{PROSE}\n"
    assert summarize_readme(readme) == PROSE


def test_skips_bullet_link_lists():
    readme = f"""
# Terraform

- Website: https://example.com
- Forums: [Discuss](https://example.com/discuss)

{PROSE}
"""
    assert summarize_readme(readme) == PROSE


def test_skips_bare_url_line_with_short_label():
    readme = f"YouTube channel : https://www.youtube.com/@example\n\n{PROSE}\n"
    assert summarize_readme(readme) == PROSE


def test_keeps_prose_that_merely_contains_a_url():
    readme = "Widget is a fast gateway for tunnelling traffic, documented at https://example.com/docs\n"
    assert summarize_readme(readme).startswith("Widget is a fast gateway")


def test_skips_code_fences():
    readme = f"""
```bash
npm install widget && echo "this is a long enough line to look like prose maybe"
```

{PROSE}
"""
    assert summarize_readme(readme) == PROSE


def test_strips_html_comments_and_entities():
    readme = "<!-- hidden note that is quite long and would otherwise be picked -->\n\nCaf&eacute; is a tool for making coffee at industrial scale.\n"
    assert summarize_readme(readme).startswith("Café is a tool")


def test_flattens_markdown_links_inside_prose():
    readme = "Widget is built on [React](https://react.dev) and runs anywhere you need it.\n"
    assert summarize_readme(readme) == "Widget is built on React and runs anywhere you need it."


def test_ignores_short_taglines():
    readme = f"Fast.\n\nSmall.\n\n{PROSE}\n"
    assert summarize_readme(readme) == PROSE


def test_returns_empty_when_no_prose_exists():
    assert summarize_readme("# Title\n\n- [a](b)\n- [c](d)\n") == ""


def test_truncates_at_sentence_boundary():
    readme = "A" * 100 + ". " + "B" * 300 + ". Trailing sentence here.\n"
    out = summarize_readme(readme, max_chars=150)
    assert out.endswith(".")
    assert len(out) <= 150
    assert "B" not in out  # cut at the first sentence end, not mid-word


def test_truncates_mid_word_when_no_sentence_boundary():
    out = summarize_readme("word " * 200, max_chars=50)
    assert out.endswith("…")
    assert len(out) <= 51


class FakeResponse:
    def __init__(self, ok, payload=None, text=""):
        self.ok = ok
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.urls = []

    def get(self, url, headers, timeout):
        self.urls.append(url)
        return self.handler(url)


def _repo(name="acme/widget"):
    return Repo(name, f"https://github.com/{name}", "one-liner", "Go", 1, None, "search")


def test_enrich_attaches_topics_and_summary():
    def handler(url):
        if url.endswith("/readme"):
            return FakeResponse(True, text=PROSE)
        return FakeResponse(True, payload={"topics": ["cli", "go"]})

    (repo,) = enrich([_repo()], session=FakeSession(handler))

    assert repo.topics == ("cli", "go")
    assert repo.summary == PROSE
    assert repo.blurb == PROSE  # summary wins over the one-liner


def test_enrich_falls_back_to_description_when_readme_missing():
    def handler(url):
        if url.endswith("/readme"):
            return FakeResponse(False)  # 404: repo has no README
        return FakeResponse(True, payload={"topics": None})

    (repo,) = enrich([_repo()], session=FakeSession(handler))

    assert repo.summary == ""
    assert repo.topics == ()
    assert repo.blurb == "one-liner"


def test_enrich_survives_network_errors():
    import requests

    def handler(url):
        raise requests.RequestException("boom")

    (repo,) = enrich([_repo()], session=FakeSession(handler))

    assert repo.blurb == "one-liner"  # the run must not die over one bad repo


def test_enrich_sends_token_when_provided():
    captured = {}

    class TokenSession(FakeSession):
        def get(self, url, headers, timeout):
            captured[url] = headers
            return FakeResponse(True, payload={"topics": []}, text="")

    enrich([_repo()], token="secret", session=TokenSession(lambda u: None))

    assert all(h["Authorization"] == "Bearer secret" for h in captured.values())
    readme_headers = next(h for u, h in captured.items() if u.endswith("/readme"))
    assert readme_headers["Accept"] == "application/vnd.github.raw"
