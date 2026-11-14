# Agora v0 backend contract (read this first)

Product vision: SYSTEM.md. Rules: OPEN_SOURCE.md (all code written at the event; libraries OK; never copy code from other repos).
Shared types: `agora/models.py` (do not change existing fields; adding optional fields is OK).
Python 3.14 venv at `.venv` (`.venv/bin/python`, `.venv/bin/pytest`). Install extra deps with `uv pip install -p .venv <pkg>` AND add them to pyproject.toml. Permissive licenses only (MIT/BSD/Apache).

## Hard constraints
- Context.dev key in `.env` (CONTEXT_DEV_API_KEY). Never print, log or commit it.
- Context.dev limit: **10 requests/minute for the whole account**, shared by every agent and process. 51k credits.
  - Build agents: do NOT call Context.dev live. Use fixtures in `tests/fixtures/` (real responses already saved: `tests/fixtures/search.json`, `tests/fixtures/product1-3.json` (product data lives at `resp["product"]["data"]["product"]`, with `isProductPage`)) and mocks.
  - Only the integration agent makes live calls, and all live calls go through the disk cache (`.cache/contextdev/`).
- Frontend: one static viewer in `agora/static/` (vanilla JS/CSS, no build step), served by the API. Everything a hunt does is an `Event`.
- Money is EUR internally (`price_eur`). Show math, never invent numbers: estimates carry `confidence` + `basis`.

## Modules and owners

| module | does | public API |
|---|---|---|
| `agora/contextdev.py` | async Context.dev client: token-bucket limiter (10/min, shared via a file lock in `.cache/`), disk cache keyed by request body, credit ledger | `async search(query, n=10, highlights=False, country=None) -> list[dict]`, `async product(url) -> dict|None`, `async extract(url, schema) -> dict|None`, `async create_monitor(...)`, `ledger() -> dict` |
| `agora/fx.py` | currency → EUR (frankfurter.app daily rates, cached, static fallback) | `to_eur(amount, currency) -> float|None` |
| `agora/need.py` | free text → Need (rules; optional Gemini if GEMINI_API_KEY set) | `parse_need(text) -> Need` |
| `agora/discover.py` | Need → lanes (new / refurbished / used / rental / service) → query variants → candidate URLs (dedupe by URL, cap per domain) | `async discover(need) -> AsyncIterator[Event]` (emits `lane`, `source`) |
| `agora/reader.py` | URL → Offer. **Cheap-first cascade**: 1) direct fetch + extruct JSON-LD/microdata (free) 2) Context.dev product 3) Context.dev json schema (listings, services). Condition guessed from domain/text. | `async read(url, need) -> Offer|None` |
| `agora/resolve.py` | offers → Things (model-number tokens, normalised titles, relevance vs need; reject accessories/irrelevant) | `resolve(need, offers) -> list[Thing]` + `relevance(need, offer) -> float` |
| `agora/judge.py` | trust score + flags, TRUE COST (resale curve from used offers), HAGGLE for used, verdict | `judge(need, things) -> Verdict` (mutates offers) |
| `agora/hunt.py` | orchestrates the above as one live event stream | `async hunt(text) -> AsyncIterator[Event]` |
| `agora/store.py` | SQLite (`agora.db`): needs, offers, snapshots (price history), things, watches, mandates, purchases log | plain functions |
| `agora/watch.py` | WATCH engine: rule on a Need (`max_price`, `max_true_cost`, `min_trust`, conditions), recheck loop, Context.dev semantic monitors + webhook, actions notify / one_tap / auto_buy within MANDATE (cap, expiry, merchants), append-only decision log | `create_watch(...)`, `async check_watch(id) -> list[Event]`, `async run_all()` |
| `agora/buy.py` | BUY levels: L1 notify (ntfy.sh topic), L2 one-tap link, L3 auto-buy against our own **mock shop** (`/mockshop` routes) honouring the mandate (AP2-style mandate idea) | `async act(watch, offer) -> dict` |
| `agora/api.py` | FastAPI: `GET /hunt?q=` (SSE stream of Events), `POST /watches`, `GET /watches`, `POST /watches/{id}/check`, `POST /hooks/contextdev`, `GET /things/{id}/history`, `/mockshop/*`, `GET /ledger` | `app` |
| `agora/mcp_server.py` | agent door: MCP tools `find_offers`, `true_cost`, `watch`, `get_buy_link` (MIT `mcp` SDK) | stdio server |
| `agora/proof.py` | signed mandates (HMAC-SHA256, key from AGORA_SIGNING_KEY or `.cache/signing.key`) + hash-chained decision log | `sign_mandate(m, need_text)`, `verify_mandate(m)`, `verify_chain(rows)`, `watch_proof(watch_id)` |
| `agora/exa.py` | Exa look-alike lane: `findSimilar` on a good EU shop surfaces small dealers. No EXA_API_KEY = inert. Disk cache `.cache/exa/` | `async find_similar(url, n, exclude_domains)`, `async search(query, ...)`, `enabled()` |
| `agora/cli.py` | `python -m agora "query"`: live ASCII ladder in the terminal | `main()` |

## Event types (hunt stream)
`need` {need} · `lane` {lane, queries} · `source` {url, domain, lane} · `offer` {offer} · `skip` {url, reason} · `thing` {thing_id, name, n_offers} · `truecost` {url, true_cost} · `verdict` {verdict} · `budget` {credits_used, requests, saved_by_free_reads} · `done` {ms} · `error` {where, message}

Additive (round 1, all optional for consumers):
- `rank` {top:[{url, source, cond, price_eur, per_month, per, delta}], leader_changed, reason}: sent while offers stream in, only when the top 3 by true cost change ("used at usedlens €8/mo overtook new at e-infin €29/mo").
- `lane` {lane:"lookalike", queries:["like dakauf.eu"], via:"exa"} and `source` {..., lane:"lookalike", via:"exa", similar_to}.
- `truecost` also carries `evidence` [{line_index, url, urls?, via, quote, fetched_at}] (one per receipt line it can source), `price_check` ("verified" | "disputed" | null), `beat_eur` (sticker at which this offer would beat the leader; null = cannot win), `gap_eur` (price - beat).
- `budget` also carries `free_reads` [domains read via JSON-LD], `cache_hits`, `pages`, `offers`, and `credit_eur` + `credit_eur_basis` only when AGORA_EUR_PER_CREDIT is set. Counted per hunt (contextvar), never mixed with other hunts.
- `TrueCost.per` = "month" | "job" (services: `per_month_eur` is the job total, render as /job).
- Offer.raw (not streamed): `witnesses` [{via, price, currency, fetched_at, quote, primary}], `price_check`, `tier`, `recurring_only`, `final_url`, `redirected_from`, `beat_eur`, `gap_eur`, `evidence`.

Additive (round 2, all optional for consumers):
- `verdict` may come twice: first `{verdict, provisional: true, pending_reads, offers_so_far}` once the leaderboard has been still for 3 s (or at 8 s), then the final `{verdict, provisional: false, changed_from}` (`changed_from` = the provisional {headline, best_true_cost_url, best_offer_url} when the picks moved, else null; absent when no provisional was sent).
- `late` {url, source, changed_verdict, delta, note}: a page that landed after the provisional verdict, compared with the latest verdict ("adorama.com arrived late (used €1,099): verdict unchanged").
- `skip` for timeouts carries `timeout: true`. Read timeout = 12 s of page work (time queued for the shared Context.dev limiter is added back); domains that keep timing out (`.cache/slow_domains.json`) get 5 s.
- `lane` {lane:"sibling", queries, family} + `depreciation` {family, model, points:[{model, year, median_eur, n}], rate, source:"measured"|"assumed", pairs, basis}: depreciation measured from neighbouring generations (agora/depreciation.py); a measured rate replaces the category rate in every true cost basis.
- `price_check` can also be "consistent": only the same page's search listing agrees (not independent, never "verified"). Flags: "from-price, not a specific unit", "possible grey import: no EU warranty (...)", "outside the EU (...): ... ships to Finland | does not ship to Finland | shipping to Finland unconfirmed". Offer.raw: `ships_to`, `ships_text`, `from_price`, `search_text`, `m2_per_hour`, `area_rate_source`.
- Product headline leads with the best offer you can surely buy (EU, or states it ships to FI) when the cheapest-to-own one may not ship here.
- Replay: `GET /hunt?q=...&replay=<slug>|auto&speed=1|2|4` streams `tests/fixtures/live_<slug>.jsonl` at its recorded pace; `GET /recordings`; CLI `--replay SLUG --speed N`.
- Story: `GET|POST /demo/story/refusal?pause=1.5&beat=771` SSE of `story` {step, title, text}, `watch` {step, watch_id, index, decision, reason, price_eur, hash, prev_hash}, `proof` {chain_ok, first_broken_index, signature_ok, rows, purchases}, `done`. Mock shop: `POST /mockshop/products/{id}/hidden_fee {fee_eur, label}`; auto-buy signs a cart (proof.sign_cart) and refuses any checkout that does not match it (decision outcome `refuse`, buy status `refused`).

API additions: `GET /watches/{id}/proof` {mandate, signature_ok, chain, chain_ok, first_broken_index, head, purchases} · `POST /arm` {query, action?, create?} -> price-to-beat watch suggestions.
MCP additions: `why_not(url, query)`, `arm_watches(query, action, create)`; `watch` returns `proof_url`.

Additive (round 3, all optional for consumers):
- Modules: `agora/share.py` (tables `shares`, `clicks`), `agora/lease.py` (signed webhook leases), `agora/trust.py`
  (photo reuse via pHash, look-alike shop names, young domains; network only in `warm()`/`prefetch()`),
  `agora/fence.py` (prompt-injection fence), `agora/coupons.py`, `agora/domainstats.py`, `agora/demo_buy.py`.
- `need` event carries `hunt_id`. `truecost` also carries `band` {label low|typical|high, p25, p75, median,
  badges, basis, what, text}, `prices_shown`, `offer_id` (buy by id), `hunt_id`, `coupons`, `injection`.
- Model fields: `TrueCost.band`, `Verdict.price_band`. Offer.raw: `band`, `prices_shown`, `net_price_eur`,
  `was_eur`, `discount_claim_pct`, `gtin14`, `gtin12`/`gtin14`/`gtin8`, `regular_price` (JSON-LD ListPrice /
  StrikethroughPrice too), `matched_by`, `coupons` [{code, percent | amount+currency, text, where, verified:false}],
  `injection` [signal names; display only], `snippet_only`, `skipped_paid_read`, `fallback_reason`,
  `page_text` (visible text, ≤6k chars, never streamed), `offer_id`.
- Flags: "discount inflated ...", "price disagrees: ...", "photo copied from another seller's listing ...",
  "stock photo ...", "shop name looks like ...", "shop domain is only N days old ...", "scam pattern ...",
  "page shows €X incl. VAT and €Y excl. VAT ...". `price_check` can be "disputed" for a lone product-format
  price far under the market.
- `lane` event carries `home_country`. Skip reason "hunt budget Ns reached" (`timeout: true`).
- `hunt(budget_s=..., fresh=False, hunt_id=None)`: env AGORA_HUNT_BUDGET_S (default 20, 0 = no cap);
  `fresh=True` = every paid read with maxAgeMs 0. Env AGORA_COUNTRY (default fi, "none" = off),
  AGORA_TRUST_BUDGET (s, default 1.5), AGORA_TRUST_FETCH=0 (no image/WHOIS fetches).
- Reader: `read(url, need, fresh=False, **kw)`, `read_with_reason(max_age_ms=, snippet_ok=, fresh=)`,
  `snippet_fallback()`. Context.dev: `product/extract/search(max_age_ms=)`, `fresh_reads()`,
  `normalize_country()`. Slow domains get 5 s of page work and a 12 s wall-clock cap
  (`.cache/slow_domains.json` gains `ema_s`, `n_timed`).
- Watch: `Rule.logic` (JSON Logic), `min_move_pct`, `on_restock`, `haggle`; open mandate (`kind: open`) ->
  closed mandate per cart (`buy.sign_closed`); haggle loop with the mock shop (intent trace -> counter-offer);
  offer provenance (`buy.register_offer`, `buy.lookup_offer`, `buy.buy_offer`).

API additions (round 3):
- `GET /` = viewer for browsers (Accept: text/html), JSON index otherwise; `GET /api` (index), `GET /viewer`, `/static/*`.
- `POST /share` {query, sharer} -> {id, path, url}; `GET /share/{id}` (stats); `GET /s/{id}` -> 302 to the viewer;
  `GET /go/{share_id|-}/{offer_token}` (token = url-safe base64 of the URL, no padding): logs a click, 302 out.
- `POST /buy` {offer_id, watch_id?, hunt_id?}: provenance-gated buy by id.
- Leases: `POST /watches/{id}/leases`, `GET /leases`, `DELETE /leases/{id}`, `GET /leases/{id}/deliveries`,
  `POST /leases/retry`. Deliveries signed Standard Webhooks style (`webhook-id`, `webhook-timestamp`, `webhook-signature`).
- `GET /watches/{id}/proof` also returns `mandate_chain` {open, open_digest, closed:[...], ok}.
- Mock shop: `POST /mockshop/products/{pid}/feedback`, `POST /mockshop/checkout_sessions/{sid}/cancel`,
  `POST /mockshop/products/{pid}/page_banner`, `GET /mockshop/counter_offers`; checkout accepts `offer_code`.
- MCP: `subscribe_watch`; offer briefs carry `price_band` and `offer_id`, summaries carry `hunt_id`.
- CLI: `python -m agora demo-buy [--pause N] [--verbose] [--tmp-db]`.

Additive (list pages):
- A marketplace search/list page (`discover.is_list_page`) in the used/refurbished lane or on a known marketplace is cut
  into listings: free from schema.org ItemList JSON-LD when present (tori.fi), else ONE paid Context.dev json read with
  `reader.LIST_SCHEMA` {listings:[{title, price, currency, url, image, condition, location}]}. Up to `MAX_LIST_OFFERS` (8)
  Offers, each with its own listing URL, `source` = the marketplace domain, `read_via` "jsonld" or "contextdev_json",
  `raw.from_list_page` = the search URL, `raw.step` "jsonld_itemlist" | "contextdev_list".
- `read_with_reason(..., expand_lists=True)` returns `list[Offer]` for such a page (the hunt streams one `offer` event
  per listing); without it the best listing comes back alone.

Additive (round 7, more offers per hunt):
- `agora/places.py`: offline European gazetteer. `find_place(text) -> (name, cc, span) | None`, `country_for(where)`,
  `language_for(where, cc)`, `place_ok(...)`. Ambiguous names ("nice", "reading", "split") need "in/near" before them;
  Nordic towns in an IKEA query are product names. `need.detect_place` uses it after the Finnish case forms.
- Service lane (live): English query + local-language query (`discover.SERVICE_LOCAL`, e.g. "schoonmaker Tilburg prijs
  per uur") + one search inside the country's service marketplaces (`discover.SERVICE_MARKETS`, sent as
  `include_domains`; `lane` event gains `sites`). New lane: + a local-language shop query (home or asked-for country)
  when the bucket has >= `LOCAL_NEW_MIN_TOKENS`. Search results per query 10 -> 15 (same one token). Job boards / wage
  pages are skipped for services ("job ad (a wage, not a price)").
- Read order by expected yield (`discover.expected_yield`, `paid_priority`; `LaneGate.acquire(lane, list_page, prio)`):
  services = stated rates / provider price lists, then directories, then the rest; a directory domain that listed no
  prices before (`.cache/list_yield.json`, `domainstats.note_list_yield/list_yield`) goes last. Product used/refurb
  lanes read a marketplace search page first (it is no longer dropped when item pages were found).
- Reader, services: a directory page (`discover.is_service_directory`) is ONE paid read with
  `reader.SERVICE_LIST_SCHEMA` -> one Offer per priced provider (`raw.step` "contextdev_providers", `from_list_page`);
  a provider page uses `reader.SERVICE_SCHEMA` (rates with unit, `min_hours`, `one_time`). A snippet stating exactly one
  rate with its unit is a free offer (`read_with_reason` reason "snippet_rate", read_via "search_highlight");
  fallbacks take the first stated rate; ranges, cost guides and unit-less service prices never become offers.
  `raw.min_hours` raises the job's hours in `judge.service_cost`; `raw.unit_from` "title" when the unit came from the title.
- `hunt.DEFAULT_MAX_SOURCES` 24 -> 32.
- Service comparison (like with like): `resolve.service_line_kind(need, title, unit)` -> main | callout | fee | premium |
  task | off_topic. A provider's price list becomes ONE offer (`reader.best_service_offer`): fees (admin, surcharge,
  materials) and other services (sofa cleaning, laundry, deep / end-of-tenancy clean for "home cleaning") never; a
  call-out line becomes `raw.callout_fee`; the rest stays in `raw.other_prices`. Single offers that are fees or another
  service are rejected by `resolve.explain` with that reason. Open-ended trades (plumber, electrician, handyman, no
  task asked: `resolve.is_open_trade`) compare a standard call: hourly rate x `resolve.TRADE_HOURS` (1 h, page minimum
  wins) + call-out fee, labelled an estimate; task prices, visit fees alone and premium (emergency/weekend) rates get
  no true cost and `raw.not_comparable`. Ex-VAT rates ("ALV 0 %", "zzgl. MwSt.") get the country's VAT. Service
  medians count one directory page once; per-unit trust (an hourly rate is never judged against a per-m² price).
  Deal-site / voucher prices carry `raw.deal` and "(deal)". Headline: "€52 for one 24 m² clean at X, €26/h × 2 h." /
  "€60 for a standard 1-hour call (estimate) at X, €60/h × 1 h + €39 call-out."

Additive (model relevance check, `agora/relevance.py`):
- After the rule filter, ONE Gemini Decisions call per hunt (`POST https://generativelanguage.googleapis.com/v1beta/decisions`,
  model `gemini-decision-1`, one `choice` question per listing: match | other_model | accessory | broken | not_an_offer |
  different) -> `{match: yes|no|unsure, reason, confidence, via: gemini|cache|fallback}` per offer. Hard timeout 2.5 s;
  no key / error / timeout / low confidence (< 0.6) = "unsure" and the rules decide. The model can only drop an offer
  the rules kept, never rescue one. Sends only the need's item text (+ must_have) and each listing's title, price,
  condition and source domain (no place, budget, URL or seller). Verdicts cached in memory per (need, title).
- API: `async prefetch(need, offers)` (stores `offer.raw["relevance_llm"]`), `async classify(need, offers)`,
  `veto(need, offer) -> reason|None`, `enabled()`, `stats()`. `resolve.resolve`/`explain` read the stored verdict
  (no network): skip reason "model check: accessory or part, not the item (97% sure)".
- Env: GEMINI_API_KEY (env or `.env`) enables it; AGORA_RELEVANCE_LLM=0 off; GEMINI_DECISION_MODEL,
  AGORA_RELEVANCE_TIMEOUT_S (2.5), AGORA_RELEVANCE_MIN_CONF (0.6). AGORA_OFFLINE=1 disables it.

Additive (seller reviews, `agora/reviews.py`):
- After a hunt is `done`, the viewer opens a SEPARATE SSE stream `GET /reviews?hunt_id=<live hunt>&domains=<hosts,
  most important first>&paid=1&service=0` (the /hunt stream is unchanged and still ends at `done`). The server orders
  a live hunt's sites itself (`reviews.hunt_targets`: the pick, the 6 cheapest all-in shops, then marketplaces and
  service providers; max 10 registrable domains); `domains` covers replays (unknown hunt_id) and adds hosts. Replays
  send `paid=0` (free reads + cache, never credits). 404 when there is nothing to check.
- Events: `review` {domain (registrable), hosts [offer hosts it covers], status checking|done|none, rating (raw stars
  of 5, count-weighted), count, sources [{name, url, rating, count, via page|search snippet|self-reported}],
  adjusted_score 0..1 (0.5 = normal for the category), label solid|mixed|watch out|unknown, summary (one plain
  sentence; marketplaces: "The tori.fi platform: ... The individual seller is not rated here."), red_flags [str],
  grumbles [str], baseline, recent_rating, platform, why pick|cheap|platform|provider|listed, bias_note, cached?,
  checked_at?, offline?}, then `done` {ms, domains, cached, free_pages, paid}. Whole phase <= 40 s
  (`PHASE_BUDGET_S`). Cached sites come first as `done`; the others as `checking`, then `done`/`none`.
- Sources, cheapest first: free plain fetch + extruct of Trustpilot (`www.trustpilot.com/review/<domain>`; its bot
  wall is detected and skipped for 10 min), SmartCustomer/Sitejabber (`sitejabber.com/reviews/<domain>`), the shop's
  own home page (seller AggregateRating only, never a Product's; self-reported, weight 0.3, never enough on its own).
  Paid steps only for sites without >= 30 reviews from a free source, paced by the shared bucket (each waits for a
  token inside the phase budget, then queues in the client's limiter; max 6 per phase): A) ONE batched Trustpilot
  search per 4 sites (`"<d1> <d2> ... reviews"`, includeDomains trustpilot.com): its pages give Trustpilot's own
  summary (review count + mood, never invented stars) and recent review text, for any pending site, incl. the same
  brand on another TLD (yoojo.nl -> trustpilot.com/review/yoojo.fr, named "Trustpilot (yoojo.fr, same brand)");
  then for the pick, if still unrated, its local-language search ("<domain> reviews|kokemuksia|ervaringen|
  Erfahrungen" by TLD); B) ONE Context.dev JSON read of the Trustpilot page of the most important site still without
  stars (the pick first); C) a local-language search for the rest, and Reddit for the pick if there is room.
  Snippet star ratings are only taken from review sites (Trustpilot, Kiyoh, Trusted Shops, ...), never from a blog.
- Negativity bias: per-source baselines (Trustpilot 3.6, SmartCustomer 2.6, own site 4.4, ...; platform -1.5,
  services +0.3, floor 1.5), Bayesian prior of 30 reviews at the baseline, count + recency weighting (last 12 months, >= 5
  reviews). Red flags (scam, never delivered, refunds refused, fake/counterfeit, account closed) are told apart from
  grumbles (slow delivery, customer service waits, returns); only repeated, mostly recent red flags in low-star
  reviews make "watch out": >= 2 recent concrete ones (the bare word "scam" counts half and is never enough); a shop
  with >= 500 reviews or a marketplace platform needs far more. Red-flag kinds also include subscription traps /
  surprise invoices. Fewer than 10 independent reviews = "unknown". "Nothing found" is only cached when every
  source was tried.
- Cache: SQLite table `reviews` (domain, data, label, checked_at), `store.save_review/get_reviews`, TTL 7 days
  ("none" 2 days). AGORA_OFFLINE=1: cache only, the rest `status: none` with `offline: true`.
- Judge: `reviews.preload(urls)` + `reviews.signals_for(offer)` (cache only) join the trust signals. "watch out" ->
  flag "reviews: red flags in recent reviews (...)", trust capped at 0.4 = risky, never the pick; a very low "mixed"
  -> "reviews: rated low (...)" (-0.1). Viewer: `core.isUnsure` includes a watch-out seller, so when reviews land
  after the verdict the pick may move; `S.recheck` {from, to, domain} + bus `recheck` -> "Re-checked after reviews".
  Bus: `review` (data), `reviews` {state checking|done}. `core.trustMark(item)` -> {state, label, text}.

Additive (round 8, direct marketplace pages; registry + splitter ported from teammate Robert / rpaszekdev):
- `agora/marketplaces.py`: `SITES` (search URL template, country, lane, listing-link regex per site), `site_for(url)`,
  `site_query(thing, site)` (filler out; generic nouns dropped when a brand/model word carries the query, else
  translated), `direct_pages(...)`, `split_rows(md, html, site)` (code-only, <= 25 rows), `SECOND_HAND` (193 sources).
- Discover (lean live plan, product needs): `lane` gains `direct` [{site, domain, url, query, paid}]; those pages are
  emitted first as `source` {..., direct: true, site, paid, list_page: true} with no web search. Used lane: the home
  (or asked-for) country's marketplace (tori = free ItemList) + kleinanzeigen + vinted.<home> while the bucket allows
  (`PAID_DIRECT_MIN_TOKENS`); refurbished: backmarket; new: the home country's big shop. Bulky things: home only.
  When kleinanzeigen/vinted are read directly, the "used kleinanzeigen OR vinted" search is dropped. AGORA_DIRECT=0 = off.
- Reader: a known site's search page = ONE Context.dev scrape (markdown + html, country of the site, maxAgeMs 30 min)
  cut by `split_rows`: up to `reader.MAX_SPLIT_OFFERS` (20) offers, read_via "contextdev_markdown_split",
  raw.step "markdown_split", raw.site, raw.from_list_page, raw.price_with_buyer_fee (vinted). Links but no prices ->
  the JSON list read; no listing links -> skip. ItemList pages of known sites keep 20 listings too.

Additive (origin, UI round A; docs/UI_ROUND_A.md section 6): `agora/origin.py`, pure and offline.
- `origin_for(offer: Offer | dict, flags=None)` / `origin_from_payload(offer_dict, flags=None)` -> `origin`
  {country_code (ISO alpha-2 upper, "GB" for the UK, null = unknown, never "EU"), country_name, city, basis,
  basis_text (plain words, the UI shows it verbatim), confident, eu, ships_to_fi (true/false/null), ships_text}.
- Evidence, first hit wins: listing `location` via places.find_place (services: basis `service_area`) -> confident;
  `raw.seller_address` {country, locality} (reader: offers.seller.address, else the page's Organization /
  LocalBusiness / Store address) -> confident `seller_address`; marketplace (national classifieds confident, vinted /
  ebay / backmarket by TLD a guess) `marketplace`; `origin.KNOWN_SHOPS` -> `known_shop` guess; ccTLD `domain`;
  currency (EUR says nothing) `currency`; ccTLD + currency agreeing `domain_currency`; else `unknown` "not stated".
- ships_to_fi: FI -> true "yes, domestic"; judge.ships_to_fi(raw) / flags "ships to Finland" -> true "yes, the shop
  says so", "does not ship to Finland" -> false; EU or unknown -> null "not stated"; outside the EU -> null "not
  confirmed by the shop".
- Events: `offer.origin` on every `offer` event (before judge: no flags yet); `origin` on every `truecost` event
  (after judge, with the offer's flags: the one to trust). `hunt.replay()` adds both in memory to recordings that
  lack them (`hunt.add_origins`; fixtures are not rewritten). Agent cards (`find_offers`, `GET /api/offers`,
  `get_offer`) carry `origin`; recordings keep the recorded one.

Additive (used-dealer units, grades, import clearance, review badges):
- `agora/units.py` (pure): `USED_DEALERS`, `is_used_dealer(url)`, `grade_info(*texts)` -> {grade (as the seller wrote it,
  "Excellent (9)", "Like new", "Fair"), grade_score 0..1, shutter_count, battery_health}, `cards_from_html` (Wex unit
  cards), `pick_units` (page's own unit + cheapest of each grade, then cheapest; `MAX_UNITS` 8).
- Reader: a used dealer's page with several in-stock units -> one Offer per unit with `expand_lists=True` (free JSON-LD
  page: main unit + its unit cards; paid JSON read: every same-item offer, `raw.step` "contextdev_units"). Each unit has
  its own URL (or page URL + `#unit-N`), `raw.unit_of` = page URL, `raw.units_on_page`, `raw.from_list_page` when
  the URL differs. `OFFER_SCHEMA` items gain nullable `grade`, `shutter_count`, `battery_health`. Used/refurb offers carry
  `raw.grade`, `raw.grade_score`, `raw.shutter_count`, `raw.battery_health`, `raw.grade_from` (title|page) when stated.
  JSON-LD blocks ending in `};` are parsed (extruct drops them).
- Judge: receipt line `("condition: Good (8), shutter count 14,641 (seller's grade); lower than the usual Excellent (9)
  here, so a lower price is expected; same grade elsewhere: €X", 0.0)` + `raw.grade_note`; units of one page vote once
  per grade in market medians and are never merged as a VAT pair; used dealers get no haggle script.
  Imports from outside the EU add `("courier customs clearance fee (est., UPS/DHL/FedEx typically €10–20)", 15.0)`
  (marketplace / private listing: `("postal customs handling fee (est., usually under €10)", 5.0)`) and, over €150,
  `("customs duty: 0% for cameras (ITA agreement)", 0.0)` (cameras/phones/tablets/laptops) or `("customs duty: possible
  over €150, depends on the category (not priced)", 0.0)`; `import_fee` / all-in include the clearance fee.
- Reviews: the shop's own page is scanned for rating badges ("4.8 Trustpilot Rating", Feefo/Reevoo/Google/Trusted Shops,
  TrustBox attributes) -> source {name "Trustpilot (shown on the shop's own page)", via "shown on the shop's own page"},
  weight 0.3, at most 100 reviews, never counted as independent (badge-only = label "unknown", status done, summary
  "4.8★ on Trustpilot, as shown on the shop's own page (not checked independently); ..."). Its Trustpilot link
  (uk.trustpilot.com/review/www.<domain>) is followed; big shops (known shops or badge/link on the page) the batch missed
  get one own Trustpilot search (incl. the local `uk.`/`de.` site, max 2 per phase) and the paid page read uses the
  linked / local Trustpilot page.

## Tests
`tests/` with pytest, offline by default (fixtures/mocks). Live tests marked and skipped unless `AGORA_LIVE=1`.

Additive (category context):
- `GET /hunt?q=&cat=<taxonomy node id>` -> `hunt(text, category=id)`; the viewer (stream.js) sends the page URL's `cat`.
  `Need.category` (optional dict: id, label, path, path_ids, kind, lanes, size, domains, labels, synonyms, service,
  source, confidence). `need.categorize(need, category_id|None)`: a tree node sets the need's kind (service / digital
  -> service lanes only; product / vehicle / food / property -> product lanes from the node); typed text uses
  `taxonomy.classify` (confidence >= 0.6, score >= 0.85) and turns a product need into a service only on a strong
  service node clearly ahead of the best product node (not food-drink). New event right after `need`:
  `category` {id, label, path, kind, confidence, source: "tree"|"classified", lanes, size, domains}.
- Service lane: the job in the local language (SERVICE_LOCAL, else the node's label) also when no place is asked
  (home country, AGORA_COUNTRY); the node's own / same-country where-to-look domains join the service-market search.
- `resolve.kind_mismatch(need, offer)`: a service need rejects things for sale ("a product, not a gunsmith service
  (...)": books/manga/merch that only share the name, guns and parts, goods-only marketplaces, product pages without
  service wording); a product need rejects service ads ("a service, not a bike"). `resolve.far_provider`: a local
  trade priced in USD/CAD/AUD on a non-EU domain is "a provider abroad". Both run before the list-page reason.

Additive (category pages, owner 14 Nov: "Lifestyle Services" hunted its own words):
- tree.json rows: `"h": 0` + `"b": reason` (root | vague | other | group | department | official) = browse-only; absent
  = huntable. Roots carry `"a"` (one-line about) and `"pop"` [[words, id]]. Rules in `agora/taxonomy/browse.py`
  (`assess`, `should_fold`); hand overrides/renames/moves in curated.py (`RENAMES`, `MOVES`, `FOLD_UP`, `HUNTABLE`,
  `ABOUT`, `POPULAR`). Empty umbrellas fold into their parent (old ids stay aliases: `sp:se-6-4` -> `beauty-wellness`).
- Taxonomy: `huntable(id)`, `browse_reason(id)`, `concrete_under(id, n)`; `node()` gains `huntable`, `browse_reason`.
- API: every category item gains `huntable`, `browse_reason`; `GET /api/categories/page?id=` {label, path, about,
  why, groups [{..., examples}], items, official, popular [{q, id, label}], asked?}; `/search?within=<id>`;
  `/classify` match gains `exact`, `browse` {id,label,path} (words name a browse-only node), `choices` (browse-only);
  `/nodes` resolves old ids (`asked`).
- Viewer: phase `category` (`?c=<id>[&typed=]`, catpage.js). A browse-only node, or typed words that exactly name
  one, opens its page; only huntable nodes hunt. Bus: `category` {id, typed?}, `catpage`, `ask` {free: true}.
