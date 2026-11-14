# Agora: THE LINE (merged design spec)

Status: final merged spec for the Junction 2026 submission (Sun 15 Nov, 10:00).
It combines our engine and lab viewer with the prototype by our teammate **rpaszekdev**
(cutouts, start shelf, "your price" line, live log, research). His style was neo-brutalist.
This spec keeps its warmth and drops the comic parts.

---

## 1. The pivot

**One line.** A single horizontal euro ruler runs across the page. Every product sits on it
as a real photo cutout, like an object on a shelf. Cheaper is left. Dearer is right.

Everything the product does is something done to the line:

| feature | what happens on the line |
|---|---|
| start screen | the line is a shelf of ~14 real cutouts at their real prices |
| search | the shelf sinks; new offers drop onto the line at their tag price |
| ranking | the leader gets a yellow highlighter swipe; a caption says who took the lead |
| ALL IN | **The Turn**: the line relabels and every object slides to what you actually pay, all in (tag + shipping + import VAT + fees, paid once) |
| risky offers | they tip off the line into a "set aside" tray |
| verdict | a hand-drawn ink circle around the winner, one sentence above the line |
| detail | tap an object, its receipt slides out |
| watch | drag the yellow "your price" tag along the line |
| buy at target | an offer slides left across your tag and a receipt drops |
| agent door (MCP) | the line flips into the JSON an agent gets, same order |

The rule is printed under the line in one sentence:
**"Ranked by what you pay, all in. No paid placements."**

**The primary number everywhere is the all-in price you pay once** (owner feedback, 14 Nov:
"when people look for products they straight up want to see just what it costs altogether for the
full thing"). All in = `truecost.true_cost.sticker_eur + extras_eur` (extras = shipping, import VAT,
duties, fees, net of VAT refunded on export); services use the job total. Shipping we cannot see is
said in words: "+ shipping" (abroad, unconfirmed), "shipping not listed" (domestic), "no shipping to FI".
Per-month and resale-adjusted figures are **not** on the line or in the headline. They survive only as
an option inside the receipt: "If you resell it after a year: about €110 net" (a fold; the per-month
figure is a quiet clause inside it).

**The pick** (`core.pickUrl()`) is the lowest all-in price you can surely buy: not set aside (too good to
be true, price disagrees), not rejected, and not "unsure" (abroad without confirmed shipping to Finland,
does not ship, out of stock, a from-price). If nothing is sure, the lowest all-in that is not set aside.
After the Turn `S.leader` is the pick, so every module rings, watches and buys the same offer.
Unsure offers stay on the line at their all-in price with "+ shipping"; the sentence names a cheaper
unsure one honestly ("The lowest tag, €633 at allenscamera.net, is €795 after import VAT, plus shipping
it does not confirm to Finland.").

## 2. The wow moments

### Wow 1: The Turn (about 1 second)
1. Offers drip onto the line at their **tag price**. The cheapest tag (allenscamera, €633) sits far left.
2. The `rank` caption reads "used at tori.fi took the lead".
3. The first `truecost` arrives (or the final verdict, whichever is first). The page fires `turn` once.
4. The axis label cross-fades: "price on the tag" becomes "€ you pay, all in: tag + shipping + import VAT + fees".
   The switch reads [ Price on the tag | What you actually pay ].
5. Every object slides to its all-in total, in plain euros. 900 ms, 30 ms stagger, no bounce.
6. Each object leaves a faint ghost dot at its old spot, joined by a hairline arc.
7. allenscamera jumps right: €633 tag → €795 + shipping (import VAT 25.5%, US shop). The UK and US
   shops all jump by their import VAT; tori.fi (€825, nothing added) stays put.
8. mpb.com "€239" tips off the line, rotates 8°, drops into "not counted": "too good to be true".
9. An ink circle draws itself around the pick (tori.fi) in 600 ms. The highlighter fades out.
10. The sentence locks in: **"€825 all in. Used, tori.fi."**
    Small under it, in plain words: "Nothing added on top of the tag; shipping not listed. Cheapest new:
    €1,029 at e-infin.com · refurbished: €1,513 + shipping at sacameraland.com."
    Its own line: "The lowest tag, €633 at allenscamera.net, is €795 after import VAT, plus shipping it
    does not confirm to Finland."

Implementation rule: compute the true-mode scale first. Animate each object **once** from
its tag x to its final true x. Never a rescale followed by a slide.

### Wow 2: The night shift (finale, about 25 s)
1. You drag the yellow tag to €1,030 and tick "Buy it for me". Release.
2. The tag says "Agora is guarding €1,030" with a small clock: "checked 2 s ago".
3. `/demo/buy` streams. Objects drift as prices change and leave ghost dots.
4. Three mono lines type in above the line:
   - "shop says sold out · page shows in stock · lie caught"
   - "€1,099 offered · declined, above your €1,030"
   - "shop counters €1,028 · accepted inside your mandate"
5. The mock-shop object slides left across the tag. The tag pulses once.
6. A torn-edge receipt drops: "Bought €1,028 · €2 under your price · mandate #12",
   with a small **-3° "bought" stamp** (the only rotated element in the app).
7. "verify" turns one tampered ledger row red: "row 4 changed after signing · caught".

### Wow 3 (short): what an agent sees
Press **A** or the footer link. The line cross-fades into a `<pre>` of the `find_offers` JSON
in the same order, with the same numbers. One engine, two doors.

All three come from recorded streams, so they are deterministic and work offline.

## 3. Screen states

### 0. Start (3-second test)

```
+----------------------------------------------------------------------------------+
| agora —•                                               how it works   for agents |
|                                                                                  |
|                       What do you want to buy?                     (serif 64)    |
|        +--------------------------------------------------------------+          |
|        | a camera, a used iPhone, someone to clean my flat…        ⏎  |          |
|        +--------------------------------------------------------------+          |
|        ( Sony A7 III camera )  ( iPhone 15, used )  ( Home cleaning, Helsinki )  |
|                                                                                  |
|     [toaster] [kettle]  [jacket]   [espresso]   [bike]  [iPhone]   [PS5] [Vespa] |
|       _o_      _o_        _o_        _o_         _o_      _o_       _o_    _o_   |
|  ======|========|==========|==========|===========|========|=========|======|==  |
|      €10       €30        €100       €300        €1k      €3k       €10k         |
|  cheaper · real listings from European marketplaces · dearer                     |
|                                                                                  |
|  Ranked by what you pay, all in. No paid placements. We may earn a fee,         |
|  never a better spot.                                                            |
+----------------------------------------------------------------------------------+
```
- Shelf is on a log scale. Hover a shelf object: "€24 · Kleinanzeigen · used".
  Click: fills the box with the item's query ("try: red espresso machine") and runs it.
- Nothing else above the fold.

### 1. Hunting (0 to about 4 s)

```
+----------------------------------------------------------------------------------+
| agora   [ sony a7 iii body                                        ⏎ ]            |
|         Sony A7 III body ×   new ×   refurbished ×   used ×   ships to FI ×      |
|         reading jessops.com · 14 shops · 12 offers            how we found this →|
|                                                                                  |
|   used at tori.fi took the lead                                  (caption 15)    |
|   hunting…  checking 3 more shops                                                |
|                                                                                  |
|        (o)      [tori u]          (o)(o)   [e-infin n] (o)  [newegg r]  [wedio n]|
|        _o_       _o_              ·  ·       _o_        ·     _o_        _o_     |
|  ======|=========|=================|==|=======|=========|======|==========|===   |
|      €239       €825 ▔▔▔▔         €979     €1,029          €1,448      €1,608    |
|   price on the tag                                                    dearer →  |
+----------------------------------------------------------------------------------+
```
- Box shrinks into a header bar. URL becomes `?q=…`.
- Need chips come from the `need` event. Tapping × re-runs without that chip.
- Status says "hunting…" from the `need` event onward (fixes the old "pick a chip" bug).
- Offers fly in from the domain name in the ticker (450 ms) and land at tag price.
- At most **5 full cutouts**: the leader, the best per condition, the cheapest tag.
  Every other offer is a 28 px round photo dot. Hover or focus grows it to 72 px.

### 2. Result (after the Turn)

```
+----------------------------------------------------------------------------------+
| agora   [ sony a7 iii body ⏎ ]   chips…                       how we found this →|
|                                                                                  |
|   €825 all in. Used, tori.fi.                           (serif 44)   ✓ checked   |
|   Nothing added on top of the tag. Cheapest new: €1,029 at e-infin.com · …       |
|   The lowest tag, €633 at allenscamera.net, is €795 after import VAT, + shipping |
|                                                                                  |
|    ╭─────╮                                                                       |
|   ( tori u )    [allens u] [e-infin n]      [sacam r]   [bhphoto n]   [newegg r] |
|    ╰─_o_─╯  · ·   _o_  ·    _o_       ·      _o_          _o_         _o_       |
|  ====|=====[ typical ]=|====|=========|=======|============|===========|===      |
|   €800         €1,000       €1,200          €1,400        €1,600                 |
|   € you pay, all in: tag + shipping + import VAT + fees                  ▼       |
|                                                       [ ○ € your price ]  ← drag |
|   set aside (2): mpb.com "€239" too good to be true · …                         |
|   Ranked by what you pay, all in. No paid placements.   what an agent sees →   |
+----------------------------------------------------------------------------------+
```
- Faint p25-p75 "typical" bracket from `verdict.price_band`, with the word ("€825 is typical").
- Late events add a small object with "late · verdict unchanged". They never move the circle.
- Services (cleaning): the axis is "€ per job". Objects with no photo get a monogram plate.
  Mixed units: off-unit offers sit in a small "different unit" tray.

### 3. Receipt sheet (tap any object)

```
                                  +------------------------------+
                                  |  [ big cutout on stage ]     |
                                  |  Sony A7 III · tori.fi · FI  |
                                  |  used                        |
                                  |  Price on the tag     €825  ▸ |
                                  |  Shipping       not listed   |
                                  |  ------------------------    |
                                  |  You pay, all in             |
                                  |  €825              (serif)   |
                                  |  If you resell it after a    |
                                  |  year: about €110 net     ▾  |
                                  |    (fold: resale line with   |
                                  |     ~~ A7 II / III / IV ~~)  |
                                  |  • seller unknown            |
                                  |  offer €790, fair €760–820   |
                                  |  [Open listing] [Watch €932] |
                                  +/\/\/\/\/\/\/\/\/\/\/\/\/\/\/-+
```
- Right sheet on desktop (420 px). Bottom sheet on mobile (88vh).
- Each receipt line (`true_cost.receipt` = [label, eur] pairs) expands to its evidence
  quote, domain and fetched time (`truecost.evidence[line_index]`).
- The receipt adds up to the all-in total. Resale lines are taken out of it and live in the
  "If you resell it after …: about €X net" fold, which holds the depreciation sparkline
  (`depreciation.points`) and, as a quiet clause, the per-month figure. Never the headline.
- Missing shipping is a row in words: "Shipping · not listed" / "Shipping to Finland · not confirmed / not offered".
- Flags are plain words with a dot. Never colour alone.
- "Watch at €X" uses `core.beatAllIn(item)`: the tag at which its all-in price would beat the pick's
  (extras assumed to scale with the tag). While the sheet is open,
  the line shows a ghost notch at `beat_eur` for this object only.
- Esc or backdrop click closes. Focus is trapped while open.

### 4. Watch (drag the tag)

```
|   3 offers under €1,030 · e-infin would need to drop €97                        |
|        [tori u]  [allens]   [e-infin]    ║€ 1,030║     (grey)  (grey)  (grey)    |
|  ========|=========|=========|===========╨═══════╨==========|=======|=====      |
|   showing price at the till ·                                                    |
|   Watching Sony A7 III body. I'll tell you when one lands left of €1,030.       |
|   [ ] Buy it for me at or under €1,030  (EU sellers · 14 days)                  |
```
- Dragging switches the line to tag view (300 ms) with a small pill "showing price at the till".
  On release it returns to the all-in view. Watches are on the tag price because that is what
  a shop changes.
- Left of the tag: full colour. Right: 35% grey. A tick only when an offer crosses the tag.
- Live caption from `beat_eur` and `gap_eur`.
- Empty zone left of the tag: light hatch, "nothing here yet · I'll keep watching".
- Release → `POST /watches {query, max_eur, action, mandate}`. Then the guard clock.
- A "see it buy" link appears after arming (and in stage mode).

### 5. Buy finale — see wow 2.

### 6. Drawer "how we found this" (right, 380 px)
- Lanes and queries. Pages read and skipped, grouped by reason
  ("different model (a7r-3 vs a7-3)"). One budget line: "3 credits · 9 free reads · 2 cache hits".
- "Why this pick": built from the page's own all-in ranking (cheapest per condition, cheaper-but-unsure
  count) plus the engine's `verdict.lines` minus its per-month arithmetic.
- Copy-link icon (the `?q=` URL; `POST /share` if available).

### 7. Agent view (A key) — see wow 3.

### 8. Errors (honest copy)
- No recording and live off: "No recording for that. Try one of these, or turn on live search in lab."
- 429: "Context.dev allows 10 reads a minute. Showing a recorded hunt for this instead."
  Then load the nearest recording (client-side word overlap against `/recordings`).

## 4. Mobile (< 640 px)

- Answer first. Above the line: the winner's cutout (120 px), one big serif number
  ("€825 all in"), and the plain-words sentence.
- Then the line turns **vertical**: ruler down the left at 56 px, cheapest at the top,
  objects hang right in 72 px rows. The page scrolls. The Turn is a vertical re-sort.
- The tag becomes a horizontal yellow bar dragged with the thumb. Hit area 44 px.
- Ticker is one truncating line. Sheet and drawer are bottom sheets at 88vh.
- Fallback if the vertical build slips: horizontal line in a scroll container,
  auto-centred on the winner.
- No horizontal page scroll at 390 px. Gutter 16 px.

```
+--------------------------------+
| agora  [sony a7 iii body  ⏎]   |
| used × new × refurb × FI ×     |
| [cutout]  €825 all in.         |
|           Used, tori.fi.  ✓    |
| lowest tag €633 is €795 + ship |
|  €795 ┼─ [allens u] + shipping |
|  €825 ┼─ (tori u)  ◯           |
|  €1,029 ┼─ [e-infin n]         |
|   ·  ┼  ·· 6 more              |
|  €1,513 ┼─ [sacam r]           |
| ═══ € your price ═══  drag ↕   |
| set aside (2) ›                |
| how we found this ›            |
+--------------------------------+
```

## 5. Style: "warm spec sheet"

Editorial calm with one soft-brutalist stroke. The line is the only heavy mark.

```css
:root {
  --paper:  #F4F1EA;   /* page */
  --stage:  #E8E3D8;   /* cutout plates */
  --receipt:#FBF9F4;   /* receipt paper */
  --ink:    #1C1B18;
  --ink-2:  #5E5A52;   /* secondary */
  --ink-3:  #9A948A;   /* ticks, ghosts */
  --hair:   rgba(28,27,24,.12);
  --accent: #F5D547;   /* rpaszekdev's yellow: ONLY highlighter + your-price tag */
  --flag:   #B4532A;   /* set aside, too cheap; always with a word */
  --ok:     #2F6B4F;   /* ✓ checked, chain ok, bought stamp */
  --alarm:  #B3261E;   /* tamper row only */
  --serif: "Instrument Serif", Georgia, serif;
  --sans:  "Inter Tight", system-ui, sans-serif;
  --mono:  "JetBrains Mono", ui-monospace, monospace;
  --ease:  cubic-bezier(.2,.7,.2,1);
  --t-ui: 160ms; --t-drop: 450ms; --t-turn: 900ms;
  --r-sheet: 12px; --r-pill: 999px;
  --line-h: 340px;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper:#161513; --stage:#22201C; --receipt:#1E1C19; --ink:#EEEAE1;
  --ink-2:#B5AFA4; --ink-3:#6E695F; --hair:rgba(238,234,225,.12);
}}
:root[data-theme="dark"] { /* same values as above */ }
```

Type
- Instrument Serif only for: the start question (64/56 px), the verdict sentence
  (44 px desktop / 30 px mobile, line-height 1.05), the receipt total.
- Inter Tight 400/500 for UI: 15 px body, 13 px labels, sentence case, never all-caps.
- JetBrains Mono 12 px for tick numbers, receipt lines, ticker, JSON. `tabular-nums` everywhere.
- Big next to small. No 18-28 px tier.

Shapes
- 1 px `--hair` rules. No card boxes on the main view.
- The line: 1.5 px solid `--ink`, 6 px ticks.
- The only shadow: a contact ellipse under each cutout (radial-gradient, 18% ink, blur 6 px).
  Sheets get `0 8px 24px rgba(0,0,0,.08)`.
- Hand-drawn character in exactly three SVG places, never as a font:
  1. the rough ink circle around the winner (wobbly path, stroke-dashoffset draw);
  2. the torn bottom edge of receipts (clip-path zigzag);
  3. the yellow highlighter swipe under the leader (skewed rect, ragged ends).
  Plus the single -3° bought stamp in the finale.
- The your-price tag is a yellow price tag with a punched hole.
- Logo: "agora" in Instrument Serif italic plus a small line-and-dot mark.
- Banned: Marker Felt, sketchy borders, offset hard shadows, rotated stickers, emoji,
  candy pastels, all-caps.
- Condition marks: a letter on the plate (n, r, u, rent, svc) and the word on hover.

## 6. Motion rules

- 160 ms UI feedback, 450 ms drops and fly-ins, 900 ms the Turn. Ease `--ease`, no bounce.
- Transform and opacity only.
- Motion is saved for threshold crossings: new leader, the Turn, an offer crossing the tag,
  a purchase. Hover and chip removal only fade.
- Drops fall 24 px and fade in. Several at once drip every 70 ms.
- Rescale during the hunt: FLIP on translateX, 450 ms.
- `prefers-reduced-motion`: positions jump, only opacity changes. The Turn is a 300 ms
  cross-fade and ghost dots are still drawn.

## 7. Hidden behind disclosure (one path each)

| was on the page | now |
|---|---|
| Auto/Live/Replay, speed, Stage, clock | `?lab=1` or **L** key panel |
| budget/credits meter | drawer, one line |
| sources chip wall, wire log, skips, lanes | one ticker line + drawer |
| 7 verdict bullets, strikethrough | drawer, "why this pick" |
| 12 rows per offer card | receipt sheet for the tapped object only |
| depreciation section | sparkline on the resale line |
| raw hashes, digests, rule text | behind "verify" |
| most offers | 28 px dots |
| old dark viewer | `/lab` (unchanged) |

Removed outright: the 17-card grid, the standing-order form (now the tag + one checkbox),
the share form with a name field, mock-shop buttons (stage script only), the dark mono-caps
theme. From the teammate's wall: kind tabs, MAX, country select, ships toggle, sort,
site tiles, permanent receipt column, AI-chat toggle, emoji.

## 8. Copy

| place | text |
|---|---|
| title | What do you want to buy? |
| placeholder | a camera, a used iPhone, someone to clean my flat… |
| chips | Sony A7 III camera · iPhone 15, used · Home cleaning, Helsinki |
| shelf caption | cheaper · real listings from European marketplaces · dearer |
| footer | Ranked by what you pay, all in. No paid placements. We may earn a fee, never a better spot. |
| status | hunting… · checking N more shops · ✓ checked |
| axis, tag mode | price on the tag |
| axis, all-in mode | € you pay, all in: tag + shipping + import VAT + fees |
| switch | Price on the tag · What you actually pay |
| headline | €825 all in. Used, tori.fi. (abroad, unconfirmed: "€795 + shipping. …") |
| receipt total | You pay, all in · €825 |
| resale option | If you resell it after a year: about €110 net |
| axis, services | price for one job |
| tray | set aside (N) |
| ticker link | how we found this → |
| sheet buttons | Open listing · Watch at €X |
| tag idle | your price |
| tag pill | showing tag prices |
| empty zone | nothing here yet · I'll keep watching |
| watch line | Watching {thing}. I'll tell you when one lands left of €X. |
| checkbox | Buy it for me at or under €X (EU sellers · 14 days) |
| guard | Agora is guarding €X · checked Ns ago |
| finale link | see it buy → |
| bought | Bought for €X all in. €Y under your price. (receipt: Bought €X · mandate #n) |
| verify | verify → / chain ok / row N changed after signing · caught |
| agent link | what an agent sees → |

## 9. Demo script (2 minutes)

| time | beat | say |
|---|---|---|
| 0:00 | start screen | "Every shop shows you a sticker. We show you what you actually pay, all in." |
| 0:10 | point at the shelf | "Real listings, real prices, cheap to dear. That's the whole interface: one line." |
| 0:15 | click "Sony A7 III camera" | "One box for anything: products, used, rentals, services." |
| 0:20 | offers drop in, caption changes | "We're reading 25 shop pages live. The leader so far is the cheapest tag." |
| 0:35 | **The Turn** | "Now shipping and import VAT. Watch the cheap one jump." |
| 0:45 | verdict sentence | "€825 all in, used, in Finland. The €633 one is €795 before shipping it won't confirm." |
| 0:55 | tap allenscamera → receipt | "Every line has a source. Tap it, you see the quote." |
| 1:05 | drag the tag | "Not ready to buy? Draw your price." |
| 1:15 | tick "Buy it for me", see it buy | "Agora guards it. It catches a fake 'sold out', declines €1,099, accepts €1,028." |
| 1:35 | verify → red row | "Every decision is signed. If anyone edits the log, you see it." |
| 1:45 | press A | "Agents get the same line through MCP. Same order, same numbers." |
| 1:55 | footer | "No paid placements. Thanks to our teammate rpaszekdev for the cutout wall." |

Stage mode `?stage=1` plays this unattended: Sony chip → Turn → auto-drag tag → finale → A.
Captions: 1 "One search box." · 2 "Every shop, one euro line." · 3 "Cheapest tag is not cheapest."
("€633 at allenscamera.net is €795 once import VAT is on it, and shipping is still unknown.") ·
4 "What you actually pay, all in." (the split on the lowest tag: €633 tag + €162 import VAT = €795 all in
+ shipping) · 5 "Set your price." · 6 "Agora watches overnight." · 7 "Proof, not promises." →
"Bought for €819 all in, while you slept."

---

# BUILD PLAN

New UI lives in `agora/web/`. Vanilla ES modules, no build step. Fonts from Google Fonts.
The old viewer (`agora/static/`) stays untouched and is served at `/lab`.

## Folder and ownership (disjoint)

```
agora/web/
  index.html               B1
  css/base.css             B1  (tokens, type, header, start screen, chips, ticker, lab panel)
  css/line.css             B2
  css/sheet.css            B3  (sheet, drawer, verdict, torn edge, agent view)
  css/watch.css            B4  (tag, guard, finale, stamp)
  js/core.js               B1  (bus + store + helpers; the contract below)
  js/stream.js             B1  (SSE → store)
  js/main.js               B1  (boot, start screen, header, chips, ticker, lab/stage, keys L and /)
  js/line.js               B2
  js/verdict.js            B3
  js/sheet.js              B3
  js/drawer.js             B3
  js/agent.js              B3
  js/tag.js                B4
  js/finale.js             B4
  assets/shelf/*.png       B4
  assets/shelf.json        B4  (curated ~14)
  assets/brands.json       B4
  assets/marks.svg         B2  (circle, highlighter, symbols)
agora/api.py               B1  (routes: /, /lab, /web static, include cutout router)
agora/cutout.py            B4  (APIRouter with GET /cut, allowlist, cache)
agora/native/cutout.m      B4  (copied from rpaszekdev, credited)
scripts/precut_fixtures.py B4
tests/test_web.py          B1
tests/test_cut.py          B4
README.md, OPEN_SOURCE.md  B1 (credits section; B4 sends text)
```

## The contract (`js/core.js`, written by B1 first, within 15 minutes)

```js
export const bus = new EventTarget();
export function emit(type, detail) { bus.dispatchEvent(new CustomEvent(type, {detail})); }
export function on(type, fn) { bus.addEventListener(type, e => fn(e.detail)); }

export const S = {
  q: '', slug: null, live: false,
  phase: 'start',            // 'start'|'hunting'|'turned'|'watch'|'finale'
  mode: 'tag',               // 'tag'|'true'  (which x the line uses)
  unit: 'month',             // 'month'|'job'
  need: null,
  offers: new Map(),         // url -> Item
  leader: null,              // url
  verdict: null,             // {verdict, provisional, ...} from the last verdict event
  rank: null, depreciation: null,
  sources: [], skips: [], lanes: [], budget: null, late: [],
  turned: false,
  you: null,                 // your-price EUR (tag price)
  watch: null,               // {id, max_eur, action}
};
// Item = {url, offer, tc /* truecost event data */, setAside, full /* full cutout? */,
//         ghostX /* px before Turn */, arrived /* ms */, late}

export function cutSrc(url)        // '/cut?u=' + encodeURIComponent(url), or null if !url
export function xValue(item)       // S.mode==='true' ? allIn(item) : offer.price_eur
export function allIn(item)        // sticker_eur + extras_eur (job: total_eur); null until costed
export function pickUrl()          // lowest all-in among not set aside and not unsure
export function netAfterResale(item) // total_eur after resale: the receipt's option, never the ranking
export function beatAllIn(item)    // {beat, gap}: tag at which it would beat the pick all in
export function isSetAside(item)   // tc present and (tc.true_cost==null or flags match
                                   //  /too good to be true|price disagrees/)
export function eur(n, {dp}={})    // "€1,029" / "€9.16"
export function goHref(url)        // '/go/-/' + base64url(url) without padding
export function condLetter(c)      // new→'n', refurbished→'r', used→'u', rental→'rent', service→'svc'
```

### Bus events (fired by B1's stream.js unless noted)

| event | detail | fired when |
|---|---|---|
| `reset` | {q} | new search starts (S cleared) |
| `need` | need | need event; phase='hunting' |
| `lane`,`source`,`skip`,`budget`,`depreciation` | raw data | same SSE event |
| `offer` | Item | offer event (Item added to S.offers) |
| `truecost` | Item | truecost merged into Item.tc |
| `rank` | rank data | S.leader updated |
| `verdict` | data | S.verdict set |
| `turn` | {} | **once**: first truecost OR final verdict. B2 owns the visual; S.mode='true' set by B1 before emit |
| `late` | data | late event |
| `done` | {ms} | stream end |
| `error` | {message, kind:'404'\|'429'\|'net'} | stream failure |
| `select` | url | B2 (click/Enter on object) → B3 opens sheet |
| `tag` | {eur, from} | B3 "Watch at €X" or B4 drag → B4 moves tag |
| `watch` | {id, max_eur, action} | B4 after POST /watches ok |
| `finale:start` | {} | B4 or stage script |
| `story` | {step, title, text} | B4 (from /demo/buy) |
| `proof` | data | B4 |
| `agent` | {on:bool} | A key / footer link → B3 |
| `drawer` | {open:bool} | ticker link → B3 |

### Functions each module exports (called by main.js on boot)

```js
// line.js (B2)
export function mountLine(el /* #line */) {}
export const line = {
  setMode(mode),            // 'tag'|'true', animates 300 ms (used by tag drag)
  highlightBelow(eur|null), // lit/grey around the tag (tag-price units)
  xFor(eur) -> px, eurFor(px) -> eur,   // current scale, for the tag
  rect(url) -> DOMRect|null,            // for sheet origin and finale
  placeExtra(id, {img, eur, label}) -> handle with .moveTo(eur) .remove()  // finale mock-shop object
  ghostNotch(eur|null),     // beat_eur notch for the open sheet
  pulse()                   // line ticks once
};
// verdict.js (B3)  export function mountVerdict(el /* #verdict */) {}
// sheet.js   (B3)  export function mountSheet(el /* #sheet */) {}   export function openSheet(url) {}
// drawer.js  (B3)  export function mountDrawer(el /* #drawer */) {}
// agent.js   (B3)  export function mountAgent(el /* #agent */) {}
// tag.js     (B4)  export function mountTag(el /* #tag */, line) {}
// finale.js  (B4)  export function mountFinale(el /* #finale */, line) {}  export function runFinale() {}
```

### DOM ids (index.html, B1)

```
#app[data-phase]
  header#bar         > a.logo, form#ask > input#q, nav#links
  div#chips          (need chips)
  div#ticker         (one line + a#how)
  section#start      > h1, #examples
  section#verdict    (B3)
  section#line       (B2; contains its svg + figures; #tray inside)
  div#tag            (B4; absolutely positioned over #line)
  section#finale     (B4; captions + bought receipt)
  aside#sheet        (B3)  aside#drawer (B3)  div#agent (B3)
  div#lab            (B1)
  footer#rule
```

## Builders

### B1 — shell, stream, routing (owns index.html, base.css, core.js, stream.js, main.js, api.py, tests/test_web.py, README/OPEN_SOURCE credits)
- Write core.js first and tell the others it is there.
- api.py: `GET /` (HTML) serves `agora/web/index.html`; `GET /lab` and `/viewer` serve the old
  `agora/static/index.html` (check its relative asset paths still resolve; mount `/static` stays).
  Mount `agora/web` at `/web`. `app.include_router(cutout.router)` guarded by try/except.
  JSON index for non-browsers unchanged.
- Start screen: question, box, 3 chips from `GET /recordings` with human labels, footer rule.
- stream.js: if `slugify(q)` is in `/recordings` → `/hunt?q=…&replay=auto&speed=1&max_gap=2`,
  else live `/hunt?q=` (only if lab live is on; otherwise the honest error + nearest recording).
  Map SSE → store → bus. Fire `turn` exactly once.
- Header collapse, need chips (× removes chip text and re-runs), ticker (250 ms cross-fade),
  `?q=` URL state, `?lab=1` / **L** panel (mode, speed, max_gap, live toggle, stage),
  `?stage=1` script, **/** focuses the box, **A** emits `agent`.
- tests/test_web.py: `/` HTML returns the new page, `/lab` returns the old one, JSON `/` unchanged.

### B2 — THE LINE (owns line.js, line.css, assets/marks.svg)
- SVG for axis, ticks, ghosts, arcs, bracket, circle, highlighter. `<figure>` cutouts on top.
- Start: log10 scale for the shelf (reads `assets/shelf.json`).
- Hunt: "nice" linear scale, 8% padding, FLIP rescale 450 ms. Fly-in from `#ticker` rect.
- Collision: plates within 64 px rise 1 or 2 tiers, then collapse to a dot.
- Full cutouts: leader + best per condition + cheapest tag, max 5. Rest 28 px dots.
- On `turn`: store ghostX, compute the true-mode scale, one animation per item, ghost dots +
  hairline arcs, set-aside items to `#tray`, circle around `verdict.best_true_cost_url`
  (or S.leader), fade highlighter. Axis label swap. Typical bracket after the Turn.
- Services and missing images: monogram plate (domain initial, serif, on --stage).
- Mobile < 640 px: vertical layout via class, same data.
- Keyboard: ←/→ moves between objects, Enter emits `select`.
- Test with the Sony, iPhone and cleaning recordings.

### B3 — verdict, receipt sheet, drawer, agent view (owns verdict.js, sheet.js, drawer.js, agent.js, sheet.css)
- Verdict: big = all-in total (or per job) + condition + domain of `pickUrl()`.
  Small = what was added on top of the tag + cheapest per condition; own line = the lowest tag's all-in. Provisional:
  "checking N more shops" (`pending_reads`). Final: ✓ checked. Mobile adds the winner cutout.
- Sheet: per section 3. Evidence on tap. Sparkline from `S.depreciation`. Flags as words.
  Haggle and coupons folded. Open via `goHref`. "Watch at €beat" emits `tag`.
  Calls `line.ghostNotch(beat_eur)` while open.
- Drawer: lanes, sources/skips grouped by reason, budget line, verdict.lines, copy link.
- Agent view: JSON shaped like MCP `find_offers` built from S in line order (ranked by `all_in_eur`),
  `pick` first, `net_if_resold_eur` per offer as a secondary field.

### B4 — cutouts backend, assets, tag, finale (owns agora/cutout.py, agora/native/cutout.m, scripts/precut_fixtures.py, tests/test_cut.py, assets/shelf*, assets/brands.json, tag.js, finale.js, watch.css)
- Copy (read-only source) `cutout.m`, `shelf/*.png`, `shelf/shelf.json`, `shelf/brands.json`
  from rpaszekdev's repo. Curate ~14 shelf items spread over price, at most 3 from eBay.de.
- cutout.py: `router = APIRouter()`, `GET /cut?u=`. Port his guards: allowlist (URLs from
  fixtures, served offers via a `remember(url)` helper, shelf), https public host only, no
  redirects, 8 MB cap, image/* only, 20 s timeout. Disk cache `.cache/cuts/<sha256>.png`
  checked first. On failure: 302 to the raw image. Non-darwin: 302 to raw. Unknown URL: 403.
  Compile with `/usr/bin/clang` into `.cache/cutout-bin` on first use.
- precut_fixtures.py: walk `tests/fixtures/live_*.jsonl`, cut every `offer.image`
  (image fetches only, zero Context.dev calls). Run once.
- Front-end fallback when no cutout: the raw photo inside a rounded --stage plate,
  `object-fit: contain`, `mix-blend-mode: multiply` on light theme, soft contact shadow.
- tag.js: yellow punched-hole tag, pointer + keyboard (←/→ 1%, Shift 10%), role=slider,
  aria-valuetext. Drag → `line.setMode('tag')`, `line.highlightBelow`, live caption from
  beat_eur/gap_eur, hatch empty zone. Release → watch line + checkbox → `POST /watches`
  `{query, max_eur, action:'notify'|'buy', mandate:{cap_eur, days:14, rule:'eu sellers'}}`.
  Then the guard clock.
- finale.js: EventSource `/demo/buy?pause=1.2`. story → 3 typed caption lines; watch →
  move the mock-shop object (`line.placeExtra`), ghost dots; crossing → tag pulse; done/proof →
  torn receipt + -3° stamp. "verify" → `POST /demo/tamper {watch_id}` then
  `GET /watches/{id}/proof`, red row at `first_broken_index`.

## Integration (last 20 minutes, B1 leads)
- Headless Playwright at 1440 and 390: start, hunting t=2 s, after the Turn, sheet open,
  tag dragged, finale receipt. Use the cached chromium_headless_shell executable path.
- `pytest` green. Replay works with the network off. No horizontal scroll at 390.
  Zero console errors. Teammate repo untouched. No live Context.dev calls.

## Credits
Teammate **rpaszekdev**: the cutout pipeline (`cutout.m`, the safe `/cut` proxy idea), the start
shelf, the "your price" line and empty-zone idea, fly-in from source, the live log, and the
research in his `research/` folder. Third-party inspirations go in OPEN_SOURCE.md; no code copied.
