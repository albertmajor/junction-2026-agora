<img src="agora/web/assets/brand/logo-128.png" width="64" alt="PriceMonkey logo">

# PriceMonkey

**One search box for everything you can buy, products and services.**

Type "sony a7 iii body", "iphone 15 128gb used" or "home cleaning helsinki 60m2". PriceMonkey reads new,
refurbished, used, rental and service offers from across the web at the same time and puts them on one
price ladder. It ranks them by what owning the thing really costs you: the price, plus import VAT and
shipping, minus what you get back when you resell it, per month. Every number shows its source.

Then it can keep going for you. A **watch** is a standing order on a need. You sign a mandate (a spending
cap, an expiry, allowed merchants). The agent waits for a price that fits, catches shops that lie about
stock or add hidden fees, haggles, and buys inside your limit. Every decision lands in a hash-chained log
that anyone can check.

Built at Junction 2026.

## How to run the demo

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv venv .venv
uv pip install -p .venv -e .
cp .env.example .env            # or create .env yourself; the only key is CONTEXT_DEV_API_KEY=...
.venv/bin/uvicorn agora.api:app --port 8765
```

Open **http://localhost:8765**. Pick one of the three examples, or type anything. Every product lands on
**one price line** (cheaper left, dearer right) as a photo cutout; then the line turns to what each one really
costs you per month. Tap an object for its receipt, drag the yellow tag to set your price.

- `http://localhost:8765/?stage=1` plays the whole demo in one take (Sony A7 III, the Turn, your price,
  the night-shift buy, the agent view). It replays a recorded live hunt, so it costs no credits.
- Keys: **/** search, **A** what an agent sees, **L** the lab panel (replay speed, max gap, live search).
- `?q=sony a7 iii body` opens a hunt directly; `?lab=1` opens the lab panel.
- `http://localhost:8765/lab` is the old lab viewer with every panel open.

Without a `.env` key, everything still works from the recordings. Live search is off by default; turn it on
in the lab panel (it needs `CONTEXT_DEV_API_KEY`). The account allows 10 requests per minute; on a 429 the
viewer says so and shows the nearest recorded hunt instead.

Other ways in:

```bash
.venv/bin/python -m agora "sony a7 iii body" --replay sony-a7-iii-body   # terminal ladder, zero credits
.venv/bin/python -m agora demo-buy --tmp-db                             # offline: lie detector, haggle, auto-buy, proof
.venv/bin/python -m agora.mcp_server                                    # agent door (MCP, stdio)
.venv/bin/pytest -q                                                     # the test suite, fully offline
```

Useful environment variables: `AGORA_BASE_URL` (default `http://localhost:8765`, used for the mock shop's
links and the allowed CORS origin), `AGORA_DEMO_TOKEN` (when set, scripts must send `x-agora-token` to
change state), `AGORA_OFFLINE=1` (no network at all), and `AGORA_DB` (the SQLite file).

## For agents

Agents get listings, not a checkout. Ask for a thing; get new, refurbished, used, rental and service offers
ranked by **all-in price** (sticker + shipping + import VAT/fees), each with a link to the listing page.

```bash
claude mcp add pricemonkey -- "$PWD/.venv/bin/python" -m agora.mcp_server
```

Tools: `find_offers(query, country?, max_price_eur?, conditions?, limit?)`, `get_offer(url)`,
`explain_price(url)` (the receipt), `watch_price(query, target_eur)` (notify only). Offline, answers come
from the recorded hunts and say so. Page text is fenced and labelled untrusted; calls are rate-limited per
client; buying tools stay hidden unless `AGORA_MCP_EXPERIMENTAL_BUY=1`. Non-MCP agents: `GET /api/offers?q=`
(`agora/agent_http.py`) or the `GET /hunt?q=` stream. Schemas and examples: `docs/AGENTS_GUIDE.md`.

## Architecture in brief

The product is called PriceMonkey; the Python package is still `agora` (internal name, env vars stay `AGORA_*`).
The one brand spot in the web app is `data-brand` on `<html>` in `agora/web/index.html`; logo, mascot, favicons
and the share image live in `agora/web/assets/brand/`.

```
need  ->  discover  ->  read  ->  resolve  ->  judge  ->  verdict          (SSE stream: GET /hunt)
                                                    \->  watch -> buy -> proof
```

| module | job |
|---|---|
| `need.py` | free text -> a Need (thing, condition, budget, place). Rule-based, with an LLM step only if a key exists. |
| `discover.py` | finds pages that sell the thing, in lanes: new / refurbished / used / rental / service |
| `reader.py`, `contextdev.py` | page -> Offer. Free JSON-LD first (extruct), then Context.dev. Page text is fenced (`fence.py`). |
| `resolve.py` | groups offers into Things (the same product across shops) and drops lookalikes |
| `judge.py`, `depreciation.py`, `fx.py` | true cost per month (import VAT, FX, measured depreciation), price bands, trust, verdict |
| `trust.py`, `domainstats.py` | photo reuse, young domains, sellers seen before |
| `hunt.py` | runs it all as one race: a provisional verdict in a few seconds, late pages after; records and replays hunts |
| `watch.py`, `buy.py`, `mockshop.py` | standing orders: JSON Logic rules, the sold-out lie detector, the haggle loop, L1 notify / L2 one-tap / L3 auto-buy |
| `proof.py` | HMAC-signed open and closed mandates, signed carts, a hash-chained decision log |
| `lease.py` | agents lease signed webhooks for a watch (Standard Webhooks format) |
| `mcp_server.py` | the agent door: find_offers, true_cost, watch, get_buy_link, why_not, arm_watches, subscribe_watch |
| `api.py`, `web/`, `static/` | FastAPI + server-sent events; the viewer "the line" (`web/`, vanilla ES modules, no build step) and the old lab viewer (`static/`, at `/lab`) |

Safety, in short: page text is data, never instructions (fenced, with a random id per block). The agent
only buys offers that PriceMonkey's own reader stored, at the price it read. Auto-buy runs only on our mock shop,
under a signed mandate with a cap. The shop checks the mandate, the signed cart and the closed mandate
itself, keeps its own spend ledger, and refuses replays. State-changing routes refuse other web origins.

More detail: `CONTRACT.md` (data contract and module map) and `SYSTEM.md` (product design).

## Sponsor tech

- **Context.dev**: the page reader (page -> structured product JSON, search) and change monitors behind
  watches (`POST /hooks/contextdev`). Every request goes through one rate limiter and a credit ledger
  (`GET /ledger`), because the account allows 10 requests per minute.
- Exa (discovery), Oxylabs (blocked sites) and Gemini (need parsing) are wired in as optional lanes. They
  turn on only when their keys exist and degrade gracefully without them. The demo does not depend on them.

## Credits

**All code in this repository was written by us at Junction 2026.** We read other projects for ideas and
wrote our own code; we copied no code from any of them. Specs were implemented from their public text.

**Our teammate rpaszekdev** built the first prototype of the interface during the event, and the viewer
stands on his ideas and code: the photo cutout pipeline (`cutout.m`, macOS Vision) and the safe `/cut`
image proxy, the start shelf of real cutouts at their real prices, the draggable "your price" line and its
empty zone, offers flying in from the shop they were read on, the live log of every page read, and the
research in his `research/` notes (UI concepts, competitors, Reddit frustrations, personalization, the
agent interface). We kept the warmth of his wall and calmed the style down.

Libraries we depend on (all permissive licenses): FastAPI, Uvicorn, httpx, Pydantic, extruct, price-parser,
the MCP Python SDK, panzi-json-logic, imagehash, Pillow, tldextract, python-whois, pytest.

Ideas and inspiration (ideas only, no code):

- **Gumroad** (antiwork/gumroad, MIT): the global-affiliate idea behind "share a hunt" with attributed
  clicks, and its MCP event subscriptions behind watch leases
- **changedetection.io**: restock watching, rule conditions, the multilingual sold-out "lie detector"
- **PriceBuddy**, **PriceGhost** / PriceStalker, Discount-Bandit, **Keepa** / camelcamelcamel: one product across
  many stores, price bands, "lowest in N days" badges
- **fli** (Google Flights library): the low / typical / high price band
- **morphic** (generative UI) and **Vane** (ex-Perplexica): streaming typed results, sources first
- **anthropics/commerce-agents**: fencing untrusted page text and the provenance gate on buying
- **AP2** (open -> closed mandates), **ACP** (checkout sessions, intent traces), **UCP**, Standard Webhooks,
  and the EU Omnibus Directive 30-day price rule: public specs we implemented ourselves
- Meilisearch (lexicographic ranking), Open Prices (price proof), Open Icecat and GS1 (GTINs), Ditto and
  the WDC Products dataset (product matching), WebShop (shopping-agent benchmark)

See `OPEN_SOURCE.md` and `INSPIRATION.md` for the full research notes and licenses.

## License

MIT. Like every Junction 2026 submission, this project is released under the MIT License.
