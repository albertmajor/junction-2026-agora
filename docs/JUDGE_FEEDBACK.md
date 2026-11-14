# Judge feedback (Junction 2025, Context.dev booth)

Sources: five phone videos filmed at the Context.dev booth, transcribed with whisper.cpp large-v3. The transcripts and frames are in the session scratch dir `judges/`.
- `mcp_video-4124` is 2 s long and contains only "Good."
- `mcp_video-4164` (3:02) has the main critique and a live try.
- `mcp_video-4135` (0:40) is the wrap-up.
- `video-4183` (5:00) covers speed, outliers, currency and affiliate money.
- `video-4190` (5:00) has Thomas (Context.dev) testing his espresso machine, plus clarifying questions and noise.

The transcripts have no speaker labels, so attributions are best-effort. Every judge was from Context.dev, which is the challenge sponsor.

Status key: **UI** = a web builder does it in this round. **ENGINE** = a note for the quality loop, which owns resolve/judge/need/discover/hunt/longtail/reader/marketplaces/sources. **PITCH** = goes in docs/PITCH_NOTES.md. **LATER** = docs/AFTER_HACKATHON.md.

---

## What they liked (keep it, and don't break it)

| # | Quote | What we do |
|---|---|---|
| K1 | "Nice, quick, snappy autocomplete." / "How is it this fast?" / "It's suspiciously fast, it's actually quite good" / "very snappy" | Keep it. Don't add anything that delays the first offer. The landing copy can mention speed ("first prices in seconds"), but only if a recording backs it up. |
| K2 | "It immediately places everything on a scale by price. This is smooth." / "it's snowing prices" | The line is our signature. The landing should show it (the drawn mock-line in "How it works") and name it. |
| K3 | "Are you waterfall… the moment you make the request you show the data immediately?" / "That's very sick." | We stream results. Say it in the copy ("you watch it happen"). |
| K4 | "it's already starting to recommend things." | The pick arrives live. Keep it. |
| K5 | "It's very cute." / banana-eating loader: "It's so cool." | Keep the monkey and the banana loader. Owner's placement is frozen (docs/pricemonkey-*.json, mascot.js MONKEY_PLACE). |
| K6 | "I can tell how it works. It's really fucking cool." / "It's production ready." / "I like your product." | Quote them in the pitch (PITCH). |
| K7 | Thomas: "All the time I had to … detect the structure of the page to not get rate blocked." | This is the pain Context.dev removes for us. Put it in the Context.dev banner copy and the pitch. |
| K8 | "Are you using our product extraction…?" The judge says it pulls hidden data from the page, "I think that's why it's working." | Say on the banner that Context.dev reads the structured product data from the page, not only the HTML. |

## Critiques and suggestions

### F1. Validate with real customers, not with judges (4164, 4135). PITCH, UI
> "what we're looking for is not just a business case… something you can put out in the market." / "the people who are going to be using it, it's not me, it's going to be some customer." / "I would be much more interested to hear if you come to a front end … based on customer feedback… Not my feedback, because I'm not their target." / "Now I'm getting the point of not validating."

- **PITCH:** add a "What users told us" slide. Run 5–10 hallway tests with real shoppers before the pitch: one task each ("find the cheapest X delivered to you"), time it, and record one quote. Don't present the A/B choice as the judges' vote.
- **UI (landing):** leave room for a small "what testers said" strip. Only fill it with quotes we really collected; until then, hide it or leave it out. Never invent testimonials.

### F2. Show that very specific queries work (4164). UI
> "I didn't even read it and I was about to type in PS5 without a GTA…" / "how specific can I be?"

- The start examples (`#examples`, main.js) and the placeholder should include constraint-heavy queries, for example: "PS5 Pro without GTA bundle, delivered to Helsinki", "Sony A7 III body only, under €900, used is fine", "someone to clean a 2-room flat in Kallio this Friday".
- **Landing:** give it a section of its own, "Be as specific as you like." It should show 3–4 real-looking queries, each with the constraint highlighted and what we do with it (filter, rank, ask).

### F3. Ask a clarifying question when a query is broad or ambiguous (4190, Thomas). ENGINE, UI
> "if you detect that it's … super broad … you should probably … quickly ask a question. 'We see multiple products with this name.'" / "Huh? This is not at all what I want."

- **ENGINE (need.py / resolve.py):** when the resolved need has more than one strong product identity (several distinct models or categories share the name), or a low-confidence identity, emit an event `clarify {question, options:[{label, q, image?}]}` before or alongside the first offers. Don't block the hunt; keep the stream running for the top guess.
- **UI (intent.js / intent.css):** the `#intents` chooser already exists. It should render a `clarify` event as "We see a few products called *X*. Which one?" with picture chips. Clicking a chip re-asks with the chosen `q`. Until the engine sends `clarify`, reuse the existing intent-plan list and change only the copy.

### F4. Relevance: off-target cheap hits for niche products (4190). ENGINE
> "The results gave an irrelevant hit for 79 EUR … This is not… What is that?" / "it still needs to better understand … what the user is looking for."

- **ENGINE (judge.py):** tighten the Gemini relevance gate for exact-model queries. If the query names a model and the listing's title or category doesn't contain it (or it's an accessory, part or other category), drop it to "not counted". Use a price-sanity check against the median of the matched offers: an offer below about 0.3× the median for a named model is suspect, and should be flagged or excluded unless it's clearly used or damaged and still the same model.

### F5. Let the user filter out noise easily; more pictures (4190, 4183). UI
> "can you make the UI so … it's easy for a user to filter out the noise … with pictures, for example." / "This feels more like it. That with more pictures in there?" / "put out … more pictures that you can see in the app right away and … scroll it."

- **UI (ledger.js / listings.css):** show a thumbnail on every ledger row, and give each row a one-click "not this" that moves it to "not counted" and re-picks. The "not counted" group stays visible, so the user can see what we removed and why.
- **LATER / ENGINE:** use Context.dev's image endpoint (it pulls and categorizes every image on a page in one request) to fill missing product photos.

### F6. One extreme outlier squashes the price line (4183). UI
> "There's one extreme outlier, so now it's all going…"

- **UI (line.js `range()`, around l.119):** base the domain on robust bounds (for example the 5th–95th percentile, or median ± 3×IQR) rather than raw min/max. Outliers beyond the bounds get pinned at the edge as a small "→ €4,900" (or "€12 ←") marker that is still clickable. The log scale gets the same treatment.

### F7. Make currency and price conversion explicit (4183). UI
> "How do you handle the price conversions?" / "How do you decide the currency?" / "Does the price make sense, though?"

- **UI:** wherever the original currency isn't EUR, show the original price ("$699 → €643 at today's rate") in the sheet and on the ledger row hover. The landing's all-in section should say it in one line: "Every price converted to euros at today's rate, with the original kept."
- Check the copy claims "Everything in euros", "whether it reaches you" and "No paid placements" against what the code really does (fx.py, origin.py, footer).

### F8. More results (4183). ENGINE, UI
> "we have only 10 responses now" / "You increased it" / "We can max it out" / "it could be even faster"

- **ENGINE (hunt.py):** raise the offer cap, as long as time-to-first-offer doesn't get worse.
- **UI:** the ledger must handle 40+ rows. Collapse it after about 12 with "show all N".

### F9. Too gamified for someone who "just wants to search" (4183). UI
> "It's very gamified, I just wanted to search it."

- Keep the line, but make the plain path obvious: once the hunt is done, the verdict and the ranked list must be reachable with one scroll and no animations in the way. Respect `prefers-reduced-motion`. Don't add any new game-like effects on the results page.
- On the landing, keep the playfulness in the copy and the monkey, not in extra motion.

### F10. Monetization: affiliate links, shown transparently (4183). PITCH, LATER
> "You know how you guys should make money? … Affiliate links." / "rank towards the ones where you have affiliates a little bit" / Team: "we still want to be pro-consumer" / Judge: "Maybe what you should do is show the data appropriately." The judge compared it to Camelcamelcamel.

- Our position is "We may earn a fee, never a better spot" (already in the footer). Affiliate links count only as a tie-breaker between equal all-in prices, and each one is labelled.
- **PITCH:** a business model slide covering affiliate revenue (Amazon Associates, Awin, Tradedoubler and others), low running costs ("it will cover itself"), and the judge's pocketknife engine as a reference point.
- **LATER:** auto-generated SEO and LLM pages for each product hunted (example: "Cheapest Sony A7 III delivered to Finland, today"), built from real hunts. Context.dev has a 40k-person newsletter, so ask them about a feature.

### F11. The voice is "so serious" (4190). LATER
> "This voice is so serious" (Gemini Live during the monkey-AI demo)

- There's no TTS in `agora/web/js` in this repo, so it's probably in the second prototype. Wherever it lives, give the monkey a warmer, playful voice and persona prompt.

### F12. Keep Context.dev visible (all videos). UI, PITCH
- Keep the landing's "Powered by Context.dev" banner (owner request 4/5) and the live reading log. The banner copy should name the real pain: page structures, rate blocks, hidden product data.

---

## Notes for the engine quality loop (do not do these in web builders)

1. **Clarify event** (F3). In need.py/resolve.py, detect an ambiguous or broad identity and emit `clarify {question, options[]}`. Add it to CONTRACT.md's event list. The UI renders it in `#intents`.
2. **Relevance gate** (F4). In judge.py, enforce model-token matching and an accessory/part/category mismatch check for exact-model queries, plus a price-sanity check against the matched-offer median. Test case: a niche espresso machine query (for example "Lelit Bianca", German dual-boiler with pre-infusion) must not show a €79 accessory as the pick.
3. **Offer cap** (F8). In hunt.py, raise the cap (10 → 30–50) while keeping time-to-first-offer.
4. **Images** (F5). If enough credits are left, use the Context.dev image extraction to fill missing photos.
