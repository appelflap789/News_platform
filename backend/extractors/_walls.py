"""Telling that a page keeps its text behind a login or a paywall.

Nothing here gets past such a wall. It only recognises one, so that a source can be told to leave those items
out instead of storing the few lines in front of the wall (`sources.skip_walled`, see pipeline/scrape.py).

A page counts as walled when one of these is true:

* the address the download ended on is a login page;
* the page says of itself that it is not free (schema.org `isAccessibleForFree: false`, which publishers add
  for search engines, or the `article:content_tier` meta tag) and shows only a short text;
* the page shows only a short text and, outside its header and footer, asks to log in or subscribe in order
  to read on.

"A short text" is the important half of the last two. A site with a paywall says "subscribe" on every page,
also on the free ones, and a publisher may mark an article as paid and still show all of it.

Checked in October 2026 against 81 pages from a real library that could be opened: none of the 74 that were
readable was called walled, and seven openings of paid articles that had been stored as if they were whole were
recognised, all by what the page says of itself (Süddeutsche Zeitung, Tagesspiegel, Der Spiegel, Le Monde,
EUobserver, The Africa Report, Turkey Recap).
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..util import word_count

# A text of this many words or more was readable, whatever the page asks for underneath it.
SHORT_WORDS = 250
# When the page itself says it is not free, more is needed to believe the whole text is there: the openings
# that paid articles show run to 250 words and more (Der Spiegel showed 253 of an interview).
SHORT_WORDS_NOT_FREE = 400
LOGIN_SEGMENTS = {
    "login", "log-in", "signin", "sign-in", "inloggen", "aanmelden", "anmelden", "einloggen", "connexion",
    "sso", "oauth", "authorize", "paywall",
}
# What a page says when the rest of the text is behind a wall. Each asks for a login or a subscription *in
# order to read*: "subscribe" or "log in" alone are on every page of a news site.
GATE_PHRASES = (
    # English
    "subscribe to continue", "subscribe to read", "subscribe to keep reading", "subscribe now to read",
    "to continue reading", "to keep reading", "to read the full article", "to read the full story",
    "to read this article", "to read the rest", "this article is for subscribers", "for subscribers only",
    "subscribers only", "subscriber-only", "exclusive to subscribers", "already a subscriber", "log in to read",
    "sign in to read", "log in to continue", "sign in to continue", "register to read", "register to continue",
    "create a free account to", "become a member to", "this content is for members", "unlock this article",
    "unlock this story",
    # Dutch
    "om verder te lezen", "verder lezen met", "lees verder met", "lees dit artikel met", "alleen voor abonnees",
    "exclusief voor abonnees", "dit artikel is alleen", "al abonnee", "word abonnee om", "log in om",
    "inloggen om", "neem een abonnement", "met een abonnement lees",
    # German
    "weiterlesen mit", "jetzt weiterlesen", "um weiterzulesen", "nur für abonnenten", "für abonnenten",
    "bereits abonnent", "sie sind bereits abonnent", "anmelden und weiterlesen", "artikel freischalten",
    "mit einem abo weiterlesen",
    # French
    "réservé aux abonnés", "réservé à nos abonnés", "article réservé", "pour lire la suite",
    "la suite de cet article est réservée", "abonnez-vous pour lire", "déjà abonné",
)
OUTSIDE_THE_ARTICLE = ("script", "style", "noscript", "template", "header", "nav", "footer")


def on_page(url: str, soup: BeautifulSoup, text: str) -> str:
    """Why this page looks walled, in words for the user, or '' when it does not.

    `url` is where the download ended after redirects, `text` the main text that was taken from the page.
    """
    segments = {segment.lower() for segment in urlsplit(url).path.split("/") if segment}
    if segments & LOGIN_SEGMENTS:
        return "its address leads to a login page"
    words = word_count(text)
    if words >= SHORT_WORDS_NOT_FREE:
        return ""
    if _says_not_free(soup):
        return f"the page says it is for subscribers and shows {words} words"
    if words >= SHORT_WORDS:
        return ""
    phrase = _gate_phrase(soup)
    if phrase:
        return f'the page shows {words} words and then asks to log in or subscribe ("{phrase}")'
    return ""


def _says_not_free(soup: BeautifulSoup) -> bool:
    """What the page declares about itself. `isAccessibleForFree` is the more precise statement: one "false"
    anywhere means a part of the item is paid (the free part of a paid article is marked "true"), and when it
    only says "true" that stands, also on a site whose every page carries content_tier "locked"."""
    said: list[bool] = []
    for marked in soup.find_all(attrs={"itemprop": "isAccessibleForFree"}):
        said.append(_truth(marked.get("content", marked.get_text())))
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            _collect(json.loads(script.string or script.get_text() or ""), said)
        except (ValueError, TypeError):
            continue
    if False in said:
        return True
    if True in said:
        return False
    tier = soup.find("meta", attrs={"property": "article:content_tier"}) or soup.find(
        "meta", attrs={"name": "article:content_tier"})
    return bool(tier) and str(tier.get("content", "")).strip().lower() == "locked"


def _truth(value) -> bool | None:
    """true, "False", "http://schema.org/False": publishers write it all three ways."""
    word = str(value).strip().lower().rstrip("/").rsplit("/", 1)[-1]
    return True if word == "true" else False if word == "false" else None


def _collect(data, said: list, depth: int = 0) -> None:
    """Every isAccessibleForFree in this JSON-LD, however deep."""
    if depth > 8:
        return
    if isinstance(data, list):
        for entry in data:
            _collect(entry, said, depth + 1)
    elif isinstance(data, dict):
        if "isAccessibleForFree" in data:
            said.append(_truth(data["isAccessibleForFree"]))
        for value in data.values():
            if isinstance(value, (dict, list)):
                _collect(value, said, depth + 1)


def _gate_phrase(soup: BeautifulSoup) -> str:
    """The first phrase on the page, outside its header, navigation and footer, that asks for a login or a
    subscription in order to read on."""
    body = BeautifulSoup(str(soup.body or soup), "lxml")  # a copy: the caller still needs the page whole
    for tag in body.find_all(OUTSIDE_THE_ARTICLE):
        tag.decompose()
    visible = re.sub(r"\s+", " ", body.get_text(" ")).lower()
    return next((phrase for phrase in GATE_PHRASES if phrase in visible), "")
