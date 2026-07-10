"""Post repositories to a Discord channel via an incoming webhook."""
from __future__ import annotations

import time
from typing import Optional

import requests

from .sources import Repo

# Discord hard limits, see https://discord.com/developers/docs/resources/message
MAX_EMBEDS_PER_MESSAGE = 10
MAX_TITLE = 256
MAX_DESCRIPTION = 4096

COLOR_TRENDING = 0x2DA44E
COLOR_SEARCH = 0x0969DA


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_embed(repo: Repo) -> dict:
    footer_bits = [f"⭐ {repo.stars:,}"]
    if repo.stars_gained is not None:
        footer_bits.append(f"+{repo.stars_gained:,} recently")
    if repo.language:
        footer_bits.append(repo.language)
    footer_bits.append(repo.source)

    return {
        "title": _truncate(repo.full_name, MAX_TITLE),
        "url": repo.url,
        "description": _truncate(repo.description, MAX_DESCRIPTION),
        "color": COLOR_TRENDING if repo.source == "trending" else COLOR_SEARCH,
        "footer": {"text": " · ".join(footer_bits)},
    }


def chunk(repos: list[Repo], size: int = MAX_EMBEDS_PER_MESSAGE) -> list[list[Repo]]:
    return [repos[i : i + size] for i in range(0, len(repos), size)]


def _post(url: str, payload: dict, session: requests.Session, timeout: int) -> None:
    for attempt in range(5):
        resp = session.post(url, json=payload, timeout=timeout)
        if resp.status_code == 429:
            # Discord tells us exactly how long to wait; respect it rather than guess.
            retry_after = float(resp.json().get("retry_after", 1))
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return
    raise RuntimeError(f"Discord kept rate-limiting after {attempt + 1} attempts")


def send(
    webhook_url: str,
    repos: list[Repo],
    header: Optional[str] = None,
    session: Optional[requests.Session] = None,
    timeout: int = 15,
) -> int:
    """Send repos as embeds. Returns the number of HTTP requests made."""
    http = session or requests.Session()
    batches = chunk(repos)
    for i, batch in enumerate(batches):
        payload: dict = {"embeds": [build_embed(r) for r in batch]}
        if i == 0 and header:
            payload["content"] = _truncate(header, 2000)
        _post(webhook_url, payload, http, timeout)
        if i < len(batches) - 1:
            time.sleep(0.5)  # stay under the webhook's 5-per-2s bucket
    return len(batches)
