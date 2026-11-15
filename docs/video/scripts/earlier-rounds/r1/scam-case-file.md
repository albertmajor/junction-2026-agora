# CASE FILE: THE €239 CAMERA (v3) (scam-case-file) — round-1 avg judge score 6.3

## CASE FILE: THE €239 CAMERA

Target 1:56. Hard cap 2:00. 292 spoken words (numbers spelled out), about 2.5 words a second. Read at a normal talking pace. The pauses after "Scam?", "Dollars." and "It says no." are part of the timing.

---

**0:00–0:11 | THE LISTING**

[SCREEN: Load `?q=sony%20a7%20iii%20body`, the free cached replay, so nothing gets typed and no credits are spent. Let the line fill, then zoom on the mpb.com card: "Sony Alpha A7 III", €239, used, real product photo.]

[TEXT: CASE 001. Sony A7 III, used. €239.]

VO: "I searched for a used Sony A7 III. First thing I see: mpb, two hundred thirty-nine euros. The other used ones it found are about nine fifty. So. Scam?"

---

**0:11–0:21 | THE EVIDENCE**

[SCREEN: Open the mpb card's flags. Highlight "too good to be true: 75% under the used median (€949)". Then push in on "price disagrees: product read €239 vs the used market €949; nothing in the title or search listing backs it (probably another item's price on the page)".]

VO: "PriceMonkey checked it against the others. Seventy-five percent under, and nothing in the title backs it up. Probably another item's price on the page."

[SCREEN, under the VO, no line read: the third flag on the same card, "seen before in 7 hunts". Hold it for one second.]

---

**0:21–0:38 | THE VERDICT ON THE CASE**

[SCREEN: Stay on the mpb card at full size.]

VO: "To be fair to mpb, that's probably not a scam. It's a wrong number. But a site that just sorts by cheapest puts it right at the top, and you'd click it. I would."

[SCREEN: Pull back to the whole line. The mpb card is greyed and sits outside the ranking. Caption it with the app's own words, not a slogan: "not costed: price unconfirmed (far off the market or disputed)".]

VO: "Here it stays on screen. It just doesn't get ranked."

---

**0:38–0:53 | THE CHEAPEST REAL ONE**

[SCREEN: allenscamera.net card: used, $699.95. Open the receipt. Show only two rows: the evidence row `via: contextdev_product`, "price 699.95 USD", and the bottom line "all in €794.82". The middle rows (€633.32 at 1 USD = €0.905 ECB; import VAT 25.5% +€161.50) are visible but not called out.]

VO: "Cheapest one that's real: Allens Camera. Six ninety-nine ninety-five. Dollars. With Finnish import VAT, that lands at seven ninety-five."

[SCREEN: Flag: "shipping to Finland unconfirmed".]

VO: "Ships to Finland? The page doesn't say."

[SCREEN: Hard cut to the jessops.com card. Flag: "does not ship to Finland". Hold for half a second.]

VO: "Jessops, to be fair, does say. It says no."

---

**0:53–1:12 | HOW IT READ THE PAGES**

[SCREEN: Split screen, three seconds: the jessops receipt row `via: jsonld` on the left (the free read). Then swap the right side through two Context.dev rows: allens `via: contextdev_product` "price 699.95 USD", then tori.fi `via: contextdev_json` "price 825 EUR". Small Context.dev logo in the corner.]

VO: "If a page gives us its price for free, we take it. If not, Context.dev reads the page. Product extraction on Allens, JSON extraction on this tori listing."

[SCREEN: Hunt summary: 17 offers. Scroll the set-aside list without sound, then stop on one row: "different model (a7r-3 vs a7-3)".]

VO: "Seventeen offers made the line. The rest got set aside, each with a reason. This one's an A7R III. Different camera."

---

**1:12–1:26 | THE PICK**

[SCREEN: The tori.fi card at the top: used, €825, price band "typical". Then the verdict line in full: "Buy used at tori.fi for €825: resell in 12 mo for ~€715, so it costs €9.16/mo. The cheapest sticker (€633 at allenscamera.net) lands at €795 with import costs and costs €20/mo."]

VO: "So I'd buy the used one on tori, eight twenty-five. Allens is thirty euros cheaper, if they even ship. Sell it after a year and it works out to about nine euros a month."

[SCREEN, 1 s insert, no VO: the tori.fi receipt's suggested message to the seller, ending "shutter count / battery health? Thanks!"]

---

**1:26–1:37 | THE WATCH**

[SCREEN: On the tori.fi sheet, click "Watch at €…". Show the watch confirmation. Do not cut to the API index.]

VO: "I set a watch on it. Context.dev keeps checking that page and pings me if the price drops. It hasn't yet, so I can't show you that part."

---

**1:37–1:50 | THE RULE**

[SCREEN: The small monkey mark in the footer, then tilt to the footer line, on screen only and not read out: "Ranked by what you pay, all in. No paid placements. We may earn a fee, never a better spot."]

VO: "Yes, there's a monkey. To be first on this line, a shop has to be cheaper at my door. If we ever earn a fee off one, it still doesn't get a better spot."

---

**1:50–1:56 | SIGN-OFF**

[SCREEN: Back on the full price line. Slow push toward the greyed €239 mpb card, still outside the ranking. No music swell.]

VO: "That's PriceMonkey. The two thirty-nine is still on there. Still not ranked. See you."

[TEXT, small, bottom corner: PriceMonkey · built on Context.dev]

END ~1:56

## Judge verdicts
- score 7: Very good facts: tori is correctly read via contextdev_json, and allens via contextdev_product, both confirmed in tests/fixtures/live_sony-a7-iii-body.jsonl. "Jessops, to be fair, does say. It says no." is a great line. The ending, where the €239 card is "still not ranked", is a neat callback. It's VO only with no face, though, and the case-file gimmick is fighting the tone. Section 0:53–1:12 shows `via:` rows on a split screen, which is engineer-pleasing and viewer-numbing. | best: "To be fair to mpb, that's probably not a scam. It's a wrong number. But a site that just sorts by cheapest puts it right at the top, and you'd click it. I would." | worst: [TEXT: CASE 001. Sony A7 III, used. €239.] The true-crime framing is a YouTube trope, and it undercuts the "it's not a scam" honesty that follows.
- score 5.8: The case-file frame undercuts itself: it builds to 'Scam?' and answers no 20 seconds later, so the gimmick costs credibility instead of earning it. The strong parts are worth keeping: the split screen of 'via: jsonld' against 'via: contextdev_product' against 'via: contextdev_json' is the clearest on-screen proof of how the pages are read in any script, 'seen before in 7 hunts' hints at memory across hunts, and the ending callback to the still-unranked €239 is elegant. Too much of the runtime (0:00-0:38) goes on a price that, by its own admission, isn't a scam. | best: VO: "That's PriceMonkey. The two thirty-nine is still on there. Still not ranked. See you." | worst: [TEXT: CASE 001. Sony A7 III, used. €239.] ... "So. Scam?" ... "To be fair to mpb, that's probably not a scam. It's a wrong number."
- score 6: 'Scam?' at 0:11 is a strong curiosity hook. Then at 0:21 the answer is 'probably not a scam, wrong number', so the case closes 20 seconds in and the case-file frame has nothing left to carry. 'via: jsonld' and 'contextdev_json' split screens mean nothing to a viewer. Ending on the €239 card that's still unranked is a nice callback, but most people will have left by then. | best: Jessops, to be fair, does say. It says no. | worst: If a page gives us its price for free, we take it. If not, Context.dev reads the page. Product extraction on Allens, JSON extraction on this tori listing.
