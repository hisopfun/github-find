"""Fetch trending / recently-hot repositories from GitHub.

Two independent sources:
  - scrape_trending(): github.com/trending HTML. Closest to GitHub's own
    definition of "trending", and the only place that exposes stars-gained.
  - search_recent(): official Search API. Stable, but ranks by total stars
    of recently-created repos, which is a different notion of "hot".
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

TRENDING_URL = "https://github.com/trending"
SEARCH_URL = "https://api.github.com/search/repositories"
USER_AGENT = "github-find/0.1"

_STARS_GAINED_RE = re.compile(r"([\d,]+)\s+stars?\s+(?:today|this week|this month)")


@dataclass(frozen=True)
class Repo:
    full_name: str
    url: str
    description: str
    language: Optional[str]
    stars: int
    stars_gained: Optional[int]  # None when the source can't tell us
    source: str
    topics: tuple = ()  # filled in later by enrich.py
    summary: str = ""

    @property
    def sort_key(self) -> tuple:
        return (self.stars_gained or 0, self.stars)

    @property
    def blurb(self) -> str:
        """Best available explanation of what this repo is."""
        return self.summary or self.description


def _int(text: str) -> int:
    return int(text.replace(",", "").strip())


def parse_trending(html: str) -> list[Repo]:
    soup = BeautifulSoup(html, "html.parser")
    repos: list[Repo] = []

    for row in soup.select("article.Box-row"):
        anchor = row.select_one("h2 a")
        if anchor is None:
            continue
        full_name = re.sub(r"\s+", "", anchor.get_text())

        desc_el = row.select_one("p")
        desc = desc_el.get_text(strip=True) if desc_el else ""

        lang_el = row.select_one('[itemprop="programmingLanguage"]')
        language = lang_el.get_text(strip=True) if lang_el else None

        star_el = row.select_one('a[href$="/stargazers"]')
        stars = _int(star_el.get_text()) if star_el else 0

        gained = None
        gained_el = row.select_one("span.float-sm-right")
        if gained_el:
            m = _STARS_GAINED_RE.search(gained_el.get_text(strip=True))
            if m:
                gained = _int(m.group(1))

        repos.append(
            Repo(
                full_name=full_name,
                url=f"https://github.com/{full_name}",
                description=desc,
                language=language,
                stars=stars,
                stars_gained=gained,
                source="trending",
            )
        )
    return repos


def scrape_trending(
    language: Optional[str] = None,
    since: str = "daily",
    session: Optional[requests.Session] = None,
    timeout: int = 15,
) -> list[Repo]:
    url = f"{TRENDING_URL}/{language}" if language else TRENDING_URL
    http = session or requests.Session()
    resp = http.get(
        url,
        params={"since": since},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    return parse_trending(resp.text)


def parse_search(payload: dict) -> list[Repo]:
    return [
        Repo(
            full_name=item["full_name"],
            url=item["html_url"],
            description=item.get("description") or "",
            language=item.get("language"),
            stars=item.get("stargazers_count", 0),
            stars_gained=None,
            source="search",
        )
        for item in payload.get("items", [])
    ]


def search_recent(
    days: int = 7,
    min_stars: int = 10,
    language: Optional[str] = None,
    limit: int = 25,
    token: Optional[str] = None,
    today: Optional[dt.date] = None,
    session: Optional[requests.Session] = None,
    timeout: int = 15,
) -> list[Repo]:
    since = (today or dt.date.today()) - dt.timedelta(days=days)
    query = f"created:>{since.isoformat()} stars:>={min_stars}"
    if language:
        query += f" language:{language}"

    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    http = session or requests.Session()
    resp = http.get(
        SEARCH_URL,
        params={"q": query, "sort": "stars", "order": "desc", "per_page": min(limit, 100)},
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    return parse_search(resp.json())[:limit]


def merge(*groups: list[Repo]) -> list[Repo]:
    """Dedupe by full_name; earlier groups win. Sorted by stars gained, then total."""
    seen: dict[str, Repo] = {}
    for group in groups:
        for repo in group:
            seen.setdefault(repo.full_name, repo)
    return sorted(seen.values(), key=lambda r: r.sort_key, reverse=True)


def combine(
    trending: list[Repo],
    search: list[Repo],
    limit: int,
    search_share: float = 0.3,
) -> list[Repo]:
    """Fill `limit` slots from both sources, giving search a guaranteed quota.

    The two sources rank on incomparable axes -- trending knows stars *gained*,
    search only knows stars *total* -- so a single sort would let trending win
    every slot. Quota keeps brand-new repos visible. Trending wins duplicates.
    """
    trending = sorted(trending, key=lambda r: r.sort_key, reverse=True)
    search = sorted(search, key=lambda r: r.sort_key, reverse=True)

    if not trending:
        return search[:limit]
    if not search:
        return trending[:limit]

    search_slots = min(len(search), max(1, round(limit * search_share)))
    picked = trending[: limit - search_slots]
    taken = {r.full_name for r in picked}

    for repo in search:
        if len(picked) >= limit:
            break
        if repo.full_name not in taken:
            picked.append(repo)
            taken.add(repo.full_name)

    # Search may have run dry (or been all duplicates); backfill from trending.
    for repo in trending:
        if len(picked) >= limit:
            break
        if repo.full_name not in taken:
            picked.append(repo)
            taken.add(repo.full_name)

    return picked
