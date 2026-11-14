# AGORA: system draft v0 (rough)

One search box for everything you can buy online, products and services.
Live web in, one comparison out. Made for people and for agents.

## 1. Pipeline

```
 user / agent
     │  "used sony a7 iii under €900 near Helsinki"
     ▼
┌──────────────┐   NEED: {kind: product|service, thing, budget, where, when, must-haves}
│ 1 INTENT     │   Gemini (Nemotron as backup)
└──────┬───────┘
       ▼
┌──────────────┐   Exa: find every page that sells / offers it (shops, marketplaces, small sites,
│ 2 DISCOVER   │        service providers). Known sources get queried directly as well.
└──────┬───────┘   output: a list of URLs
       ▼
┌──────────────┐   Context.dev: page → JSON using one universal OFFER schema
│ 3 READ       │   Oxylabs: pages that block bots + other EU countries
└──────┬───────┘   runs in parallel, results stream into the UI as they land
       ▼
┌──────────────┐   which offers are the SAME thing? (title + specs + photo)
│ 4 RESOLVE    │   offers → THING clusters; services → normalised unit price
└──────┬───────┘   Nemotron VL reads photos: model, condition
       ▼
┌──────────────┐   TRUE COST · trust score · price history · reviews · verdict
│ 5 JUDGE      │
└──────┬───────┘
       ▼
┌──────────────┐   web UI (live wall)  +  MCP / REST for agents
│ 6 SERVE      │   every outbound link → affiliate rewrite
└──────┬───────┘
       ▼
┌──────────────┐   WATCHERS: re-check pages, alert or act when a rule matches
│ 7 WATCH      │   Context.dev change monitoring + cron
└──────────────┘
```

Each search leaves its results in the index, so the catalogue builds itself
from what people search for. There is no prebuilt crawl: the web is the database.

## 2. Data model (Postgres on Aiven)

```
NEED      id, raw_text, parsed_json, user_or_agent, created_at
SOURCE    domain, type (shop|marketplace|service|review), country, block_level, affiliate_program
OFFER     id, url, source, thing_id, title, price, currency, shipping, condition,
          location, seller_id, in_stock, photos[], specs_json, first_seen, last_seen
SNAPSHOT  offer_id, price, in_stock, seen_at            ← price history
THING     id, canonical_name, category, specs_json, embedding
SELLER    id, source, name, rating, age, review_count, risk_flags[]
REVIEW    thing_id | seller_id, source, stars, text_summary
WATCH     id, need_id, rule (e.g. price < 900 AND km < 50), action (notify|draft_buy), owner
CLICK     offer_id, affiliate_url, user, ts               ← revenue tracking
```

One OFFER schema covers products and services:
- product: price + shipping + condition
- service: price_unit (per hour / m² / job), callout_fee, availability, area

## 3. Systems that make it more than a price-comparison site (draft list, to iterate)

| # | System | What it does |
|---|---|---|
| A | TRUE COST | price + shipping + fees + import − resale value after 12 months (read from used listings). "New €799, resells for €520 → it really costs you €279 a year." |
| B | ONE LADDER | new, refurbished, used and rental for the same thing on one axis, across EU countries |
| C | TRUST SCORE | flags listings that are too cheap, from new sellers, with reused stock photos or with mismatched specs |
| D | BUY OR WAIT | price history + seasonality → "drops ~15% in Nov, wait 9 days" |
| E | WATCHERS | standing orders: "tell me when an A7 III under €900 shows up within 50 km". Runs without the user |
| F | QUOTE SWARM | services rarely publish prices → the agent sends the same quote request to 10 providers and lines up the answers. Risky: needs consent and rate limits |
| G | SWAPS | "cheaper thing that does the same job" instead of only the exact product |
| H | AGENT DOOR | MCP tools: find_offers, compare, true_cost, watch, get_buy_link. Agents get one call instead of 40 sites |

## 3b. Core loop v1: TRUE COST + WATCH + BUY  (picked 2026-11-13)

```
 search ─▶ TRUE COST ranks offers ─▶ "not yet, set a watch" ─▶ WATCHER runs alone ─▶ hits rule ─▶ BUY
                                                                                          │
                                                                    notify · 1-tap · auto (mandate)
```

### TRUE COST = what it really costs you over the time you own it
```
 sticker price
 + shipping + import/VAT gap + payment fees
 + running cost (ink, subscription, energy)      optional per category
 − resale value at month N  (median of used listings for the same THING, by age)
 − cashback / coupon found
 ───────────────────────────────
 = true cost  →  shown per month of ownership
```
Example (made-up numbers): new €799 −> resale €520 at 12 mo = €23/mo · used €430 −> resale €380 = €4/mo.
The used one wins by 6×, which a normal comparison site can't show.

### WATCH = a standing order on a NEED, not on one URL
```
WATCH {
  need:    "sony a7 iii body"                 matches ANY new offer that resolves to this THING
  rule:    true_cost < €900  AND trust ≥ 0.7  AND km < 50
  sources: all known + re-run DISCOVER daily   new shops count too
  action:  notify | one_tap | auto_buy
  mandate: max €900, expires 2026-12-31, merchants: any EU, needs 2FA above €500
}
```
- re-check: Context.dev change monitors on known offer pages + scheduled re-search (Exa) for new pages
- every check writes a SNAPSHOT → the price history chart builds itself
- prediction: "price drops below your target in ~9 days with 60% odds" (from history + similar THINGS)
- group watch: 50 people watching the same THING = demand signal (later: group-buy deal with a seller)

### BUY = three levels
```
 L1 notify     push/email with the affiliate link                       works everywhere, demo-safe
 L2 one tap    prefilled cart / checkout deep link, user pays           a few big shops
 L3 auto buy   agent checks out inside the signed MANDATE               needs an agent-payment rail
               (candidates: Stripe/OpenAI Agentic Commerce Protocol, Google AP2,
                Visa/Mastercard agent cards; check what is live) or a browser agent with a capped virtual card
```
Every purchase and every skipped one goes to an append-only log: "bought at €872, 3% under your target, saved €127 vs the day you set it."

Demo: L1 + L2 for real, L3 on a mock shop we control (the agent buys live on stage).

## 4. Money

```
now     affiliate rewrite on every outbound click (Amazon, Awin, Adtraction, Tradedoubler…)
later   fee per agent API call · paid watchers · fee on checkout made through Agora
```

## 5. Sponsor map (one visible job each)

```
Exa          DISCOVER   finds the pages                      main $2,500
Context.dev  READ+WATCH page → offer JSON, change monitors    main €2,000 + tech €750
Oxylabs      READ       blocked sites, EU geo                 tech €1,000 voucher
Gemini       INTENT+JUDGE parse need, write verdict           tech €4,000
Nemotron     RESOLVE    photo → model/condition               tech RTX 5080
Aiven        STORE      Postgres + Valkey cache               tech €1,000
```

## 5b. Context.dev: verified 2026-11-13 (account bercimajor19, 51,000 credits, 10 req/min)
- search  /v1/web/search        1 credit, ~1.8 s, real shop URLs (Walmart, B&H, eBay, Amazon, small shops)
- product /v1/web/scrape product ~2 credits, 4–15 s, gives name/brand/sku/price/currency/availability/images
  test: same A7 III → $1,398 (Kenmore), $1,398 (B&H), $789.99 (eBay), and each shop uses a different SKU → RESOLVE is needed
- json    /v1/web/scrape json    our own schema → use for used listings + services
- monitors page+instructions (semantic: "alert if price < €900"), search target (new pages for a query),
          schedule + signed webhook → this IS the WATCH engine
- ⚠ 10 req/min limit: a 40-site live search needs batches (/v1/batches) or caching
- client: agora/contextdev.py   docs: docs/contextdev/

## 6. Open questions

- Scope for the demo: all categories, or 2 verticals (electronics + one service like cleaning)?
- Live search speed: 40 sites × extraction can take 20–60 s. Stream results, cache hot queries.
- Resale value (A) needs enough used listings per THING, so it is weak for rare items.
- Quote swarm (F): emailing real businesses during a demo needs care.
- Affiliate approval takes days, so the demo uses mock affiliate IDs.
