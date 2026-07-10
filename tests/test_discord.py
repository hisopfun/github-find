import pytest

from github_find import discord
from github_find.sources import Repo


def _repo(name="acme/tool", desc="A tool.", gained=42, source="trending", topics=(), summary=""):
    return Repo(name, f"https://github.com/{name}", desc, "Go", 1234, gained, source,
                topics, summary)


def test_build_embed_shape():
    embed = discord.build_embed(_repo())
    assert embed["title"] == "acme/tool"
    assert embed["url"] == "https://github.com/acme/tool"
    assert embed["description"] == "A tool."
    assert embed["color"] == discord.COLOR_TRENDING
    assert embed["footer"]["text"] == "⭐ 1,234 · +42 recently · Go · trending"


def test_build_embed_prefers_readme_summary_over_one_liner():
    embed = discord.build_embed(_repo(desc="terse", summary="A much better explanation."))
    assert embed["description"] == "A much better explanation."


def test_build_embed_appends_topics_as_tags():
    embed = discord.build_embed(_repo(topics=("cli", "go")))
    assert embed["description"] == "A tool.\n`cli` `go`"


def test_build_embed_caps_topic_count():
    embed = discord.build_embed(_repo(topics=tuple(f"t{i}" for i in range(20))))
    assert embed["description"].count("`") == discord.MAX_TOPICS * 2


def test_build_embed_drops_topics_rather_than_bust_the_description_cap():
    embed = discord.build_embed(_repo(summary="x" * discord.MAX_DESCRIPTION, topics=("cli",)))
    assert len(embed["description"]) == discord.MAX_DESCRIPTION
    assert "`cli`" not in embed["description"]


def test_build_embed_omits_gained_when_unknown():
    embed = discord.build_embed(_repo(gained=None, source="search"))
    assert "recently" not in embed["footer"]["text"]
    assert embed["color"] == discord.COLOR_SEARCH


def test_build_embed_truncates_long_description():
    embed = discord.build_embed(_repo(desc="x" * 5000))
    assert len(embed["description"]) == discord.MAX_DESCRIPTION
    assert embed["description"].endswith("…")


def test_chunk_respects_discord_embed_count_limit():
    embeds = [discord.build_embed(_repo(f"o/r{i}")) for i in range(23)]
    batches = discord.chunk_embeds(embeds)
    assert [len(b) for b in batches] == [10, 10, 3]


def test_chunk_respects_discord_total_char_limit():
    # Long summaries: the 6000-char cap bites before the 10-embed cap does.
    embeds = [discord.build_embed(_repo(f"o/r{i}", summary="x" * 1000)) for i in range(10)]
    batches = discord.chunk_embeds(embeds)

    assert len(batches) > 1  # would have been a single over-budget message
    assert all(len(b) <= discord.MAX_EMBEDS_PER_MESSAGE for b in batches)
    for batch in batches:
        assert sum(discord.embed_chars(e) for e in batch) <= discord.MAX_CHARS_PER_MESSAGE


def test_chunk_keeps_oversized_single_embed_rather_than_dropping_it():
    embeds = [discord.build_embed(_repo(summary="x" * (discord.MAX_CHARS_PER_MESSAGE + 500)))]
    batches = discord.chunk_embeds(embeds)
    assert len(batches) == 1 and len(batches[0]) == 1


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
