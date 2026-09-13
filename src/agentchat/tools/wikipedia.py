"""Wikipedia lookup as a standalone CLI, usable as a user-defined tool.

    python -m agentchat.tools.wikipedia "turing machine"

Not the `wikipedia` PyPI package: a tool subprocess runs under the app's interpreter, so a
third-party import only works if it was installed into the app environment — and that package
has been unmaintained since 2014 and breaks against current BeautifulSoup. The MediaWiki API
answers the same question over stdlib `urllib` with no dependency at all.

`action=query&prop=extracts&explaintext` resolves a loose title through Wikipedia's own
normalisation and redirects and returns plain text, so one request covers the usual
"search, pick the best match, read the intro" sequence. `--search` lists candidates instead
when the title is too vague to resolve.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://{lang}.wikipedia.org/w/api.php"
# The API asks clients to identify themselves; anonymous scripted traffic gets rate-limited.
USER_AGENT = "agentchat/0.1 (local course project; https://github.com/)"
TIMEOUT = 15
MAX_TOPIC_CHARS = 300
# `lang` is the only part of the URL that is not a query parameter, so it is the only way a
# caller could steer the request off wikipedia.org — "evil.com/?x=" as a language would build
# a URL pointing somewhere else entirely. Language codes are short and alphabetic; enforce it.
_LANG_RE = re.compile(r"^[a-z]{2,10}(-[a-z0-9]{2,10})?$")


def _api(lang: str, **params: str) -> dict:
    if not _LANG_RE.match(lang):
        raise ValueError(f"{lang!r} is not a Wikipedia language code")
    query = urllib.parse.urlencode({"format": "json", "formatversion": "2", **params})
    url = f"{API.format(lang=lang)}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def summary(title: str, lang: str = "en", intro_only: bool = True) -> tuple[str, str] | None:
    """Return (resolved title, plain text) for `title`, or None if there is no such page."""
    params = {
        "action": "query",
        "prop": "extracts",
        "explaintext": "1",
        "redirects": "1",
        "titles": title,
    }
    if intro_only:
        params["exintro"] = "1"
    pages = _api(lang, **params).get("query", {}).get("pages", [])
    for page in pages:
        if "missing" not in page and page.get("extract", "").strip():
            return page["title"], page["extract"].strip()
    return None


def search(query: str, lang: str = "en", limit: int = 5) -> list[tuple[str, str]]:
    """Candidate (title, snippet) pairs for a query that does not resolve to a page."""
    hits = _api(lang, action="query", list="search", srsearch=query, srlimit=str(limit))
    results = []
    for hit in hits.get("query", {}).get("search", []):
        snippet = re.sub(r"<[^>]+>", "", hit.get("snippet", ""))
        results.append((hit["title"], html.unescape(snippet)))
    return results


def _report(topic: str, lang: str, intro_only: bool, max_chars: int) -> str:
    found = summary(topic, lang, intro_only)
    if found is None:
        # An exact-title miss is common ("who was ada lovelace"); fall back to the search index.
        candidates = search(topic, lang)
        if not candidates:
            return f"[no Wikipedia article for {topic!r}]"
        best = candidates[0][0]
        found = summary(best, lang, intro_only)
        if found is None:
            listing = "\n".join(f"- {t}: {s}" for t, s in candidates)
            return f"[no article for {topic!r}; closest matches:]\n{listing}"

    title, text = found
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[…truncated]"
    url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
    return f"{title} — {url}\n\n{text}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Look a topic up on Wikipedia.")
    parser.add_argument("topic", nargs="*", help="article title or topic (also read from stdin)")
    parser.add_argument("--lang", default="en", help="Wikipedia language edition")
    parser.add_argument("--full", action="store_true", help="whole article instead of the intro")
    parser.add_argument("--search", action="store_true", help="list matching articles instead of reading one")
    parser.add_argument("--max-chars", type=int, default=4000, help="truncate the article at this length")
    ns = parser.parse_args(argv)

    topic = " ".join(ns.topic).strip() or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
    if not topic:
        print("[error] no topic given")
        return 2
    topic = topic[:MAX_TOPIC_CHARS]  # an article title is short; anything longer is a mistake

    try:
        if ns.search:
            results = search(topic, ns.lang)
            print("\n".join(f"- {t}: {s}" for t, s in results) or f"[no matches for {topic!r}]")
        else:
            print(_report(topic, ns.lang, not ns.full, ns.max_chars))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"[error] Wikipedia lookup failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
