# Foresight: from a signal to its second and third order consequences

Design notes, 31 October 2026, written while brainstorming with the owner. **Built the same day** as the Foresight
add-on (`backend/addons/foresight/`, `frontend/src/pages/foresight/`); README, section *Foresight*, is what was
built and what it costs. Where the build differs from these notes: a foresight is read and its first ring worked out
in one request; signpost matches are shown as items that *may* bear on a consequence (the re-check judges them);
the thresholds were measured rather than taken from here; Claude's own search terms are not used to find a
foresight's items; and section 10 (finding signals by itself) is not built. The answers to section 13 are in
CLAUDE.md, under *Foresight*. The worked example (section 8) uses the owner's own library as it was
on 31 October 2026 (1,244 items, 17 sources); the numbers in square brackets are article ids in that library.

The owner's request, in their words: "a feature where I can implement weak signal and trends and the data will
try to create 2nd or 3rth order consequences. This would then be presented in a intersting way on the
platform." Finding signals by itself is optional ("or maybe it can do this").

---

## 1. The idea in one paragraph

The owner types a **signal**: a trend, a weak signal, an event or an assumption ("Hormuz stays constrained
through the winter"). The platform first checks what the library says about it **now** (the premise check),
then works outwards in rings: direct consequences, what those cause, and what *that* causes. Every consequence
says *why* it follows (the mechanism), cites the items it rests on or is marked as reasoning without a
source, carries a likelihood word and a time horizon, and names one or two **signposts**: observable things a
news item would report if the consequence were happening. The platform then watches for those signposts in
everything it scrapes, for free, and the picture lights up as the world confirms or contradicts it.

Why this fits this platform in particular: a chatbot can write a futures wheel, but it cannot (a) ground each
step in the niche think-tank material the owner collected, (b) show how widely each idea is shared, which is
where an information edge lives, or (c) keep checking afterwards. The scraper does all three.

## 2. What the foresight literature offers

| Method | Where it comes from | What to borrow |
|---|---|---|
| **Futures wheel** | Jerome C. Glenn, 1971 | The core structure: the signal in the middle, rings of first, second, third order consequences. Also the main picture. |
| **Implications wheel** | Joel Barker | Score each implication (likelihood, and whether it is good or bad for you). Prune the weak ones before going deeper. |
| **Weak signals** | H. Igor Ansoff, 1975; Elina Hiltunen, "The future sign and its three dimensions", *Futures*, 2008 | Hiltunen's three dimensions map onto the library: *signal* (how visible: how many items), *issue* (how far it has spread: how many different sources), *interpretation* (what it means to the reader: the owner's note). |
| **Cross-impact analysis** | Theodore Gordon and Olaf Helmer, RAND, 1960s | Branches affect each other: one reinforces or dampens another. Draw those links across the wheel. |
| **Indicators and signposts** | Intelligence analysis; Richards Heuer, *Psychology of Intelligence Analysis* (1999), Analysis of Competing Hypotheses | Each consequence names what would show it is happening, *and* what would show it is not. The platform watches both. |
| **Probability yardstick** | UK Professional Head of Intelligence Assessment (PHIA); similar estimative language in US ICD 203 | Fixed words with ranges: remote (≤5%), highly unlikely (10–20%), unlikely (25–35%), realistic possibility (40–50%), likely (55–75%), highly likely (80–90%), almost certain (≥95%). Familiar to a defence and security reader, and makes Claude's wording consistent. |
| **Scenario planning** | Shell, Pierre Wack, 1970s | Later: take the two most uncertain nodes as axes of a 2×2 and write four short futures. |
| **Superforecasting** | Philip Tetlock and Dan Gardner, 2015 | Write the estimate down with a date, and look back later. A track record shows whether the wheels were any good. |

The library already holds foresight-style work that could be fed in as material: SWP's three futures of
geopolitical fragmentation for energy [390] and ECFR's two scenarios in "Sliding doors" [608].

## 3. How a signal is worked out

```
 owner types a signal ──► 1 GATHER (free) ──► 2 PREMISE CHECK (Claude) ──► owner confirms or rewords
                                                                              │
          ┌───────────────────────────────────────────────────────────────────┘
          ▼
 3 FIRST RING (Claude) ──► 4 EXPAND A BRANCH, on request (Claude, its own search per node)
          │                         │
          ▼                         ▼
 5 CROSS-LINKS (Claude, small) ──► 6 WATCH SIGNPOSTS after every scrape (free) ──► 7 LOOK BACK (owner)
```

1. **Gather (free, local).** Meaning and word search over the library for the signal (`search/meaning.search`),
   the 40 best items, with summary and the matching snippet. Newest first among equals: the premise is about now.
2. **Premise check (Claude).** "What does the library say about this right now?" Answer: *holds*, *partly
   holds*, *contradicted*, or *not covered*; a short restatement of the signal as the library sees it; the items
   for and against. The owner can accept it, reword the signal, or keep their own wording ("I know better").
   This step matters more than it looks: see section 8, where the library does not agree that the strait is
   simply closed, and the nuance is the edge.
3. **First ring (Claude).** 4–6 direct consequences, at least one of them a *dampening* one (what pushes back:
   adaptation, substitution, policy). Each has: statement, mechanism ("because…"), domain, horizon,
   likelihood word, basis (*library* with item numbers, or *reasoning*), and signposts.
4. **Expand a branch (Claude, on request).** The owner clicks a node: *Expand · reads 25 items · $0.03*. That
   node's own text is searched in the library first, so ring two is grounded in its own evidence, not the
   signal's. Expanding on request keeps the cost down and lets the owner's interest steer the tree. Stop at
   ring three: beyond it nearly everything is reasoning.
5. **Cross-links (Claude, small).** Given all node texts: which nodes reinforce or dampen each other, and why.
6. **Watch (free).** Each signpost is a small saved search, matched like a topic (`search/topics.members` with
   `reach: narrow`), against every newly scraped item. A match is shown on the node ("seen 3×, last on 2 Nov")
   without spending anything. A *Judge again* button on the signal sends the new matches to Claude when the
   owner wants a fresh verdict.
7. **Look back (owner).** On a date the owner picks, each node can be marked *happened*, *did not happen* or
   *too early to say*. Over months this is the track record.

**The owner's own knowledge is an input, not an afterthought.** They can add a note to any node, add a node of
their own, or overrule a likelihood. Claude is told that the owner's notes are expert knowledge to build on, and
the page marks those nodes as *yours*.

## 4. What a node shows: evidence, spread and the edge

Each consequence shows its **basis**:

- **from your library**: cites items, which the page links (solid outline).
- **recommended or argued in a source, not yet seen**: a think tank says it should or will happen (half filled).
- **reasoning**: Claude's inference with no item behind it (dashed outline). Always shows what would confirm it.
- **yours**: added or overruled by the owner.
- **contradicted**: an item says otherwise (red edge).

And its **spread**, which is how the information gap the owner described can be made visible:

- how many items and how many *different sources* support it, and when it first appeared in the library;
- a node backed by one or two niche sources (one CSIS chart, two ECFR papers) is **edge**; a node every source
  repeats ("oil prices are up") is **consensus**. The page can sort or colour by this.

Likelihood compounds down a chain: three *likely* steps in a row are together closer to a *realistic
possibility*. A ring-three node shows both its own likelihood and the chain's.

## 5. How it could look

**A. The cascade (first to build; works on a phone).** Columns for the rings, read left to right; a node
opens a side panel with its mechanism, cited items as cards, signposts and whether they were seen.

```
 SIGNAL  Hormuz stays constrained through the winter          Premise: partly holds · as of 28 Oct
 ────────────────────────────────────────────────────────────────────────────────────────────────────
 FIRST ORDER                     SECOND ORDER                          THIRD ORDER
 ■ The shortage moves from  ──┬─ ■ China halts fuel exports;  ───────  ┆ Diesel rationing in parts
   crude to diesel and jet    │    Asia's diesel squeeze  [237]        ┆ of Asia            reasoning
   likely · months · 5 items  │
                              ├─ ■ Europe's jet fuel gap hits ─────── ◧ Refineries kept open as
                              │    military readiness  [72][242]         strategic assets   watching 1
                              └─ ┆ Freight firms electrify    ┆
                                   faster (dampening)  [251]
 ■ Qatar LNG loses 17% for  ──── ■ Europe swaps Russian for   ───────  ┆ Winter grid peaks in the
   3–5 years   [561][1210]         US gas; Dutch heaters [862][1208]   ┆ Netherlands        reasoning
 ────────────────────────────────────────────────────────────────────────────────────────────────────
 ■ from your library   ◧ argued in a source, not yet seen   ┆ reasoning   ● edge: 1–2 sources   ○ consensus
```

**B. The wheel (the picture people remember).** An SVG of concentric rings (Glenn's futures wheel): the
signal in the centre, sectors by domain (energy, economy, security, society, politics, technology), node size
by likelihood, outline by basis, cross-links as thin curved lines (green reinforces, red dampens). Nodes whose
signposts were seen this week glow. Good on a wide screen, too dense on a phone; build after the cascade.

**C. The article.** Like the topic texts: "If Hormuz stays constrained: what follows", with a headline, an
opening, a short paragraph per branch and the edge nodes called out. Reuses `briefing.article`. Good for reading
back later and for sharing.

**D. On Home.** A card per signal: "Hormuz · 3 of 11 signposts seen · last: China resumes fuel exports?".
A signpost seen against a node ("contradicts") is the most interesting thing the page can tell the owner.

## 6. Data it needs (sketch)

New tables, in `SCHEMA` and `ADDED_COLUMNS` (`backend/db.py`), as every new table is:

```
signals        id, statement, kind (trend | weak_signal | event | assumption), horizon, owner_note,
               premise_status (holds | partly | contradicted | not_covered), premise_md, premise_sources (JSON ids),
               model, cost_usd, created_at, updated_at, look_back_on
consequences   id, signal_id, parent_id (NULL for ring 1), ring (1..3), statement, mechanism,
               domain, horizon (weeks | months | years), likelihood (PHIA word), basis (library | argued |
               reasoning | owner), sources (JSON ids), spread (JSON: items, sources, first_seen),
               dampening (0/1), owner_note, outcome ('' | happened | did_not | too_early), created_at
links          id, signal_id, from_id, to_id, effect (reinforces | dampens), why, sources (JSON ids)
signposts      id, consequence_id, text, direction (for | against), required_any (JSON), terms (JSON),
               seen (JSON: [{id, at}]), checked_through
```

Signposts carry `required_any` and `terms` exactly as a topic does, so `search/topics.members` can match them
and its measured thresholds apply unchanged. Their terms should include the library's languages
(`search/expand.library_languages`: English, Dutch, German, French), so a Nieuwsuur or SWP item can count.

## 7. What it would cost

Estimates, not measured, from the prices in `backend/ai/client.py` (Claude Sonnet 5.5: $2 per million tokens
in, $10 out; Haiku 5.5 a twentieth of that; Opus 5.5 twice Sonnet), and about 900 characters per item read:

| Step | Reads | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|
| Premise check | 40 items, ~12k tokens in, ~1k out | ~$0.035 | ~$0.002 |
| First ring | 40 items, ~15k in, ~3k out with thinking | ~$0.06 | ~$0.003 |
| Expand one branch | 25 items, ~8k in, ~1.5k out | ~$0.03 | ~$0.0015 |
| Cross-links | node texts only, ~3k in, ~1k out | ~$0.016 | ~$0.001 |
| Watching signposts | local search | free | free |

A typical signal (premise, first ring, three branches opened) is about **$0.20 on Sonnet**. A full wheel (six
first-ring nodes, fifteen expansions, cross-links) is about **$0.55–0.60** on Sonnet, $1.15 on Opus and $0.03 on
Haiku. As with every Claude step here: the price is shown on the button before it is pressed, and it counts
towards `claude_budget_usd`.

Model: Sonnet is the sensible default. This step is reasoning, and Haiku was seen leaving out instructions on
the topic texts (30 October 2026). Measure the first real runs and put the numbers in the README.

## 8. Worked example from the library: Hormuz

The owner's framing: they know, from their expertise in energy and geopolitics, that the Strait of Hormuz would
stay closed up to now, which people without that knowledge did not.

### Premise check: what the library says, as of 28 October 2026

**Partly holds.** The library tells an on-again, off-again story [471]:

- The strait was effectively closed in early 2026 [1320]. Iran attacked two LNG trains at Ras Laffan on
  18 March; QatarEnergy said repairs could take three to five years, a loss of about 17% of capacity [561].
  ECFR warned in March that bombing Iran's energy infrastructure would shut the strait entirely [674].
- In July, movement through the strait was "minimal" again [650].
- From late September, **crude** exports were back at or near pre-war levels [281][113], about 80% by one
  count [242], without a US–Iran deal [113], but relying on the US military protecting tankers [281]. Nearly
  20 commercial ships were attacked in the month to 6 October [234]. Oman is mediating [1160].
- **Refined products lag by about 50%** and freight stays high [113]; France's finance minister said 30–40% of
  Gulf refining capacity was damaged or destroyed [223]. "The real shortage isn't crude, it's everything made
  from it" [242].
- Pulling the other way: the IEA warns of a possible oil glut of 4 million barrels a day [188].

So the library would reword the signal: *"Hormuz stays open for crude under escort, but constrained and costly
for refined products, LNG and fertiliser, through the winter."* That reworded version is a sharper edge than
"closed": the obvious reading is that an open strait means relief, while the library says the pain has moved
downstream.

### First ring

| # | Consequence | Mechanism | Basis | Spread |
|---|---|---|---|---|
| A | Diesel and jet fuel stay tight while crude eases | Gulf refineries damaged; product tankers more exposed; thin European hub stocks | library [242][113][223][245] | 4 items, all reposts on r/energy and r/geopolitics |
| B | Qatar's LNG shortfall lasts years; the US becomes the swing supplier | Ras Laffan repairs take 3–5 years; Qatar buys US gas to meet contracts | library [561][1210][525] | 2 sources (CSIS, r/energy) |
| C | Fertiliser and sulphur shortages hit food-importing regions | Urea and sulphur exports through the strait hit | library [650][632] | **edge**: 2 items, both ECFR |
| D | Helium gets scarce and expensive | Qatar supplied about a third of the world's helium before the closure; the US raised output | library [525] | **edge**: 1 item (one CSIS chart) |
| E | Gulf states route around the strait, and Iran adapts | At least seven new or expanded pipelines; first post-US security arrangement discussed | library [471][516][548] | 1 source (CSIS, 3 items) |
| F | Oil prices split by region | Tanker logistics disrupted; North America far cheaper than Europe and Northeast Asia | library [1480][1479] | 1 source (Zeihan) |
| G | *Dampening:* governments and markets absorb part of the shock | IEA release of 400 million barrels; China and Japan cut imports; EU states spent €33bn | library [525][1497] | 2 sources |

### Second ring (some branches)

- **A → Asia's diesel squeeze:** China suspended fuel exports for October [237]. *Library.*
- **A → Europe's military fuel readiness:** in HCSS's conflict scenario the EU's aviation fuel deficit could reach
  24%, worse in the Netherlands; declining refining and import dependence [72]. *Library.*
- **A → Africa refines its own oil:** the closure exposed African fuel import dependence [214]. *Library, thin.*
- **A → *dampening:* fleets electrify faster:** FedEx expects $300M of electric trucks to save $800M in
  diesel [251]. *Library, one example.*
- **A → data-centre backup:** more diesel demand from data-centre generators, and interest in storage
  instead [1211][192]. *Library:* cross-link to the owner's *Datacenters* and *Diesel prices* topics.
- **B → Europe swaps dependence:** reliance on US gas called as serious a risk as Russian gas was [862]; Dutch
  gas at €1.77/m³ in October, nearly half of an RTL panel planning electric heating [1208]. *Library.*
- **C → North Africa under strain:** Egypt's and Tunisia's finances, the Morocco–Algeria balance and Libya [650];
  a global food-crisis risk together with Ukraine and El Niño [632]. *Library.*
- **E → Iran and the Houthis hit the bypasses:** the 2026 Houthi drone attacks on Saudi Arabia's East-West
  pipeline [471]; why Iran and the Houthis keep winning the waterways [1541]; Houthi strikes on Riyadh's airport
  [1049]. *Library.*
- **G → help gets targeted:** Italy, Hungary and Ireland move from price caps for everyone to targeted aid [1497].
  *Library.*
- **A + B → a push to clean energy:** solar investment in Southeast Asia roughly quadrupled in the first half
  [863]; China "passed the stress test", which strengthens its hand in clean technology [1320]. *Library:*
  cross-link to the *rare earth materials* topic.

### Third ring (mostly reasoning, which is the point: each needs a signpost)

| From | Consequence | Basis | Signpost to watch |
|---|---|---|---|
| A → Europe's fuel gap | European governments keep refineries open as strategic assets | *argued*: HCSS recommends preserving critical refining capacity [72] | Dutch or EU support for a refinery; a planned closure cancelled ("raffinaderij", "refinery closure") |
| B → Dutch heaters | Winter peaks strain the Dutch grid locally | *reasoning*: nothing in the library on Dutch grid congestion | "netcongestie", TenneT or Liander winter warnings |
| C → North Africa | More crossings to southern Europe from Tunisia, Libya, Egypt | *reasoning* | Mediterranean crossing figures; bread or fuel protests |
| E → attacks on bypasses | Demand for cheap counter-drone defence at sea and on pipelines | *reasoning*, with [1155] (shore missiles, drones and mines can disrupt trade without a big navy) | Cross-link to the *high-low mix* topic: navies buying cheap interceptors |
| A + glut [188] | Refining margins stay high while crude is cheap: refiners outside the Gulf profit | *reasoning*, and the tension between [242] and [188] is itself a signpost | Crack spreads or refining margins in the news |
| D → helium | Chip fabs, MRI and cryogenic research feel it | *reasoning* (the quantum item [554] is about helium-3, a different supply chain: do not cite it) | Helium price or rationing news |

Signposts **against** the wheel: Gulf refineries restarting; China resuming fuel exports; Ras Laffan's force
majeure lifted; the US ending tanker escorts (which cuts the other way: crude flows fall again).

**What the library does not cover** (shown on the page, so a gap is not mistaken for an answer): freight and
insurance numbers, Asian LNG buyers beyond Thailand [534], fertiliser prices, Dutch grid congestion, and Gulf
refinery repair timelines.

## 9. Pitfalls, and what guards against them

| Pitfall | Guard |
|---|---|
| Chains that sound clever but each link is weak | Mechanism required per node; compound likelihood shown; stop at ring three; prune before expanding |
| The library's bias: European think tanks and r/energy, thin on Asian, market and US views | The source mix shown per node; the premise check lists what is *not covered* |
| Confirming what the owner already believes | Premise check first; at least one dampening consequence per ring; signposts *against* as well as *for* |
| Claude mixing its own knowledge with the library | Basis per node: *library* cites items, anything else is *reasoning*; the date "as of" on the premise |
| A wrong citation (as [554] would have been for helium) | Claude cites by number from the items it was given; the page shows the cited item's title beside the claim so a mismatch is visible |
| Old facts: the library is a snapshot | Signposts watched after every scrape; *Judge again* with the new matches |
| Cost running away | Branches expand only on a click with the price on the button; `claude_budget_usd` |
| Haiku leaving out instructions | Sonnet by default; strict JSON with a lenient reader |
| Treated as advice (the owner also asked about investing) | A *markets* lens can name affected sectors, never a buy or sell; the track record keeps everyone honest |

## 10. Finding signals by itself (later, optional)

All local and free, Claude only to word a candidate:

- **Rising:** words or groups of items whose weekly count jumps (topics already keep a 26-week `trend`). This is
  close to "a trends page across topics", listed as not built in `CLAUDE.md`.
- **Weak:** an item close to the owner's interests (their topics) but far from everything else in the library,
  or a claim that only one source makes (Hiltunen's low *issue* spread). Helium [525] would have been one.
- **Contradictions:** two recent items that disagree, like the glut [188] against the product shortage [242].
- A **signal inbox** where such candidates wait, each with *Make this a signal*. The reader could have the same
  button on any item.

## 11. Where it would go in the code

- `backend/foresight/` with `wheel.py` (plan and run the Claude steps, following `backend/ai/briefing.py`:
  build the request, show the price, then send) and `signposts.py` (matching after a scrape, like the topics'
  auto-update in `briefing.update_topics`).
- `backend/api/foresight.py`: `GET/POST /api/signals`, `GET /api/signals/{id}`,
  `POST /api/signals/{id}/premise`, `POST /api/consequences/{id}/expand`, `POST /api/signals/{id}/links`,
  `POST /api/signals/{id}/judge`, `PUT /api/consequences/{id}` (owner note, outcome).
- Jobs through the existing job manager, so progress and cancel work as for every other Claude step.
- `frontend/src/pages/foresight/`: a list of signals, a signal page with the cascade, later the wheel (inline SVG).
  New buttons only appear when `meta` says the backend can do it, because the owner restarts it themselves.
- Tests offline with the hash embedder and a stand-in for Claude, like `tests/test_meaning.py`.

## 12. Order of building (proposal)

1. **Signal page:** type a signal, premise check, first ring, expand on click, the cascade, sources per node.
2. **Watching:** signposts matched after each scrape, seen or contradicted on the node, a card on Home, owner
   notes and the owner's own nodes, *Judge again*.
3. **Wheel and links:** the SVG wheel, cross-links, the article view, look-back and the track record.
4. **Signal inbox:** candidates found by the platform.

## 13. Questions for the owner (open)

1. Is a signal typed freely, or also made from an item (*Make this a signal* in the reader)?
2. One ring at a time with expand-on-click (cheap, steerable), or the whole wheel in one go?
3. Which lenses matter most: energy, defence and security, the Netherlands, markets?
4. Likelihood in words (PHIA yardstick) or in percentages?
5. Which view first: the cascade, the wheel or the article?
6. Should a seen signpost only show on Home, or also send something?
7. Sonnet or Opus for this step?
8. Should the platform keep a track record (look back on a date and mark what happened)?
