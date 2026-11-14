# PriceMonkey: 2-minute video script

**Hard limit: 2:00. Target cut: 1:52.** Junction is "very strict" about this (guidebook, Project Submission).
Every number below comes from a recording in `tests/fixtures/` or from `docs/PITCH_NOTES.md` section 6. If you
change a query or record live, the numbers change: then drop the figures from the voice-over or re-check them.

## The brief, from the owner's memo (`docs/video/owner-memo.txt`)

1. **Open with the problem.** Say clearly what is wrong and what we solve.
2. **Then how we solve it, and lean hard on being pro-consumer.**
3. **Sound like the YouTuber in "The style i want/"** (Louis Rossman: seven transcripts, text only, no video or
   images in that folder).
4. **Monkey vibe, not monkey stuff.** "Not too monkey, but a little monkey." The mascot gets a cameo; no
   banana puns, no monkey noises.
5. **The villain is the pages:** shops that bait with a tag price, hide fees, fake discounts and lie about
   stock.
6. **The solution runs on Context.dev,** because that is the challenge we are going for.

## The style, taken from the Rossman transcripts

| What he does | How we use it |
|---|---|
| Same opener every time: "Hey everybody, how's it going? Hope you're having a lovely day." Sometimes a named episode: "Welcome to today's episode of *How I'm getting screwed*." | Beat 1 uses the episode format: "today's episode of *the price on the tag is a lie*." |
| Talks straight to the camera, first person, fast, no script voice | One person on camera (talking head, desk, normal room). Short sentences. No stock music bed under the voice, or a very quiet one. |
| **Receipts.** He puts the email, the receipt or the frame on screen and reads it out ("So I sent in my inquiry and I got this back"). | Every claim is a screen recording of our own app showing the real number. Zoom in on the line he reads. |
| Dry sarcasm at the villain: "Good job, New York City." | One line of it in Beat 2. Aim it at the practice, never at a named shop. |
| Pro-consumer stance said out loud: "Consumers built your company." / "When someone screws you, just stop spending money with them." | Beat 6: "We may earn a fee, never a better spot." |
| Concrete specifics: model numbers, prices, dates, "$300 then, $950 now" | Sony A7 III, $699.95, €633, €795, €825, €9.16 a month. |
| Same sign-off: "That's it for today, and as always, I hope you learned something. I'll see you in the next video." | Beat 7, word for word, then the monkey. |
| Swears, bleeped | Keep it clean. This video is public and judged. At most one bleep, and only if it lands. |

## Who is on screen

- **Host:** one team member, talking head (laptop camera is fine), Rossman framing: chest-up, off-centre, a
  real room behind. Cut between the host (about 30% of the time) and full-screen app recordings (about 70%).
- **The app:** recorded from the offline replays so the numbers match this script and cost no credits. See
  `docs/video/SHOTLIST.md`.
- **Captions:** burned-in subtitles for the whole voice-over (judges watch muted) plus the big on-screen
  callouts listed per beat. Font: the app's fonts (`docs/pricemonkey-fonts.json`), sentence case.

## Judging criteria this video has to hit

| Code | Criterion | Weight | Challenge |
|---|---|---|---|
| C1 | Real-world impact | 20% | Context.dev main |
| C2 | Creative use of live web data | 20% | Context.dev main |
| C3 | Completeness of demo | 20% | Context.dev main |
| C4 | Technical execution (latency, accuracy) | 20% | Context.dev main |
| C5 | Real-timeness (reacts to change over time) | 20% | Context.dev main |
| T1 | Creative use of Context.dev (several endpoints) | 40% | Best Use of Context.dev |
| T2 | How central live web data is | 30% | Best Use of Context.dev |
| T3 | Technical execution (accuracy, latency, change over time) | 30% | Best Use of Context.dev |
| T0 | Minimum: Context.dev data visibly drives something in the demo | pass/fail | Best Use of Context.dev |

Exa, Oxylabs and Gemini are optional lanes in the code and the demo does not depend on them (README, Sponsor
tech). **Do not pitch them in this video.** If the team enters Exa or Oxylabs anyway, their rules need a live
call in the demo, and the replay recordings below are not live.

---

## The script

Voice-over speed is about 2.6 words per second (Rossman pace). Each beat's word count is in brackets.

### Beat 1: Cold open (0:00 to 0:07)

**Shot:** Host to camera.
**VO [19 words]:**
> "Hey everybody, how's it going? Hope you're having a lovely day. Welcome to today's episode of: the price on
> the tag is a lie."

**Caption (big):** `the price on the tag is a lie.`
**Hits:** C1 (sets up a consumer problem).

### Beat 2: The problem, with receipts (0:07 to 0:30)

**Shots:** fast cuts, one per sentence, each a zoom on a real flagged offer from the Sony A7 III recording
(SHOTLIST S2a to S2d).

**VO [55 words]:**
> "I want a Sony A7 three. Here's one for six hundred and thirty-three euros. Except it's a US shop, so add
> import VAT, and they may not even ship to Finland. Here's another one for two hundred and thirty-nine.
> Too good to be true? It is. Every shop shows you the nicest number it can. Good job, internet."

**On-screen callouts (one per cut):**
- S2a: `$699.95 → €633 tag` then `+ €161.50 import VAT` then `= €795 at your door`
- S2b: `shipping to Finland: unconfirmed`
- S2c: `€239 ← 75% under the used median (€949). Not counted.`
- S2d: host to camera for "Good job, internet." (deadpan)

**Hits:** C1 (real need: you can't trust the tag), sets up C4 (accuracy).

### Beat 3: The answer (0:30 to 0:48)

**Shots:** S3. The start screen with the monkey; type `sony a7 iii body`; the banana loader for under a
second; offers fly onto the line from the shop they were read on. Then the live reading log.

**VO [45 words]:**
> "So we built PriceMonkey. One search box. It asks every shop at once: new, refurbished, used. Context.dev
> reads each page into clean product data, price, condition, stock, so we never wrote a scraper for a single
> shop. Every offer lands on one line, cheap on the left."

**Captions:** `PriceMonkey: one search box, every shop.` then `Context.dev: page → product JSON` (over the
live log) then `17 offers from 24 pages read` (from the recording).
**Hits:** T0, T1, T2, C2 (live pages as the data source), C3.

### Beat 4: The Turn, what you actually pay (0:48 to 1:13)

**Shots:** S4. The line turns from tag prices to all-in prices. Open the allenscamera.net receipt, then the
tori.fi one. Zoom on the verdict headline.

**VO [55 words]:**
> "Now watch the line turn. That's what you pay at your door: tag, shipping, import VAT, fees, minus what you
> resell it for. The cheapest tag lands at seven ninety-five. The used one in Finland: eight twenty-five all
> in, nine euros a month to own. The other: twenty. Every number shows its source."

**Captions:** `Cheapest tag is not cheapest.` then `tori.fi €825 all in → €9.16/mo` vs `US shop €795 + ? shipping → €20.49/mo`
then `every number shows its source` (over an open receipt with source rows).
**Hits:** C1, C4 (accuracy, FX at today's rate, import VAT), C3.

### Beat 5: It keeps watching (1:13 to 1:33)

**Shots:** S5. Drag the yellow "your price" tag. Then the `?stage=1` overnight beat ("PriceMonkey watches
overnight") and the hash-chained log catching an edited row.

**VO [50 words]:**
> "Set your price and walk away. A watch is a standing order with a spending cap. It catches pages that say
> 'in stock' but show 'sold out', and discounts that were never real, under the EU thirty-day price rule.
> Every decision goes into a log you can check."

**Captions:** `your price, your cap, your rules` then `sold out? the page says so, we skip it` then
`fake "was" price → discount inflated (EU Omnibus, 30 days)` then `Proof, not promises.`
**Small honest label in the corner during the buy:** `auto-buy shown on our demo shop`.
**Hits:** C5 (reacts to change over time; Context.dev monitors feed watches), T3, C3.

### Beat 6: Pro-consumer (1:33 to 1:47)

**Shots:** host to camera, then a quick cut of the footer line and the agent view (press **A**).

**VO [36 words]:**
> "And the business? We may earn a fee, never a better spot. No paid placements. Your AI agent gets the
> exact same line through MCP, with no checkout. Nobody gets to buy a higher ranking."

**Captions:** `We may earn a fee, never a better spot.` then `same line for your agent (MCP)`.
**Hits:** C1 (a business that stays on the buyer's side), C3, T2.

### Beat 7: Sign-off (1:47 to 1:55)

**Shots:** host to camera; last frame is the monkey on the start screen with the logo and the repo link.

**VO [19 words]:**
> "PriceMonkey. Ask the monkey. That's it for today, and as always, I hope you learned something."

**End card (hold 3 s, inside the 2:00):** logo, `PriceMonkey: what you'd really pay`, `Built on Context.dev`,
repo URL, `Junction 2026`.

**Total VO:** about 280 words, about 1:48 at 2.6 words per second. With the 3 s end card that is about 1:52. Leave the slack, don't fill it.

---

## Optional swap (only if it's real by recording time)

**Hallway test quote.** If the team runs the user test in `docs/PITCH_NOTES.md` section 2, replace the second
half of Beat 6 with one real tester on camera or one verbatim quote card: `"..." - first name, role`. Never
invent or polish one. Judges asked for customers, not judges (`docs/JUDGE_FEEDBACK.md` F1).

**Judge quote.** One booth quote may go on a card in Beat 3, labelled `a Context.dev judge at our booth`:
`"It's snowing prices."` Do not present judges as users.

## What we must not say (it's not true, or not proven)

- "Reads any site" or "beats every rate limit." Say: "We never wrote a scraper for a single shop."
- "It buys for you on any shop." Auto-buy runs only on our mock shop, under a signed mandate.
- Exact live speeds in milliseconds. The recordings were partly cached. "First prices in seconds" only with the
  replay on screen.
- Anything about cars, insurance or other quote-only services. They are the weakest areas
  (`docs/QUALITY_REPORT.md`).
- Any testimonial we did not collect.
- Exa, Oxylabs or Gemini as part of the demo.
