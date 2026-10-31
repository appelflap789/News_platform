"""Quick detect: builds a recipe from what a site advertises (feeds, sitemaps). No AI, no cost."""

from __future__ import annotations

from urllib.parse import urlsplit

from ..connectors import Context
from ..errors import ScrapeError
from ..jobs import Job
from ..pipeline.scrape import preview_article
from ..schemas import FeedRecipe, Recipe
from ..util import truncate
from ._prescan import Prescan, prescan
from .base import Analysis, Analyzer, analyzers, make_previews


REDDIT_REPORT = """\
**Reddit** is read through its public feeds, so there is nothing to analyse. Two feeds are set up for `{name}`.
*Shared articles* is switched on and *Posts and comments* is off; use the switch on each feed below to change
that. Both can be on.

- **Shared articles.** Only the posts that share an article. The article itself is opened on the site it comes
  from and its text is stored here, under the title and date of the post, with a closing line that says who
  shared it and links to the discussion. Text, picture and video posts are skipped. When the article's site
  turns the scraper away or sits behind a paywall, the item is kept with what the post itself said and marked
  as partial.
- **Posts and comments.** Every post: its own text, the link it shares, and its 30 highest-voted comments.
  Replies to comments are left out, because Reddit's feed does not say which comment a reply belongs to.

**Speed.** Reddit allows about one request a minute. A page of 25 posts is one request, so *Shared articles*
is quick. *Posts and comments* needs one more request for every post, so it collects about one post a minute.

**Comments are a snapshot** of the moment a post is scraped; they are not refreshed afterwards. For discussions
that have had time to form, point the feed at `…/top/?t=day` or `…/top/?t=week`.

A plain subreddit address lists what is *hot*; add `/new` to the feed's address for strictly newest first.
Reddit's listings go back about 1,000 posts, which is as far as a deep scrape can reach. The number of comments,
and whether *Shared articles* carries comments too, is under each feed's *Connector settings*."""


YOUTUBE_REPORT = """\
**YouTube** is read through its own doors, so there is nothing to analyse. One feed is set up for `{name}`.

- **With a YouTube API key** (Settings) every video the channel uploaded is listed, fifty to a page, with its
  length and number of views. An *Update* looks at the newest page; a *Deep scrape* walks the whole channel{count}.
- **Without a key** the channel's public feed is read: its 15 newest videos. Older ones cannot be reached.

Each video is stored with its title, upload date, description, length and views, and plays in the reader.

**What is said in a video.** YouTube's API gives a transcript only to the owner of a video, so that is done by
Google's Gemini API, which can read a public video (it needs a Gemini API key in Settings). Claude then turns
the transcript into an article with headings, a summary and tags, and that article is what search, topics and
"More like this" work with. A run does a set number of videos, the newest first; the rest wait for the next
run or for the button on the Settings tab. Without a Gemini key a video keeps its description as its text.
"""


def youtube_recipe(url: str, ctx: Context) -> Recipe:
    """The recipe for a YouTube channel, given the channel's address or the address of one of its videos."""
    from ..connectors import youtube

    about = youtube.describe(url, ctx)
    count = f" ({about['videos']:,} videos)" if about["videos"] else ""
    return Recipe(
        site_name=about["name"], homepage=about["homepage"], icon_url=about["icon_url"],
        description=about["description"][:300] or f"The videos of {about['name']} on YouTube.",
        feeds=[FeedRecipe(name="Videos", connector="youtube", url=about["homepage"], content_type="video")],
        structure_report=YOUTUBE_REPORT.format(name=about["name"], count=count),
    )


PODCAST_REPORT = """\
**A podcast** is published as a feed, and that feed is what is read. Spotify was only asked which show this
is; the show's own feed was then found in Apple's podcast directory:

`{feed}`

It carries {episodes} episodes. Each is stored with its title, date, length and description, and plays in the
reader. An *Update* looks at the newest ones.

**What is said in an episode.** Spotify gives out neither the audio nor a transcript, so the audio file the
feed offers is downloaded and written out by Google's Gemini API (it needs a Gemini API key in Settings), unless
the feed carries the publisher's own transcript. Claude then turns the transcript into an article with headings,
a summary and tags, and that article is what search, topics and "More like this" work with. A run does a set
number of episodes, the newest first; the rest wait for the next run or for the button on the Settings tab.
Without a Gemini key an episode keeps its description as its text.
"""


def podcast_recipe(url: str, ctx: Context) -> Recipe:
    """The recipe for a podcast, given the Spotify address of the show or of one of its episodes."""
    from ..connectors import podcast

    about = podcast.describe(url, ctx)
    return Recipe(
        site_name=about["name"], homepage=about["homepage"], icon_url=about["icon_url"],
        description=about["description"][:300] or f"The podcast {about['name']}.",
        feeds=[FeedRecipe(name="Episodes", connector="podcast", url=about["feed"], content_type="podcast")],
        structure_report=PODCAST_REPORT.format(feed=about["feed"], episodes=about["episodes"]),
    )


def recipe_from_prescan(scan: Prescan) -> Recipe:
    recipe = Recipe(
        site_name=scan.site_name,
        homepage=scan.homepage,
        description=scan.description,
        language=scan.language,
        icon_url=scan.icon_url,
    )
    report: list[str] = []
    if scan.kind == "reddit":
        path = urlsplit(scan.url).path.strip("/")
        name = "/".join(path.split("/")[:2]) or "reddit"
        recipe.site_name = name
        recipe.homepage = "https://www.reddit.com/" + "/".join(path.split("/")[:2])
        recipe.description = f"Posts from {name} on Reddit."
        recipe.icon_url = "https://www.reddit.com/favicon.ico"
        recipe.feeds.append(FeedRecipe(name="Shared articles", connector="reddit", url=scan.url,
                                       content_type="article", options={"collect": "articles"}))
        recipe.feeds.append(FeedRecipe(name="Posts and comments", connector="reddit", url=scan.url,
                                       content_type="post", enabled=False,
                                       options={"collect": "posts", "comments": "30"}))
        report.append(REDDIT_REPORT.format(name=name))
    elif scan.kind == "pdf":
        recipe.feeds.append(FeedRecipe(name="Document", connector="single", url=scan.final_url,
                                       content_type="document"))
        report.append("This address is a single **PDF document**. It is stored as one item; add more document "
                      "addresses under *Extra URLs* in the feed's settings.")
    elif scan.kind == "sitemap":
        recipe.feeds.append(FeedRecipe(name="Sitemap", connector="sitemap", url=scan.final_url, enabled=False))
        report.append("This address is an **XML sitemap**: a list of every page of the site. The feed is switched "
                      "off until you give it a *URL pattern* that selects the article pages; otherwise every page "
                      "would be scraped as an article.")
    else:
        for index, found in enumerate(scan.feeds):
            title = truncate(found["title"], 60) or f"Feed {index + 1}"
            name = title if title not in {f.name for f in recipe.feeds} else f"{title} ({index + 1})"
            recipe.feeds.append(FeedRecipe(name=name, connector="rss", url=found["url"],
                                           content_type="news", fetch_detail=not found["full_content"]))
        if scan.feeds:
            report.append(f"Found **{len(scan.feeds)} feed(s)** advertised by the site:")
            report.extend(
                f"- `{f['url']}` - {f['entries']} entries, newest {f['latest'][:10] or 'unknown'}"
                + (" (carries the full text)" if f["full_content"] else "")
                for f in scan.feeds
            )
            report.append("\nFeeds give the latest items only. If this source has an archive of publications you "
                          "want, run **Claude analysis** to map its listing pages and pagination.")
        else:
            report.append("**No feed found.** Quick detect only recognises RSS/Atom feeds and sitemaps. "
                          "Run **Claude analysis** to work out this site's listing pages.")
            if scan.sitemaps:
                recipe.feeds.append(FeedRecipe(name="Sitemap", connector="sitemap", url=scan.sitemaps[0],
                                               enabled=False))
                report.append(f"\nA sitemap exists (`{scan.sitemaps[0]}`) and is added switched off: it needs a "
                              "*URL pattern* selecting the article pages before it is useful.")
    recipe.structure_report = "\n".join(report)
    return recipe


@analyzers.register
class HeuristicAnalyzer(Analyzer):
    name = "heuristic"
    label = "Quick detect"
    description = ("No AI. Finds RSS/Atom feeds and sitemaps the site advertises; understands Reddit, YouTube "
                   "channels, podcasts on Spotify and PDF links.")
    requires_ai = False

    def analyze(self, url: str, hint: str, job: Job, ctx: Context) -> Analysis:
        job.log(f"Opening {url}")
        scan = prescan(url, ctx, job)
        if scan.kind == "youtube":
            job.log("YouTube is supported natively - looking up the channel.")
            recipe = youtube_recipe(url, ctx)
        elif scan.kind == "podcast":
            job.log("A podcast is read from its own feed - looking up the show and its feed.")
            recipe = podcast_recipe(url, ctx)
        else:
            job.log(f"Found {len(scan.feeds)} feed(s), {len(scan.sitemaps)} sitemap(s).")
            recipe = recipe_from_prescan(scan)
        job.log("Sampling each feed…")
        if scan.kind == "reddit":
            job.log("Reddit allows about one request a minute, so this can take that long.")
        previews = make_previews(recipe, ctx, job)
        notes = []
        if scan.blocked:
            notes.append(f"The page itself could not be opened ({scan.blocked}), but the site's feed is reachable.")
        for feed in recipe.feeds:
            sample = (previews.get(feed.name, {}).get("items") or [{}])[0].get("url")
            if feed.connector != "rss" or not feed.fetch_detail or not sample:
                continue
            try:
                preview_article(sample, recipe.article, ctx)
            except ScrapeError as error:
                feed.fetch_detail = False
                notes.append(f"**{feed.name}**: article pages cannot be read ({error}). Only the text the feed "
                             "itself carries (usually a summary) will be stored; each item links to the original.")
        if notes:
            recipe.structure_report += "\n\n" + "\n\n".join(notes)
        return Analysis(recipe=recipe, previews=previews)
