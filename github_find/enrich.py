"""Add topics and a README-derived summary to each repo.

GitHub's one-line description is often terse or missing. The README's opening
prose paragraph is usually a much better "what is this", but it is buried under
badges, logos and link lists that carry no meaning in a Discord embed.
"""
from __future__ import annotations

import dataclasses
import html
import re
from typing import Optional

import requests

from .sources import Repo

API = "https://api.github.com"
USER_AGENT = "github-find/0.1"

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CODE_FENCE = re.compile(r"^```.*?^```", re.S | re.M)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_BADGE_URL = re.compile(r"(shields\.io|badge|travis-ci|circleci|codecov)", re.I)

_ANY_LINK = re.compile(r"<a\b[^>]*>.*?</a>|\[[^\]]*\]\([^)]*\)|https?://\S+", re.S | re.I)
# A line that is mostly link with a few words of label around it is a link, not prose.
_MIN_PROSE_AROUND_LINKS = 25
# What's left of a nav bar once its links are removed: bullets, pipes, dashes.
_SEPARATORS_ONLY = re.compile(r"^[\s •·|,/\-–—]*$")

# Lines that are structure, not prose.
_SKIP_LINE = re.compile(
    r"""^\s*(
          \#            # heading
        | [-*+]\s       # bullet
        | \d+\.\s       # numbered list
        | \|            # table row
        | >             # blockquote
        | -{3,}|={3,}   # horizontal rule / setext underline
    )""",
    re.X,
)


def _headers(token: Optional[str], raw: bool = False) -> dict:
    accept = "application/vnd.github.raw" if raw else "application/vnd.github+json"
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_link_nav(raw_line: str) -> bool:
    """True for lines that are links plus glue: nav bars, `Docs: https://…`, etc."""
    if not _ANY_LINK.search(raw_line):
        return False
    remainder = _ANY_LINK.sub("", raw_line)
    remainder = html.unescape(_HTML_TAG.sub("", remainder)).replace("\xa0", " ").strip()
    if _SEPARATORS_ONLY.match(remainder):
        return True
    # Too little text left around the links to be an explanation of anything.
    return len(remainder) < _MIN_PROSE_AROUND_LINKS


def summarize_readme(markdown: str, max_chars: int = 350) -> str:
    """Return the first prose paragraph of a README, flattened to plain text."""
    text = _HTML_COMMENT.sub("", markdown)
    text = _CODE_FENCE.sub("", text)
    text = _MD_IMAGE.sub("", text)

    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for raw_line in text.splitlines():
        structural = (
            _SKIP_LINE.match(raw_line.strip())
            or _BADGE_URL.search(raw_line)
            or _is_link_nav(raw_line)
        )
        line = html.unescape(_HTML_TAG.sub("", raw_line)).replace("\xa0", " ").strip()
        if not line or structural:
            flush()  # a blank or structural line ends the paragraph before it
            continue
        current.append(_MD_LINK.sub(r"\1", line))
    flush()

    for para in paragraphs:
        cleaned = re.sub(r"\s+", " ", para).strip()
        # Short fragments are logos, taglines or stray link text, not a summary.
        if len(cleaned) >= 40:
            return _truncate_at_sentence(cleaned, max_chars)
    return ""


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end > max_chars // 2:
        return cut[: end + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def fetch_metadata(
    full_name: str, token: Optional[str], session: requests.Session, timeout: int = 15
) -> tuple[list[str], str]:
    """Return (topics, readme_summary). Missing pieces come back empty, never raise."""
    topics: list[str] = []
    summary = ""

    try:
        resp = session.get(
            f"{API}/repos/{full_name}", headers=_headers(token), timeout=timeout
        )
        if resp.ok:
            topics = resp.json().get("topics") or []
    except requests.RequestException:
        pass

    try:
        resp = session.get(
            f"{API}/repos/{full_name}/readme",
            headers=_headers(token, raw=True),
            timeout=timeout,
        )
        if resp.ok:
            summary = summarize_readme(resp.text)
    except requests.RequestException:
        pass

    return topics, summary


def enrich(
    repos: list[Repo],
    token: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> list[Repo]:
    """Attach topics + README summary. A repo that fails to enrich is left as-is."""
    http = session or requests.Session()
    enriched = []
    for repo in repos:
        topics, summary = fetch_metadata(repo.full_name, token, http)
        enriched.append(dataclasses.replace(repo, topics=tuple(topics), summary=summary))
    return enriched
