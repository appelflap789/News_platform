"""Try a site scraper from the command line.

    python -m backend.scrapers list
    python -m backend.scrapers test <name> [--pages 2] [--items 4] [--stream KEY]
    python -m backend.scrapers add <name>

`test` runs the scraper against the live site exactly as a scrape would, prints what it finds and stores
nothing. `add` puts the scraper in the library as a source (the dashboard's Add source page does the same).
"""

from __future__ import annotations

import argparse
import sys

from .. import db
from ..connectors import Context, connectors
from ..errors import ScrapeError
from ..pipeline.scrape import build_article
from ..util import truncate
from . import scrapers
from ._sources import add_source, describe_all, recipe_for

LISTED_FIELDS = ("title", "author", "published", "summary", "image_url")
STORED_FIELDS = ("title", "author", "published_at", "summary", "text", "image_url", "pdf_url")


def _fill(label: str, rows: list[dict], fields: tuple[str, ...]) -> None:
    if rows:
        counts = ", ".join(f"{name} {sum(1 for row in rows if row.get(name))}/{len(rows)}" for name in fields)
        print(f"  {label}: {counts}")


def _spread(items: list, count: int) -> list:
    """`count` items from across the list, so the oldest page listed is sampled as well as the newest."""
    if len(items) <= count:
        return items
    step = (len(items) - 1) / max(count - 1, 1)
    return [items[round(index * step)] for index in range(count)]


def run_list() -> int:
    for entry in describe_all():
        state = f"source {entry['source_id']}" if entry["source_id"] else "not added"
        streams = ", ".join(stream["name"] for stream in entry["streams"])
        print(f"{entry['name']:<20} {entry['label']:<28} {state:<12} {streams}")
    return 0


def run_test(name: str, stream_key: str, pages: int, items: int) -> int:
    scraper = scrapers.get(name)
    recipe = recipe_for(scraper)
    connector = connectors.get("scraper")
    ctx = Context()
    feeds = [feed for feed in recipe.feeds if (feed.opt("stream") == stream_key if stream_key else feed.enabled)]
    if not feeds:
        print(f"'{name}' has no stream '{stream_key}'." if stream_key else f"'{name}' has no enabled stream.")
        return 1
    failures = 0
    for feed in feeds:
        print(f"\n=== {scraper.label} / {feed.name} ===\n{feed.url}\n")
        listed = []
        try:
            for index, page in enumerate(connector.iter_pages(feed, ctx)):
                print(f"  page {index + 1}: {len(page.items)} items  {page.url}  {page.diagnostics or ''}")
                listed.extend(page.items)
                if index + 1 >= pages:
                    break
        except ScrapeError as error:
            print(f"  LISTING FAILED: {error}")
            failures += 1
        if not listed:
            print("  The listing returned no items.")
            failures += 1
            continue
        print(f"\n  {len(listed)} items listed, {len({item.url for item in listed})} different URLs")
        _fill("listing gives", [vars(item) for item in listed], LISTED_FIELDS)
        for item in listed[:3] + listed[-1:]:
            print(f"    {truncate(item.title, 70):<70}  {item.url}")

        articles = []
        for item in _spread(listed, items):
            print(f"\n  --- {item.url}")
            try:
                article = build_article(feed, item, recipe, connector, ctx)
            except ScrapeError as error:
                print(f"  FAILED: {error}")
                failures += 1
                continue
            articles.append(article)
            for key in ("title", "author", "published_at", "content_type", "language", "tags", "image_url",
                        "pdf_url"):
                print(f"  {key:<13} {article[key]}")
            print(f"  {'summary':<13} {truncate(article['summary'], 200)}")
            print(f"  {'text':<13} {len(article['text']):,} characters, {article['word_count']:,} words"
                  f"{'  (PARTIAL: ' + article['partial_reason'] + ')' if article['partial_reason'] else ''}"
                  f"{'  (BEHIND A LOGIN OR PAYWALL: ' + article['wall'] + ')' if article['wall'] else ''}")
            print(f"  {'  starts':<13} {truncate(article['text'], 300)!r}")
            if len(article["text"]) > 800:
                print(f"  {'  ends':<13} {article['text'][-200:]!r}")
        print()
        _fill("stored items would have", articles, STORED_FIELDS)
    return 1 if failures else 0


def run_add(name: str) -> int:
    scraper = scrapers.get(name)
    existing = next((entry["source_id"] for entry in describe_all() if entry["name"] == name), None)
    if existing:
        print(f"'{name}' is already in the library as source {existing}.")
        return 0
    print(f"Added '{scraper.label}' as source {add_source(scraper)}. "
          f"Restart the platform if it is running, then open the source and press Update or Deep scrape.")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # titles are not limited to the console's code page
    parser = argparse.ArgumentParser(prog="python -m backend.scrapers", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="the scrapers in backend/scrapers/")
    test = commands.add_parser("test", help="run a scraper against the live site without storing anything")
    test.add_argument("name")
    test.add_argument("--stream", default="", help="only this stream (default: every enabled stream)")
    test.add_argument("--pages", type=int, default=2, help="listing pages to walk (default 2)")
    test.add_argument("--items", type=int, default=4, help="items to open and read (default 4)")
    add = commands.add_parser("add", help="add a scraper to the library as a source")
    add.add_argument("name")
    args = parser.parse_args()

    db.init()
    if args.command != "list" and args.name not in scrapers.names():
        print(f"There is no scraper called '{args.name}'. Available: {', '.join(scrapers.names()) or 'none'}")
        return 1
    if args.command == "list":
        return run_list()
    if args.command == "test":
        return run_test(args.name, args.stream, args.pages, args.items)
    return run_add(args.name)


if __name__ == "__main__":
    sys.exit(main())
