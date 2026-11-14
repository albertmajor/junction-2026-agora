# Pitch notes

Built from `docs/JUDGE_FEEDBACK.md` (five booth videos, all judges from Context.dev) and from the recorded
live hunts in `tests/fixtures/live_*.jsonl`. Every number below comes from a recording or from the code; the
source is named next to it. If a number is not here, do not say it on stage.

The one-line pitch: **PriceMonkey asks every shop at once and puts every offer on one line, ranked by what
you actually pay at your door.**

---

## 1. Judge quotes we can use

Use them as quotes from the Context.dev judges at the booth. The transcripts have no speaker labels, so never
put a name on a quote except Thomas's (he was testing his own espresso machine, video 4190).

| Use it for | Quote | Video |
|---|---|---|
| Speed | "How is it this fast?" / "It's suspiciously fast, it's actually quite good." | 4183 |
| The line | "It immediately places everything on a scale by price. This is smooth." | 4164 |
| The line | "It's snowing prices." | 4183 |
| Streaming | "The moment you make the request you show the data immediately? … That's very sick." | 4183 |
| Live pick | "It's already starting to recommend things." | 4164 |
| Overall | "I can tell how it works. It's really fucking cool." (bleep or say "really cool" on stage) | 4164 |
| Overall | "It's production ready." / "I like your product." | 4135 |
| Monkey | "It's very cute." / on the banana loader: "It's so cool." | 4164 |
| Context.dev pain | Thomas: "All the time I had to … detect the structure of the page to not get rate blocked." | 4190 |
| Context.dev magic | "Are you using our product extraction?" … it pulls the hidden data from the page, "I think that's why it's working." | 4190 |

Do not use: anything that frames the judges as our users. The main critique (F1) was exactly that: "Not my
feedback, because I'm not their target." Quote the judges for craft and tech, quote real shoppers for value.

What we changed because of them (one slide, or one sentence each in the talk):

- "How specific can I be?" → specific queries are now a landing section and the start examples (F2).
- "We see multiple products with this name" → ambiguous queries get a "which one?" question (F3; engine work).
- The €79 accessory as the pick → relevance gate and price sanity check (F4; engine work).
- "One extreme outlier, so now it's all going…" → the line uses robust bounds and pins outliers at the edge (F6).
- "How do you handle the price conversions?" → the original price and today's rate are shown next to every
  converted price (F7).
- "It's very gamified, I just wanted to search" → the plain ranked list is one scroll away, no new motion (F9).

---

## 2. Hallway user test (do this before the pitch)

The judges asked for customers, not judges (F1). Ten minutes per person, 5 to 10 people, all on the same
laptop, all on the live site.

**Who.** People who bought something online in the last month and are not on our team or at the Context.dev
booth. Hackathon volunteers, other teams' members who are not judging, people in the food queue.

**Setup.** Laptop with the site open on the start page, a phone stopwatch, this sheet. Do not explain the
product. Do not touch the keyboard. If they get stuck for 30 s, say only "what would you try next?"

**The task (say exactly this).**
> "Find the cheapest way to get a [thing they actually want or recently bought] delivered to you. Tell me
> when you're sure you've found it."

Fallback thing if they can't think of one: "a used Sony A7 III camera body".

**Record per person.**

| # | Who (role, age range) | Thing | Time to first price (s) | Time to "I'm sure" (s) | Did they open a receipt? | Did they trust the pick? (y/n/why) | One quote, verbatim | What confused them |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| … | | | | | | | | |

**Then ask two questions, and write the answers word for word.**
1. "How would you have done this without it?" (we want the tab count and the minutes)
2. "Would you use this next time? Why, or why not?"

**Rules.**
- Write quotes verbatim, including the critical ones. Ask "can we quote you, first name only?" If no, use the
  role ("a student").
- Report every tester, including the ones who failed or did not like it. Report the median time, not the best.
- Only quotes from this test go on the landing's testers strip (`REAL_QUOTES` in `agora/web/js/landing.js`,
  which ships empty) and on the slide below. Never invent or polish a testimonial.

### Slide template: "What users told us"

```
WHAT USERS TOLD US                                  (sentence case on the real slide)

We gave N shoppers one task: "find the cheapest way to get ___ delivered to you."

  N of N found a price they trusted     median ___ s     usual way: ___ tabs, ___ min

  "______________________________"  - first name, role
  "______________________________"  - first name, role
  "______________________________"  - the most critical one, and what we changed because of it

What we changed after the test: ________________
```

Keep the critical quote. A slide with only praise reads like the judges' F1 warning.

---

## 3. Demo script (about 2 minutes)

Run it from the recording so the numbers are fixed and it costs no credits:
`http://localhost:8765/?q=sony%20a7%20iii%20body` (offline replay of `tests/fixtures/live_sony-a7-iii-body.jsonl`),
or `?stage=1` for the whole scripted take. Have a live query ready as a second beat only if the network is good.

**Beat 1, the specific query (10 s).** Type it as you'd say it to a friend. On stage we can type the full
"Sony A7 III body only, used is fine, under €900", but the recording behind the numbers below is
`sony a7 iii body`. If you type the long version live, the numbers will differ: say "live" and do not quote
the figures below.

> "I want a Sony A7 III. Body only. Used is fine."

**Beat 2, the line (20 s).** Prices snow onto one line, cheaper left, dearer right, as each shop is read. The
recording has **17 offers** from **24 pages read**, across new, refurbished and used.

> "Every shop answers at once. Each one lands on this line the moment we've read it. You're watching it
> happen, not waiting for a results page."

The provisional pick arrives while pages are still landing (first verdict at 3.4 s, last page at 20 s in the
recording; that recording was partly cached, so do not promise those exact times live).

**Beat 3, the outlier (20 s).** Point at the **€239 "Sony Alpha A7 III" at mpb.com**.

> "Here's a camera for €239. Too good to be true? PriceMonkey thinks so: it's 75% under the used market
> median of €949, and nothing on the page backs that price up. It's probably another item's price on the
> same page. It stays visible, it's flagged, and it is not counted."

(Flags from the recording: "too good to be true: 75% under the used median (€949)" and "price disagrees:
product read €239 vs the used market €949 … probably another item's price on the page".)

**Beat 4, the all-in receipt (40 s).** Open the cheapest sticker: **allenscamera.net, used, $699.95**.

| line | EUR | where it came from |
|---|---|---|
| sticker ($699.95 at 1 USD = €0.905, ECB rate via frankfurter) | €633.32 | the listing page, read by Context.dev product extraction |
| import VAT 25.5% (shop outside the EU, estimate) | €161.50 | rule |
| **all in** | **€794.82** | shipping unknown, counted as €0; shipping to Finland unconfirmed |

Then the used one from tori.fi: **€825, all in, in Finland.**

> "The sticker is not the price. The US shop is €192 cheaper on the tag. At your door it's €30 cheaper, before
> shipping, and they may not even ship to Finland. Over a year, counting what you'd sell it for, tori.fi costs
> €9.16 a month and the US one €20.49. PriceMonkey picks tori.fi."

(Verdict from the recording: "Buy used at tori.fi for €825: resell in 12 mo for ~€715, so it costs €9.16/mo.
The cheapest sticker (€633 at allenscamera.net) lands at €795 with import costs and costs €20/mo.")

**Beat 5, the agent (10 s, optional).** Press **A**: "Your agent gets the same line." `find_offers` over MCP
returns the same 17 offers ranked by `all_in_eur`.

Close: "One question, every shop, what you'd really pay. Ask the monkey."

---

## 4. The Context.dev story

The judges were all from Context.dev, and the tech story is genuinely theirs. Say it plainly.

**The pain (Thomas's own words).** Reading shops is hard: every shop has its own page structure, half the
price data sits in hidden structured markup, and if you scrape you spend your time "detecting the structure
of the page to not get rate blocked".

**What Context.dev does for us.**
- **Structured extraction.** One `product` call turns a listing page into product JSON (title, price,
  currency, condition, stock, image, SKU). In the Sony recording the €633 sticker came in `via:
  contextdev_product`, with the original "price 699.95 USD" kept as the quote.
- **No per-shop parsers, no fight with page layouts.** We wrote zero site-specific scrapers for product
  pages. The judge put it best: "I think that's why it's working."
- **Search** finds the pages in each lane (new, refurbished, used, rental, service).
- **Monitors** are wired for watches (`POST /hooks/contextdev`).

**How we use it carefully (this is the engineering slide).**
- **Free first.** The reader tries the page's own JSON-LD before paying for a read. In the city bike
  recording, 213 offers came from free reads (`saved_by_free_reads` in the `budget` event).
- **One limiter for the whole account.** The account allows 10 requests per minute across every process, so
  every call goes through a shared token bucket (a file lock in `.cache/`), a disk cache keyed by request,
  and a credit ledger (`GET /ledger`).
- **The numbers from one hunt.** City bike with a basket (`live_city-bike-with-basket.jsonl`): 32 pages read,
  10 Context.dev requests, 32 credits, **322 offers**.

Do not say "Context.dev beats every rate limit" or "reads any site". Say: "We never wrote a scraper for a
single shop, and our only rate limit is our own account's 10 a minute, which one limiter handles."

---

## 5. Business model

Position first, because a judge raised it and the team answered it well: **"We may earn a fee, never a
better spot."** That line is already in the footer and on the landing.

**Revenue.**
1. **Affiliate links, labelled.** Every outbound click already goes through `GET /go/{share|-}/{token}`, so
   adding an affiliate tag is one change in one place, with logged clicks. An affiliate link is only a
   **tie-breaker between equal all-in prices**, and it is labelled. Never a better spot. Programs to apply to
   first (see `docs/AFTER_HACKATHON.md` section 5): Awin (hosts Back Market), Adtraction (Nordics), eBay
   Partner Network; Amazon Associates EU once there's traffic. Commission rates are not verified yet.
2. **Price pages for search and LLMs.** One honest page per popular item ("Cheapest Sony A7 III delivered
   to Finland, today"), built only from real hunts, with schema.org `AggregateOffer`, price history and an
   `llms.txt`. That's the camelcamelcamel model the judge compared us to: price history and alerts for
   free, paid by affiliate clicks. We add all-in prices, every condition, and many shops instead of one.
3. **Watches.** "Tell me when it's under €700 all in" brings people back without ads.
4. **Agents.** The MCP server and `/api/offers` give agents the same ranked line. Later, a small fee on
   agent-driven purchases (phase 3, not now; it needs payments and consumer-law work).

**Costs.** Low, and the judge saw that ("it will cover itself"): one small server, SQLite, static pages on a
free host, and Context.dev credits. The ledger showed 50,068 credits left; the plan in
`docs/AFTER_HACKATHON.md` caps tracking at 350 credits a day for 50 items.

**Distribution.** Context.dev runs a newsletter that the judges said reaches about 40,000 people. Ask them
for a feature as a showcase customer (a number they told us; do not put it on a slide as ours).

What we will not do: pay-for-placement, hidden affiliate ranking, fake "was" prices (we check claimed "was"
prices against our own 30-day low, as the EU Omnibus Directive requires), fake reviews.

---

## 6. Numbers we can say (and where they come from)

| Claim | Number | Source |
|---|---|---|
| Offers for "sony a7 iii body" | 17, from 24 pages | `live_sony-a7-iii-body.jsonl`, `budget` event |
| Cheapest tag vs best buy | €633 tag → €795 all in (US) vs €825 all in (tori.fi) | same recording, verdict + receipt |
| Monthly cost | tori.fi €9.16/mo vs US €20.49/mo over 12 months | same recording |
| Outlier flagged | €239 at mpb.com, 75% under the used median €949 | same recording, `truecost` flags |
| A big hunt | 322 offers, 32 pages, 10 Context.dev requests, 32 credits | `live_city-bike-with-basket.jsonl` |
| Second-hand registry | 124 second-hand domains (curated from a 193-source list) plus 149 marketplace search templates | `agora/marketplaces.py` `SECOND_HAND`, `SITES` |
| Context.dev limit | 10 requests/minute for the account | `CONTRACT.md` |

Speed: say "you see the first prices within seconds" only with the recording on screen. The recordings were
partly cached, so do not quote the millisecond timings as live performance.
