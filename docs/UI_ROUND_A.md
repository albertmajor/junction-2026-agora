# UI round A: type with personality, Context.dev live, a landing page, a tidier result, flags

Status: lead-designer decisions for round A (owner items A1-A4 + FLAGS). Builders follow this file.
Base spec: DESIGN.md (the line, the Turn, the all-in rule). Nothing here changes the engine's ranking.
Before screenshots: `/private/tmp/claude-501/-Users-albertmajor/74b73fcc-8778-49b1-9032-b77c63a35414/scratchpad/uiA/before/{d,m}-{0start,1hunting,2result,3sheet}.png` (1440 / 390, offline replay).

Rules that do not change:
- **The main number everywhere is the all-in price** (tag + shipping + import VAT + fees). Tag price is secondary.
- **Cutouts stay OFF by default** (`core.CUTOUTS`, `?cutouts=1` only). Plain listing photos.
- Calm "software UI", warm paper and ink. Not neo-brutalist: no offset shadows, no sticker rotations, no all-caps, no emoji.
- `prefers-reduced-motion`: every new motion falls back to opacity only.
- 390 px: no horizontal page scroll, 16 px gutter. Dark mode keeps working (tokens in `:root`, dark overrides
  under `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])` and `:root[data-theme="dark"]`).
- Process safety: stop servers only by the PID you saved from `$!`. Never touch port 8765. No live Context.dev calls.

---

## 0. What the before shots show (the problems we fix)

1. **Type.** Instrument Serif is a condensed display face; next to Inter Tight (also tight) the page reads narrow and
   generic. The headline "€825 all in. Used, tori.fi." looks squeezed. Nothing has a voice of its own.
2. **Context.dev is invisible.** The reading row (pills with a letter in a circle, "reading…") is small, mostly
   letters instead of logos, and vanishes 2.4 s after the hunt. Nobody can tell which API did the work.
3. **Start screen stops at the fold.** Question, box, shelf, footer. Nothing to scroll to.
4. **Result screen is loose.** The verdict paragraph wraps at an odd width; "Seller · platform no reviews found" is an
   orphan line; the switch, axis caption, "dearer →" and the your-price tag float in a row with no grid; "not counted (1)"
   floats; the ledger has a huge empty middle, the all-in column is not aligned (the "+ shipping" suffix pushes the
   numbers), and "no reviews found" repeats on every row as noise. The sheet's close button sits on the sheet's edge.
5. **Where is it from?** Only a "· FI" text in the sheet, guessed in the browser from the TLD/currency.

---

## 1. Type (A1)

### Decision

| role | face | why |
|---|---|---|
| display (start question, verdict number, receipt total, landing headings, logo) | **Fraunces** (variable: opsz, wght, SOFT, WONK) | warm "old-style soft" serif with real character; the optical-size axis keeps it crisp at 40-64 px; `SOFT` rounds the terminals (friendly, not cute); `WONK` gives the italic logo its leaning n/m/h. Much wider and calmer than the condensed Instrument Serif. |
| UI text | **Instrument Sans** (variable: wdth, wght) | a grotesk with a little warmth (open apertures, slightly humanist), normal width (replaces the tight/condensed Inter Tight), very legible at 13-15 px. |
| numbers in tables, receipts, live log | **IBM Plex Mono** 400/500 | a typewriter-warm mono that fits paper and receipts better than JetBrains Mono. |

Exact Google Fonts link (replace the current one in `index.html`; verified 200):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght,SOFT,WONK@0,9..144,300..700,0..100,0..1;1,9..144,300..700,0..100,0..1&family=Instrument+Sans:ital,wdth,wght@0,75..100,400..700;1,75..100,400..700&family=IBM+Plex+Mono:wght@400;500&display=swap">
```

Tokens (`css/base.css`, builder 1):

```css
--serif: "Fraunces", "Iowan Old Style", Georgia, serif;
--sans:  "Instrument Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
--mono:  "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
--display-vs: "opsz" 96, "SOFT" 50, "WONK" 0;     /* big serif */
--logo-vs:    "opsz" 48, "SOFT" 100, "WONK" 1;    /* italic logo */
```

Type scale (big next to small, no 18-28 px middle tier except landing section heads):
- Start question: Fraunces 400, 64 px / 1.02, `letter-spacing: -0.02em`, `font-variation-settings: var(--display-vs)`; 44 px on phones.
- Verdict headline: Fraunces 400, **40 px** desktop / 30 px phone, line-height 1.05; the euro figure in the headline is
  Fraunces **500** with `font-variant-numeric: lining-nums tabular-nums`. (Fraunces is wider than Instrument Serif: 40 px
  is the same line length as the old 44 px.)
- Receipt total: Fraunces 500, 40 px, lining numbers.
- Logo: Fraunces italic 400, 26 px, `var(--logo-vs)`.
- Landing section heads: Fraunces 400, 36 px (28 px phone). Landing kicker: Instrument Sans 500, 13 px, `--ink-2`.
- UI: Instrument Sans 400/500, 15 px body, 13 px labels. `font-feature-settings: "tnum" 1` stays on body.
- Mono: IBM Plex Mono 12 px for tick numbers, ledger numbers, receipt lines, live log, JSON.

### Colour accents (personality, still calm)

Keep paper/ink. Add three accents, each with one job, always next to a word:

```css
--accent: #F5D547;   /* yellow highlighter: the pick, your-price tag (unchanged) */
--live:   #D9480F;   /* vermilion: "live" dot, the reading progress hairline, the Context.dev pulse. Nothing else. */
--ink-blue: #23406B; /* deep ink blue: links in the landing, code blocks' keys, "Powered by Context.dev" mark */
--ok: #2F6B4F;  --flag: #B4532A;  --alarm: #B3261E;   /* unchanged */
--paper-2: #EDE8DD;  /* a second paper tone for landing bands and the live-log panel */
/* dark: --live:#FF7A45; --ink-blue:#9DB8E8; --paper-2:#1D1B18 */
```

### Motion and small details

All transform/opacity, ease `--ease`, no bounce.
1. **Load:** question, box, examples rise 10 px with a 60 ms stagger (exists); the start shelf drops in after 200 ms.
2. **Headline number counts up** when the verdict lands: 600 ms from the cheapest tag to the all-in figure, tabular
   digits so nothing jiggles (verdict.js). Reduced motion: no count.
3. **Logo**: on hover the italic "agora" eases `SOFT` 100 → 0 and `wght` 400 → 500 over 300 ms (variable-font morph,
   `transition: font-variation-settings`). The dot in the mark gets the `--accent` yellow (exists).
4. **Live dot**: 6 px `--live` dot with a 1.6 s opacity breathe next to "Reading the web live".
5. **Landing grid reveal**: IntersectionObserver, cards fade + rise 8 px, 40 ms stagger per row, once.
6. **Colour-in**: landing product photos are muted (see section 3); on hover/focus they ease to full colour in 400 ms
   and lift 2 px with a soft contact shadow.
7. **Scroll cue**: under the start hero a 1 px hairline grows 0 → 32 px, then the word "browse ↓" fades in. Once.
8. **Flags** pop in with a 160 ms fade when the origin arrives (never move layout: the slot is reserved).

---

## 2. Live log: "what Context.dev is reading right now" (A2)

Replaces the `#reading` pill row (main.js `drawReads`/`readPage`/`flyToLine` move into `js/livelog.js`).

### Desktop (≥ 641 px) during the hunt

A calm panel under the header, full content width, `--paper-2` background, 12 px radius, 1 px hair border,
max 6 visible rows (newest on top), row height 32 px.

```
+-------------------------------------------------------------------------------------------------+
| ● Reading the web live                       24 pages · 17 offers · 9.4 s     Powered by [◆] Context.dev |
|-------------------------------------------------------------------------------------------------|
| [tori]   tori.fi           marketplace search · used   Context.dev  scrape    ✓ 8 offers  ▢▢▢▢+4 |
| [kl]     kleinanzeigen.de  marketplace search · used   Context.dev  scrape    reading ━━━━━─      |
| [B&H]    bhphotovideo.com  product page · new          Context.dev  product   ✓ 1 offer   ▢       |
| [e]      e-infin.com       product page · new          free  JSON-LD          ✓ 1 offer   ▢       |
| [ebay]   ebay.com          product page · used                                skipped · accessory  |
| [Q]      search            "sony a7 iii body used"     Context.dev  search    15 results           |
+-------------------------------------------------------------------------------------------------+
```

Columns (CSS grid: `24px minmax(140px,180px) minmax(0,1fr) 150px 200px`):
1. **Mark**: 20 px brand logo in a 24 px round plate (`--receipt`, 1 px hair ring). Lookup order:
   `assets/brands.json` (Context.dev brand logos, `media.brand.dev`) → `https://www.google.com/s2/favicons?domain=<d>&sz=64`
   → monogram (Fraunces, first letter). `onerror` walks the chain. Lane rows (search) use a small magnifier glyph (inline SVG).
2. **Domain** (Instrument Sans 500, `--ink`).
3. **What**: page kind + lane in `--ink-2`: "marketplace search · used", "product page · new", "provider price list ·
   service", "search: “…query…”". Source fields: `source.list_page`, `source.direct`, `source.lane`, `lane.queries`.
4. **Method chip** (IBM Plex Mono 11 px): which Context.dev endpoint did the read. From `offer.read_via` (or the
   source's `paid`/`direct` before the offer lands):

   | read_via | chip |
   |---|---|
   | `contextdev_markdown_split` | `Context.dev · scrape` |
   | `contextdev_json` | `Context.dev · extract` |
   | `contextdev_product` | `Context.dev · product` |
   | `search_highlight` / lane rows | `Context.dev · search` |
   | `jsonld` | `free · JSON-LD` (grey: we read it ourselves) |

   Context.dev chips carry a 4 px `--ink-blue` square; free reads a hollow square.
5. **Yield**: while reading, a 2 px `--live` progress hairline that creeps (indeterminate, CSS) plus "reading";
   then "✓ N offers" in `--ok` with up to 4 **18 px offer thumbnails** (plain photos, round 4 px) that pop in one
   by one (70 ms drip) and then **fly to the line** (the existing 450 ms flight, now from the thumbnail, max 4
   in flight); "+N" after 4. Skips: "skipped · <short reason>" in `--ink-3`, row at 55% opacity
   (reason shortened: "different model", "accessory", "no price", "rate limit", "out of time").

Header line: live dot + "Reading the web live" (Instrument Sans 500), counters in mono (pages, offers, seconds; the
clock from main.js's tick clock moves here), right: **Powered by Context.dev** mark (section 2.1).
Replays say "Replaying a recorded live hunt" with a hollow dot instead of the live dot (honest).

Row motion: a new row enters from the top: the list FLIPs down 32 px (200 ms) and the new row fades in. Rows update
in place (no re-render flash): build each row once, keyed by domain, mutate its cells.

### After `done`

The panel collapses (320 ms height + opacity) into **one summary line** that stays on the result screen:

```
✓ Read 24 pages on 20 sites in 20.1 s · 11 via Context.dev, 6 free · 17 offers      show log ▾    Powered by [◆] Context.dev
```

"show log" expands the full log (all rows, scroll at 280 px, grouped: offers first, then skips grouped by reason).
Budget numbers come from the `budget` event (`requests`, `free_reads`, `cache_hits`, `pages`, `offers`).

### Phone (≤ 640 px)

Panel without columns 3-4: mark, domain, yield. Max 3 rows. Header: live dot + "Reading live" + counters; the
Powered-by mark goes to the summary line after `done`. The old ticker (`#ticker .tick-text`) is hidden on desktop
while the live log is on (`#app[data-log="on"]`, set by livelog.js; CSS rule in base.css) and stays the single
aria-live line on phones.

### 2.1 "Powered by Context.dev" mark

`<a class="cd-mark" href="https://context.dev" target="_blank" rel="noopener">Powered by <img
src="https://www.google.com/s2/favicons?domain=context.dev&sz=64" alt="" width="14" height="14"> <b>Context.dev</b></a>`
Instrument Sans 12 px, `--ink-2`, the word "Context.dev" in 500 `--ink-blue`, image falls back to a 10 px `--ink-blue`
square. Appears in: live-log header and summary line (livelog.js), landing "Powered by" section and footer (builder 1).

---

## 3. Landing page below the search (A3)

`index.html` gets `<section id="landing" aria-label="About">` **after `</main>` and before `#rule`**, shown only
when `#app[data-phase="start"]`. The start hero gets `min-height: calc(100svh - 120px)` so the first grid row peeks
~80 px above the fold. Sections alternate `--paper` / `--paper-2` full-bleed bands
(`margin-inline: calc(50% - 50vw); padding-inline: calc(50vw - 50%)`), max text width 640 px, 96 px vertical
rhythm (64 px phone).

### 3.1 Browse grid

Kicker: "Browse" · Head: **"Or start from something real."**
Sub: "Real listings our hunts have read, at the price on their tag. Pick one and we hunt it across Europe, all in."

- Data: `assets/shelf.json` (13 cut-out objects; fields `img, title, price_eur, site, country, condition, query, recording?`)
  plus the three recorded hunts (from `GET /recordings`, labelled like the example chips, image = the pick's photo
  from a small static map in landing.js: Sony → `assets/shelf/kamera-0.png`, iPhone → `assets/shelf/iphone-15-0.png`,
  cleaning → a Fraunces monogram plate "clean").
- Grid: `repeat(auto-fill, minmax(200px, 1fr))`, 24 px gap; phone 2 columns, 12 px gap. Cards have no box: a
  1:1 `--paper-2` plate (12 px radius) with the object centred (`object-fit: contain`, 78% size) and under it:
  title (Instrument Sans 500 14 px), then mono 12 px `€72 · blocket.se · used` with a 12 px flag (shelf `country`).
- **Muted**: `filter: grayscale(1) sepia(.12) contrast(1.02) brightness(1.04); mix-blend-mode: multiply;` (dark mode:
  no blend, `opacity: .85`). Hover/focus: full colour, lift 2 px (section 1, motion 6).
- Click/Enter: `bus` event `ask` {q}. The integrator wires `on('ask', d => run(d.q))` in main.js and scrolls to top.
  Offline (no live search: `GET /status` → `live: false`), cards **without** a recording show a quiet "live only"
  label and run anyway (the honest "offline we have three recorded searches" message appears); recorded ones lead
  the grid with a small "recorded hunt" label.
- Card order: the three recorded hunts first, then shelf by price.

### 3.2 How it works

Kicker: "How it works" · Head: **"One question. Every shop. One line."** Three columns (stacked on phone), each with a
tiny inline-SVG drawing in the line style (1.5 px ink, one yellow dot):
1. **You ask once.** "Anything you can buy: a camera, a used iPhone, someone to clean your flat."
2. **We read the shops, live.** "Context.dev reads marketplace searches and shop pages while you watch: price,
   shipping, condition, and where it ships from."
3. **You see what you'd pay, all in.** "Every offer lands on one euro line at tag + shipping + import VAT + fees.
   The cheapest you can surely buy gets the circle."
Under them, one line: "Not ready? Drag your price onto the line and we'll watch it for you."

### 3.3 Sources

Kicker: "Sources" · Head: **"Where we look."**
Sub: "Second-hand marketplaces, refurbishers and big shops across Europe, plus any shop the search turns up."
- Logo wall from `assets/brands.json` (23 brands): 40 px tall cells, logo max 96×28 px, `grayscale(1) opacity(.7)`,
  colour on hover; name under each in 12 px `--ink-2`; grouped in three rows with small labels:
  "Second-hand" (tori, blocket, finn, dba, kleinanzeigen, marktplaats, 2dehands, olx, vinted, gumtree, leboncoin,
  wallapop, subito, willhaben, ebay.de), "Refurbished" (backmarket, rebuy), "Shops" (amazon.de, verkkokauppa.com,
  power.fi, cdiscount, idealo, pricerunner).
- Footnote (mono 12 px): "193 second-hand sources in our registry · free JSON-LD first, Context.dev where it matters."

### 3.4 For agents

Kicker: "For agents" · Head: **"Same line, for your agent."**
Sub: "Agents get the same offers in the same order, ranked by all-in price, over MCP or plain JSON. Read-only:
Agora never buys for an agent."
Two code blocks (IBM Plex Mono 13 px on `--receipt`, 1 px hair, 10 px radius, keys in `--ink-blue`, copy button):

```bash
claude mcp add agora -- /path/to/Junction/.venv/bin/python -m agora.mcp_server
```
```bash
curl "$ORIGIN/api/offers?q=sony+a7+iii+body&limit=3"
```
(`$ORIGIN` is filled from `location.origin` at runtime.) Under: tools as a small table — `find_offers`, `get_offer`,
`explain_price`, `watch_price` (one line each, from docs/AGENTS_GUIDE.md). Links: "what an agent sees →" (emits
`agent` {on:true} after running the Sony example) and "API index →" (`/api`).

### 3.5 Powered by Context.dev

Band in `--ink` with `--paper` text (the only dark band; in dark mode `--paper-2` with a `--live` hairline top).
Head: **"Powered by Context.dev."**
Body: "Every page Agora reads goes through Context.dev: web search to find the shops, product extraction, structured
JSON from listing pages, markdown scrapes of marketplace search results, and the brand logos you see in the live log.
We spend it carefully: free JSON-LD first, paid reads where they matter."
Four mono facts in a row: "search · product · extract · scrape" (one per endpoint, each with a one-line note).
Link: "context.dev →".

### Brand name in one place

The name will change. **One HTML spot:** `index.html` `<html data-brand="Agora">`, `<title>Agora</title>`, the logo
`<span>` text. **One JS spot:** `core.js` `export const BRAND = document?.documentElement?.dataset.brand || 'Agora'`
(integrator adds it). Modules read it with `import * as core from './core.js'` and `core.BRAND || 'Agora'`
(a namespace import never throws if the export is missing). No other file hard-codes "Agora" in copy.

---

## 4. Result screen cleanup (A4): tidy, keep every feature

Grid: 12 columns, 24 px gap, content max 1240 px (unchanged container).

```
header   [logo] [ box                    ]                               how it works · for agents
log      ✓ Read 24 pages … 17 offers   show log ▾                          Powered by Context.dev
verdict  [ cols 1-8 ]                                            [ cols 9-12: pick card ]
         €825 all in. Used, tori.fi.                              [photo 112]  🇫🇮 tori.fi
         Added on top   nothing; shipping not listed             used · Helsinki
         Cheapest new   €1,029 · e-infin.com 🇳🇱?                ★ platform · no reviews
         Lowest tag     €633 at allenscamera.net 🇺🇸? is €795 …   [Open listing] [Receipt]
line     ( the line, unchanged behaviour )
toolbar  [Price on the tag | What you actually pay]  € you pay, all in: …   not counted (1) ▸   [your price]
ledger   All 16 offers, by what you pay, all in                                            filter: all · sure only
         #  photo  shop                  title                     cond.   tag     all in        note
```

Verdict (verdict.js + sheet.css styles for `#verdict`):
- Headline unchanged in words, Fraunces 40 px, count-up on the number.
- The small paragraph becomes a **3-row facts list** (`<dl class="v-facts">`, label column 120 px `--ink-3` 13 px,
  value 15 px): "Added on top", "Cheapest new / refurbished / used" (one row per condition present, max 2),
  "Lowest tag" (the lowest-tag contrast line). Same sentences as now, split at their natural seams; nothing removed.
- **Pick card** on the right (desktop ≥ 1100 px; under the headline on narrower): photo 112 px plate, flag + shop,
  condition · city, the trust mark (replaces the orphan "Seller ·" line), buttons "Open listing" (`goHref`) and
  "Receipt" (emits `select`). Phone: the existing winner photo + headline layout, pick card buttons under the facts.

Line toolbar (line.js / line.css): one row under the axis, CSS grid `auto 1fr auto auto`: switch, axis caption,
the set-aside tray as a compact chip "not counted (1) ▸" that opens its list inline below, and room for the tag
(tag.js is not changed; leave 160 px clear at the right of the toolbar for `#tag`). "dearer →" moves under the axis
end as a 12 px label.

Plates on the line: a 14 px flag in the plate's top-left corner (full plates only; dots get it on hover/focus
growth). Caption stays "€825 tori.fi"; for an unsure origin no extra text, the flag shows it (section 5).

Ledger (ledger.js; styles in line.css):
- Fixed columns: `28px 44px minmax(170px, 230px) minmax(0,1fr) 88px 80px 112px 120px`
  (# · photo · shop · title · condition · tag · all in · note). Phone: hidden (as now).
- Shop cell: flag + domain on line 1; trust mark on line 2 (11 px) **only** when it says something
  (solid, mixed, watch out, a star rating); "no reviews found" becomes nothing (the sheet still says it).
- **All in** right-aligned, IBM Plex Mono 500, numbers aligned. "+ shipping" / "no shipping to FI" moves to the
  note column as a small word, not a suffix. Tag column `--ink-3`.
- Note column: "the pick" (yellow highlighter), "late", "still costing", "+ shipping", "re-checked after reviews".
- Row height 52 px, hover `--paper-2`, the pick row has a 2 px `--accent` left rule.
- Header row (`role=row`, 12 px `--ink-3`): "shop · title · condition · tag · all in".
- Optional segmented filter at the right of the heading: "all · sure only" (sure = not `core.isUnsure`). Default all.
- Keep exports `rows()` (tests use it) and keep `statusFor` in verdict.js (tests/web/live_ui.test.mjs imports it).

Sheet (sheet.js / sheet.css):
- Close button inside the sheet (top-right 12 px inset), 36 px hit area.
- Header order: photo plate, title, **meta row**: `[flag] Finland · Helsinki · tori.fi · used` (replaces "tori.fi · FI").
- New receipt-adjacent row **"Ships from"**: `[flag] Finland — Helsinki` + basis line in 12 px `--ink-2`
  ("from the listing's location" / "a guess from the .com domain and prices in US dollars") and
  **"Ships to Finland"**: "yes, domestic" / "yes, the shop says so" / "no, the shop does not ship to Finland" /
  "not confirmed by the shop". Uses `origin.basis_text`, `origin.ships_text`.
- Group the folds (resale, reviews, why not stars, haggle, how this was worked out) under one 13 px `--ink-3`
  heading "Details", same order. Nothing removed.

---

## 5. Flags (owner FLAGS item)

Component (new `js/flags.js`, builder 3; used by line, ledger, sheet, verdict):

```js
export function originOf(item)            // (item.tc && item.tc.origin) || (item.offer && item.offer.origin) || null
export function flagHtml(item, {size = 14} = {})  // '<span class="flag" ...>' or '' (reserved width when origin pending)
export function originTitle(origin)       // the tooltip / aria-label text
```

Markup: `<span class="flag" data-sure="1|0" data-fi="yes|no|unknown" title="…" aria-label="…">
<img src="https://flagcdn.com/{cc}.svg" alt="" width="14" height="10" loading="lazy"><span class="flag-cc">FI</span></span>`
- Image: 14×10 (line, ledger), 18×13 (sheet, pick card); 2 px radius; `box-shadow: 0 0 0 1px var(--hair)`.
  `onerror` → hide the img, show the 2-letter code in IBM Plex Mono 10 px in a hair-ring pill (works offline).
- `.flag-cc` is visually hidden when the image loads (kept for screen readers / copy).
- **Guess** (`confident: false`): image at 70% opacity, a dotted 1 px `--ink-3` underline under the flag, and a tiny
  superscript "?" (9 px, `--ink-3`). Never colour alone: the tooltip says "guess".
- **Does not ship to Finland** (`ships_to_fi === false`): a 9 px `--flag` "no FI" word after the flag in the ledger
  and sheet (the line already says "· no shipping to FI").
- Unknown origin (`country_code: null`): no flag; ledger shows nothing, sheet says "Ships from: not stated".

Tooltip text (`originTitle`), two sentences, plain words:
- confident: "Seller in Finland (Helsinki), from the listing's location. Ships to Finland: yes, domestic."
- guess: "Probably the United States: a guess from the .com domain and prices in US dollars. Ships to Finland: not
  confirmed by the shop."
- shop address: "Shop based in Germany (Berlin), from the address the shop states on its page. Ships to Finland: not stated."
Format: `${confident ? lead : 'Probably ' + name + ':'} ${basis_text}. Ships to Finland: ${ships_text}.`

---

## 6. Origin data contract (engine, builder 4)

New `agora/origin.py`. Every `offer` event carries `offer.origin`; every `truecost` event carries `origin` too
(recomputed after judge, so shipping flags are known). Replays add it on the fly; agent cards carry it.

```jsonc
"origin": {
  "country_code": "FI",              // ISO 3166-1 alpha-2, upper case; "GB" for the UK; null = unknown. Never "EU".
  "country_name": "Finland",         // English short name; null when unknown
  "city": "Helsinki",                // display case; null when not known
  "basis": "listing_location",       // listing_location | seller_address | service_area | marketplace | known_shop
                                     // | domain | currency | domain_currency | unknown
  "basis_text": "from the listing's location",   // plain words, used verbatim in the UI tooltip and sheet
  "confident": true,                 // false = a guess (domain / currency / known_shop / multi-country marketplace)
  "eu": true,                        // country in the EU (null when unknown)
  "ships_to_fi": true,               // true | false | null (not stated)
  "ships_text": "yes, domestic"      // "yes, domestic" | "yes, the shop says so" | "no, the shop does not ship to Finland"
                                     // | "not confirmed by the shop" | "not stated"
}
```

Evidence order (first hit wins for the country; later hits can only raise confidence when they agree):
1. **Listing location** — `offer.location` through `places.find_place()` / `country_for()`
   ("Helsinki metropolitan area" → FI, Helsinki). Confident. Services: basis `service_area`
   ("from the provider's service area: Helsinki region").
2. **Seller address in JSON-LD** — `offer.raw["seller_address"]` {country, locality} (reader stashes
   `offers.seller.address` / the page's `Organization`/`LocalBusiness` `address.addressCountry` + `addressLocality`;
   country names or codes normalised). Confident. "from the address the shop states on its page".
3. **Marketplace** — `marketplaces.site_for(url)` country, or `marketplaces.second_hand(domain)` when its country is not
   "eu": national classifieds (tori.fi, blocket.se, kleinanzeigen.de …) → that country, confident for classifieds
   ("tori.fi lists sellers in Finland"); multi-country platforms (vinted.<tld>, backmarket.<tld>) → TLD country, guess.
4. **Known shop** — a small table in origin.py for big non-ccTLD shops seen in recordings: bhphotovideo.com,
   adorama.com, keh.com, walmart.com, newegg.com, buydig.com, mpex.com, allenscamera.net, swappa.com, gazelle.com →
   US; jessops.com, wexphotovideo.com, cvp.com → GB. Shops we cannot place (e-infin.com, mpb.com in EUR) stay out of
   the table and fall through. Guess ("a guess from what we know about this shop").
5. **ccTLD** — `.fi .de .se .nl .co.uk (GB) .fr .it .es .pl .dk .no .at .be .ch .ee .lv .lt .ie .pt .cz .sk .hu .gr .jp
   .com.au …`; generic TLDs (.com .net .org .eu .shop .store .io) give nothing. Guess, "from the .de domain".
6. **Currency** — USD→US, GBP→GB, ZAR→ZA, SEK→SE, NOK→NO, DKK→DK, PLN→PL, CHF→CH, CZK→CZ, HUF→HU, JPY→JP,
   CAD→CA, AUD→AU; EUR gives nothing. Guess, "from prices in US dollars". When the ccTLD and currency agree:
   basis `domain_currency`, "from the .co.uk domain and prices in pounds", still a guess.
7. Nothing → `country_code: null`, basis `unknown`, "not stated".

`ships_to_fi`:
- `judge.ships_to_fi(offer)` when raw is present (JSON-LD shippingDetails / page text) → true/false.
- Flags (`truecost` / offer flags): "does not ship to Finland" → false; "ships to Finland" → true;
  "shipping to Finland unconfirmed" → null.
- Country FI (any basis) → true, "yes, domestic". Services in FI → true.
- EU country, not stated → null, "not stated" (EU shops usually do; we do not claim it).
- Outside the EU, not stated → null, "not confirmed by the shop".

API (`agora/origin.py`):

```python
def origin_for(offer: Offer | dict, flags: list[str] | None = None) -> dict    # pure, no network
def origin_from_payload(offer: dict, flags: list[str] | None = None) -> dict   # replay / agent cards (no raw)
```

Wiring:
- `hunt.offer_payload(offer)` adds `"origin": origin_for(offer)`; the `truecost` event adds
  `"origin": origin_for(offer, flags)` after judge.
- `hunt.replay()`: pre-scan the loaded recording for `url → flags` from its `truecost` events; for each `offer`
  event without `offer.origin` add `origin_from_payload(offer, flags.get(url))`; for each `truecost` event without
  `origin` add it from the matching offer payload + its flags. Fixtures on disk are **not** rewritten.
- `agent_api.offer_card()` adds `"origin"`; `get_offer` too. Recordings path (`result_from_recording`) gets it
  through `offer_card`.
- CONTRACT.md: an "Additive (origin)" section; docs/AGENTS_GUIDE.md: one row for `origin` in the card table.
- Tests `tests/test_origin.py`: tori listing with location → FI confident; Helsinki service area → FI service_area;
  JSON-LD seller address DE → confident DE; bhphotovideo USD → US guess, ships null "not confirmed by the shop";
  jessops flags "does not ship to Finland" → GB, false; co.uk + GBP → domain_currency; e-infin.com EUR → unknown;
  replay of `sony-a7-iii-body` puts `origin` on every offer and truecost event; `offer_card` has origin;
  ambiguous city names ("reading") not taken without a preposition (places handles it).

---

## 7. Integration hooks (main.js / core.js / stream.js are owned by the integrator, not the 4 builders)

- `core.js`: `export const BRAND = …` (section 3); nothing else changes.
- `main.js`:
  - remove the reading-row code (`brands` fetch, `reads`, `readPage`, `readOffer`, `lineTarget`, `flyToLine`,
    `readSkip`, `readDone`, `readReset`, `drawReads`) and its calls; `load('livelog')` and call
    `mountLivelog($('reading'), line)` (after `mountLine`), `load('landing')` and `mountLanding($('landing'))`.
  - `on('ask', d => { scrollTo({top: 0, behavior: 'smooth'}); run(d.q); })`.
  - Move the tick clock to the live log: call `livelog.clock(startMs)` or let livelog.js own its own clock from
    `reset`/`done` (it does; main.js keeps `clockStart/clockStop` only for phones, or drops them).
  - `document.title` uses `core.BRAND`.
- `stream.js`: pass the recorded time on the bus: in `handle()`, for `lane`, `source`, `offer`, `skip`, `budget`
  set `d._t = ev.t_ms` (offer: `it._t`) before `emit`. Nothing else; livelog.js listens to the bus itself
  (`reset, need, lane, source, offer, skip, truecost, budget, done, error`).
- `index.html` keeps every DOM id that tests/test_web.py checks (incl. `id="reading"`).

---

## 8. Build split (4 builders, disjoint files)

| builder | owns (only these files) |
|---|---|
| 1 base/landing | `agora/web/index.html`, `agora/web/css/base.css`, `agora/web/js/landing.js` (new), `agora/web/css/landing.css` (new) |
| 2 live log | `agora/web/js/livelog.js` (new), `agora/web/css/livelog.css` (new) |
| 3 result + flags UI | `agora/web/js/verdict.js`, `ledger.js`, `sheet.js`, `line.js`, `flags.js` (new), `agora/web/css/line.css`, `css/sheet.css` |
| 4 engine origin | `agora/origin.py` (new), `agora/hunt.py`, `agora/agent_api.py`, `agora/reader.py` (seller-address stash only), `tests/test_origin.py` (new), `CONTRACT.md`, `docs/AGENTS_GUIDE.md` |

Builder 1 links `css/landing.css` and `css/livelog.css` in index.html. Nobody edits main.js, core.js, stream.js,
tag.js, finale.js, drawer.js, agent.js, watch.css, api.py: the integrator does section 7.
Verification for everyone: offline server on a free port (8900-8999) with `AGORA_OFFLINE=1`, scratch `AGORA_DB`,
stop by saved PID; headless shots at 1440 and 390 (`uvx --with playwright python`); `.venv/bin/pytest -q` green;
`node --test tests/web/` green.
