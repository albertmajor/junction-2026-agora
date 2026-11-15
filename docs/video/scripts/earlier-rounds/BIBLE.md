# PriceMonkey video bible (Junction 2026, Context.dev)

## 1. What PriceMonkey is

- **One search box for things and services.** You type plain words, like "sony a7 iii body", "iphone 15 128gb used" or "home cleaning helsinki 60m2". It searches new, refurbished, used, rental and service offers at the same time. Each offer appears on **one price line** as it gets read, cheaper on the left. Then the line "turns" to the **all-in price**: the tag plus shipping, import VAT and fees, converted to euros at today's ECB rate. It can also show cost per month after resale. Every number has a receipt that names its source. (README.md)
- **Context.dev is how it reads the web.** Search finds pages in each lane. The `product` and JSON extraction calls turn a listing page into price, condition, stock and image. Monitors are wired up for watches (`POST /hooks/contextdev`). It tries the page's free JSON-LD before it pays for a read. One rate limiter plus a credit ledger keep it under the account's 10 requests a minute. (README, PITCH_NOTES §4)
- **It flags bad offers, keeps them visible and doesn't count them.** Examples: "too good to be true", "price disagrees", "outside the EU: import VAT added, shipping to Finland unconfirmed", "does not ship to Finland", "out of stock", "possible grey import: no EU warranty", "from-price, not a specific unit". (fixtures)
- **Watches, haggling, auto-buy and a hash-chained proof log exist, but auto-buy runs only on its own mock shop** under a signed mandate. (README; `?stage=1` tour; `python -m agora demo-buy --tmp-db`)
- **Agents get the same ranked line** through MCP (`find_offers`, `get_offer`, `explain_price`, `watch_price`, which only notifies) and through `GET /api/offers`. Agents get listings, not a checkout. (README)
- **Pro-consumer position.** The footer says "Ranked by what you pay, all in. No paid placements. We may earn a fee, never a better spot." There is no affiliate revenue yet; affiliate links are only a plan. (index.html, AFTER_HACKATHON §5)

**Do not claim:**
- It "reads any site", "beats rate limits" or "buys for you on any shop".
- Live speeds in milliseconds (the recordings were partly cached: the Sony replay shows 0 credits and 32 cache hits).
- Anything about cars, insurance or quote-only services. They are the weakest areas (QUALITY_REPORT).
- Testimonials, user numbers or revenue. `REAL_QUOTES = []`; nobody has been tested yet.
- Exa, Oxylabs or Gemini as part of the demo.
- That judges are users.
- **The PS5 Pro OLX story in v2 (1,600 zł, 1,200 clicks) has no source anywhere in the repo.** Treat it as unverified.
- The "14 tabs, 1 h 16 min evening" and "top three are sponsored" are illustrative story copy on the landing page (landing.js `night`), not measurements.

## 2. Real facts and numbers you can film

**Sony A7 III** (`tests/fixtures/live_sony-a7-iii-body.jsonl`; replays at `?q=sony%20a7%20iii%20body` at no credit cost)
- **17 offers from 24 pages, 20 distinct shops.** Shops include tori.fi, mpb, keh, B&H, Walmart, Jessops, Wex, CVP, sacameraland (South Africa), allenscamera. 23 pages were set aside, each with a reason ("different model (a7r-3 vs a7-3)", "page gone (HTTP 404)", "timeout after 12s"). The first pick came at 3.4 s and the hunt ended at 20 s; these timings come from a partly cached run.
- **allenscamera.net, used, $699.95.** The tag shows €633.32 (1 USD = €0.905). Import VAT at 25.5% adds €161.50, so it is **€794.82 all in**. Shipping is unknown and counted as €0. Flags: "33% below €949", "shipping to Finland unconfirmed". Cost per month: **€20.49**.
- **tori.fi, used, €825.** All in €825; resale ~€715 after 12 months, so **€9.16 a month**. This is the pick, and its price is "typical" (band €825 to €979).
- The verdict text reads: "Buy used at tori.fi for €825: resell in 12 mo for ~€715, so it costs €9.16/mo. The cheapest sticker (€633 at allenscamera.net) lands at €795 with import costs and costs €20/mo."
- **mpb.com at €239.** Flags: "too good to be true: 75% under the used median (€949)"; "price disagrees … probably another item's price on the page"; "not costed". It is not ranked.
- Other flags you can show:
  - jessops.com: "does not ship to Finland"
  - dakauf.eu: "out of stock"
  - e-infin.com €1,029: "possible grey import: no EU warranty"
  - wedio.com: "from-price, not a specific unit"
  - sacameraland: R25,999 (ZAR), €1,387 on the tag, €1,513 landed
- Depreciation is measured, not assumed: "Sony A7 III used sells for 35% less than Sony A7 IV; launched 3 yr apart => -13%/yr".
- The tori.fi receipt includes a suggested message to the seller asking for the serial number, photos and shutter count.

**iPhone 15 128GB used** (`live_iphone-15-128gb-used.jsonl`)
- The best you can be sure of: tori.fi used, €480 (€14 a month).
- swappa.com refurbished: €298, **€374 landed**, but "its page does not say it ships to Finland".
- Two offers flagged "too good to be true: 55% under".

**Home cleaning, Helsinki, 60 m²** (`live_home-cleaning-helsinki-60m2.jsonl`)
- mikoy.fi €25/h, so about **€62 for the job**. That assumes 25 m² an hour for every provider.
- About €38 after the household tax deduction, once your yearly €150 excess is used up.
- Comparison: homora €95, kidesiivous €118. Flags: "recurring-contract price", "from-price".

**City bike with a basket** (`live_city-bike-with-basket.jsonl`)
- **322 offers from 32 pages, using 10 Context.dev requests and 32 credits. 213 came from free reads.**
- Final pick: €60 used at tori.fi. New starts at €233 at cdon.fi.
- "32 listings abroad are pickup only: shown, never the pick."
- **Caution:** "147 offers look risky" here is partly the known false-positive problem on broad searches. Do not present it as a scam count.

**Across the app**
- 4 recorded hunts read 80 pages on 64 sites (landing.js `READ`).
- 124 second-hand domains and 149 marketplace search templates (PITCH_NOTES §6).
- The test suite has 1,683 passing tests (QUALITY_REPORT).
- `tests/fixtures/poisoned_listing.html` is a fake Sony listing with instructions planted for AI buyers. Page text is fenced and treated as data, never as instructions (`fence.py`). You can only film this from a test.
- Judge quotes, labelled as Context.dev judges at the booth and never as users:
  - "It's snowing prices."
  - "How is it this fast?"
  - "Are you using our product extraction? … I think that's why it's working."
  - Thomas: "All the time I had to … detect the structure of the page to not get rate blocked." (PITCH_NOTES §1)

## 3. Judging criteria and video rules

**Guidebook, verbatim** (`guidebook.txt`):
- "2 minute long video pitch of the final project … available for everyone to enjoy. And to be very frank: not a second longer than 2 minutes, and we will be very strict with this."
- "The project submission must contain a pitch video, maximum 2 minutes long."
- General criteria:
  - **INNOVATION:** "new or different compared to the already presented ones?"
  - **IMPACT:** "significant impact on society through solving the problem(s) it addresses?"
  - **IMPLEMENTATION:** "realistic, viable and feasible."
- Deadline: Sun 15 Nov 10:00. Set the project to FINAL.

**Context.dev challenge.** The challenge is called "Web Is Your Real-Time Database" (DRAFT.md). The criteria below come from the SCRIPT_v1.md table; the original challenge text is not in the repo.
- Main challenge, 20% each: real-world impact; creative use of live web data; completeness of demo; technical execution (latency, accuracy); real-timeness (reacts to change over time).
- Best Use of Context.dev: creative use of several endpoints (40%); how central live web data is (30%); technical execution (30%).
- Minimum, pass/fail: **Context.dev data visibly drives something in the demo.**

## 4. The owner's intent (`docs/video/owner-memo.txt`)

- "first we probably have to start with showcasing the problem … clearly explaining what the problem is, what we're solving"
- "then how we solve it, but really have to emphasize … I guess we're like pro-consumer"
- "the vibe should be like the monkey vibe, but of course don't do any monkey shit … not too monkey, but a little monkey … Just a little monkey"
- "Emphasizing how it's an issue right now, how all these fucking pages are trying to scam and shit"
- "And then how we solve it … With context.dev. Because that's the challenge we're going for"
- He called SCRIPT_v1 "total slop". His voice reference is the Rossman transcripts.

## 5. The Rossman voice: techniques with real lines

1. **The same plain opener, then straight to the point:** "Hey everybody, how's it going? Hope you're having a lovely day." On short clips he skips the pleasantries: "so if you needed any more proof that New York City was designed to [suck]…"
2. **A named episode as a running bit:** "Welcome to today's episode of How I'm getting [screwed]." / "…of I Hate the Modern Internet." Use it sparingly; v1 copied it and it read as a gimmick.
3. **A personal story with exact specifics:** "a Samsung 990 Pro 4 TB drive that died." / "two 80 millimeter fans … 3000 RPM."
4. **A price shock told as then versus now:** "I bought for 300 plus tax … now $950."
5. **Receipts read out loud:** "So, I sent in my inquiry and I got this back." He quotes the email and the timestamps: "They emailed me 2:24 p.m. … I emailed back 2:27."
6. **"I'm not saying X. I'm saying Y."** He uses it to escalate: "I'm not saying I went down from number 15 to number 17 … I'm saying in the top 100 results."
7. **Deadpan sarcasm at the villain's logic:** "and I'm confident that that would totally fix the homeless problem." / "a good job New York City … great job."
8. **Rhetorical outrage pointed at a specific act:** "How stupid do you think I am?" / "It's insulting."
9. **"To be fair" concessions, which make the attack credible:** "to be fair to Apple, this was not just Apple's fault … but it is a hundred percent their fault how they handled [it]."
10. **Showing the mechanism:** "Let's go over what's going on here in just the most simple of terms." / "the problem here is the mechanism…"
11. **Credentials stated bluntly when they matter:** "That is a PC3000 … We have a data recovery lab. That is what we do."
12. **Pre-empting the obvious objection:** "Now for those of you who are wondering, oh maybe your computer you plug it into isn't working…"
13. **Fact-checking out loud:** "Texas Penal Code 22.04 is actually about injury to a child." / "No, it doesn't."
14. **Rhythm:** run-on spoken sentences, then short punches: "It's all fake." / "That never happened. That doesn't exist." He repeats words for force: "You are done. You are done."
15. **The thesis about incentives, in plain words:** "when you do the right thing, it will be cheaper for them than when they do the wrong thing." / "Consumers built your company and now you're [screwing] them."
16. **Admitting his own interest, without polish:** "the smart thing to do would be to shut up … The stupid thing to do would be to make this video." / "I don't ever … ask you to buy Raycons."
17. **A concrete call to action for the viewer:** "start checking your subscriptions" / "report it for what it is."
18. **The same sign-off, with no moral wrap-up:** "That's it for today and as always I hope you learned something. I'll see you in the next video."

## 6. Slop blacklist

**Phrases to ban:**
- "In a world where…", "Meet PriceMonkey", "Introducing…"
- "game-changer", "seamless(ly)", "revolutionize", "effortless", "unlock", "empower", "supercharge", "next-level", "harness the power", "leverage", "cutting-edge", "AI-powered" as an adjective
- "Imagine if…", "What if I told you…"
- "It's not just X, it's Y"
- "Say goodbye to X", "Gone are the days"
- "Here's the thing", "Let that sink in"
- "Proof, not promises."-style slogan pairs
- "Ask the monkey" as a tagline

**Structures to ban:**
- Lists of three ("your price, your cap, your rules"; "new, refurbished, used" said as a jingle)
- Chains of rhetorical questions
- A tidy moral ending or uplifting summary
- Em-dash flourishes
- Every sentence the same length
- Invented stats, invented testimonials or user counts
- Vague villains ("the internet", "big retail") with no receipt on screen
- Captions that repeat the voice-over word for word as slogans
- Stock music swells

**What made v1 slop** (SCRIPT_v1.md):
- It was written as a beat table to tick criteria ("Hits: C1, T2"), not as something a person would say.
- It copied Rossman's catchphrases word for word ("today's episode of: the price on the tag is a lie"). That is a costume, not a voice.
- It used slogans: "Proof, not promises.", "your price, your cap, your rules", "Set your price and walk away", "Nobody gets to buy a higher ranking", "Ask the monkey".
- It put jargon in the voice-over: "MCP", "hash-chained", "EU Omnibus thirty-day rule".
- It crammed numbers in (€633, €795, €825, €9.16, €20) with no story about why the viewer should care.
- "Good job, internet" aimed at an abstraction.
- The problem section was 23 seconds; the rest was a feature tour.
- It had no "I", no personal stake, no "to be fair", and no mechanism explained.

**v2 improved but still risky:**
- The PS5 Pro story has no source in the repo.
- It reuses "Good job, internet."
- "He does the boring part" is borderline cute.

**Fixes:**
- One real purchase story, told in the first person.
- Read the receipt out loud.
- Aim at a specific practice: the tag versus what you pay at your door, a "price" that is another item's price, "ships to Finland?" never answered.
- Explain the mechanism once.
- Show Context.dev reading the page on screen.
- State the "never a better spot" rule in plain words.
- Plain sign-off.