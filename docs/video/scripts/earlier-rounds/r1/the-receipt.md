# The Receipt (v2): Seven Ninety-Five Plus Question Mark (the-receipt) — round-1 avg judge score 7.2

# The Receipt v2 (target 1:57, hard cap 2:00)

Voice: one person, one mic, a bit annoyed, talking like he's showing a friend his screen. No music, just room tone.

**The counter:** a plain monospace number in euros, top right, from the first frame. The dollar tag sits under it as a small grey label ("tag: $699.95"). It tracks **only the Allen's camera**, it **only ever goes up**, and it **never leaves the screen**. From 0:33 it shrinks into the corner and stays there unchanged. Other prices appear as normal on-screen tags and never on the counter.

---

**0:00–0:10 | The tag**
[SCREEN: PriceMonkey receipt for the allenscamera.net offer (replay `?q=sony%20a7%20iii%20body`). Tight crop on "Used Sony A7 III Body" and the tag $699.95.]
[TEXT counter: €633.32, with the small grey label "tag: $699.95 · 1 USD = €0.905"]

> Used Sony A7 III. Six ninety-nine ninety-five. Cheapest real tag out of twenty shops. Now watch what it costs to get it to Finland.

**0:10–0:26 | Reading the receipt**
[SCREEN: the same receipt, moving down one row at a time: the USD→EUR row, then the import VAT row (25.5%, €161.50) with a slow push-in, then the shipping row (unknown, counted as €0) and its flag "outside the EU: import VAT added, shipping to Finland unconfirmed".]
[TEXT counter: €633.32 → "+ €161.50 VAT" ticks in → €794.82 → "€794.82 + shipping ?"]

> Tag's in dollars, so that's converted. Fine. But the shop's outside the EU, so Finland adds twenty-five and a half percent VAT. On a used camera. Shipping? The page doesn't even say if they ship here.

**0:26–0:33 | The real price**
[SCREEN: hold on the counter, now large and centred for a beat: "€794.82 + shipping ?". Nothing else moves.]

> So the real price is seven ninety-five plus question mark. That's the number. Question mark.

**0:33–0:47 | To be fair, and the worse ones**
[SCREEN: the counter shrinks back to the top-right corner and stays there. Cut to the jessops.com offer and its flag "does not ship to Finland" (about 3 s). Then the e-infin.com offer at €1,029 with "possible grey import: no EU warranty" (about 3 s).]

> To be fair, Allen's isn't lying. The tag is the tag. You just find out the rest at checkout. And they're not the worst. Jessops won't ship to Finland. This one's a grey import, no EU warranty.

**0:47–0:58 | The price that isn't one**
[SCREEN: the mpb.com "Sony Alpha A7 III" offer at €239 in the not-counted group. Show both flags in full: "too good to be true: 75% under the used median (€949)" and "price disagrees … probably another item's price on the page". The monkey in the corner does one small slow head tilt. That is its only reaction in the video. The counter does not change.]

> And mpb. Two thirty-nine for an A7 III. No. That's some other item's price from the same page. A dumb scraper puts that on top. Here it's flagged and not counted.

**0:58–1:16 | How it reads the shops (Context.dev)**
[SCREEN, 0:58–1:05: split screen. Left: the real allenscamera.net listing page in a normal browser (pre-recorded, see shoot notes). Right: the PriceMonkey receipt for the same offer, with its source line, and the price row highlighted. A thin line draws from the price on the page to the price on the receipt.]
[SCREEN, 1:05–1:16: start screen, type `sony a7 iii body`, Enter. Offers land on the price line one at a time from different shops, and the line visibly re-orders as each one arrives. The counter stays in the corner.]
[TEXT, lower third, 0:58–1:05: "Read by Context.dev: search finds the listing, product extraction pulls price + stock. Free JSON-LD tried first."]
[TEXT, small, 1:05–1:16: "Recorded hunt, replayed · 17 offers · 20 shops · 23 pages set aside, each with a reason"]

> Every shop builds its page differently. Context.dev finds the listings and pulls the price out of each page, whatever the layout. If the price is already sitting in the page code, we skip the paid read. And the line re-sorts every time another shop comes in.

**1:16–1:38 | The turn, and why the dearer one wins**
[SCREEN: Sony hunt, finished. All prices switch from tag to all-in (euros, delivered to Finland). The counter slides out of the corner and docks next to the allenscamera row: "€794.82 + shipping ?". Tap the tori.fi used offer: receipt "€825, all in", resale about €715 after 12 months, €9.16/mo. Then the verdict text in full.]
[TEXT, small, on the tori.fi receipt: "resale ~€715 after 12 mo (measured: A7 III used sells 35% under A7 IV)"]
[TEXT verdict: "Buy used at tori.fi for €825: resell in 12 mo for ~€715, so it costs €9.16/mo. The cheapest sticker (€633 at allenscamera.net) lands at €795 with import costs and costs €20/mo."]

> So here's every offer with what they left off the tag. The comparison sites I've used sort by the tag. Here, the cheapest tag is the trap. The pick is a used one on tori.fi. Eight twenty-five, all in. Yeah, more. But sell it in a year and it's about nine euros a month. Allen's is about twenty.

**1:38–1:45 | Watch**
[SCREEN: the watch control on the tori.fi offer being set, and its confirmation. Film only the setting, not an alert.]
[TEXT, small: "Watches run on Context.dev Monitors. Notify only."]

> Not ready yet, put a watch on it. It keeps checking and only tells you. It won't buy anything.

**1:45–1:53 | Where we stand**
[SCREEN: scroll to the footer: "Ranked by what you pay, all in. No paid placements. We may earn a fee, never a better spot." Hold, no zoom.]

> We don't make a cent off this yet. If a shop ever pays us a cut, it still doesn't move up.

**1:53–1:57 | Out**
[SCREEN: start screen, empty search box, cursor blinking. The monkey idles in the corner. The counter comes back one last time, top right, alone: "€794.82 + shipping ?". Cut to black.]
[TEXT: PriceMonkey · reads the web with Context.dev · Junction 2026]

> That's it for today. See you.

[END ~1:57]

## Judge verdicts
- score 7.5: The persistent counter that only goes up is the strongest single visual device in the set, and it keeps the whole video on one question. The voice is right: "a bit annoyed, showing a friend his screen". The monkey's one head tilt at €239 is good restraint. It drags in the middle: the 0:58–1:16 Context.dev block (a split screen, a line drawn from page to receipt, live typing, re-sorting) does too much. "Cheapest real tag out of twenty shops" needs checking against the replay. There's no face cam, so it's less Rossman. | best: "So the real price is seven ninety-five plus question mark. That's the number. Question mark." | worst: [TEXT: "resale ~€715 after 12 mo (measured: A7 III used sells 35% under A7 IV)"] is a nerdy footnote nobody can read at speed, and it looks like a made-up stat.
- score 7.5: It has the strongest visual device in the set: one counter that only goes up and ends alone on screen as '€794.82 + shipping ?'. After 60 videos, that frame is what a judge would remember. The Context.dev beat is concrete: the real listing page sits beside the receipt, with a line drawn from the price on the page to the price on the receipt, and it says 'we skip the paid read' when JSON-LD exists. Weaknesses: 1:16-1:38 crams three ideas (the line switching to all-in prices, a jab at comparison sites, the per-month resale maths) into 22 seconds. 'Cheapest tag is the trap' reads like slogan copy. The 'measured: A7 III used sells 35% under A7 IV' overlay is an unexplained claim, so either source it or cut it. The ending ('That's it for today. See you.') is limp next to the counter shot, so let the counter be the last thing. | best: So the real price is seven ninety-five plus question mark. That's the number. Question mark. | worst: So here's every offer with what they left off the tag. The comparison sites I've used sort by the tag. Here, the cheapest tag is the trap.
- score 6.5: The counter that only goes up and never leaves the screen is a strong visual device, and '+ shipping ?' is the most memorable image in the set. But it spends 33 seconds on one receipt before anything else happens. The 'Now watch what it costs' hook is fine, not gripping. The Context.dev section reads like a sponsor read. A short-attention viewer leaves around 0:25 unless the counter animation is snappy. | best: So the real price is seven ninety-five plus question mark. That's the number. Question mark. | worst: Every shop builds its page differently. Context.dev finds the listings and pulls the price out of each page, whatever the layout.
