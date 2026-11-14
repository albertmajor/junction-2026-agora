# Junction 2026 draft (NOT submitted)

Due: Fri 13.11 23:59 (draft + challenge pick, can be changed later) · Final: Sun 15.11 10:00

**Project name:** Agora

**Punchline:** One search box for everything you can buy. Agora shows what owning it really costs and buys when the price is right.

**Description (short):**
Type anything, a product or a service. Agora reads the live web, using shops, marketplaces, refurbishers and service providers across Europe, and puts new, refurbished and used offers on one ladder. For each offer it calculates the TRUE COST: the price plus fees, minus what you can resell it for later. "New costs you €23/month, this used one €4/month." Set a watcher with a spending limit and Agora tracks the price, logs every decision, and buys within your rules once the target is hit. The same engine is an MCP tool, so AI agents can shop with one call instead of 40 sites.

## Challenges

### Main (pick 1–2)
| | Challenge | Prize | Why it fits |
|---|---|---|---|
| ★ | Context.dev: "Web Is Your Real-Time Database" | €2,000 / €500 | Fits the brief exactly: search, product extraction and monitors are the core of the product |
| ★ | Exa (main challenge) | $2,500 | Discovery: finds every page that sells the item, small shops included |

### Side prizes (stack on the same repo)
| Prize | Amount | What we use it for |
|---|---|---|
| Best Use of Context.dev | €750 / €250 | search + product/JSON extraction + semantic price monitors |
| Gemini API | €4,000 / 2,000 / 1,000 | parse the need, write the verdict |
| Oxylabs | €1,000 voucher | sites that block bots + other EU countries (needs a card, cancel after) |
| Aiven | €1,000 | Postgres for price history + Valkey cache |
| Nemotron (NVIDIA) | RTX 5080 | read listing photos for model + condition (optional) |

### Not a fit
Valio, Bahn Spread, AfterQuery, S-Pankki, Cala, Intel/hardware, health

## Technologies
Python, FastAPI (SSE), SQLite→Aiven Postgres, Context.dev, Exa, Gemini, MCP, extruct, price-parser; frontend TBD

## Open before Sunday
- Team on the platform (still "Create or Join Team")
- 2-min video, pitch deck PDF, public repo (MIT), demo link, phone + Discord
