"""Web search + page fetch, as a standalone CLI usable as a user-defined tool.

    python -m agentchat.tools.websearch "who won the 2018 world cup"

Why not `curl "https://www.google.com/search?q=..."`:
- Google answers scripted clients with a consent interstitial or a 429, and assembles the
  result list in JavaScript, so the HTML that comes back contains no results to read.
- A raw `{query}` placeholder is spliced into the URL unencoded, so any query with a space
  produces a malformed URL that curl rejects outright.
- A search page is only a list of links; the answer lives on the page behind the first one.

So this uses DuckDuckGo's no-JavaScript HTML endpoint (which returns the results as plain
markup), percent-encodes the query, unwraps DDG's redirect links, and then follows the top
hit and strips it to readable text — the "click the first result" step curl cannot do.

stdlib only: user tools are subprocesses, and adding a dependency for them is not worth it.
"""

from __future__ import annotations

import argparse
import html
import ipaddress
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

SEARCH_URL = "https://html.duckduckgo.com/html/"
# DDG serves the JS-only page to obvious bots; a normal browser UA gets the plain markup.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TIMEOUT = 15
MAX_BYTES = 2_000_000

_RESULT_RE = re.compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SNIPPET_RE = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.S)
_DROP_RE = re.compile(r"<(script|style|noscript|template|nav|header|footer|aside)[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANKS_RE = re.compile(r"\n{3,}")


@dataclass
class Result:
    title: str
    url: str
    snippet: str


class BlockedURL(ValueError):
    """The URL points somewhere this tool will not fetch from."""


def _check_url(url: str) -> None:
    """Refuse anything but public http(s).

    The model chooses the URL, and the tool runs on the developer's own machine, which usually
    sits next to things that answer without authentication: the vLLM server on :8000, the app
    on :8080, a router, a cloud metadata endpoint. Without this check `read_page` is a
    server-side request forgery primitive that the model can aim anywhere. Schemes like
    `file://` would likewise turn it into an arbitrary file reader.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedURL(f"only http and https are allowed, not {parsed.scheme or 'a relative URL'!r}")
    host = parsed.hostname
    if not host:
        raise BlockedURL("no host in the URL")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as e:
        raise BlockedURL(f"could not resolve {host}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise BlockedURL(f"{host} resolves to the non-public address {ip}")


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    """Re-run the check on every hop: a public URL may redirect to a private one."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_GuardedRedirects)


def _get(url: str, data: bytes | None = None) -> str:
    _check_url(url)
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    )
    with _opener.open(request, timeout=TIMEOUT) as response:
        raw = response.read(MAX_BYTES)
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def _text(fragment: str) -> str:
    """Markup fragment -> the words a reader would see."""
    return html.unescape(_TAG_RE.sub("", fragment)).strip()


def _unwrap(href: str) -> str:
    """DDG links go through `//duckduckgo.com/l/?uddg=<encoded target>` — return the target."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def search(query: str, limit: int = 5) -> list[Result]:
    """Top organic results for `query`, most relevant first."""
    body = urllib.parse.urlencode({"q": query}).encode()  # POST: long queries survive intact
    page = _get(SEARCH_URL, data=body)
    snippets = [_text(s) for s in _SNIPPET_RE.findall(page)]
    results = []
    for i, (href, title) in enumerate(_RESULT_RE.findall(page)):
        results.append(Result(_text(title), _unwrap(href), snippets[i] if i < len(snippets) else ""))
        if len(results) == limit:
            break
    return results


def fetch_text(url: str, max_chars: int = 4000) -> str:
    """The readable text of a page, truncated — a model does not need the markup."""
    page = _get(url)
    page = _DROP_RE.sub(" ", page)
    text = html.unescape(_TAG_RE.sub("\n", page))
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    text = _BLANKS_RE.sub("\n\n", text)
    return text[:max_chars] + ("\n[…truncated]" if len(text) > max_chars else "")


def _report(query: str, limit: int, open_first: bool) -> str:
    try:
        results = search(query, limit)
    except (urllib.error.URLError, OSError, BlockedURL) as e:
        return f"[error] search failed: {e}"
    if not results:
        return f"[no results for {query!r}]"

    lines = [f"Search results for {query!r}:"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.title}\n   {r.url}\n   {r.snippet}" if r.snippet else f"{i}. {r.title}\n   {r.url}")
    if open_first:
        top = results[0]
        lines.append(f"\n--- Contents of {top.url} ---")
        try:
            lines.append(fetch_text(top.url))
        except (urllib.error.URLError, OSError, BlockedURL) as e:
            lines.append(f"[could not open the top result: {e}]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search the web and read the top result.")
    parser.add_argument("query", nargs="*", help="search terms (also read from stdin if omitted)")
    parser.add_argument("-n", "--limit", type=int, default=5, help="how many results to list")
    parser.add_argument("--no-open", action="store_true", help="list results without fetching the top page")
    parser.add_argument("--url", help="skip the search and just read this page")
    ns = parser.parse_args(argv)

    if ns.url:
        try:
            print(fetch_text(ns.url))
        except (urllib.error.URLError, OSError, BlockedURL) as e:
            print(f"[error] could not read {ns.url}: {e}")
            return 1
        return 0

    query = " ".join(ns.query).strip() or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
    if not query:
        print("[error] no query given")
        return 2
    print(_report(query, ns.limit, not ns.no_open))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
