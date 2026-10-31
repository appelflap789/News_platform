"""Test setup: a throwaway database and a small fake website served from this machine.

Nothing here touches the internet or the real `data/` folder.
"""

from __future__ import annotations

import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

# Must be set before `backend` is imported: config reads it at import time.
# One fixed folder, reused by every run (each test empties the tables), so runs leave nothing behind to pile up.
os.environ["NSP_DATA_DIR"] = os.path.join(tempfile.gettempdir(), "nsp_tests")
# Set to empty rather than removed: config loads `.env` on import, which would put a real key back, and the
# tests must never reach the real Claude API (or spend money).
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
# The same goes for the two Google keys videos use: no test may reach YouTube's or Gemini's API.
os.environ["YOUTUBE_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
# Embeddings come from a stand-in that counts words, so no test downloads the real model.
os.environ["NSP_EMBEDDER"] = "hash"

import pytest  # noqa: E402

from backend import config, db  # noqa: E402

PUBLICATIONS = [
    ("p1", "Drone swarms and the future of air defence", "2026-09-28",
     "Autonomous drone swarms are changing how small states think about air defence."),
    ("p2", "Klimaatverandering en de energietransitie in Nederland", "2026-09-21",
     "De energietransitie vraagt om nieuwe keuzes rond klimaatverandering en netcapaciteit."),
    ("p3", "Anduril and the new defence industrial base", "2026-09-14",
     "Anduril builds autonomous systems, including the Ghost drone, with venture funding."),
    ("p4", "Semiconductor supply chains after the export controls", "2026-09-07",
     "Export controls on chips reshape supply chains across Europe and Asia."),
    ("p5", "Arctic security and the northern sea route", "2026-08-31",
     "Melting ice opens the northern sea route and raises new security questions."),
    ("p6", "Cyber resilience for critical infrastructure", "2026-08-24",
     "Operators of critical infrastructure face a growing cyber threat."),
]
NEWS = [
    ("a1", "Institute opens new research programme on unmanned systems", "Mon, 05 Oct 2026 09:00:00 +0000"),
    ("a2", "Conference report: climate change adaptation in delta cities", "Fri, 02 Oct 2026 14:30:00 +0000"),
    ("a3", "New fellow joins the technology and security team", "Wed, 30 Sep 2026 08:15:00 +0000"),
]
PER_PAGE = 2
FILLER = (" This paragraph gives the analysis enough length to be recognised as the main text of the page, "
          "with several sentences about the subject, its background and what it means for policy makers.")


def make_pdf(lines: list[str]) -> bytes:
    """A minimal one-page PDF with a text layer."""
    text = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text.encode("latin-1")),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info << /Title (Drone swarms full report) >> >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


PDF = make_pdf([f"Line {n} of the full report on drone swarms and layered air defence for small states."
                for n in range(1, 13)])


def page(title: str, body: str, head: str = "") -> str:
    return (f"<!doctype html><html lang='en'><head><title>{title} | Example Institute</title>"
            f"<meta property='og:site_name' content='Example Institute'>"
            f"<meta name='description' content='Research on security and technology.'>{head}</head>"
            f"<body><header><nav><a href='/'>Home</a><a href='/publications'>Publications</a>"
            f"<a href='/news'>News</a></nav></header>{body}<footer><a href='/contact'>Contact</a></footer>"
            f"<script>window.tracking = 1;</script></body></html>")


def listing(page_number: int) -> str:
    chunk = PUBLICATIONS[page_number * PER_PAGE:(page_number + 1) * PER_PAGE]
    cards = "".join(
        f"<article class='teaser'><a class='teaser__link' href='/publications/{slug}?utm_source=list'>"
        f"<h3 class='teaser__title'>{title}</h3></a><time datetime='{date}'>{date}</time>"
        f"<p class='teaser__summary'>{summary}</p><img src='/img/{slug}.jpg'></article>"
        for slug, title, date, summary in chunk
    )
    more = (page_number + 1) * PER_PAGE < len(PUBLICATIONS)
    pager = f"<a class='pager__next' href='/publications?page={page_number + 1}'>Next</a>" if more else ""
    related = "<aside><a class='related' href='/publications/p6'>Related: cyber</a></aside>"
    return page("Publications", f"<main><h1>Publications</h1><div class='list'>{cards}</div>{pager}</main>{related}")


def publication(slug: str) -> str | None:
    found = next((p for p in PUBLICATIONS if p[0] == slug), None)
    if not found:
        return None
    _, title, date, summary = found
    pdf = "<a class='download' href='/files/p1.pdf'>Download the report (PDF)</a>" if slug == "p1" else ""
    body = (f"<main><article><h1>{title}</h1><span class='byline'>Jane Researcher</span>"
            f"<time datetime='{date}T10:00:00+00:00'>{date}</time>"
            f"<div class='body'><p>{summary}{FILLER}</p><p>Second paragraph.{FILLER}</p>{pdf}</div>"
            f"</article></main>")
    return page(title, body, f"<meta property='og:image' content='/img/{slug}-large.jpg'>")


def news(slug: str) -> str | None:
    found = next((n for n in NEWS if n[0] == slug), None)
    if not found:
        return None
    return page(found[1], f"<main><article><h1>{found[1]}</h1><p>News item text.{FILLER}</p>"
                          f"<p>More detail.{FILLER}</p></article></main>")


# A second section of the fake site, where some items are behind a login or paywall and some are not.
TEASER = ("The ministry announced a new programme for coastal defence on Tuesday, after months of debate in "
          "parliament about its cost and about which shipyards would take part in the work. Officials said the "
          "first contracts would be signed before the end of the year, and that two foreign partners had shown "
          "interest in joining.")
NOT_FREE = '<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [{"@type": ' \
           '"NewsArticle", "headline": "x", "isAccessibleForFree": "False", "hasPart": {"@type": ' \
           '"WebPageElement", "isAccessibleForFree": "False", "cssSelector": ".paywall"}}]}</script>'
PREMIUM = {
    # slug: (title, what its page is)
    "free": ("Coastal defence programme announced", "free"),
    "declared": ("Shipyards compete for the coastal defence contracts", "declared"),
    "gate": ("Foreign partners eye the coastal defence programme", "gate"),
    "login-needed": ("Members' briefing on coastal defence", "login"),
    "forbidden": ("Coastal defence: the documents", 403),
    "busy": ("Coastal defence live blog", 500),
    "long-declared": ("The long read on coastal defence", "long-declared"),
    "free-short": ("Short note on coastal defence", "free-short"),
}


def premium(slug: str) -> str | None:
    if slug not in PREMIUM:
        return None
    title, kind = PREMIUM[slug]
    head, extra = "", ""
    body = f"<p>{TEASER}</p>"
    if kind == "free":
        body += f"<p>Second paragraph.{FILLER}</p>"
    elif kind == "declared":
        head = NOT_FREE
    elif kind == "gate":
        extra = "<div class='paywall'><h3>Subscribe to continue reading</h3><p>Already a subscriber? Log in.</p></div>"
    elif kind == "long-declared":  # marked as paid, and yet the whole text is there
        head = NOT_FREE
        body += "".join(f"<p>Paragraph {n}.{FILLER}</p>" for n in range(16))
    elif kind == "free-short":  # a free note on a site whose every page advertises its subscriptions
        return (f"<!doctype html><html lang='en'><head><title>{title}</title></head><body>"
                f"<header><a href='/subscribe'>Subscribe to read everything</a> Already a subscriber? Log in to "
                f"continue</header><main><article><h1>{title}</h1>{body}</article></main>"
                f"<footer>Become a member to read our archive.</footer></body></html>")
    return page(title, f"<main><article><h1>{title}</h1>{body}{extra}</article></main>", head)


def premium_feed(base: str) -> str:
    items = "".join(
        f"<item><title>{title}</title><link>{base}/premium/{slug}</link>"
        f"<description>Short teaser for {slug}.</description></item>" for slug, (title, _) in PREMIUM.items())
    return (f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>Premium</title>"
            f"<link>{base}/</link><description>Premium</description>{items}</channel></rss>")


def feed(base: str) -> str:
    items = "".join(
        f"<item><title>{title}</title><link>{base}/news/{slug}</link><pubDate>{date}</pubDate>"
        f"<description>Short teaser for {slug}.</description><category>institute</category></item>"
        for slug, title, date in NEWS
    )
    return (f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>Example Institute News"
            f"</title><link>{base}/</link><description>News</description>{items}</channel></rss>")


def sitemap(base: str) -> str:
    urls = [f"{base}/", f"{base}/contact"]
    urls += [f"{base}/publications/{p[0]}" for p in PUBLICATIONS] + [f"{base}/news/{n[0]}" for n in NEWS]
    entries = "".join(f"<url><loc>{u}</loc><lastmod>2026-09-{10 + i:02d}</lastmod></url>" for i, u in enumerate(urls))
    return f"<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>{entries}</urlset>"


class Handler(BaseHTTPRequestHandler):
    hits: list[str] = []

    def log_message(self, *args) -> None:  # keep test output quiet
        pass

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        base = f"http://{self.headers['Host']}"
        Handler.hits.append(self.path)
        path = parts.path
        body: str | bytes | None = None
        kind = "text/html; charset=utf-8"
        if path == "/":
            body = page("Home", "<main><h1>Example Institute</h1><p>Welcome.</p></main>",
                        "<link rel='alternate' type='application/rss+xml' title='News' href='/feed.xml'>"
                        "<link rel='icon' href='/icon.png'>")
        elif path == "/publications":
            body = listing(int(parse_qs(parts.query).get("page", ["0"])[0]))
        elif path.startswith("/publications/"):
            body = publication(path.rsplit("/", 1)[-1])
        elif path.startswith("/news/"):
            body = news(path.rsplit("/", 1)[-1])
        elif path == "/feed.xml":
            body, kind = feed(base), "application/rss+xml"
        elif path == "/premium.xml":
            body, kind = premium_feed(base), "application/rss+xml"
        elif path.startswith("/premium/"):
            slug = path.rsplit("/", 1)[-1]
            answer = PREMIUM.get(slug, ("", 404))[1]
            if isinstance(answer, int):
                self.send_response(answer)
                self.end_headers()
                return
            if answer == "login":
                self.send_response(302)
                self.send_header("Location", f"/login?next={path}")
                self.end_headers()
                return
            body = premium(slug)
        elif path == "/login":
            body = page("Log in", "<main><h1>Log in</h1><form><input name='email'><input name='password'></form></main>")
        elif path == "/sitemap.xml":
            body, kind = sitemap(base), "application/xml"
        elif path == "/robots.txt":
            body, kind = f"User-agent: *\nDisallow: /private/\nSitemap: {base}/sitemap.xml\n", "text/plain"
        elif path == "/files/p1.pdf":
            body, kind = PDF, "application/pdf"
        elif path == "/private/secret":
            body = page("Secret", "<main><p>Not for crawlers.</p></main>")
        elif path in ("/walled", "/walled/feed"):  # every page of the site is Imperva's bot check
            body = ('<html>\n<head>\n<META NAME="robots" CONTENT="noindex,nofollow">\n<script src="/_Incapsula_'
                    'Resource?SWJIYLWA=5074a744e2e3d891814e9a2dace20bd4,719d34d31c8e3a6e6fffd425f7e032f3">\n'
                    '</script>\n<body>\n</body></html>')
        elif path == "/js-only":
            body = "<!doctype html><html><head><title>App</title></head><body><div id='root'></div>" \
                   "<script src='/app.js'></script></body></html>"
        elif path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/publications")
            self.end_headers()
            return
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="session")
def site() -> str:
    """Base URL of the fake website."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(autouse=True)
def clean_state():
    """Every test starts with empty tables and test-friendly scraping settings."""
    db.init()
    for table in ("articles", "sources", "topics", "jobs", "settings", "removed"):
        db.execute(f"DELETE FROM {table}")
    config.reset_cache()
    # Matching by meaning is off unless a test switches it on: the older tests are about words.
    config.update({"block_private_hosts": False, "request_delay_seconds": 0, "meaning_enabled": False})
    Handler.hits.clear()
    from backend.connectors import connectors

    connectors.get("reddit").forget()  # it keeps listing pages for a while
    from backend.search import embed

    embed.forget()
    yield


class FakeJob:
    """Stands in for jobs.Job where a test calls pipeline code directly."""

    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []
        self.usage: dict = {}

    def log(self, message: str, level: str = "info") -> None:
        self.logs.append((level, message))

    def progress(self, *args, **kwargs) -> None:
        pass

    def check_cancelled(self) -> None:
        pass

    def text(self) -> str:
        return "\n".join(message for _, message in self.logs)


@pytest.fixture
def job() -> FakeJob:
    return FakeJob()
