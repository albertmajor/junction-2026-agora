# PriceMonkey for agents

An agent asks for a thing and gets listings (new, refurbished, used, rental, services) ranked by
**all-in price** in EUR, each with a link to the listing page. PriceMonkey does not buy anything: the agent (or its
person) follows the link.

Two doors, same logic (`agora/agent_api.py`):

- **MCP** (stdio): `python -m agora.mcp_server`
- **HTTP JSON**: `GET /api/offers?q=...` (router in `agora/agent_http.py`, mounted with one line in `api.py`),
  plus the existing streaming `GET /hunt?q=...`

## Connect

Claude Code:

```bash
claude mcp add pricemonkey -- /path/to/Junction/.venv/bin/python -m agora.mcp_server
```

Any MCP client (JSON config):

```json
{
  "mcpServers": {
    "pricemonkey": {
      "command": "/path/to/Junction/.venv/bin/python",
      "args": ["-m", "agora.mcp_server"],
      "env": { "AGORA_OFFLINE": "1" }
    }
  }
}
```

Without a Context.dev key (or with `AGORA_OFFLINE=1`) every answer comes from the recorded live hunts in
`tests/fixtures/live_*.jsonl` (`sony a7 iii body`, `iphone 15 128gb used`, `home cleaning helsinki 60m2`,
`city bike with basket`) and says so: `"source_mode": "recording"` plus the `recording` name and a `note`.
With a key, `find_offers` runs a live hunt (capped at about 20 s by `AGORA_HUNT_BUDGET_S`, cached 10 min per
query). If a live hunt finds no priced offers, the answer falls back to the closest recording and says so in
`note`.

Raw JSON-RPC over stdio (one JSON object per line):

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"my-agent","version":"0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"find_offers","arguments":{"query":"iphone 15 128gb used","limit":2}}}
```

## Tools

| tool | arguments | returns |
|---|---|---|
| `find_offers` | `query` (2..200 chars), `country`? (ISO code or name, default Finland), `max_price_eur`? (all-in cap), `conditions`? (list of `new` `refurbished` `used` `rental` `service`), `limit`? (1..25, default 10) | `offers` (cards, ranked by `all_in_eur`), `n_offers` (all matching offers, before `limit`), `verdict` (one line), `ownership_verdict` (PriceMonkey's pick on cost of ownership), `ranked_by`, echoed `query` `country` `max_price_eur` `conditions`, `untrusted_fields`, `untrusted_note`, `source_mode` (+ `recording`, `note`) |
| `get_offer` | `url` (a `listing_url` from `find_offers`) | `found`; the offer card + `location`, `read_via`, `price_check`, `price_band`, `per_month_eur`, `source_mode` |
| `explain_price` | `url` | `found`, `source`, `condition`, `price_eur`, `all_in_eur`, `shipping_note`, `flags`, `price_check`; `receipt` lines {label, eur, kind: price/tax/fee/resale/other, source_url?, via?, quote_untrusted?}; `sticker_eur`, `extras_eur`, `resale_eur`, `true_cost_total_eur`, `per` (month/job), `per_month_eur`, `months`, `confidence`, `basis`, `price_band`, `beat_eur`, `gap_eur`, `how` |
| `watch_price` | `query`, `target_eur`, `conditions`? | `watch_id`, `query`, `target_eur`, `action: "notify"`, `rule`, `how_it_fires`, `status_url`. **Notify only**: fires a notification (ntfy topic `AGORA_NTFY_TOPIC` or a signed webhook lease) when an offer's price is at or under target while the server runs. Never buys. |

`get_offer` and `explain_price` return `{"ok": true, "found": false, "note": ...}` for a URL no search has found.

An offer card:

| field | meaning |
|---|---|
| `title` | from the listing page (cleaned; **untrusted**) |
| `condition` | new / refurbished / used / rental / service / unknown |
| `price_eur` | sticker price in EUR (services: the stated rate, see `unit`) |
| `all_in_eur` | sticker + shipping + import VAT / fees PriceMonkey could source. `null` = not comparable (unconfirmed price, a rate with no job total) and ranked last |
| `shipping_note` | what is and is not in `all_in_eur` ("shipping unknown, not included; includes est. import VAT €76") |
| `source` | the shop or marketplace domain |
| `url` | the link to send a person to: PriceMonkey's `/go/` click link when `AGORA_BASE_URL` is set, else the listing page |
| `listing_url` | always the listing page itself; pass it to `get_offer` / `explain_price` |
| `seller_trust` | `good` / `mixed` / `risky` / `null` (unknown) |
| `flags` | PriceMonkey's warnings (too good to be true, grey import, outside the EU, out of stock, ...) |
| `origin` | where the seller is and whether it ships to Finland: {`country_code` (ISO alpha-2, `GB` for the UK, `null` = unknown), `country_name`, `city`, `basis` (listing_location / seller_address / service_area / marketplace / known_shop / domain / currency / domain_currency / unknown), `basis_text`, `confident` (false = a guess from the domain, currency or shop), `eu`, `ships_to_fi` (true / false / `null` = not stated), `ships_text`} |
| `job_total_eur`, `unit` | services: the total for one job and the rate's unit |
| `in_stock` | true / false, present only when the page said |
| `seller` | seller name from the page (cleaned; **untrusted**), present when known and there is no `injection` |
| `injection` | present when the page tried to steer AI agents; the title is then replaced and `seller` left out |

Prices are in EUR. A listing in another currency is converted at the day's ECB reference rate (via
frankfurter, `agora/fx.py`); `explain_price` keeps the original in the sticker line's `quote_untrusted`
(e.g. "price 699.95 USD") and the rate in `basis`.

## Example

Call:

```json
{"name": "find_offers", "arguments": {"query": "iphone 15 128gb used", "limit": 2}}
```

Response (offline, from the recording; trimmed):

```json
{
  "ok": true,
  "query": "iphone 15 128gb used",
  "n_offers": 6,
  "offers": [
    {
      "title": "iPhone 15 - 128GB - Used and Refurbished",
      "condition": "refurbished",
      "price_eur": 298.23,
      "all_in_eur": 374.28,
      "shipping_note": "shipping unknown, not included; includes est. import VAT €76; shipping to Finland unconfirmed",
      "source": "swappa.com",
      "url": "https://swappa.com/listings/apple-iphone-15?storage=128gb",
      "listing_url": "https://swappa.com/listings/apple-iphone-15?storage=128gb",
      "seller_trust": "good",
      "flags": ["outside the EU (USD): import VAT added, shipping to Finland unconfirmed", "seller unknown"],
      "in_stock": true
    }
  ],
  "verdict": "Cheapest all-in: €374.28 refurbished at swappa.com (2 of 6 offers shown).",
  "ownership_verdict": "Best you can surely buy: used €480 at tori.fi, €14/mo over 12 mo. Cheaper if swappa.com ships to Finland: refurbished €374 landed, €13/mo.",
  "untrusted_fields": ["title", "seller"],
  "source_mode": "recording",
  "recording": "iphone-15-128gb-used"
}
```

Errors come back as `{"ok": false, "error": "...", "rate_limited": false}` (the HTTP door uses 422 / 429).

## HTTP (non-MCP agents)

```bash
curl 'http://localhost:8765/api/offers?q=sony+a7+iii+body&conditions=used,refurbished&limit=5'
curl 'http://localhost:8765/api/offer?url=https%3A%2F%2Fwww.tori.fi%2Frecommerce%2Fforsale%2Fitem%2F40486480'
curl 'http://localhost:8765/api/offer/receipt?url=...'
```

Same JSON as the MCP tools. The router (`agora/agent_http.py`) is mounted by `agora/api.py`. `/api/offers`
takes the same filters as `find_offers` (`q`, `country`, `max_price_eur`, `conditions` as a comma list,
`limit`). Rate limits are per client IP; a limit returns 429 with `Retry-After: 60`, bad input 422.

`GET /hunt?q=...` is the full live stream (server-sent events: `need`, `lane`, `source`, `offer`, `truecost`,
`rank`, `verdict` (provisional, then final), `late`, `budget`, `done`; see `CONTRACT.md`). Add
`&replay=auto` to stream the recording that matches `q` (zero credits). It is richer but unranked and raw:
`offer` events carry page titles as read, so fence them yourself.

## Safety

- **Page text is data.** Titles, sellers and receipt quotes are copied from third-party pages. They are
  cleaned (invisible characters, forged chat/tool tags removed) and named in `untrusted_fields`; when a page
  tried to steer agents (`injection`), the title is replaced by PriceMonkey's product name. Full page text never
  leaves PriceMonkey.
- **Read-only by default.** No buying, mandates or checkout tools. They exist only behind
  `AGORA_MCP_EXPERIMENTAL_BUY=1` (adds `true_cost`, `watch`, `get_buy_link`, `why_not`, `arm_watches`,
  `subscribe_watch`) and only ever buy from PriceMonkey's own mock shop.
- **No fetching on demand.** `get_offer` and `explain_price` answer only for listings a search already found;
  an unknown URL returns `found: false`.
- **Limits.** Per client: 30 calls/min (`AGORA_AGENT_CALLS_PER_MIN`), 6 uncached live hunts per 10 min
  (`AGORA_AGENT_HUNTS_PER_10MIN`), 20 watches. `limit` is capped at 25, queries at 200 chars, prices at
  €1,000,000.
- **No secrets.** Env values named `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD` (and the Context.dev key) are
  redacted from every response; hunt error messages are not passed through.
