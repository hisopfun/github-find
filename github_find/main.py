"""CLI: collect hot GitHub repos and push them to Discord."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import requests

from . import discord
from .enrich import enrich
from .sources import Repo, combine, merge, scrape_trending, search_recent

SINCE_LABEL = {"daily": "today", "weekly": "this week", "monthly": "this month"}


def collect(args: argparse.Namespace, token: str | None) -> list[Repo]:
    session = requests.Session()
    trending: list[Repo] = []
    search: list[Repo] = []

    if args.source in ("trending", "both"):
        try:
            trending = scrape_trending(args.language, args.since, session=session)
        except Exception as exc:  # noqa: BLE001 - the trending page has no API contract
            print(f"warn: trending scrape failed ({exc})", file=sys.stderr)
            if args.source == "trending":
                raise

    if args.source in ("search", "both"):
        try:
            search = search_recent(
                days=args.days,
                min_stars=args.min_stars,
                language=args.language,
                limit=args.limit,
                token=token,
                session=session,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"warn: search API failed ({exc})", file=sys.stderr)
            if args.source == "search" or not trending:
                raise

    if args.source == "both":
        return combine(trending, search, args.limit, args.search_share)
    return merge(trending, search)[: args.limit]


def format_header(args: argparse.Namespace, count: int) -> str:
    scope = f" `{args.language}`" if args.language else ""
    window = SINCE_LABEL.get(args.since, args.since)
    today = dt.date.today().isoformat()
    return f"**🔥 GitHub hot repos{scope} — {window}** ({today}) · {count} repos"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="github-find")
    p.add_argument("--language", help="filter by language, e.g. python")
    p.add_argument("--since", default="daily", choices=["daily", "weekly", "monthly"])
    p.add_argument("--source", default="both", choices=["trending", "search", "both"])
    p.add_argument("--days", type=int, default=7, help="search: repos created in last N days")
    p.add_argument("--min-stars", type=int, default=10, help="search: minimum star count")
    p.add_argument("--limit", type=int, default=10, help="max repos to post")
    p.add_argument(
        "--search-share",
        type=float,
        default=0.3,
        help="source=both: fraction of slots reserved for newly-created repos",
    )
    p.add_argument("--dry-run", action="store_true", help="print instead of posting")
    p.add_argument(
        "--no-enrich",
        action="store_true",
        help="skip README/topics lookup (2 fewer API calls per repo)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")

    if not args.dry_run and not webhook:
        print("error: DISCORD_WEBHOOK_URL is not set (or use --dry-run)", file=sys.stderr)
        return 2

    repos = collect(args, token)
    if not repos:
        print("no repos found; nothing to post", file=sys.stderr)
        return 0

    if not args.no_enrich:
        repos = enrich(repos, token=token)

    if args.dry_run:
        print(format_header(args, len(repos)))
        for r in repos:
            gained = f"+{r.stars_gained}" if r.stars_gained is not None else "-"
            print(f"\n  {r.full_name:<45} ⭐{r.stars:<8,} {gained:<8} [{r.source}] {r.language or ''}")
            if r.blurb:
                print(f"      {r.blurb}")
            if r.topics:
                print(f"      topics: {', '.join(r.topics[:discord.MAX_TOPICS])}")
        return 0

    requests_made = discord.send(webhook, repos, header=format_header(args, len(repos)))
    print(f"posted {len(repos)} repos in {requests_made} message(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
