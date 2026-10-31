# News Scraper Platform

A personal dashboard that collects news, reports, papers and forum posts from any source you plug in, and lets you read them in one place and follow topics across all of them.

The idea in one sentence: **you give an address, Claude works out how that source is built and writes a reusable "recipe", and from then on the platform scrapes it without AI.**

- [Start](#start)
- [Using the dashboard](#using-the-dashboard)
- [How plugging in a source works](#how-plugging-in-a-source-works)
- [Videos and single items](#videos-and-single-items)
- [Built scrapers](#built-scrapers)
- [How it is built (the modular part)](#how-it-is-built)
- [Extending it](#extending-it)
- [Recipe reference](#recipe-reference)
- [Topics and search](#topics-and-search)
- [Where Claude is used, and what it costs](#where-claude-is-used-and-what-it-costs)
- [Data and API](#data-and-api)
- [Rules the scraper follows](#rules-the-scraper-follows)
- [Tests](#tests)
- [Known limits](#known-limits)
- [Developing the dashboard](#developing-the-dashboard)

---

## Start

Double-click **`start.bat`**. It starts the platform and opens `http://127.0.0.1:8765` in your browser. Close the window (or press Ctrl+C) to stop it.

The Python environment lives in `.venv` inside this folder and is already set up. If that folder is ever missing, `start.bat` rebuilds it from `requirements.txt` on the next start. `start.bat` does not install what is added to `requirements.txt` later; after such a change run `.venv\Scripts\python.exe -m pip install -r requirements.txt` once.

**The embedding model.** Search and topics also work by meaning (see [Topics and search](#topics-and-search)). The model for that runs on this computer and is kept in `data/models` (about 240 MB). If that folder is missing it is downloaded on the next start, which needs internet once.

**Claude API key.** Open **Settings** in the dashboard and paste an Anthropic API key (create one at <https://console.anthropic.com/settings/keys>). It is saved to `.env` in this folder and never shown again. Without a key everything except the Claude features works: you can add sources with *Quick detect*, scrape, search and build topics by hand.

Manual start, if you prefer: `.venv\Scripts\python.exe run.py` (add `--no-browser` to not open a browser).

If a start ever fails with *"An Application Control policy has blocked this file"*, start it again. Windows was still checking a newly installed file; it happened once here, right after installation, and not again.

---

## Using the dashboard

The sidebar on the left is the list of pages.

| Page | What it is for |
|---|---|
| **Home** | Shelves, as on YouTube: your **topics** as cards (see [Topics on Home](#topics-on-home)), your **favorites** (two rows), and the **latest items** (two rows; *Show more* opens the whole feed, newest first). The search box finds items that contain your words (all of them; `"quoted words"` must appear together) and items that are about the same thing in other words or another language; those carry a *by meaning* mark. Searching, or picking a kind of content, turns the page into the results. Point at a card and a star and a bin appear: the star adds it to [Favorites](#favorites), the bin [removes the item](#removing-items) from your library. |
| **Topics → a topic** | A page per subject, described under [The topic page](#the-topic-page): *What is new*, *The long run*, a timeline, a trend, the sources, and *Up next*. `←` and `→` flip to the previous and the next topic. |
| **Topics → New topic** | Name a topic, say in a sentence what it is about, let Claude suggest terms (or type them; they are in English, plus translations only into a language that at least 5% of your library, and ten items, is really written in: a translated item counts as English), see the count update live, save. |
| **Sources → a source** | The source's own page, laid out like a channel. Tabs: **Items** (its cards), **Structure** (how the site is built, its feeds, the recipe editor, re-analysis), **Settings** (automatic updates, leaving out items behind a login or paywall, AI summary and tags, delete). Buttons: **Update** (fetch what is new), **Deep scrape** (walk back through the archive, as far as you say: until the source has so many items, or all of it) and, when some of its items are not in English, **Translate N items** (see *Translation to English*). |
| **Sources → Add source** | First a box to [save one page or one video](#videos-and-single-items) by its address. Then the three-step wizard described in the next section, which also takes a YouTube channel. Below it: the [built scrapers](#built-scrapers), added with one click. |
| **Activity** | Every analysis, scrape, embedding run and topic text that ran, with its log and what Claude cost. |
| **Settings** | The Anthropic key, the two optional Google keys that videos use, how many items have an embedding, models, scraping behaviour, and the list of installed plugins. |
| **Removed items** | What you [took out of your library](#removing-items) yourself, the last one first, each with **Put back**. |
| **Favorites** | The items you starred, the last one first. Home shows the first two rows of them. |

The **Sources** heading in the sidebar has a small menu: all sources, only the ones that collect articles, or only the ones that collect videos.

Clicking a card opens the **reader**, a panel that slides over the page. `Esc` closes it, `←` and `→` step through the list you opened it from, and `Delete` (or the bin at the top) [removes the item](#removing-items) and shows the next one. *Open original* goes to the source; *PDF* appears when the item has one. A video plays at the top of the reader, with its length and views, and can be read as an article or as a transcript. An address ending in `?article=12` opens that item directly. An item that came from Reddit has a **Summarise comments** button (see [What the comments say](#what-the-comments-say)). Under the text the reader lists your **topics** (a click puts the item in a topic or takes it out) and **More like this**: the items closest to it in meaning.

### Favorites

The star on a card (it shows when you point at the card, and stays when it is on) or at the top of the reader adds an item to **Favorites**; clicking it again takes it out. Favorites have a shelf on Home, two rows, the last one you starred first, and a page of their own in the sidebar. A favorite stays a favorite when you remove it and put it back.

### Removing items

Every card has a bin (it shows when you point at the card), on Home, on a source's page and on a topic's page, and so has the reader. One click takes the item out of your library: out of the feed, the search and every topic. There is no question first; the message that appears has **Undo**.

- **A scrape does not bring it back.** The item's address is remembered. A source that still lists it treats it as known: its page is not opened and nothing is stored, on an update and on a deep scrape alike, and the scrape's log says how many such items it passed. This holds for every source, and also after you delete the source and add it again.
- **Put back returns it as it was.** The removed item is kept, with its translation, AI summary, transcript and embedding, so putting it back costs nothing and asks nothing of Claude. Do it with **Undo**, or later on the **Removed items** page (in the sidebar under *Platform*; Home links to it once something is removed). Saving a removed item again by its address, with *Save one page or video*, puts it back too.
- **When its source is gone.** Deleting a source also drops the kept copies of what you removed from it; the addresses stay remembered. Such an entry says so, and its button is **Let in again**: the address is forgotten, and a source that lists the item collects it at its next scrape.

This is something else than *Not this* on a topic's timeline, which takes an item out of that one topic and leaves it in your library. It is also not the list of items a source [left out](#items-behind-a-login-or-paywall) because their page could not be read: that list is the scraper's, this one is yours.

---

## How plugging in a source works

```
 address ──► ANALYZER ──► RECIPE ──► (you review it) ──► SCRAPER ──► items in the library
              Claude        JSON                           no AI
              or Quick
              detect
```

**1. Address.** A homepage, a publications page, an RSS feed, a subreddit, or a PDF. Optionally say what you want from it ("only reports and papers").

**2. Analysis.** Two analyzers are installed:

- **Claude analysis** (`backend/analyzers/claude_agent.py`). Claude is given four tools and works in a loop:
  - `fetch_page` returns a *digest* of a page: scripts and styling removed, repeated elements collapsed to the first three, plus the navigation links and the most common link paths. A 1 MB listing page becomes about 9 KB, which keeps the analysis cheap. Claude can zoom into one region with a CSS selector.
  - `test_feed` runs a feed configuration against the live site and returns the items it finds, so Claude sees whether its selectors and pagination work.
  - `test_article` runs the extraction on one item page.
  - `submit_recipe` hands in the result. A recipe containing a feed that was never tested, or that returned nothing, is pushed back once.

  Claude also writes the **structure report** you see on the review step and on the source's Structure tab: what the site is, how its content is organised, what it chose to scrape and what stands in the way.
- **Quick detect** (`backend/analyzers/heuristic.py`). No AI and no cost. Finds the RSS/Atom feeds and sitemaps a site advertises, and understands [Reddit](#reddit) and direct PDF links. It cannot work out listing pages and pagination; that is what Claude analysis is for.

**3. Review.** You see the structure report, every feed with a live sample of what it finds, and the recipe itself. Everything is editable, and each feed has a **Test** button. Then *Save and start scraping*.

After that, **scraping uses no AI**. A scrape lists each feed, skips what is already stored, opens the new items, extracts title, date, author, text, image and PDF, and stores them. An *Update* stops as soon as a listing page has nothing new; a *Deep scrape* keeps going into the archive.

**How many the first scrape takes** is asked on the wizard's last step, under *Options*: *How many to collect now*, the newest so many. It is filled in with 20 for a YouTube channel or a podcast, which can hold hundreds (with a YouTube API key a channel is listed fifty to a page, and a first scrape that takes three pages brings 150), and left empty for other sources, which then take the first listing pages as set in Settings. A channel or a podcast lists its items strictly newest first, so an update of one stops at the first video or episode it already has: the ones below it that were never collected stay out, until a *Deep scrape* is asked to go back for them.

**How far a deep scrape goes** is yours to say. The button first asks *How far back?*: **go back until the source has so many items**, with a number to type or pick (it suggests the next round number: 100 for a source that has 36), or **Everything in the archive**. It says how many more that is and about how long it takes. The walk is newest first and stops the moment that many new items are stored, in the middle of a listing page if need be. What is stored already is passed without being opened, so asking for a larger number later goes on where the last time stopped, and if the archive holds fewer items the run ends there and says so. *Everything* is bounded as before: by a built scraper's own limit, or by *pages on a deep scrape* in Settings (25). A number is not bounded by pages, only by itself. Measured on 14 October 2026 on clingendael.org: from 36 items to 50 in 35 seconds, three listing pages passed and two read.

### Items behind a login or paywall

Some items cannot be read in full: the page shows an opening and then asks to log in or subscribe, sends you to a login page, or refuses the scraper altogether. What happens to them is a choice per source, **Leave out items behind a login or paywall**. It is one of the options on the review step of the wizard, there is a switch for it above the built scrapers, and it can be changed any time on the source's Settings tab.

- **Off** (the default): the item is stored with the lines that could be read (the opening the page shows, or what the listing said) and marked as partial. The reader says so, and the scrape log names the site once.
- **On**: the item is not stored. The log says how many were left out and why, and the Settings tab lists them. The scraper remembers them, so later scrapes do not open them again; *Try them again at the next scrape* forgets the list. An item that failed for a passing reason (a timeout, a busy server) is not remembered and is simply tried again next time. When you switch the option on for a source that already has partial items, a button removes those.

Nothing gets past a wall here; it is only recognised (`backend/extractors/_walls.py`). A page counts as walled when the download ends on a login page, when the page says of itself that it is not free (the `isAccessibleForFree` marking that publishers add for search engines, or `article:content_tier`) and shows fewer than 400 words, or when it shows fewer than 250 words and asks, outside its header and footer, to log in or subscribe in order to read on. A refusal is a page that answers 401, 402, 403 or 451, a bot challenge, or a `robots.txt` that says no. The option only does something for feeds that open every item; a feed that stores teasers on purpose is left as it is.

Checked in October 2026 by opening 103 addresses from this library again: none of the 74 readable items was called walled; 7 items that had been stored as whole were recognised as openings of paid articles (Süddeutsche Zeitung, Tagesspiegel, Der Spiegel, Le Monde, EUobserver, The Africa Report, Turkey Recap); and of 22 partial items, 19 came from a site that refuses the scraper for good, one from a server that was busy, and two were Google forms with almost no text.

When a site changes and a feed stops finding items, the source page says so. Open **Structure → Analyse again** to get a fresh recipe; it is shown as a draft for you to save.

---

## Reddit

Paste a subreddit's address (`https://www.reddit.com/r/geopolitics/`) in *Add source*. Nothing is analysed; the review step shows two feeds, each with a switch:

| Feed | What it stores | Cost |
|---|---|---|
| **Shared articles** (on) | Only posts that share an article. The article itself is opened on the site it comes from and its text is stored, under the post's title and date, with a closing line saying who shared it and linking to the discussion. Text, picture and video posts are skipped. | One request to Reddit per 25 posts, plus the articles from their own sites |
| **Posts and comments** (off) | Every post: its own text, the link it shares, and its 30 highest-voted comments | One more request to Reddit per post |

Both can be on; they store different things (the article under its own address, the post under Reddit's).

- **Reddit allows about one request a minute** to a reader without an account, and the platform keeps to that. *Shared articles* is therefore quick, and *Posts and comments* collects about one post a minute. Reddit's official API is faster, but since November 2025 it needs an application approved by Reddit; the platform does not use it.
- **Articles the scraper cannot read** (the site refuses it, or shows a subscribe box instead of the text) are kept with what the post itself said and marked as partial, or left out when the source is set to [leave out items behind a login or paywall](#items-behind-a-login-or-paywall). On r/geopolitics and r/energy about a third of the shared articles are of this kind. Nothing is fetched from archive sites to get around a paywall.
- **Comments are a snapshot** of the moment the post was scraped, and only top-level comments: Reddit's feed does not say which comment a reply belongs to. For discussions that have had time to form, point the feed at `…/top/?t=day` or `…/top/?t=week`.
- **How far back:** a plain subreddit address lists what is *hot*; `/new` is strictly newest first. Reddit's listings end after about 1,000 posts.
- The number of comments (`comments`, 0 to 100), and whether *Shared articles* carries comments too, is under each feed's *Connector settings*.

### What the comments say

Every item that came from Reddit, an article that was shared there or a post itself, has a button in the reader: **Summarise comments**. It reads the 50 highest-voted comments under the post, at that moment, and has Claude sum up what people think: the main view, the lines of argument and roughly how common each is, where commenters disagree, and what they add that is worth knowing. From then on the item has two views, **Article** and **Comments**; the Comments view shows the summary and, under it, the comments it was made from. **Read the comments again** takes a fresh look later, when the discussion has moved on.

Nothing has to be switched on for this, and the feeds do not have to collect comments. It costs one request to Reddit (so it sometimes waits up to a minute) and a fraction of a cent for Claude. Measured on 13 October 2026 with Claude Haiku: 15 comments, 2,609 tokens in and 535 out, $0.0005; a post with two or three comments gets two or three sentences for $0.0003.

What it cannot know: the numbers of votes (Reddit's feed gives the order, not the counts), and replies to comments (only top-level comments are in the feed). It is the view of the most upvoted commenters of one subreddit, which is not the same as what is true, and the summary is written to report it as their view.

---

## Videos and single items

### Saving one page, one video or one podcast episode

*Add source* starts with a box, **Save one page, video or podcast episode**. Paste the address of an article, a PDF, a YouTube video or a podcast episode on Spotify and it is stored at once, without making a source of the site it comes from. It lands in **Saved articles**, **Saved videos** or **Saved podcasts**, sources that appear in the sidebar when you first use them. They have nothing to update; their Settings tab (AI summary, leaving out paywalled pages, writing videos up) applies to whatever you save next; a saved page in another language gets the reader's *Translate to English* button. Saving an address that is in the library already opens that item.

### YouTube

A **channel** is added like any other source: paste its address (`youtube.com/@name`), or the address of one of its videos, in the wizard. Quick detect recognises it, so no Claude analysis is needed or paid for. A **single video** goes in the box above. Every video is stored with its title, channel, upload date, description, thumbnail, length and number of views, and plays in the reader. The sidebar's *Sources* heading has a small menu, **All / Articles / Videos**, to show only one kind.

How much of a channel is collected depends on a key (`backend/connectors/youtube.py`):

| | Without a YouTube API key | With a YouTube API key (Settings) |
|---|---|---|
| Finding a channel | By its `/channel/UC...` address or by one of its videos. Not by its @name: YouTube shows visitors from Europe a consent page instead of the channel page, and the platform does not click such pages away | By its @name as well |
| Videos listed | The public feed of the channel's *Videos* tab: its 15 newest | Every video on its *Videos* tab, fifty to a page. *Update* reads the newest page, *Deep scrape* walks the whole channel |
| Length and views | From each video's own page (one request per new video) | From the API, for a whole page at once; the views of videos that are stored already are brought up to date on every scrape |

The key is free: in the Google Cloud console, switch on *YouTube Data API v3* for a project and create an API key. It allows 10,000 units a day and a page of fifty videos costs two.

**Shorts are left out.** What is listed is the channel's *Videos* tab: its regular videos, without Shorts and without live streams. (On the channel this was first tried on, six of the fifteen newest uploads were Shorts of half a minute.) To collect everything a channel uploads, set the feed's **Shorts** option to *yes* on the source's Structure tab. A Short you paste into *Save one page or video* is saved like any other video.

### Podcasts

Paste a Spotify link of one **episode** in the *Save one…* box, or the link of a **show** in the wizard with *Quick detect* to follow it. (In Spotify: the three dots, *Share*, *Copy link*.)

Spotify itself gives out neither the audio nor a transcript: its developer API has no such thing, and taking either from its player is against its terms, so the platform does not. A Spotify link is only used to learn *which* episode or show is meant; its public page says the title, the show, the date and the length. The rest follows the open route every podcast app takes (`backend/connectors/podcast.py`):

1. **The show's own feed.** A podcast is published as a feed with one entry per episode and the audio file attached. The feed is looked up in Apple's podcast directory (public, no key), and the episode is found in it by its title, or by its day and length when the title was edited.
2. **The transcript.** If the feed carries the publisher's own transcript, that is used. Otherwise the audio file is downloaded, handed to Gemini (uploaded for the one request and deleted again straight after) and written out with times and speakers; advertisements are left out.
3. **The article.** Claude writes the transcript up exactly as it does for a video (next section).

An episode is stored with its title, show, date, length and description, and plays in the reader from the feed's audio file. Measured on 13 October 2026 with a 33-minute episode of *The Daily*: saved in 1 second, 33 MB of audio downloaded in 5 seconds, written out by Gemini in 130 seconds (6,200 words; 53,744 tokens read), written up by Claude Haiku in 11 seconds for $0.0022. Two and a half minutes in all.

- **A show that is only on Spotify** has no feed. Its episodes are stored with what Spotify's page says (title, date, length, description) and cannot be written out; the reader says so.
- **An old episode** may no longer be in the feed (many feeds hold only the latest ones). It is stored the same way, without audio.
- **A followed show** is read from its feed, ten episodes to a page, and a run by itself writes out a few of them (Settings → *Podcast episodes transcribed in one run*, 5 by default), the newest first: an episode can be a download of 50 MB and an hour for Gemini to hear. The rest wait until you ask, with one of the two buttons below.
- **Length.** *Longest video or episode to transcribe* (two hours by default) applies; an hour of audio is about 115,000 tokens for Gemini.
- Music is not a podcast: a Spotify link to a track, album or playlist is refused.

The **Sources** menu in the sidebar has a fourth choice for them, *Podcasts*.

### Transcribe and summarise: the two buttons

A run by itself does a set number of videos or episodes. For the rest there are two buttons, for videos and podcasts alike:

- **On the source's page**, next to *Update*: **Transcribe and summarise N episodes** does everything that has not been done yet, the newest first. The line under the header says how many there are, about how long it takes and about what Claude will cost. It can be stopped; what is finished is kept. It stays within what one run may spend on Claude (Settings) and skips what is longer than the longest length set there. If Gemini says it has had enough for now, the run stops and says how many are left.
- **In the reader**, on a video or episode that has not been done: **Transcribe and summarise this episode** does only that one, whatever its length, and also when an earlier try failed. The reader switches to the article when it is ready. A short episode takes under a minute.

The button on a source's Settings tab still does "the next few" and can retry the ones that failed.

Measured on 13 October 2026 with episodes of three to four minutes: 22 to 36 seconds each, $0.0006 each with Claude Haiku.

### From a video to an article

What is *said* in a video is the part worth searching, and it takes two steps (`backend/pipeline/videos.py`), which run after a scrape has stored the videos:

1. **Writing out.** YouTube's own API gives a video's transcript only to someone who may edit that video, and reading it off YouTube's player is against YouTube's terms and its `robots.txt`, so the platform does neither. Google's **Gemini API** is the official way: it is given the address of a public video and writes out what is said, with times. This needs a Gemini API key (Settings; create one at aistudio.google.com/apikey). Google does not charge for reading YouTube videos while that feature is in preview; the free tier reads at most eight hours of video a day, and Google may use what the free tier is sent to improve its products.
2. **Writing up.** Claude (the *Video article model*, Claude Haiku 5.5 by default) turns the transcript into an article: a bottom line, then the video's own line of thought under headings that carry the time each part starts at, with the facts, figures and names kept and every claim attributed to the speaker. It also writes a two-sentence summary and tags. The article becomes the item's text, so search, embeddings, topics, timelines and the texts on a topic page treat a video like any other item. Estimated from the length of the request: about 0.2 cents for twenty minutes of video and 0.3 cents for an hour with Claude Haiku, 20 times that with Claude Sonnet. Measured on 12 October 2026 with Claude Haiku: 13 videos of 9 to 24 minutes cost $0.018 together.

In the reader a video has three views: **Article**, **Transcript** (as Gemini wrote it out; it can mishear a name) and **Description** (YouTube's). Without a Gemini key a video keeps its description as its text and is found by its title and description only.

Each video is written up as soon as it has been written out, so articles appear one by one and stopping a run keeps every one that is finished. Because Gemini is slow and limited per day, one run does a set number of videos (Settings → *Videos transcribed in one run*, 25 by default), the newest first; the rest wait for the next scrape or for the button on the source's Settings tab, which also says how many are waiting, too long (Settings → *Longest video to transcribe*, two hours by default) or could not be read. Writing up counts towards what one run may spend on Claude. *Write videos up as articles* is a switch per source, on by default; the wizard shows it for a YouTube channel.

---

## Built scrapers

A recipe is a set of CSS selectors, and that is as far as it goes. For a site you want everything from, there is a second way: a **site scraper**, a Python file in `backend/scrapers/` written for that one site. It can do what a recipe cannot: combine what the listing says with what the item page says, skip the kinds of items you do not want, read the report behind a download button.

```
 you give Claude Code a website ──► it studies the site and writes backend/scrapers/<name>.py
                                    ──► tests it against the live site ──► you add it in the dashboard
```

**Getting one.** Open Claude Code in this folder and say which site you want, for example *"build a scraper for https://hcss.nl/research/"*. `CLAUDE.md` in this folder tells it how: what to look at first, the rules a scraper follows, how to test it. Restart the platform afterwards.

**Using one.** *Add source* lists the built scrapers under the wizard. **Add and scrape** makes it a source like any other: Update, Deep scrape, automatic updates, leaving out items behind a login or paywall, AI summary and tags, topics and search all work the same. Its Structure tab shows the scraper's own notes on how the site is built.

**Installed now**

| Scraper | Collects |
|---|---|
| `clingendael` | Reports and papers, policy briefs, articles, op-eds and alerts from clingendael.org (roughly 5,000 items, going back to 2001). Title, authors, date, the *In short* takeaways, the text, and for reports and policy briefs the full text of the PDF. Podcasts and multimedia are left out. |
| `csis` | Everything under csis.org/analysis: commentaries, reports, briefs, transcripts, newsletters. Two feeds: *Latest* (the first page of the listing, the ten newest) and *Archive* (the site's sitemap, over 22,000 pages back to the 1990s, roughly newest first). The first scrape takes about 100 items in two minutes; a deep scrape of everything is about eight hours and is only for when you want the back catalogue. Kind, title, authors, date, summary, text, programs as tags, and the PDF link. See the note below. |

**Why CSIS needs a built scraper.** The listing at csis.org/analysis shows ten items a page, and every further page (`?page=1` and on) is answered with a Cloudflare bot challenge for anything that is not a browser. The scraper does not try to get past that. The site's sitemap, which it publishes for crawlers, lists the same pages, so the archive is read from there. Two limits follow. The sitemap runs days to weeks behind, so an item that was never among the ten latest while you scraped only arrives once the sitemap catches up: give the source an update interval of a day. And some report PDFs are protected (encrypted) and cannot be read; those items are stored with their abstract and the link to the PDF (12 of the 160 newest items on 12 October 2026).

**Trying one from the command line**

```
.venv\Scripts\python.exe -m backend.scrapers list
.venv\Scripts\python.exe -m backend.scrapers test clingendael --pages 2 --items 4
.venv\Scripts\python.exe -m backend.scrapers add clingendael
```

`test` runs the scraper against the live site the way a scrape would, prints what it finds, and stores nothing.

**How deep a deep scrape goes.** For recipes that is the *Listing pages on a deep scrape* setting. A site scraper knows its own archive and sets the limit itself (`archive_pages`), so a deep scrape of Clingendael walks all of its 430-odd listing pages. That is several thousand items and takes a few hours; you can stop it and start it again, because items that are already stored are skipped.

---

## How it is built

```
News scraper platform oktober/
├── start.bat              double-click to run
├── run.py                 starts the web server
├── requirements.txt
├── .env                   your API key (created by the Settings page; not in git)
├── data/platform.db       everything that was collected (SQLite; not in git)
├── data/models/           the embedding model (downloaded once; not in git)
│
├── backend/               Python, FastAPI
│   ├── main.py            the web app: /api + the built dashboard
│   ├── config.py          settings (one list; the Settings page is drawn from it)
│   ├── db.py              SQLite schema and helpers, full-text index
│   ├── schemas.py         the Recipe model
│   ├── registry.py        the plugin mechanism
│   ├── jobs.py            background jobs with live logs
│   ├── scheduler.py       automatic updates
│   ├── removed.py         the items you removed yourself: kept out of every scrape, kept to put back
│   │
│   ├── fetchers/          PLUGINS: how bytes are downloaded        (http)
│   ├── connectors/        PLUGINS: how a feed's items are listed   (rss, html_list, sitemap, reddit, youtube, podcast, single, scraper)
│   ├── extractors/        PLUGINS: how one item becomes clean text (html, pdf)
│   ├── analyzers/         PLUGINS: how an address becomes a recipe (claude, heuristic)
│   ├── scrapers/          PLUGINS: code written for one site       (clingendael, csis)
│   │
│   ├── pipeline/          scrape.py (run a recipe, save one link), enrich.py (optional AI summary + tags), translate.py (translation, on request),
│   │                      videos.py (a video's transcript, then its article)
│   ├── search/            query.py (search by words), embed.py (embeddings), meaning.py (search by meaning),
│   │                      topics.py (what belongs to a topic, timeline, trend), expand.py (Claude suggests terms)
│   ├── ai/                client.py (the only place that calls Claude), briefing.py (the two texts on a topic page),
│   │                      gemini.py (the only place that calls Google's Gemini: what is said in a video)
│   └── api/               one file per area: sources, scrapers, links, articles, topics, system
│
├── frontend/              React + Vite
│   ├── dist/              the built dashboard, served by the backend
│   └── src/
│       ├── pages/         PLUGINS: one folder per page, found automatically
│       ├── cards/         PLUGINS: one file per card look, found automatically
│       ├── components/    Sidebar, Reader, ArticleGrid, RecipeEditor, TopicEditor, JobProgress, ...
│       ├── lib/           api.js, router.jsx, app.jsx (shared state), format.js, useJob.js
│       └── styles/app.css design tokens at the top; the rest follows them
│
├── CLAUDE.md              instructions for Claude Code, including how to build a scraper for a new site
└── tests/                 226 tests; no internet needed
```

### The one mechanism behind all of it

Every plugin folder owns a **registry**. A plugin is a class with a `name`, decorated with `@<registry>.register`. On start-up each folder imports all of its files, so **adding a file is all it takes**; no list has to be edited.

A plugin declares the options it understands as `fields`. That one declaration is used in three places:

1. the **recipe editor** in the dashboard draws a form from it,
2. the **tool schema** Claude fills in is generated from it,
3. the **reference section of Claude's prompt** is generated from it.

So a new connector is immediately usable by hand in the editor and by Claude during analysis.

The dashboard works the same way: `src/pages/index.js` picks up every `pages/*/page.jsx`, and the sidebar is drawn from what those files declare. `src/cards/index.js` picks up every `*Card.jsx`. The Settings page is drawn from the list in `backend/config.py`.

### What depends on what

```
api ──► pipeline ──► connectors ──► fetchers
 │         │    └──► extractors ──► fetchers
 │         └───────► ai/client          (only when "AI summary + tags" is on)
 ├────► analyzers ─► pipeline (to test feeds), ai/client (claude analyzer only)
 └────► search ────► ai/client          (only for term suggestions and the texts on a topic page)
```

Site scrapers sit beside this: the `scraper` connector hands a feed to the file in `scrapers/` that the recipe names, and that file uses the same fetchers and extractors.

Scraping never imports the Claude code unless enrichment is switched on for that source.

---

## Extending it

| I want to… | Do this |
|---|---|
| Get everything out of one particular site | Add a **site scraper**: one file in `backend/scrapers/`. Ask Claude Code for it; see [Built scrapers](#built-scrapers) |
| Support a new kind of source (an API, a different feed format) | Add a **connector**: one file in `backend/connectors/` |
| Read a new document type (Word, EPUB) | Add an **extractor**: one file in `backend/extractors/` |
| Open pages that need JavaScript | Add a **fetcher** (a headless browser): one file in `backend/fetchers/` |
| Try a different way of analysing sources | Add an **analyzer**: one file in `backend/analyzers/` |
| Add a page to the dashboard | Add a folder with a `page.jsx` in `frontend/src/pages/` |
| Give a content type its own card | Add a `SomethingCard.jsx` in `frontend/src/cards/` |
| Add a setting | Add one entry to `SETTINGS` in `backend/config.py` |
| Add API endpoints | Add a module in `backend/api/` and list it in `backend/api/__init__.py` |
| Add a processing step per item (e.g. an importance score) | Follow `backend/pipeline/enrich.py`; see [below](#where-an-importance-filter-would-go) |

After a backend change, restart the platform. After a dashboard change, run `npm run build` in `frontend/` (see [Developing the dashboard](#developing-the-dashboard)).

### A new connector

```python
# backend/connectors/json_api.py
import json
from collections.abc import Iterator

from ..registry import Field
from ..schemas import FeedRecipe
from .base import Connector, Context, Item, ListPage, connectors


@connectors.register
class JsonApiConnector(Connector):
    name = "json_api"
    label = "JSON API"
    # Claude reads this description to decide when the connector fits.
    description = "Reads items from a JSON endpoint that returns a list of objects with a url and a title."
    fields = [
        Field("items_key", "Items key", help="The key holding the list of items, e.g. 'results'."),
    ]

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        result = ctx.fetch(feed.url, feed.fetcher)
        rows = json.loads(result.text)[feed.opt("items_key", "items")]
        yield ListPage([Item(url=row["url"], title=row.get("title", "")) for row in rows], result.url)
```

`iter_pages` yields one `ListPage` per page of the listing, newest first, for as long as there are pages; the scraper decides when to stop. Set `inline_content = True` on the class if listing entries already hold the whole item, so item pages are never opened. A connector that needs more say overrides `opens_items(feed)` and `read_item(item, feed, ctx)`: the Reddit connector does, to read a post's comments or the article a post links to. `connectors/_pagination.py` has ready-made page-number and next-link handling.

### A new extractor

```python
# backend/extractors/plain_text.py
from .base import Extracted, Extractor, extractors


@extractors.register
class PlainTextExtractor(Extractor):
    name = "text"
    label = "Plain text file"
    priority = 20                     # lower runs first; pdf is 10, html is 50

    def matches(self, result) -> bool:
        return result.content_type == "text/plain"

    def extract(self, result, rules, ctx) -> Extracted:
        text = result.text
        return Extracted(title=text.split("\n", 1)[0][:200], text=text, content_type="document")
```

### A new fetcher

Subclass `Fetcher` in `backend/fetchers/`, give it a `name` (say `browser`), implement `fetch(url, *, max_bytes=None, robots=True) -> FetchResult`, and register it with `@fetchers.register`. A feed then selects it with `"fetcher": "browser"` in its recipe. This is the place for a headless browser when you need pages that only exist after JavaScript runs.

### A new page

```jsx
// frontend/src/pages/saved/page.jsx
import { PageHeader } from '../../components/ui.jsx'

function SavedPage() {
  return <PageHeader title="Saved" subtitle="Items you marked to read later." />
}

export default {
  id: 'saved',
  path: '/saved',                        // address after the #; use :name for parameters
  title: 'Saved',
  icon: 'check',                         // a name from components/Icon.jsx
  nav: { section: 'main', order: 2 },    // leave out to keep it off the sidebar
  component: SavedPage,                  // receives { params, query }
}
```

That is the whole change: the route works and the page is in the sidebar. A page that should appear once per thing (per source, per topic) adds `navItems: (app) => [...]`; see `pages/source/page.jsx`. Sidebar sections are listed in `pages/index.js`.

Inside a page, `useApp()` gives the shared state (`sources`, `topics`, `meta`, `openReader`, `notify`, `fail`), `api` from `lib/api.js` talks to the backend, and `<ArticleGrid load={...} />` gives you the card wall with paging and the reader for free.

### A new card

A file `frontend/src/cards/PodcastCard.jsx` that default-exports `{ types: ['podcast'], component: PodcastCard }` makes every item of content type `podcast` use that card (`VideoCard.jsx` is the one for videos). `cards/parts.jsx` has the pieces (`CardFrame`, `Thumb`, `CardText`) to build it from. Content types themselves are listed in `backend/schemas.py` (`CONTENT_TYPES`).

### Where an importance filter would go

You mentioned wanting "more important / less important" later. The places it touches are few, which is the point of the layout:

1. a column on `articles` in `backend/db.py` (for example `importance REAL`),
2. a step that fills it, modelled on `backend/pipeline/enrich.py` (which already shows a per-item Claude call with a fixed JSON answer) and called from the same spot in `pipeline/scrape.py`,
3. an `ORDER BY` option in `backend/search/query.py`,
4. a filter chip on the pages that use `ArticleGrid`.

---

## Recipe reference

A recipe is plain JSON stored with the source. You rarely write one by hand, but this is what Claude produces and what the editor edits:

```json
{
  "site_name": "CCDCOE",
  "homepage": "https://ccdcoe.org/",
  "description": "NATO Cooperative Cyber Defence Centre of Excellence: research on cyber defence.",
  "language": "en",
  "icon_url": "https://ccdcoe.org/favicon.ico",
  "feeds": [
    {
      "name": "Publications",
      "connector": "html_list",
      "url": "https://ccdcoe.org/library/publications/",
      "content_type": "paper",
      "enabled": true,
      "fetch_detail": true,
      "fetcher": "http",
      "options": {
        "item_selector": "div.research-items-item",
        "link_selector": "a.research-items-item__link",
        "title_selector": ".research-items-item__title",
        "summary_selector": ".research-items-item__excerpt",
        "date_selector": ".research-items-item__year h6"
      }
    }
  ],
  "article": { "extract_pdf_text": "true" },
  "structure_report": "Markdown shown on the Structure tab."
}
```

This recipe was run against the live site while building the platform: it lists 275 publications, and the item pages that were tried yield the abstract plus the full text of the linked PDF.

**Feed fields**

| Field | Meaning |
|---|---|
| `name` | Name of the stream ("Publications", "News") |
| `connector` | Which connector lists the items |
| `url` | Feed address, first listing page, or sitemap |
| `content_type` | `article`, `news`, `report`, `paper`, `post`, `document`, `other`. Decides the card and the filter chip |
| `enabled` | Switched-off feeds are kept but not scraped |
| `fetch_detail` | `true`: open each item's page for the full text. `false`: store what the listing itself carries |
| `fetcher` | How pages are downloaded (`http`) |
| `options` | Settings of the connector, all as text |

**Connectors and their options**

| Connector | Use it for | Options |
|---|---|---|
| `rss` | RSS and Atom feeds | pagination options (below) |
| `html_list` | A page listing items: news overview, publications archive | `item_selector` (one element per item), `link_selector`, `title_selector`, `date_selector`, `summary_selector`, `image_selector`, plus the pagination options |
| `sitemap` | A `sitemap.xml`, when there is no feed and no usable listing | `url_pattern` (regular expression an item URL must match), `exclude_pattern`, `sitemap_pattern` |
| `reddit` | A subreddit, user or search on [Reddit](#reddit) | `collect` (`posts` or `articles`), `comments` (how many per item, empty = none) |
| `single` | One page or PDF that has no listing | `extra_urls` |
| `scraper` | A site that has a [built scraper](#built-scrapers) | `scraper` (its name), `stream` (which of its streams) |

**Pagination options** (`rss` and `html_list`): `pagination` is `none`, `next_link`, `page_param` or `url_template`. With `next_link` give `next_selector`. With `page_param` give `page_param` (the query parameter, e.g. `page`). With `url_template` give `page_template` (a full URL containing `{page}`). `page_start` is the number the start URL itself stands for (often 1; on Drupal sites 0) and `page_step` how much it grows per page.

**`article` section** (item pages; leave empty for automatic detection): `body_selector`, `title_selector`, `date_selector`, `author_selector`, `image_selector`, `pdf_link_selector`, and `extract_pdf_text` (`"true"` also reads the linked PDF and uses its text when it is longer than the page).

---

## Topics and search

Items are found in two ways, and both are used everywhere.

**By words.** SQLite's full-text index (FTS5) with BM25 ranking. Matches in the title count most, then tags, then summaries, then the body. A single word of four letters or more matches by prefix (`drone` finds `drones` and `droneaanval`); several words must appear next to each other; accents and capitals are ignored.

**By meaning.** Every item gets an *embedding*: a list of 384 numbers that stands for what it is about. Two texts on the same subject get lists that lie close together, whatever words or language they use. They are made by a small multilingual model (`paraphrase-multilingual-MiniLM-L12-v2`) that runs on this computer through onnxruntime: nothing is sent anywhere and it costs nothing. Measured here in October 2026: 380 items in 20 seconds the first time, a search in 50 milliseconds.

- **What is embedded** is the title plus a summary: Claude's when the item has one, otherwise the site's. Never the opening of the stored text, which is too often a copyright page or a line of boilerplate. So items with an English *AI summary* are placed best; a Dutch or German item without one is still placed, a little less surely.
- **When.** At the end of every scrape, after labelling, and at the end of a translation run. When a title or summary changes, the embedding is dropped by a database trigger and made again. On start-up, and with the button on the Settings page, whatever is missing is filled in.
- **The library's average is taken off.** All items in a library like this share something ("politics and energy", and a little of "this is Dutch"), which hides the differences that matter. From 50 items on, the average embedding is subtracted from every item. Before that the embeddings are used as they are, with stricter thresholds.
- **Switch.** Settings → *Understand items by meaning*. Off, or with the packages missing, everything works by words alone as it did before.

The search box on Home merges the two result lists by rank, so an item both ways agree on comes first. An item only counts as found by meaning when it is close to the question (0.40 or more) and not much further away than the closest item is; a question the library has nothing on finds nothing.

### What belongs to a topic

A topic has a name, a sentence on **what it is about**, and two word lists:

- **About any of** (`terms`): an item must mention at least one. *Suggest terms with Claude* fills the list with synonyms, related terms and translations.
- **Must mention one of** (`required_any`, optional): for a specific company, person or programme.

An item is in a topic for one of three reasons, shown on the page as counts and on the items as marks:

| | |
|---|---|
| **By its words** | It matches the term lists. |
| **By meaning** | It is close to what the topic is about without using its terms. "What the topic is about" is a point among the embeddings: the name and the description, pulled towards the topic's best word matches and the items you said belong, and away from the ones you said do not. *Reach* (narrow, balanced, broad) sets how close an item must be. A topic with a *must mention* list only takes items that name it. |
| **You said so** | *Belongs here* (the topic chips in the reader). *Not this* (the cross on a timeline entry, or the same chips) removes an item whatever the rest says. Both also teach the topic. |

Meaning also takes away. A report on diesel prices that names the Strait of Hormuz once matches the words of a topic on the strait without being about it. Such an item is a **mention**: it is listed under *Only mention it* at the bottom of the page, and the timeline, the trend and Claude's texts are made from the items that are about the topic. Measured on this library: of 41 items that contain "Strait of Hormuz", 13 are about it and 28 mention it; one more was found by meaning alone. A topic about one name (*must mention*) sets nothing aside.

Membership is worked out when it is asked for, so a new item is in its topics the moment it is stored and embedded. *Also collect by meaning* can be switched off per topic; it then goes by its words alone.

### Topics on Home

Home starts with a section **Topics**: every topic you made, as a card like the cards of items. A click opens the topic's page.

- **The picture is automatic.** A topic has no picture of its own, so its card shows up to four pictures from its newest items, as a mosaic. A source gets one picture before any source gets a second, a picture that does not load makes way for the next, and a topic whose items have no pictures shows its text instead. The card therefore changes as news comes in, and needs no work.
- **Or pin one.** *Edit topic* on the topic's page has **Picture on its card**: *Automatic*, or one of the pictures of its twelve newest items. Pick one and the card keeps it.
- **What else the card says:** the opening of the topic's last *What is new* (or, until one is written, what the topic is about), how many items it has, how recent the newest is, a **new** mark with the number since you last opened it, and **spiking** when the topic takes up clearly more of your library this week than in the four weeks before.
- **Order and size:** the topics with something new first, then the ones whose newest item is most recent. All of them are shown, on cards the same size as the items' (three to a row on a 1500-pixel window, so eight topics take three rows).
- **Searching** on Home narrows the topics to those whose name or description has one of your words. A filter on a kind of item (*Report*, *Video*) is about items, so the topics step aside.

### The topic page

| Part | What it shows | Made by |
|---|---|---|
| **What is new** | A short update from the items that reached the library since the previous update (and were published in the last 30 days), laid out as a news article: the section name, a headline, one sentence that sums it up, a byline (when it was written, from how many items, how long it reads), then the update in short paragraphs with the lead picture to the right of the text, and its numbered sources as one line of title each. Earlier updates stay underneath. When nothing new has arrived, **Rewrite** writes the latest update again from the same items, in its place (an update from before headlines gets one that way). | Claude, when you press the button, or after a scrape when *Keep this up to date by itself* is on |
| **The long run** | The standing summary, laid out as a feature article: the section name, a headline, the bottom line, a byline, then sections (how it developed, who wants what, where sources disagree, gaps) that start with the lead picture to the right of the text and have one or two more, and the numbered sources as one line of title each. | Claude, when you press the button |
| **Timeline** | The topic's items by date, newest first, each with a small picture next to its date (the item's own, or another of the same story's; left empty when there is none). Items that say almost the same thing within ten days are one entry (one event in several reports, a paper and its announcement, a repost); *+2 more* opens them. Entries that arrived since your last visit are marked *new*. | Counted |
| **Trend** | Items per week over six months, and two comparisons: the last 7 days against the 28 before (*spiking*, *steady*, *quieter*) and the last 3 months against the 3 before (*building*, *steady*, *fading*). | Counted |
| **Sources** | Which sources and which kinds of content the topic is made of, and how many items are in it by words, by meaning and by your say. | Counted |
| **Up next** | Your other topics, the one closest in meaning first, with what is new in each. | Counted |

The trend compares **shares**, not counts: the topic's items as a part of everything the library collected in the same days. Otherwise adding a source would make every topic "rise". A comparison is only named when the library itself has enough items in both periods (30 for the short one, 100 for the long one); until then it says *too little history*. Two things it cannot correct for: a source that only reaches back a few days (Reddit) makes the last week look busy for the topics it covers, and a library that is only scraped by hand has gaps. Set update intervals on your sources.

---

---

## Where Claude is used, and what it costs

All Claude calls go through `backend/ai/client.py`, using the official `anthropic` Python SDK.

| Feature | When it runs | Model (changeable in Settings) |
|---|---|---|
| Source analysis | Once per source, when you add or re-analyse it | `claude-opus-5-5`, effort `high` |
| Topic term suggestions | When you press the button | `claude-opus-5-5`, effort `low` |
| *The long run* on a topic page | When you press the button | `claude-opus-5-5`, effort `medium` (the *Topic model*) |
| *What is new* on a topic page | When you press the button, or after a scrape for topics where you switched that on | `claude-haiku-5-5`, effort `low` (the *Topic update model*) |
| AI summary and tags | Per new item, only for sources where you switched it on | `claude-haiku-5-5`, effort `low` |
| Translation to English | Per item that is not in English, only when you press a Translate button (on a source's page or in the reader) | `claude-haiku-5-5`, effort `low` |
| The article of a video | Per video that has a transcript, for sources where *Write videos up as articles* is on (see [From a video to an article](#from-a-video-to-an-article)) | `claude-haiku-5-5`, effort `low` (the *Video article model*) |
| What the comments say | When you press *Summarise comments* on an item from Reddit | `claude-haiku-5-5`, effort `low` (the *Article tagging model*) |

Scraping, embeddings, search, topic matching, timelines and trends make no Claude calls.

Token use and an estimated cost are shown on every job (Activity page, and next to the result in the wizard). Published prices in October 2026: Claude Opus 5.5 is $4 per million input tokens and $20 per million output tokens; Claude Sonnet 5.5 is $2 and $10; Claude Haiku 5.5 is $0.10 and $0.50. The source analysis re-sends the growing conversation on each step, so it uses prompt caching to keep that cheap.

**The two texts on a topic page** (`backend/ai/briefing.py`). Both buttons say, before you press them, how many items will be read and about what it costs with the model that is set; the request is built first and priced by its length.

- *What is new* reads only the items that arrived since the last update, as their summaries (Claude's, else the site's, else the opening 700 characters), at most 25, plus the standing summary and the previous update so that it does not repeat them. Measured in October 2026 with Claude Haiku 5.5: 10 items, 1,647 tokens in and 735 out, $0.0005, 5 seconds. That is 1 cent with Claude Sonnet 5.5 and 2 cents with Claude Opus 5.5.
- *The long run* reads the topic's best items (30 by default, the opening 1,800 characters of each, oldest first), the updates written so far, and its own previous version. Measured with Claude Haiku 5.5: 14 items, 8,931 tokens in and 2,178 out, $0.002, 12 seconds. With the default, Claude Opus 5.5, the same request is about 8 cents, and one over 30 long items about 13 cents (estimated from the request's length, not run).
- **As news articles.** Both are asked for in one shape: a `# headline` line, the opening (one sentence for an update, the two or three sentence bottom line for the long run), and `[[picture N]]` lines, the first one for the lead picture and, in the long run, one or two more after the first paragraph of a section. The pictures are small and sit to the right of the body text, which flows around them. Claude Haiku does not always keep to the shape, so the page is lenient: the first picture named, wherever it stands, leads; only a short first paragraph (up to 90 words) with more text after it is the opening line; and when no picture is named, the lead is the picture of the first item the text cites that has one. Claude is told which of the items it reads have a picture of their own ("picture" after the item's source and date) and chooses by number, without seeing the pictures, so this costs the same as plain text. The page cuts the text into these parts when it reads it (`briefing.article`): a picture is only shown for a cited item that has one, each once, with a caption naming the item and its source, and a click opens the item. The pictures come from the sites themselves, as on the cards; one that does not load is left out. Texts written before this have no headline; they show the picture of the first item they cite that has one. Measured on a copy of the owner's library on 30 October 2026 with Claude Haiku 5.5 (topic *hybrid warfare*): an update from 10 items, 2,791 tokens in and 1,618 out, $0.0011; the long run from 30 items, 22,746 in and 3,525 out, $0.004. Both kept to the shape, with a lead picture each and two more between sections of the long run. Two more runs the same day showed that Claude Haiku left the pictures out when the prompt let it ("when none fits"); it now asks for a picture whenever an item that has one is about the main development, and for one or two in the sections. A site can refuse to show its pictures on other pages: hcss.nl answers 403, so such a picture is left out of the page.
- *Keep this up to date by itself* (a switch per topic, off by default) writes *What is new* at the end of a scrape when three or more new items are waiting. It counts towards the limit per run below; a topic whose update would go past it is left for the next run and the log says so.

Every sentence of both texts carries the number of the item it rests on; clicking it opens that item. That is the check on them: in the test run above, Claude Haiku called SWP, which is German, a Swiss think tank.

**AI summary and tags.** For every new item of a source where the switch is on, Claude writes a two-sentence summary and five to eight topic tags. The summary is written in English whatever language the item is in, so a German or Dutch paper gets an English summary; Settings → *AI summary language* changes that to Dutch, German, French or *Same as the article*. Tags are always English. Both are shown in the reader and on the cards and are searched, so an English search or topic also finds items written in another language. The item's own text is stored as it was published; nothing is translated. For items that were stored before the switch was turned on, the source's Settings tab has a button that labels them.

What it costs depends on the length of the item, because the whole text (up to 60,000 characters) is read and only a few lines are written. With Claude Haiku 5.5: an English news article of 700 words costs about $0.0002, an English paper of 3,500 words about $0.0007 and a German one about $0.0015 (German takes about twice as many tokens per word; measured in October 2026), and the most an item can cost is about $0.003. That is roughly $0.20 per thousand news articles and never more than about $3 per thousand items. Claude Sonnet 5.5 costs 20 times as much for the same work and Claude Opus 5.5 40 times. The Activity page shows what a run really used.

**Translation to English.** Nothing is translated while scraping. A source with items that are not in English gets a **Translate N items** button next to *Update* and *Deep scrape*, and a line under its header that says how many items, about how long it takes and what it costs with the translation model set in Settings. The reader has a **Translate to English** button on any single item that is not in English, with its price. A translated item is stored in English: the title, the summary and the whole text. The home page, the source page, the search, the topics and the briefings then all work with the English version. The original is kept next to it; the reader says *Translated from German by Claude* and **Show the original** switches to the text as it was written. A card of a translated item carries a small `DE → EN` mark. A source whose items are all in English has no button at all.

How it works (`backend/pipeline/translate.py`):

- **Which items.** The language is judged on this computer from the text itself, for nothing, not from what the site says about itself (Clingendael and HCSS label their Dutch pages English). The commonest English words (*the, of, and, to…*) are about a third of an English text and a few percent of a German, Dutch or French one. An item counts as not English only on evidence of another language: most of its letters are of another script, or the common words of German, Dutch, French, Spanish, Italian, Portuguese or Polish are as frequent as the English ones (in a title or teaser of under 40 words: more frequent, and two at least). English written like headlines has few of the commonest English words but none of another language's, so it stays English. An item found to be English is marked as looked at and never judged again. Videos and podcast episodes are left out: writing one up (*Transcribe and summarise*) makes an English article of it.
- **Too long for the button.** The source's button leaves out items that take longer to read than Settings → *Longest item the Translate button on a source's page does* (20 minutes by default, counted as the cards count a "min read": 220 words a minute; 0 = no limit). The line under the header says how many it left out. The reader's button translates one of them whatever its length.
- **In what order.** The shortest first, so most items are in English within minutes and a report of a hundred pages holds up nothing but itself. Stopping the run loses nothing that is finished.
- **How.** One request translates the title and the summary; the text goes in pieces of at most 8,000 characters, cut between paragraphs, one request each, one after the other. If any request fails or is declined, the item is left exactly as it was and the button offers it again. The same goes for an item that was being translated when the run was stopped: what was done of it is lost, and it has been paid for.
- **The same text twice.** A site often lists a report twice, as the report and as a short piece about it, and both end up with the text of the same PDF. The second one takes over the translation of the first and only its title is translated.
- **What changes in the database.** `title`, `summary` and `text` become English, `language` becomes `en`, `translated_from` gets the original language, and the originals move to `original_title`, `original_summary` and `original_text`. The search index follows, so a translated item is found by English words and no longer by the words of the original, and its embedding is made again at the end of the run. Author, tags and the PDF link are not touched.
- **Limits.** A text is translated up to 250,000 characters (about 30,000 words); beyond that a line says how much of the original was left out. A translated item is not translated again when the translation model is changed.

What it costs: the text is read once and written once, and writing is the expensive part. Measured in October 2026 on German texts: a paper of 3,085 words with Claude Haiku 5.5 took 5 requests, 14,200 tokens in, 7,477 out, $0.0052 and 35 seconds; nine items of 347,000 characters together with Claude Sonnet 5.5 took 66 requests, 196,794 tokens in, 112,610 out, $1.52 and twelve minutes. So with Claude Haiku roughly $1 per thousand news articles, $5 per thousand long papers and at most about 6 cents for one very long report, and **20 times that with Claude Sonnet 5.5, 40 times with Claude Opus 5.5 and 100 times with Claude Fable 5.1** (Settings → *Translation model*). One report of 30,000 words costs 5 cents with Haiku and a dollar with Sonnet. How long it takes, from the same runs: about 2 seconds per 1,000 characters, and a few seconds per item for its title; the buttons say so beforehand.

What keeps the bill from being a surprise:

- **The price is shown before you spend it.** The source's button and the line under the header say what all of it costs with the model set now; the reader's button says what that one item costs.
- **The button spends what it said.** A press of the source's button may spend the price it showed, and a quarter more at most for an estimate that was low, also when that is more than Settings → *Most one run may spend on translating and summarising* allows. That limit still holds for scrapes (AI summary and tags, videos, topics that update themselves). An item that would take the run past what it may spend is left for the next press, and the log says so.
- **The Activity page counts every request**, also those of an item that was being translated when a run was stopped.

Measured in the owner's library on 28 October 2026 (a copy): the check found 18 German items at SWP (6 longer than 20 minutes), 8 French ones at Institut Jacques Delors (4 longer), 32 Dutch ones at HCSS (8 longer) and 13 at Clingendael (6 longer), and one German article shared on r/geopolitics under an English title; nothing in the other sources. With Claude Sonnet 5.5 as the translation model, SWP's button said 12 items, about 12 minutes and $1.52; with Claude Haiku 5.5 about $0.08. Translating one German paper of 3,600 words from the reader took about a minute with Claude Haiku 5.5 and cost $0.0059 (shown beforehand: 0.7 cents).

Two things are switched on that you should know about:

- **Refusal fallback** (Settings → *Retry declined requests on a fallback model*). If one of Anthropic's safety classifiers declines a request, the API re-runs it on the fallback model Anthropic recommends. This uses a beta feature of the API (`server-side-fallback-2026-07-01`). Switch it off if you do not want it; a declined request then simply fails with a message.
- **Long documents are labelled from their first 60,000 characters** when *AI summary and tags* is on, so that one 300-page PDF does not cost more than the rest of a source together. The full text is still stored and searchable.

---

## Data and API

Everything is in `data/platform.db` (SQLite). Back up that one file to back up the platform; delete it to start over.

| Table | Holds |
|---|---|
| `sources` | Name, address, the recipe (JSON), update interval, the AI-labels switch, whether items behind a login or paywall are left out, whether videos are written up, last scrape and last error. The two sources of saved single items have no feeds |
| `left_out` | The items a source did not store because their own page could not be read, with the reason, so that they are not opened again |
| `removed` | The items you removed yourself: the address (which no scrape stores again), the title, the source, when, and the item as it was, so that it can be put back. The copy is dropped when its source is deleted; the address stays |
| `articles` | One row per item: source, feed, URL (unique), title, author, dates, summary, full text, image, PDF, content type, language, tags, AI summary, word count, `is_partial`, and for a translated item the original title, summary and text with the language they were in. For a video: its YouTube id, length, views, the transcript, and when it was written out and written up. For a podcast episode: the address of its audio file, its length, and the same transcript columns. For an item from Reddit, once asked for: the comments under its post, Claude's summary of them, and when. And when you starred it, if you did |
| `articles_fts` | The full-text index over title, summary, AI summary, tags and text, kept in sync by triggers |
| `embeddings` | One embedding per item and the model that made it. A trigger drops it when the item's title or summary changes |
| `topics` | Name, what it is about, the two term lists, whether it also collects by meaning and how widely, whether it updates itself, when you last opened it, and *The long run* with its sources, and the picture pinned for its card on Home (empty = automatic) |
| `topic_items` | What you said about an item on a topic: *belongs here* or *not this* |
| `topic_notes` | Every *What is new* that was written, with its sources. The newest is shown; the older ones are read when *The long run* is rewritten |
| `jobs` | Every background job with its log, result and Claude usage |
| `settings` | What you changed on the Settings page |

`is_partial` marks items that could not be read in full: only the opening in front of a login or paywall, or only what the listing said (see [Items behind a login or paywall](#items-behind-a-login-or-paywall)); the reader says so.

The API is documented interactively at `http://127.0.0.1:8765/docs` while the platform runs. In short:

| | |
|---|---|
| `GET /api/meta` | Installed plugins and their option fields, content types, Claude status |
| `POST /api/sources/analyze` | Start an analysis job (`url`, `analyzer`, `hint`) |
| `POST /api/recipes/test-feed`, `/test-article` | Try a feed or an item page without storing anything |
| `GET/POST /api/sources`, `GET/PATCH/DELETE /api/sources/{id}` | Sources and their recipes |
| `POST /api/sources/{id}/scrape`, `/enrich`, `/reanalyze` | Start a job for a source. A scrape takes `deep`, and with it `limit`: stop when that many new items are stored |
| `POST /api/sources/{id}/left-out/forget`, `/partial/remove` | Open the left-out items again at the next scrape; delete the partial items stored earlier |
| `POST /api/sources/{id}/videos` | Write out and write up the videos or episodes of a source that are still waiting: as many as one run does, or all (`everything`) |
| `POST /api/articles/{id}/write` | Write out and write up one video or one episode, now |
| `POST /api/articles/{id}/comments` | Read the comments under the Reddit post an item belongs to and have Claude sum them up |
| `POST /api/links` | Save one page, one YouTube video or one podcast episode (a Spotify link) by its address |
| `PUT /api/settings/keys/{youtube or gemini}` | Store one of the two Google keys (never returned) |
| `GET /api/scrapers`, `POST /api/scrapers/{name}/add` | The built scrapers; add one as a source |
| `GET /api/articles`, `GET/DELETE /api/articles/{id}` | The feed, search (by words and by meaning), one item. `favorites=1` lists the starred ones. `DELETE` removes it from the library and remembers it |
| `PUT /api/articles/{id}/favorite` | Star an item or take its star away (`on`) |
| `GET /api/removed`, `POST /api/removed/{id}/restore` | The items you removed; put one back |
| `GET /api/articles/{id}/similar`, `/topics` | The items closest in meaning; which topics the item is in |
| `GET/POST /api/topics`, `GET/PATCH/DELETE /api/topics/{id}` | Topics. `GET` of one topic returns everything its page shows except the two lists below. The list carries what a topic's card on Home shows: pictures, the newest item's date, the trend, the opening of its last *What is new* |
| `GET /api/topics/{id}/timeline`, `/articles` | The timeline; the item wall (`scope` = `about`, `mentions` or `all`) |
| `POST /api/topics/{id}/news`, `/briefing` | Start *What is new*; start *The long run* |
| `POST /api/topics/{id}/items`, `/visit` | Say *belongs here* or *not this* about an item; mark the page as opened |
| `POST /api/topics/expand`, `/preview` | Claude's term suggestions; live count |
| `POST /api/meaning/embed` | Embed the items that have no embedding yet |
| `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel` | Jobs and their logs |
| `GET/PUT /api/settings`, `PUT /api/settings/api-key` | Settings; store the key (it is never returned) |

---

## Rules the scraper follows

- **It identifies itself honestly** (`NewsScraperPlatform/1.0 (personal research dashboard)`) and waits one second between requests to the same site. Both are settings.
- **It respects `robots.txt`** for pages it crawls: listing pages, item pages, sitemaps. The one deliberate exception is a **feed you subscribed to** (an RSS/Atom address, a subreddit's feed): robots.txt is written for crawlers that discover pages, and fetching a feed you pointed it at is what a feed reader does. Reddit, for example, disallows all crawlers in robots.txt but serves its feeds to readers. If you would rather not do this for a source, do not add its feed.
- **YouTube is read through its open doors only.** A video's own page and a channel's feed are open to visitors (the feed in the sense above: one you subscribed to); the YouTube Data API is used when you give it a key. The platform does not click away YouTube's consent page, and it does not read transcripts off YouTube's player, which YouTube's terms and `robots.txt` rule out. What is said in a video comes from Google's Gemini API instead.
- **It honours rate limits a site announces.** Reddit allows a reader without an account about one request a minute (measured in October 2026); the fetcher waits accordingly, so a Reddit scrape is slow by design.
- **It does not work around bot protection.** A Cloudflare challenge or a 403 is reported as what it is.
- **It refuses local network addresses** (localhost, 192.168.x.x and the like), also after redirects.
- **During analysis Claude can only open pages of the site being analysed.** Page content is passed to Claude as material to analyse, with the instruction that text on a page has no authority over it.
- **The platform listens on `127.0.0.1` only**, so nothing outside your computer can reach it. It has no login; do not expose it to a network as it is.

---

## Tests

```
.venv\Scripts\python.exe -m pytest
```

226 tests, about fifteen seconds, no internet and no API key (the key in `.env` is kept out of the tests). They run against a small fake website that the test suite serves itself (`tests/conftest.py`).

| File | Covers |
|---|---|
| `test_plugins.py` | Fetcher rules (redirects, robots.txt, size limit, local addresses), every connector, both extractors, recipe validation |
| `test_pipeline.py` | Scraping end to end, updates versus deep scrapes, failing items and feeds, blocked sites, search and topic matching, the scheduler, a deep scrape that goes back as many items as asked (stopping mid-page, passing what is stored, running out, counting across feeds) |
| `test_analyzers.py` | The page digest, the pre-scan, Quick detect, and the Claude analysis loop driven by scripted replies: tool handling, wrong selectors, off-site requests, untested recipes, truncated replies, refusals |
| `test_sdk_requests.py` | The Claude calls sent through the real Anthropic SDK to a fake API server: what goes over the wire, streaming, error messages, the language summaries are asked for |
| `test_api.py` | The HTTP API the way the dashboard uses it, including that the API key is stored but never returned |
| `test_translate.py` | Translation to English: telling English from other languages (also in titles, and English written like headlines), cutting a long text into pieces, what is sent to Claude and what is stored, items left alone when a request fails, a scrape never translating, the source's button leaving out what is too long and spending what it said, the reader's button for one item, an older database getting its new columns |
| `test_meaning.py` | Embeddings (made after a scrape, dropped when a title or summary changes, the library's average, switched off or not installed), search by meaning, what belongs to a topic (words, meaning, mentions, your say, reach), the topic page (timeline, trend, sources, up next, what is new since a visit), and the two texts Claude writes: what is sent (which items have a picture), what is stored, how a text is cut into headline, opening line, pictures and body, what it would cost, updating by itself within the limit per run; and a timeline entry's picture. The embeddings in the tests come from a stand-in that counts words, so no test downloads the model. And a topic's card: pictures of its newest items, one per source first, the opening of its last text in plain words, a pinned picture and back to automatic |
| `test_youtube.py` | YouTube and single links: telling videos from channels, a video's page and a channel's feed (small copies saved from the real site), listing a channel with and without a YouTube API key (the API is played by a stand-in), leaving Shorts out or taking them in, a refused key that is never shown, Quick detect, a video written out and written up (what Claude is sent, what is stored), a set number per run, videos that are too long or cannot be read, staying within the limit per run, what Gemini is sent over the wire and what its errors turn into, saving one page and one video, the two Google keys stored but never returned, a first scrape that takes the number asked for and an update that does not fill in below it |
| `test_podcasts.py` | Podcasts: telling Spotify addresses apart, an episode found in its show's feed (Spotify's pages, Apple's directory answer and the feed are copies saved from the real services), a title that was edited, a show that is only on Spotify, an episode written out from its audio and written up (what Claude is sent), Quick detect following a show a few episodes per run, a feed's own transcript used instead of listening, transcripts in every format, what Gemini is handed over the wire and that the uploaded file is deleted again, audio that cannot be fetched or heard, and the two buttons: everything that is left done on request, one episode done from the reader whatever its length, and what one episode runs into said on its job |
| `test_walls.py` | Items behind a login or paywall: recognising one (what a page says of itself, a request to log in or subscribe under a short text, a login address; what the header and footer say does not count), which failures are worth trying again, and what a scrape does with the option off (stored, marked partial) and on (left out, remembered, listed, tried again, earlier partial items removed) |
| `test_removed.py` | Removing an item yourself: gone from the feed, the search and the counts; an update and a deep scrape pass it without opening its page and say so; put back exactly as it was (Claude's work, the embedding, what you said about it on a topic); staying out when its source is deleted and added again, and being let in again; saving it by its address; a run that finds an item gone carries on; and favorites: starred, listed last-starred first, searched within, counted, kept through a removal |
| `test_reddit.py` | The Reddit connector against feeds saved from the real r/geopolitics (`tests/fixtures/reddit/`): posts, comments, shared articles read from their own (faked) sites, refused and paywalled articles, paging, Quick detect's two feeds; and what the comments say: which post an item belongs to, the comments read and summed up on request (what Claude is sent, what is stored), a post without comments, Reddit refusing |
| `test_scrapers.py` | Site scrapers: one written for the fake site (running as a feed, its own deep-scrape limit, a page it trips on, adding it from the dashboard), and the Clingendael scraper against pages saved from the real site (`tests/fixtures/clingendael/`); and the CSIS scraper against pages and a sitemap saved from the real site (`tests/fixtures/csis/`): every kind of card on the first page, the sitemap's runs walked newest first, the American date, text around figures, a 1999 piece read from its PDF, a protected PDF costing its text and not the item, and stopping when the site keeps refusing |

**What the tests do not prove.** The tests never reach the real Claude API or the real embedding model: the request format is checked against the SDK, the loops are driven by scripted replies, and embeddings come from a stand-in that counts words. What was run for real, by hand, in October 2026: source analyses, AI summaries, translations, and one *What is new* and one *The long run* (the measurements quoted above), and the embedding model on a copy of a library of 380 items, which is where the thresholds for "close in meaning" come from. A failure of a real request is shown on its job; the Activity page keeps the full log. **Gemini has run for real** (12 October 2026, in the platform itself): three videos were written out, one of 12 minutes in 28 seconds (1,771 words; 63,711 tokens read) and one of 24 minutes in 65 seconds (3,821 words; 131,324 tokens). **So has a podcast episode, start to finish** (13 October 2026, on a throwaway library): a Spotify link, the show's feed, 33 MB of audio through Gemini's Files API, and Claude's write-up; the numbers are under [Podcasts](#podcasts). The reader's player loaded that audio in a real browser. **Claude writing videos up has too** (the same day, in the platform itself): a channel's 15 newest videos, 13 of them written out and written up with Claude Haiku 5.5 in twelve minutes, for $0.018 in total (13 requests; 77,000 tokens in, 21,000 out), which is about 0.14 cents a video of 9 to 24 minutes. For the other two, both 24 minutes long, Gemini returned no text; the source's Settings tab can try those again. **One thing has not:** listing a channel through the YouTube Data API (there was no key). It is tested against a stand-in; a failure of the real thing is shown on the job with the service's own message. Also run for real, without a key: a channel's feed with and without Shorts, a video's page, saving one video and one article, and the embedded player's page, which reported the test video as playable.

Removing items was tried on a copy of a library of 400 items: a report and a video were removed, their sources (Clingendael, a YouTube channel) scraped again, and both stayed out; put back, the report was identical to what it was, embedding included. The buttons were driven in a real browser (the bin on a card, Undo, a double click, far down a long list, `Delete` in the reader, the Removed items page, a topic page), also against a platform that had not been restarted yet, where the bins rightly do not show.

Besides the automated tests, the dashboard was clicked through in a real browser (wizard, reader, search, topics, settings, phone width), and the scraper was run against real sites: War on the Rocks (100 articles), NOS, Reddit r/drones, Clingendael and CCDCOE (including PDF text), and CSIS (a first scrape into an empty library on 12 October 2026: 160 pages asked for in 198 seconds, none refused, 148 stored with a date and full text; the other 12 tripped on a protected PDF, which has since been made to cost only the PDF's text).

---

## Known limits

- **Sites behind a bot challenge.** A site that answers every non-browser visitor with a challenge cannot be read, and the wizard says so by name: a Cloudflare challenge (HTTP 403) or Imperva's bot check (Incapsula: a page of a few hundred bytes that only loads a script). PISM (pism.pl) runs Imperva's check, but not on every request: on 14 October 2026 a quick look got only the check, and a Claude analysis a few minutes later got the real pages and a source with 12 publications. Expect such a source to come back empty now and then; the clean way to support one is a browser-based fetcher plugin (see [A new fetcher](#a-new-fetcher)), which is not built. Clingendael and HCSS used to look like such sites, but it turned out that Cloudflare was only challenging the `httpx` library the platform downloaded with. Downloads now go through `requests`, which both sites serve normally, with the same honest user agent.
- **Pages that need JavaScript or a login** are not readable. The analysis notices pages with almost no text in their HTML and says so.
- **Feeds only go back so far.** An RSS feed usually holds the latest 10 to 100 items. For an archive you need a listing with pagination, which is what Claude analysis sets up.
- **Paywalled text.** If a site shows only an opening to visitors who are not logged in, the opening is what is stored, marked as partial, unless the source is set to [leave such items out](#items-behind-a-login-or-paywall). Recognising a paywall is a judgement from the page: a site that shows a long opening (400 words or more) or asks for a subscription in words the list does not know is taken for readable, and an item stored before October 2026 was not checked. Sign-up boxes sometimes end up in the text.
- **Dates.** When a listing only shows a year, the item page's own date is used if it has one; otherwise the item is dated 1 January of that year.
- **Partial items are not retried.** When an item page could not be opened and the feed's summary was stored instead, a later scrape does not try again. (With *Leave out items behind a login or paywall* on, nothing partial is stored, and an item that failed for a passing reason is tried again.)
- **Removed items are remembered by their address, and kept.** An item that a site publishes again under another address comes in as a new item. And because a removed item is kept so that it can be put back, removing things does not make `data/platform.db` smaller.
- **Meaning is approximate.** The embedding model is small and reads only a title and a summary. It places an item in the right neighbourhood (energy, Russia, the Gulf) more surely than on the right street (LNG rather than diesel), so a topic that collects by meaning will now and then take in a neighbour: use *Not this*, or set its reach to *narrow*. The thresholds were measured on one library of 380 items; `backend/search/topics.py` and `meaning.py` say what was measured.
- **Trends need history.** See [The topic page](#the-topic-page): until the library has collected steadily for some months, the long comparison says *too little history*.
- **Claude's texts can be wrong**, which is why every sentence carries a source number.
- **Podcasts depend on the show having a public feed** and on that feed still carrying the episode. Finding the feed goes by the show's name in Apple's directory: for two shows of one name the one that has the episode is taken, and when you follow a show, the one by the same publisher. An audio format other than MP3 has not been tried with Gemini.
- **One user.** There are no accounts, and the database is a single local file.

---

## Developing the dashboard

Node.js is only needed to change the dashboard, not to run the platform.

```
cd frontend
npm install        (first time)
npm run dev        dashboard with live reload on http://localhost:5173, talking to the backend on :8765
npm run build      writes frontend/dist, which the backend serves
```

Run `start.bat` alongside `npm run dev`. The look of the dashboard is controlled by the tokens at the top of `src/styles/app.css` (colours, radius, fonts, sidebar width).

Environment variables (in `.env`, all optional): `ANTHROPIC_API_KEY`, `NSP_HOST` (default `127.0.0.1`), `NSP_PORT` (default `8765`), `NSP_DATA_DIR` (default `data`).
