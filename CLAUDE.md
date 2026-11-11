# News Scraper Platform

A personal dashboard that collects publications and news from sources the user plugs in. FastAPI + SQLite
backend, React dashboard served from `frontend/dist`. `README.md` explains the architecture; read the part you
are about to change.

**Starting fresh on this project?** This file and `README.md` together are the handover: the README is the
owner's manual (what exists, how it behaves, what it costs, what was measured), this file is how to work on it
(how to run and test, the routines, the decisions already taken, how the owner likes to work, what is not
built). Read both before changing anything. Neither depends on an earlier conversation.

## Running things (the platform runs on the home server; the code is written here, you are probably in WSL)

- **The owner's platform runs on the home server** since 3 November 2026: `jacob228@192.168.1.161` (ssh from
  WSL with a key, passwordless `sudo -n`; Tailscale `100.75.117.66`), in Docker, container `news-platform`.
  `~/news-platform` holds `compose.yaml`, `config/.env` (their three API keys) and `app/` (the code the image is
  built from); the library and the model are in `/opt/news-platform/data`. README *On the home server* has the
  rest (addresses, backups, putting one back). Reachable on the home Wi-Fi and on Tailscale, port 8765.
- **A change reaches it with `server/deploy.sh`** (from WSL, in this folder): it waits for running jobs, copies
  the code, builds, restarts and checks that the platform answers; `--check` also runs the tests inside the new
  image (do that when `requirements.txt` or anything platform-dependent changed). The owner asked for code to
  reach the server straight away, so deploy every finished change once its tests pass and the dashboard is
  built, and say that you did. Never edit `~/news-platform/app` on the server: the next deploy overwrites it.
- **Reading the real library**: GET requests to `http://192.168.1.161:8765/api/...`, or read-only SQL inside the
  container: `ssh jacob228@192.168.1.161 'docker exec news-platform python -c "import sqlite3; c = sqlite3.connect(\"file:/data/platform.db?mode=ro\", uri=True); print(c.execute(\"...\").fetchall())"'`.
  `data/` on this PC holds no live library any more (the one from before the move is in
  `data/before-server-2026-11-03/`); `data/models` is still used by throwaway servers here.
- Python is the Windows venv: `.venv/Scripts/python.exe`. Run it from the project root.
- Tests: `.venv/Scripts/python.exe -m pytest` (offline, a few seconds). Run them after every backend change.
- Environment variables only reach Windows Python through `WSLENV`, e.g.
  `NSP_DATA_DIR='C:\Users\...\Temp\nsp_dev' NSP_PORT=8799 WSLENV=NSP_DATA_DIR:NSP_PORT .venv/Scripts/python.exe run.py --no-browser`.
  Without it a "test" server silently uses the real `data/` folder. The data folder must be on a Windows
  drive (SQLite cannot lock files under `\\wsl.localhost\`). Reach such a server with
  `/mnt/c/Windows/System32/curl.exe`, not WSL's curl. Also pass `NSP_MODELS_DIR` with the real `data\models`
  folder (and add it to `WSLENV`), or the throwaway server downloads the 240 MB embedding model again.
- Dashboard changes need a build with Windows npm: `cmd.exe /c "npm run build"` inside `frontend/`.
- There is no hot reload: a backend change needs a restart, which a deploy does. `start.bat` only opens the
  server's dashboard; it starts nothing.
- The code is on GitHub, **public**: https://github.com/appelflap789/News_platform, branch `main` (first pushed
  31 October 2026). Commit and push only when the owner asks. Use Windows Git
  (`"/mnt/c/Program Files/Git/cmd/git.exe"`): it has the owner's identity and Git Credential Manager; WSL's git
  has neither. `.gitignore` keeps `.env`, `data/`, `.venv` and `node_modules` out; `frontend/dist` is committed on
  purpose. Before committing a new test fixture, look for the owner's IP address in it: a YouTube watch page
  carries it in its stream links (`ip=`), and `tests/fixtures/youtube/watch.html` had it until it was replaced
  with `192.0.2.1`.

## When the user gives you a website and asks for a scraper

Build a **site scraper**: one Python file in `backend/scrapers/`, written for that site. `clingendael.py` is the
worked example (`csis.py` is a second one, for a site whose listing pages are behind a bot challenge: it reads
the first page and the sitemap, and stops asking when the site keeps refusing) and `backend/scrapers/base.py` the small API (`SiteScraper`, `Stream`, `Item`, `ListPage`,
`Extracted`, and the helpers `self.open`, `self.fetch`, `self.extract`, `self.pdf_text`). The goal is what the
user's older project `../mi-scrape/scrapers/` achieved per site: every item with title, authors, date, the
full text and the PDF link. That project has working scrapers for HCSS, StratCom, CCDCOE, WODC and NATO STO;
when asked for one of those, start from its selectors, but check them against the live site.

1. **Look at the site before writing anything.** Download the listing, its second page, a page from the far end
   of the archive, the page after the last one, and three or four item pages of different kinds. Use the
   platform's own fetcher so you see what a scrape will see:
   `.venv/Scripts/python.exe -c "from backend import db; from backend.fetchers import fetchers; db.init(); r = fetchers.get('http').fetch('URL'); open(r'C:\path\page.html','wb').write(r.content)"`
   Then study the saved HTML. Prefer the most structured door the site has: a JSON API (WordPress
   `/wp-json/wp/v2/posts`, DSpace `/server/api`), then a feed that carries full text, then listing pages.
2. **Read `robots.txt` yourself** and stay inside it (use an unfiltered listing when filtered URLs are
   disallowed, as Clingendael's are). Do not rely on the fetcher for this: Python's robots parser drops rules
   that follow a blank line.
3. **Write `backend/scrapers/<name>.py`.**
   - `list_pages` yields one `ListPage` per listing page, newest first, and returns when the listing runs out.
     Put everything the card shows into the `Item` (title, authors, date, thumbnail, category as a tag).
     Never yield an empty page unless the listing is finished: the scrape stops at the first empty one.
   - `read_item` returns an `Extracted`. `text` is the long content: the whole article, or abstract plus the
     report's PDF text (`self.pdf_text`) when the page only has an abstract. `summary` is short. `pdf_url`
     only for a real PDF. Set `content_type` per item when one listing mixes kinds.
   - All downloads go through `self.open` / `self.fetch`, never `requests` directly, so the platform's
     pacing, size limit and local-address guard apply.
   - When some items of the site are behind a login or paywall, say so per item: `self.extract` does it by
     itself, and a `read_item` that parses the page by hand sets `Extracted.wall` to the reason (see
     `backend/extractors/_walls.py`). The user can then have the source leave those items out. Never build
     a way past the wall.
   - Set `archive_pages` above the size of the archive, and write `notes` (shown on the source's Structure
     tab): how the site is built, what is collected, what is left out and why.
4. **Try it live:** `.venv/Scripts/python.exe -m backend.scrapers test <name> --pages 2 --items 4`. It runs the
   same code path as a scrape and stores nothing. Read the two "gives / would have" lines: a field that is
   often empty needs a reason or a fix. Also run `read_item` on the old pages from step 1; old items often
   have a different layout.
5. **Pin it down offline.** Save a few of the real pages under `tests/fixtures/<name>/` and add tests like the
   Clingendael ones at the bottom of `tests/test_scrapers.py`. Run the whole suite.
6. **Hand over.** Tell the user to restart the platform and add it under *Add source → Built scrapers*
   (or run `.venv/Scripts/python.exe -m backend.scrapers add <name>` yourself; this writes to the real library,
   so say that you did). Tell them what a deep scrape of this site involves: how many items, roughly how long.

Limits to state plainly instead of working around: pages that only exist after JavaScript runs need a
browser fetcher, which is not built (`backend/fetchers/` is where one would go); a site that answers every
non-browser client with a challenge or a login is not scraped.

## Conventions

- Plugins register themselves: a new file in `fetchers/`, `connectors/`, `extractors/`, `analyzers/` or
  `scrapers/` is picked up on start; no list to edit.
- Errors a user should see are `ScrapeError` subclasses (`FetchError`, `ExtractError`, `ConnectorError`).
- YouTube is not a site scraper either: channels and videos go through `backend/connectors/youtube.py`
  (README, *Videos and single items*). What is said in a video comes from Gemini (`backend/ai/gemini.py`),
  never from YouTube's player or caption endpoints, which its terms and robots.txt rule out; do not add that.
  Gemini and Claude's write-up have run for real in the user's platform (12 October 2026: 13 of a channel's
  15 videos, $0.018 on Haiku; for two 24-minute videos Gemini returned no text). The YouTube Data API path
  has not: its first real run is its first real test.
  A channel is listed through its Videos tab (playlist "UULF…"), so Shorts and live streams are left out
  unless the feed's `shorts` option says yes.
- Podcasts go through `backend/connectors/podcast.py` (README, *Podcasts*). A Spotify link only says which
  episode or show is meant (its public page; `/embed/` is disallowed by its robots.txt and not used). The audio
  comes from the show's own feed, found through Apple's podcast directory, never from Spotify's player or its
  internal transcript endpoint; do not add that. Writing out and writing up is `pipeline/videos.py`, the same
  two steps as for a video (`RECORDING` and `HEARABLE` are its two SQL conditions). Run for real once
  (13 October 2026: a 33-minute episode, $0.0022 on Haiku, Gemini 53,744 tokens).
- Reddit is not a site scraper. A subreddit goes through `backend/connectors/reddit.py`, which reads Reddit's
  public feeds (README, section *Reddit*). Reddit answers about one request a minute and 429s anything faster,
  so a live test against it is slow: plan the requests, do not send bursts.
- "What the comments say" (`backend/pipeline/comments.py`) is the pattern for a Claude step on one item at
  the user's request: a route that starts a job, the result stored in columns of its own, a button in the
  reader that shows what it costs, and a view next to *Article*. The reader's `WithComments` and `VideoText`
  are the two examples.
- The user removes items from the library themselves (the bin on a card, `Delete` in the reader). Such an
  item goes through `backend/removed.py`: its address is remembered in the `removed` table and no scrape
  stores it again (`store_article` refuses it, whichever way it comes in), and the row is kept as JSON so that
  *Put back* returns it exactly as it was. So: never delete from `articles` for the user's sake with a plain
  `DELETE`; a new way of storing items goes through `store_article`; and a job that works through a list of
  items must expect one to be gone by the time it gets there.
- A new database column goes in `SCHEMA` and in `ADDED_COLUMNS` (`backend/db.py`); the user's library already
  exists, and `ADDED_COLUMNS` is what gives it the column on the next start.
- The user's API key is in `.env`, so anything that reaches `backend/ai/client.py` outside the test suite
  spends their money. Say what a live check cost.
- Everything "by meaning" goes through `backend/search/embed.py`. The tests get a stand-in that counts words
  (`NSP_EMBEDDER=hash`, set in `tests/conftest.py`), and matching by meaning is off in a test unless the test
  switches it on. The thresholds in `search/meaning.py` and `search/topics.py` were measured on the user's
  library with the real model; a change to what is embedded, or to the model, means measuring them again on a
  copy of the library (free), not guessing.
- **Add-ons** (`backend/addons/`, README *The one mechanism behind all of it*): a part of the platform that lives in
  `backend/addons/<name>/` and `frontend/src/pages/<name>/` and that nothing else imports, so that deleting the two
  folders takes it out. The core only calls `addons.routers()`, `addons.init()`, `addons.after_scrape(job)` (in
  `pipeline/scrape._understand`) and `addons.meta()` (`meta.addons`), and the dashboard's registry picks up the
  pages, the sidebar entry and the Home shelf. Keep it so: never import an add-on from the core or from another
  page, give it its own tables (made by its `init`, referring to items by number in JSON, never by foreign key to
  `articles`), its own settings (`config.add_setting`), its own styles (imported by its `page.jsx`), and show it in
  the dashboard only when `meta.addons` names it. `tests/test_foresight.py` copies the backend without the add-on,
  adds a broken one, and checks that the platform starts; the dashboard was built once without
  `pages/foresight` to check the same (31 October 2026).
- **Foresight** is the first add-on (asked 31 October 2026: "an extra page on the left menu where I have
  foresights. just as with a topic it is possible to create a new foresight or use a foresight topic ... on the
  homescreen also a foresight category ... I let you decide how you make this but it would be interesting to have a
  large topic e.g. demographic aging and be able to see how the literature reacts with this topic"). `FORESIGHT.md`
  is the design it was built from; README *Foresight* is what was built. Decided without asking: one *Foresight*
  entry in the sidebar (not one per foresight), three kinds (trend, weak signal, event), one ring at a time on
  request, PHIA likelihood words, Claude Sonnet as its default model, start over replacing everything. Its
  thresholds (`library.NEAR_FLOOR`, `library.COMMON_SHARE`, `watch.CLOSE`, `watch.WITH_WORDS`) were measured on a
  copy of the owner's library with the real model; the README gives the numbers. Change them only after measuring
  again. Claude's own search terms are deliberately not used to find a foresight's items (they made *Demographic
  ageing* worse), and a signpost's match is shown as "may bear on it", never as a confirmation: meaning cannot tell a
  signpost from its opposite, the re-check says which way an item points.
- **Ask the library** is the second add-on (asked 7 November 2026, after I listed it as an improvement: "I want to
  start integrating the 'ask the library' function"). README *Ask the library* is what was built. Decided without
  asking: its own page in the sidebar, one question at a time (no conversation), Claude Sonnet as its default model,
  24 passages a question, the passages given to Claude as `search_result` blocks with citations on (the API says
  which passage each part rests on; do not switch to asking Claude for [n] in the text). It keeps passages in its
  own tables and, as the rule above says, no foreign key or trigger on `articles`: an item's words are fingerprinted
  in `ask_done.stamp` (lengths) and swept when gone. Its thresholds (`find.FLOOR`, `find.BELOW_BEST`, `find.WEAK`,
  `passages.REFERENCE_MARKS`) were measured on a copy of the owner's library with the real model; change them only
  after measuring again. It added the `started()` hook to `backend/addons` (called after `start_embedding` in
  `main.lifespan`). Its first run splits the whole library: on 7 November 2026 that was 62,657 passages, 20 minutes
  on the owner's PC.
- A new Claude step follows the two on the topic page (`backend/ai/briefing.py`): build the request first, show
  what it will cost before it is sent, and let it count towards `claude_budget_usd` when it runs by itself.
- The two topic texts are news articles (asked for 30 October 2026): Claude writes a `# headline`, the opening,
  and `[[picture N]]` lines choosing pictures of cited items by number (it does not see them); `briefing.article`
  cuts the stored Markdown into parts when the page reads it, so nothing else is stored and older texts still
  show. A text given to Claude again, or shown on a card, goes through `briefing.without_pictures`. The owner
  chose, when asked: two separate articles, Claude picks the pictures, the timeline's picture left of the title
  (empty when there is none). After seeing it they asked for small pictures to the right of the text instead
  of on top, no pictures in the source lists, then "more like an article": the headline, opening line and
  byline across the column, the picture floating right at the start of the body, prose instead of bullets in
  *What is new*, sources as one line of title, and *Rewrite* to write the latest update again
  (`plan_news(rewrite=True)`, which replaces that update). Claude Haiku often leaves out the picture line or
  writes one long paragraph; `briefing.article` is lenient on purpose (see its docstring): keep it so. No generated pictures: on a news-style page
  they would look like photos of what happened.
- Translation runs from its two buttons (`backend/pipeline/translate.py`): *Translate N items* next to *Update*
  (all items not in English, those over `translate_max_minutes` of reading left out) and *Translate to English*
  in the reader (one item, any length); and, since 3 November 2026, after a scrape of a source whose switch
  *Translate new items to English* (`sources.translate_new`, off by default) is on: its new items, the same
  reading limit, within `claude_budget_usd` (`scrape._translate_new`, `translate.among_new`). Asked for SWP: "can
  you make it that it translates it to english? if its more than 30 min read it does not need to do it, but
  lower ones it must translate" (so `translate_max_minutes` is 30 in their library). Which items are not in English is judged locally
  from their words (`needs_translation`); English ones are marked in `translated_at` once (`sort_out`, run when a
  source page is read), so the check is free and only done once per item. Its rule was measured on the owner's
  library (28 October 2026): change it only after judging a copy of the library again and reading what it flags.
  The old per-source switch's column `translate_enabled` is still in older libraries, still set on SWP and
  Institut Jacques Delors, and unused: do not bring it back, it would switch on sources nobody chose.
- Windows Smart App Control is on on the user's PC. It refused to load scikit-learn; numpy, onnxruntime and
  fastembed load. Try a new native package in the venv before building on it, and do not touch the setting.
- Keep the README true: it is the user's manual for this project.

## Trying a change for real

The tests are offline. Before telling the owner that something works, try it once the way they will use it,
on a throwaway copy, never on the real library.

- **The copy.** Make a fresh copy on the server with SQLite's own backup and fetch it:
  `ssh jacob228@192.168.1.161 'docker exec news-platform python -m backend.backup /data/backups --keep 7'` (it
  prints the file; it joins the nightly ones), then `rsync jacob228@192.168.1.161:/opt/news-platform/data/backups/<file>`
  into `%TEMP%\nsp_<something>\platform.db`. Never copy the live `platform.db` itself. In the copy, before starting anything, set every source's
  `interval_minutes`, `enrich_enabled` and (unless that is what is being tried) `write_videos` to 0, and every
  topic's `auto_update` to 0. Set Settings → *Translation model* in the copy to Claude Haiku before pressing a
  Translate button there (`PUT /api/settings` with `{"values": {...}}`): the owner has had Claude Sonnet set (Haiku since early November 2026; check). A throwaway server reads the real `.env`, so
  Claude and Gemini are live in it; this is what keeps it from spending by itself.
- **The server.** Start it on port 8799 with the `WSLENV` line under *Running things*. Stop it by the process
  that listens on that port (`netstat -ano`, then `cmd.exe /c "taskkill /PID <pid> /F"`), never by name.
  To try the Linux image itself, run the copy on the home server instead, without keys so that nothing can
  spend: `docker run -d --name nsp-test --user 1000:1000 -p 8799:8765 -e NSP_ENV_FILE=/nonexistent -e ANTHROPIC_API_KEY= -e GEMINI_API_KEY= -e YOUTUBE_API_KEY= -v /tmp/nsp_test:/data -v /opt/news-platform/data/models:/data/models:ro news-platform`
  (the copy in `/tmp/nsp_test/platform.db`); reach it at `http://192.168.1.161:8799` from Windows, and remove it
  and `/tmp/nsp_test` afterwards. That is how the move was tried (3 November 2026).
- **The browser.** Windows `node` (v24, `WebSocket` built in) can drive a headless Edge through the DevTools
  protocol (`msedge.exe --headless=new --remote-debugging-port=…`): real mouse moves, clicks, keys and
  screenshots. Keep the script and the Edge profile in the same temp folder. An expression that returns a DOM
  node fails; wrap it in `Boolean(...)`.
- **Afterwards.** Delete the temp folder in a command of its own (a refused delete cancels the whole command).
  Say what the check cost: Claude's dollars from the job's usage, Gemini's tokens.
- **A dashboard can meet an older backend**: a deploy ships both together, but a copy on this PC serves the
  freshly built `frontend/dist` with whatever backend it runs, and a browser tab keeps an old dashboard. So a new button is only shown when the backend says it can do it: `meta.scrape`,
  `meta.comments`, `meta.videos.can_write_one`, `stats.removed`, `stats.saved` (the *Single items* page), `translation.waiting.too_long` (a source) and
  `translation` (an article) and `meta.addons.<name>` (an add-on, such as foresight) are such signs; so is a 404 from `/api/scrape-log`
  (Settings → *Scrape log* then asks for a restart).

## How the owner works

- They ask whether something is possible, and when it is, they ask for it as a button on the page they are
  looking at. Each extra thing an item can have (a transcript, the comments) becomes a view next to *Article*
  in the reader.
- They want the recent items of a source, not its whole archive ("just the first 50 or 100"). Do not pitch
  deep scrapes; let them say how far.
- A limit that makes work stop silently reads to them as "it stopped". When a run leaves things undone, the
  page says so and has a plainly named button for the rest.
- They ask what a paid feature costs before using it. Give the total for what they are about to run, with the
  model that is set, measured where possible. A translation run once cost $2.45 where 7 cents had been
  quoted; `claude_budget_usd` exists because of that.
- They do not read German, and want items in another language in English, but by a button and not while
  scraping (28 October 2026: "Do not translate when scraping but when different langauge is detected, next to
  the update and deepscrape can you add a translate button?", items over "20 minute read" left out, and a
  translate option per item in the reader). Whether they want Dutch translated was not asked: the button counts
  Dutch items too (HCSS and Clingendael have some).
- They add and delete sources themselves. Do not write to the real library without saying so. Since the move a
  deploy restarts the platform; they no longer do (3 November 2026: "I indeed want it so that the code on the
  computer can still be written and that it immediately updates on the server").
- They want every source scraped once a day ("I also want it to scrape each day"), in the afternoon ("Can you
  do the scrape somewhere during the day. Around 15:00"): all sources were set to *Every day* when the library
  moved, and *Every day* is now a time of day (`daily_scrape_time`, 15:00, `NSP_TIMEZONE` Europe/Amsterdam;
  `scheduler.daily_slot`), not 24 hours after the last scrape. A new source starts at manual; tell them to set
  it to *Every day*.
- Settings is sorted into sections with a menu of its own (asked 3 November 2026: "You can make a different
  settings menu with more sub-menus so that settings are started to get sorted"); a new group of settings gets a
  section by itself (`pages/settings/page.jsx`, `SECTIONS`). The *Scrape log* section is what they asked for as
  "a menu in the app where it shows what it scraped each day and if it got errors which scraper gave that
  error. The menu does not need to be something big".
- Home (asked 11 November 2026: "the new articles at the top instead of the topics", "showing the same amount of topics as articles"): the latest items first, then the topics as a two-row shelf like the items (`useColumns` from `ArticleGrid`). Then, on the branch `home-front-page` (the owner said yes to it on 11 November 2026), a front page led by the newest topic update and a "since you were last here" line (`backend/api/home.py`, `pages/home/FrontPage.jsx`); not yet merged or deployed until the owner has seen it. Also discussed and not built: a shelf per topic, shelves by kind.
- Dark, sleek interface; plain words in it, in the British spelling it already has.

## Decisions already taken

- **Nothing is built to get past a paywall, a login or a bot challenge**: no archive sites, no proxies, no
  challenge solving. fd.nl was declined for this reason (its robots.txt also rules out AI use). A wall is
  recognised and said, and the owner can have such items left out.
- **Sites that are all bot check are not scraped.** The fetcher names Imperva's Incapsula check and
  Cloudflare's challenge (`fetchers/http.py`). PISM (pism.pl) shows Imperva's check only now and then: I told
  the owner it could not be read after a few requests that all got the check, and their Claude analysis got
  through minutes later (a source of 12 publications). Try more than a handful of requests, spread over
  minutes, before calling a site unreadable. PISM labels its English pages `lang="pl"`; an item's language is
  now judged from its text (`pipeline/scrape._language`), and term suggestions go by that
  (`search/expand.library_languages`).
- **Nothing is taken from a player**: not captions from YouTube's, not audio or transcripts from Spotify's.
  The open routes are Gemini for a public video and the show's own feed for a podcast.
- **Claude and Gemini run only where the owner asked**: a switch per source or a button, each showing its
  price, each within the limit per run. One exception, my choice: the source's *Translate N items* button may
  spend the price it showed plus a quarter (`translate.MARGIN`) even beyond `claude_budget_usd`, because the
  limit made each press translate a few items and silently leave the rest.
- **One local file holds the data**, and there are no accounts. So the platform is not to be opened to the
  internet as it is. On the home server it is published on every address, the home Wi-Fi and Tailscale (the
  owner's choice, 3 November 2026: "if you are on my home wifi the server is reachable but also when you are on
  tailscale. Just with jellyfin"); never forward its port, and do not add a public route.
- **The library stays SQLite**, one container, on the server's SSD; files (should PDFs ever be kept) belong on
  the HDD (`/mnt/sdb1`), outside the database. Backups only through `backend/backup.py` (SQLite's backup API).

## Not built (so that nobody assumes it is)

- Of Foresight (`FORESIGHT.md`): finding signals by itself (its section 10), scenarios from two uncertainties, a
  track record across all foresights, and a re-check that runs by itself. Built on 31 October 2026 and tried on a
  copy of the library; the owner has not used it yet.
- Story cards on Home, a trends page across topics, topics suggested from automatic groups, a world curve
  from GDELT: all from `Platform development options (2026-10-11).pdf` in this folder. (Topics themselves are
  on Home as cards since 14 October 2026: `components/TopicCard.jsx`, pictures from `search/topics.pictures`.)
- A browser-based fetcher for pages that only exist after JavaScript runs.
- Selecting several items at once to remove them.
- The comments summary in search and in the embeddings: it is only shown in the reader.
- Reading protected (AES-encrypted) PDFs: that needs the `cryptography` package, which was not installed.
- A login. (It runs on Linux since 3 November 2026: in Docker on the home server, all tests passing there.)
- A bigger embedding model. Tried on a copy of the library on 4 November 2026; the owner wants BGE-M3 "another
  time" (their material needs better models) and asked to keep the current one for now. What was found: BGE-M3
  runs in fastembed as it is (`TextEmbedding.add_custom_model`, CLS pooling, normalised; `Xenova/bge-m3`
  `onnx/model_int8.onnx` is a ready 8-bit version, 568 MB, vectors 0.98 alike to the full model's). On title +
  summary it was better on abstract and non-English searches and as good elsewhere; on the first 8,000
  characters of the text it was mixed; multilingual-e5-large had one item turning up in nearly every list.
  The 8-bit model on the server's processor: about 7 items a second, a search 20 ms, about 1.1 GB of memory.
  Switching means re-measuring every threshold of search by meaning, topics and foresight on a copy, because
  the centred similarities of another model are not on the same scale. The GTX 1050 in the server works for
  this only with old GPU software (onnxruntime-gpu 1.21, CUDA 12.4, cuDNN 9.1) and has 2 GB; its driver was
  removed again. The owner's PC (RTX 5060 Ti) is the place for one-off bulk embedding, never the daily work.
- Keeping the PDFs themselves (*Keep PDFs*, proposed 31 October 2026): only their text is stored. Search by
  meaning, topics and foresight still use one embedding per item (title and summary); only *Ask the library* uses
  passages.
- Of Ask the library: follow-up questions in a conversation, asking from a topic page or the reader, and the
  expertise map of universities (OpenAlex, CORDIS) discussed with the owner on 7 November 2026; they have not said
  which countries or topics yet.
- Never run for real: listing a channel through the YouTube Data API (there was no key).
- Offered and not answered: captions through `youtube-transcript-api`, as the owner's Note-saver project
  uses, as a second way to a video's transcript.
