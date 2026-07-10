import pytest

from github_find import discord
from github_find.sources import Repo


def _repo(name="acme/tool", desc="A tool.", gained=42, source="trending"):
    return Repo(name, f"https://github.com/{name}", desc, "Go", 1234, gained, source)


def test_build_embed_shape():
    embed = discord.build_embed(_repo())
    assert embed["title"] == "acme/tool"
    assert embed["url"] == "https://github.com/acme/tool"
    assert embed["description"] == "A tool."
    assert embed["color"] == discord.COLOR_TRENDING
    assert embed["footer"]["text"] == "⭐ 1,234 · +42 recently · Go · trending"


def test_build_embed_omits_gained_when_unknown():
    embed = discord.build_embed(_repo(gained=None, source="search"))
    assert "recently" not in embed["footer"]["text"]
    assert embed["color"] == discord.COLOR_SEARCH


def test_build_embed_truncates_long_description():
    embed = discord.build_embed(_repo(desc="x" * 5000))
    assert len(embed["description"]) == discord.MAX_DESCRIPTION
    assert embed["description"].endswith("…")


def test_chunk_respects_discord_embed_limit():
    repos = [_repo(f"o/r{i}") for i in range(23)]
    batches = discord.chunk(repos)
    assert [len(b) for b in batches] == [10, 10, 3]


class FakeResponse:
    def __init__(self, status_code=204, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append(json)
        return self.responses.pop(0)


def test_send_batches_and_puts_header_only_on_first_message(monkeypatch):
    monkeypatch.setattr(discord.time, "sleep", lambda _: None)
    session = FakeSession([FakeResponse(), FakeResponse()])

    sent = discord.send("https://hook", [_repo(f"o/r{i}") for i in range(12)],
                        header="hello", session=session)

    assert sent == 2
    assert session.calls[0]["content"] == "hello"
    assert len(session.calls[0]["embeds"]) == 10
    assert "content" not in session.calls[1]
    assert len(session.calls[1]["embeds"]) == 2


def test_send_retries_on_rate_limit(monkeypatch):
    slept = []
    monkeypatch.setattr(discord.time, "sleep", slept.append)
    session = FakeSession([
        FakeResponse(429, {"retry_after": 1.5}),
        FakeResponse(204),
    ])

    discord.send("https://hook", [_repo()], session=session)

    assert slept == [1.5]
    assert len(session.calls) == 2


def test_send_gives_up_after_persistent_rate_limiting(monkeypatch):
    monkeypatch.setattr(discord.time, "sleep", lambda _: None)
    session = FakeSession([FakeResponse(429, {"retry_after": 0.1}) for _ in range(5)])

    with pytest.raises(RuntimeError, match="kept rate-limiting"):
        discord.send("https://hook", [_repo()], session=session)
