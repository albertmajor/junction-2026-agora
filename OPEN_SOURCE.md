# Open source: rules + shortlist (2026-11-13)

## Rule (Junction 2026 guidebook p.22-23)
"All code outside of open source libraries must be written at the event."
Any code written in advance for this idea → disqualified. Every submission is licensed MIT.

So:
- ✓ install OSS libraries as dependencies (pip/npm) and call them
- ✓ read OSS apps for ideas / architecture, then write our own code. Credit them in the README
- ✓ use public specs (ACP, AP2, UCP, MCP) and datasets (WDC Products)
- ✗ copy or fork code from OSS apps (price trackers, shopping agents) into our repo
- ✗ any code we wrote before the event
- ⚠ GPL/AGPL/no-license repos: inspiration only, never copy (not MIT-compatible / no permission)
- grey zone: vendoring a permissive file with its license header kept is probably allowed as a "library",
  but avoid it, ask the organisers first

## Libraries we can use (license OK for an MIT project)
| need | library | license |
|---|---|---|
| schema.org / JSON-LD product data from HTML (free, before paying for an API) | scrapinghub/extruct | BSD-3 |
| "1.299,00 €" → 1299.00 EUR | scrapinghub/price-parser | BSD-3 |
| same product across shops (RESOLVE) | moj-analytical-services/splink, dedupeio/dedupe | MIT |
| fallback crawler for pages Context.dev misses | unclecode/crawl4ai | Apache-2.0 |
| agent that clicks through a checkout (BUY level 3) | browser-use/browser-use | MIT |
| buy-or-wait forecast | meta/prophet, unit8co/darts | MIT / Apache-2.0 |
| push alerts for WATCH | binwiederhier/ntfy, caronc/apprise | Apache-2.0 / BSD-2 |
| agent door (MCP server) | modelcontextprotocol/python-sdk | MIT |

## Specs to implement ourselves (BUY + agent door)
- agentic-commerce-protocol/agentic-commerce-protocol (OpenAI + Stripe, Apache-2.0): agent checkout
- google-agentic-commerce/AP2 (Apache-2.0): signed spend mandates → our WATCH mandate
- Universal-Commerce-Protocol/ucp (Apache-2.0): merchant-side commerce standard

## Inspiration only (read, don't copy)
- jez500/pricebuddy (GPL-3.0, 1.5k★): one product across many stores, alert rules
- clucraft/PriceGhost (no license, 1.1k★) → MIT fork mikeknight85/PriceStalker: AI-assisted extraction, back-in-stock alerts
- Cybrarist/Discount-Bandit (no license): multi-user, multi-criteria alerts
- dgtlmoon/changedetection.io (Apache-2.0, 36k★): page-change watching, restock/price detection
- injineerdaacad/price-agent, mahdii99/DealHunter (no license, 0★): LLM shopping pipelines with trust scores. Close to our idea
- megagonlabs/ditto + WDC Products dataset: research on product matching
- princeton-nlp/WebShop (MIT): benchmark for shopping agents

## README credits section (draft)
Inspired by PriceBuddy, PriceGhost, changedetection.io, Ditto/WDC Products. Built on extruct, price-parser,
splink, crawl4ai, browser-use, ntfy, MCP SDK. Implements ideas from the ACP, AP2 and UCP specs.

## Gumroad (antiwork/gumroad): MIT, 10k★, Ruby on Rails, checked 2026-11-13
License is MIT, so even copying would be legal with attribution. BUT the Junction rule is "all code outside
open source libraries must be written at the event", and Gumroad is an app, not a library. So: ideas only.
It is Ruby and we write Python, so we can't copy it anyway. Credit it in the README.

Ideas we take (our own implementation):
| Gumroad system | file | Agora version |
|---|---|---|
| Global affiliate: anyone can share any product, 10% for 7 days | app/models/global_affiliate.rb | SHARE A HUNT: whoever shares an Agora result link gets part of the affiliate commission → growth loop |
| MCP event subscriptions: agents lease a signed webhook (Standard Webhooks secret, TTL ≤ 1 day, max 20 per connection) | app/models/mcp_event_subscription.rb | AGENT WATCH LEASE: an agent subscribes to "price hit" events for a watch through MCP and gets signed callbacks |
| Best offer code: picks the code that takes the most off | app/services/best_offer_code_service.rb | COUPON STACK: find the best valid coupon / cashback per offer and subtract it in TRUE COST |
| Wishlist followers | app/models/wishlist_follower.rb | FOLLOW A LIST: public lists ("my camera kit"); followers get the same price alerts; follower count = demand signal for group deals |
| Per-category facets: "what actually decides a purchase" | app/models/taxonomy_attribute_definitions.rb | CATEGORY FACETS: per category, the 3–5 specs that decide (camera: mount, sensor, shutter count) → used by RESOLVE and filters |
| Refund policies per product | app/models/refund_policy.rb | RETURN WINDOW in TRUST + TRUE COST (30-day return = lower risk) |

## Teammate code and ideas (same team, written at the event)
Our teammate **rpaszekdev** built a prototype during Junction 2026 (repo `rpaszekdev/agora-junction-2026`).
Because he is on the team, reusing his code is allowed; we credit it here and in the README.
- `cutout.m` (macOS Vision foreground cutout) and the `/cut` proxy guards (allowlist, https only, size and
  type caps, no redirects): copied or ported into `agora/native/cutout.m` and `agora/cutout.py`
- the start-screen shelf of real cutouts (`shelf/`, `shelf.json`, `brands.json`): copied into `agora/web/assets/`
- ideas, re-implemented in `agora/web/`: one wall of cutouts, the draggable "your price" line and its empty
  zone, fly-in from the source, the live log, the chat-like request box
- research notes (`research/*.md`): UI concepts, competitors, Reddit frustrations, personalization, agent interface

## Viewer ("the line"): inspirations, no code copied
The new viewer in `agora/web/` is vanilla ES modules and CSS written at the event, with no third-party
front-end code. Fonts are Instrument Serif, Inter Tight and JetBrains Mono (SIL Open Font License,
loaded from Google Fonts). Ideas only: Google Flights' low / typical / high price band, the FLIP animation
technique (Paul Lewis), and editorial "spec sheet" layouts.

## Taxonomy data (agora/taxonomy/, built by scripts/build_taxonomy.py, 2026-11-14)
One merged tree of everything you can buy online (products + services). Data only, no code copied; the merge
code was written at the event. Raw downloads stay in `.cache/taxonomy/` (gitignored); only the merged
`agora/taxonomy/tree.json` is committed. Licences are also stored in `tree.json["sources"]`.

| source | licence | used for |
|---|---|---|
| Shopify Product Taxonomy (github.com/Shopify/product-taxonomy) | MIT | product backbone (~14.6k categories), labels in 13 languages, Google id mapping |
| Google Product Taxonomy 2021-09-21 (taxonomy-with-ids.*.txt) | published free for merchants, no explicit licence | Google ids + fi/de/nl/sv/fr/da/nb/es/it/pl labels as synonyms |
| EU CPV 2008 (ted.europa.eu) | EU open data, reuse authorised (Decision 2011/833/EU, CC BY 4.0) | products + services, 13 of 23 languages |
| NACE Rev. 2 via Statistics Finland TOL 2008 API | CC BY 4.0 | service activities, en/fi/sv, NACE codes |
| ISIC Rev. 4 (UN Statistics Division) | public classification | reference only |
| Yelp category list (developer docs) | no open licence: names + hierarchy used as facts only | local service categories |
| Category sitemaps / menus of ipon.hu, power.fi, verkkokauppa.com, jimms.fi, prisma.fi, tori.fi, blocket.se, marktplaats.nl, kleinanzeigen.de, otto.de, mediamarkt.de, coolblue.nl, emag.hu, ikea.com, fiverr.com, checkatrade.com, my-hammer.de, helpling.de | public pages, plain HTTP, category names/URLs only | extra categories, local-language labels, per-node "where to look" domains |
