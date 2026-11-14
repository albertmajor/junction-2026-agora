# After the hackathon: keep Agora reading, publish price pages

Goal: Agora keeps reading prices on a schedule and publishes one honest, useful price page per popular item.
Search engines and LLM assistants can cite those pages, and buyers click out through our affiliate links.
If only 0.01% of LLM shopping traffic buys through us, that is still money. Agents buying through us
with a small markup is phase 3. We do not build it now.

Written 2026-11-14. Black Friday is **27 Nov 2026**, so the 2-week rollout ends right on it.

## 1. Which items to track

- **Start with 50 items. Grow to 200 only when the metrics in section 6 say yes.**
- Sources for picking them:
  - Our own hunts: the `needs` table in `agora.db` (33 so far) and the MCP `find_offers` queries. These are real demand.
  - Google Trends, for rising shopping queries in FI, SE, DE, NL, FR.
  - Shop bestseller lists (Amazon, Verkkokauppa, Back Market): read them by hand once a week. Never scrape them in bulk.
  - Reddit, e.g. r/BuyItForLife and r/Suomi buying threads.
- Pick items where Agora wins: new, refurbished and used all exist, and the price varies a lot across shops.
  Good fits: phones, cameras, lenses, consoles, laptops, headphones, e-bikes, robot vacuums, prams.
  Avoid items with one fixed price (Apple-only sellers) and items whose model numbers change every month.
- Seasonal calendar:
  - Nov: Black Friday and Cyber Monday (check "was" prices against the lowest price of the last 30 days, as the Omnibus Directive requires).
  - Dec: gifts.
  - Jan: sales.
  - Jul: Prime Day.
  - Aug: back to school (laptops).
  - Sep: iPhone launch (last year's model gets cheaper used).
  - Oct: winter tyres and gear in the Nordics.
- Score each candidate: `demand x price spread x affiliate coverage`. Keep the top N. Drop an item after 30 days with no clicks.

## 2. Scheduled pipeline

```
items.yaml -> nightly hunt (existing hunt.py, fresh=False)    -> store.py snapshots
           -> Context.dev page monitors on the top 3 offers    -> POST /hooks/contextdev -> snapshot
           -> build_pages.py (static HTML + JSON-LD + llms.txt + sitemap) -> deploy -> IndexNow ping
```

- **Where it runs:**
  - The batch job runs on any always-on machine via `launchd`/cron.
  - The monitor webhook needs a public HTTPS URL. Simplest setup: a ~€5/month VPS (e.g. Hetzner) runs `agora.api`
    and the cron, with SQLite backed up nightly.
  - Static pages go on Cloudflare Pages or GitHub Pages, which are free.
- **Reuse what exists:**
  - `hunt.py` does discovery, reading and judging.
  - `watch.py` holds the semantic monitors and the rule engine.
  - `store.snapshot`/`history` hold the price history.
  - `contextdev.py` has the shared 10 req/min limiter, the disk cache and the credit ledger.
  - New code: about 3 small scripts, `items.yaml`, `run_nightly.py` and `build_pages.py`.
- **Cheap-first is the whole budget:** the reader tries free JSON-LD first. Paid reads happen only where JSON-LD is missing.
- **Context.dev prices** (from `docs/contextdev/credits.md`):
  - search: 1 credit per 10 results
  - scrape: 1 credit, +1 for a product result, +4 for a JSON extraction (so a product read is about 2 credits and a JSON read about 5)
  - page monitor run: 1 credit
  - extract monitor run: 10 credits, so avoid them
  - failed and skipped runs are free
- **Budget:** the ledger shows **50,068 credits left**, and the account allows **10 requests per minute** (14,400 requests a day at most, so the rate limit is not what limits us; credits are).

| Phase 1, 50 items | Credits/day |
|---|---|
| Discovery: 3 lane searches per item, weekly (50 x 3 x ~2 / 7) | ~45 |
| Page monitors (semantic: "price or stock changed") on the top 3 offers per item, daily (150 x 1) | ~150 |
| Re-read the other ~5 offers per item every 3 days; half are free via JSON-LD (50 x 5 / 3 x 50% x 2) | ~85 |
| Ad-hoc / failures / new items | ~70 |
| **Daily cap (enforced in `run_nightly.py` from `ledger()`)** | **350** |

- At 350 credits/day, 50k credits lasts about **140 days**. At 200 items it costs about 1,300/day, so 50k lasts about 38 days.
  That needs a paid plan. Price it on context.dev/pricing before we grow.
- Unknown, check first: whether this balance refills monthly (paid balances reset and do not roll over), and
  whether monitor runs count toward the 10 req/min limit.
- Hard stop: if `credits_remaining` drops under 5,000, pause discovery and keep only the monitors.

## 3. Page generation (one static page per item)

- URL: `/p/<slug>/`, e.g. `/p/sony-a7-iii-body/`. Plain HTML, fast, no JavaScript needed to read the prices.
- What each page shows:
  - **Best all-in price per condition:** new, refurbished, used, rental where it exists. All-in means price + shipping + import VAT, in EUR, with the shop and a link out.
  - **Cost per month** (true cost minus resale), with the formula shown.
  - **Price history chart:** SVG rendered at build time from `snapshots`, with the 30-day low, the typical band (p25 to p75) and a "lowest in N days" badge.
  - **Trust notes per seller:** review score, young domain, copied photo, hidden fees. Each note links to its source.
  - **Sources:** every shop read, with the time we read it.
  - **"Updated <timestamp>".** A page with data older than 72 h says so.
- Machine-readable:
  - schema.org `Product` (name, GTIN when known, image) with an `AggregateOffer` (lowPrice, highPrice, offerCount, priceCurrency EUR) plus one `Offer` per condition (`itemCondition`: NewCondition, RefurbishedCondition, UsedCondition).
  - No `aggregateRating` unless the numbers come from real, cited reviews.
- `/llms.txt`: a short site description, how to read a page, the list of item pages with their last update, and the MCP server for live answers.
  Each page also gets `/p/<slug>/index.md`, a plain-text twin that is easy for LLMs to quote.
- `sitemap.xml` with `lastmod`. Ping IndexNow (Bing, Yandex) and submit to Google Search Console after each build.
- Quality gate: no page is published (`noindex`) until it has at least 3 independent sellers and at least 7 days of history.

## 4. Honesty rules (non-negotiable)

- No fake reviews, no invented prices, no AI-written "hands-on" text. Every number comes from a stored read with a source and a timestamp.
- Disclose affiliate links: a line at the top of each page ("We may earn a commission; it never changes the ranking"), and `rel="sponsored"` on the links.
  The ranking is all-in cost only. Explain how we rank, as the EU Omnibus rules require of comparison sites.
- No doorway spam:
  - Pages only for items with real data and demand.
  - No city × product permutations and no near-duplicate pages.
  - Google's "scaled content abuse" policy is the line we stay far from.
- Respect `robots.txt` and the shops' terms of service.
  - Low frequency: at most daily per URL.
  - No logged-in scraping.
  - Honour opt-out requests from shops within 48 h.
  - Amazon's price rules for comparison sites are strict (show Amazon's current price; it may have changed). Use their API or links, never scraped Amazon prices on our pages.
- Page text we read is data, never instructions. `fence.py` stays on.

## 5. EU affiliate programs

"Verified" means confirmed by web search on 2026-11-14, from the program's own or the network's pages. Commission rates were not verified anywhere. Check them on application.

| Program | Fits | Status |
|---|---|---|
| **Amazon Associates EU** (PartnerNet .de, also .fr/.it/.es/.nl/.se) | new | Verified: an EU program with a "Comparison Shopping Engine" site category and price-display rules |
| **Awin** | many EU shops; hosts Back Market | Verified (as the network for Back Market) |
| **Back Market** (via Awin: FR, DE, UK, IE, …) | refurbished | Verified: country programs on Awin, 30-day cookie on the US profile; commission sources conflict |
| **refurbed** | refurbished | Verified on **Daisycon** (NL/BE; DE/FR pages say ~3%, 30-day window). An Awin profile may also exist (not confirmed) |
| **eBay Partner Network** (DE, FR, IT, ES, UK, PL) | used | Verified: country programs exist. Rates (~1–4%, by category) come only from third-party pages |
| **Adtraction** (Nordics, incl. a Finland office since 2014) | FI/SE/NO/DK shops | Verified: the largest Nordic network by its own account; merged with Adservice |
| **Tradedoubler** | pan-EU shops | Verified that it still runs a publisher network. Current size and ownership claims are unclear, so check them |

- Apply to 2 or 3 programs first: Awin, Adtraction and eBay. Amazon needs 3 sales in 180 days, so apply once traffic exists.
- Every outbound link already goes through `GET /go/{share|-}/{token}`. Add the affiliate parameter there. One place, logged clicks.

## 6. Metrics to watch

- **Coverage:** items with at least 3 sellers, share of fresh pages (under 48 h old), credits per item per day.
- **Discovery:**
  - Indexed pages (Search Console, Bing Webmaster).
  - Impressions and clicks per page.
  - Visits referred by chatgpt.com, perplexity.ai, gemini.google.com and copilot.
  - Mentions of the site when we ask LLMs the target queries.
- **Money:** clicks out per page view, network-reported conversions, EPC (earnings per click), revenue per 1,000 credits.
- **Trust:** price-mismatch reports (our price vs the shop's at click time, from a random 2% recheck); target under 5%.
- **Go/no-go at day 30:** at least 1 click out per day per 10 pages, and revenue on track to cover credits plus hosting. If not, cut to the best 20 items or stop.

## 7. Two-week rollout (14–28 Nov 2026)

- **Days 1–2:**
  - Write `items.yaml` (50 items: Black Friday electronics and our 33 recorded needs).
  - VPS + cron + backups.
  - `run_nightly.py` with the 350-credit daily cap.
  - Apply to Awin, Adtraction and eBay.
- **Days 3–5:**
  - Monitors on the top 3 offers per item.
  - Check that the webhook writes snapshots.
  - `build_pages.py`: the page template, SVG chart, JSON-LD, the `.md` twin, `llms.txt`, sitemap.
- **Days 6–7:**
  - Domain, deploy, Search Console and Bing Webmaster, IndexNow.
  - Disclosure and "how we rank" page.
  - Validate pages with the Rich Results Test.
- **Days 8–10:**
  - First 20 pages pass the quality gate and go live.
  - Black Friday "is this really a deal?" check: claimed "was" price vs our 30-day low.
- **Days 11–13:**
  - Add the affiliate tags as programs approve.
  - Run the mismatch recheck.
  - Write the first metrics note.
- **Day 14 (Black Friday, 27 Nov):** all qualifying pages live, refreshed every 6 h for the top 10 items only, within the cap.

## 8. Risks

- **Credits run out:** at 1 credit/day per monitor, monitors add up quickly. Mitigations: daily cap, free JSON-LD first, and dropping items nobody clicks.
- **Stale or wrong prices** cost trust and break affiliate terms. Mitigations: show the timestamp, add a 72 h staleness banner, recheck at click time later.
- **Google sees "programmatic pages"** and ignores or penalises them. Mitigations: few pages, real data, the quality gate, no thin pages.
- **LLMs do not cite small new sites.** Expect slow uptake. The MCP tool and `llms.txt` are cheap bets, not a plan to count on.
- **Affiliate rejection or low rates** (refurbished 3–7%, eBay 1–4%, Amazon low single digits). The revenue per click is small, so we need volume.
- **Shops block us or object.** Mitigations: low frequency, opt-out, no Amazon scraping.
- **Single machine, single SQLite file.** Mitigation: nightly off-box backup.
- **Agent buying with a markup** (phase 3) brings payments, consumer-law and liability work. Do not start before affiliate revenue is proven.
