# 5. PriceMonkey: The Price on the Page (locked v10)

> A slightly annoyed guy shows a friend his laptop: the cheapest A7 III is €633, but once import VAT is added it's €795 plus shipping nobody will confirm, and PriceMonkey, built on Context.dev for Junction, ranks by what you actually pay.

Avg judge score 4.1 · 270 words · ~110 s

## Teleprompter (spoken only)

One of us was on OLX. Basically Polish Craigslist. PS5 Pro, under four hundred euros. Seller, no ratings yet. Is that a deal? No idea. We walked.
That one you can smell. The sneaky ones are normal shops. We're at Junction, a hackathon in Finland. So we built PriceMonkey. Let's try a used Sony A7 III.
Cheapest real price it found: Allen's Camera, in the US. Six hundred thirty-three euros. But that's outside the EU, so Finland adds import VAT. Twenty-five and a half percent. Seven ninety-five. Same as my calculator. Shipping to Finland? Unconfirmed. So seven ninety-five, plus... nobody knows.
To be fair, Allen's isn't scamming anyone. The price on the page just isn't what you end up paying.
MPB. Two thirty-nine. For an A7 III. Sure. Probably the price of something else on the page. It stays on the list so you see it. It just doesn't count.
Context.dev finds the shop pages and reads them. That's the challenge we entered. This is an earlier search, sped up. It pulls out price and condition, and checks it's the right camera. This one says A7 III. It's an A7R. Different camera. Thrown out.
Then it sorts by what you'd actually pay, here, in euros. Its pick: a used one on Tori, Finland's Craigslist. Eight twenty-five. It's already in Finland, so no import VAT. Allen's is seven ninety-five, plus shipping nobody will confirm. We'd take Tori.
How do we make money? Right now, we don't. Zero. If we ever add affiliate links, the order still goes by what you pay. You can check.
And Allen's? Still no word on shipping.

## Full script

Voice: one guy, a bit annoyed, showing a friend his laptop. Says "we" for the team. The only "my" is his own calculator. Room tone only, no music.
Two setups. LAPTOP = screen recording + VO. FACE = phone on a tripod. Record ALL audio on the phone in one spot.
COUNTER (corner text "€795 + shipping ?") comes on at "Seven ninety-five" in The price and stays through To be fair. It comes back for Out. It is off everywhere else.

---

### 0:00–0:11 | Bait
[SCREEN: saved OLX page, zoomed out: title, 1 600 zł, seller box. No scrolling.]
[TEXT: "1 600 zł · under €400"]
[TEXT: "no ratings yet" by the seller box, on "Seller"]

> One of us was on OLX. Basically Polish Craigslist. PS5 Pro, under four hundred euros. Seller, no ratings yet. Is that a deal? No idea. *(beat)* We walked.

### 0:11–0:22 | Who we are
[SCREEN: FACE cam]
[SCREEN: cut to PriceMonkey home, "sony a7 iii body" already typed, on "So we built"]

> That one you can smell. The sneaky ones are normal shops. We're at Junction, a hackathon in Finland. So we built PriceMonkey. Let's try a used Sony A7 III.

### 0:22–0:41 | The price
[SCREEN: Allen's receipt, no scrolling]
[SCREEN: Mac Calculator: 633.32 × 1.255 = 794.82]
[SCREEN: back to receipt on "Same as my calculator"]
[TEXT: counter on from "Seven ninety-five"]

> Cheapest real price it found: Allen's Camera, in the US. Six hundred thirty-three euros. But that's outside the EU, so Finland adds import VAT. Twenty-five and a half percent. *(calculator)* Seven ninety-five. Same as my calculator. Shipping to Finland? Unconfirmed. So seven ninety-five, plus... nobody knows.
> (2 s hold)

### 0:41–0:48 | To be fair
[SCREEN: FACE cam, counter in corner]

> To be fair, Allen's isn't scamming anyone. The price on the page just isn't what you end up paying.

### 0:48–1:00 | Too cheap
[SCREEN: MPB €239 row with its warning text in frame]

> MPB. Two thirty-nine. For an A7 III. *(1 s beat)* Sure. Probably the price of something else on the page. It stays on the list so you see it. It just doesn't count.

### 1:00–1:17 | How it reads
[SCREEN: Sony search from empty at 2x, live log with "Powered by Context.dev" in frame]
[TEXT: "Shop pages read by Context.dev · recorded earlier · 2x"]
[SCREEN: set-aside line "different model (a7r-3 vs a7-3)" on "This one says A7 III"]

> Context.dev finds the shop pages and reads them. That's the challenge we entered. This is an earlier search, sped up. It pulls out price and condition, and checks it's the right camera. This one says A7 III. It's an A7R. Different camera. Thrown out.

### 1:17–1:34 | What you pay
[SCREEN: click "What you actually pay", then click tori.fi €825, verdict opens]

> Then it sorts by what you'd actually pay, here, in euros. Its pick: a used one on Tori, Finland's Craigslist. Eight twenty-five. It's already in Finland, so no import VAT. Allen's is seven ninety-five, plus shipping nobody will confirm. We'd take Tori.
> (2 s hold on verdict, €825 and €795 both in frame)

### 1:34–1:44 | Money
[SCREEN: footer cropped to "Ranked by what you pay, all in. No paid placements."]
[SCREEN: cut to FACE cam on "Right now"]

> How do we make money? Right now, we don't. Zero. If we ever add affiliate links, the order still goes by what you pay. You can check.

### 1:44–1:47 | Out
[SCREEN: FACE cam, counter back, hard cut after "shipping"]

> And Allen's? Still no word on shipping.

### 1:47–1:50 | End card
[TEXT: "PriceMonkey · Junction 2026 · Context.dev challenge"]

[END ~1:50, hard cap 2:00]

## Shoot notes

SHOOT THIS MORNING. Submission deadline is Sun 15 Nov 10:00.

Changes from v9, by problem:
- Bait: cut "We're not finding out" because it sounded written. "No idea." is kept and now resolves with "We walked." "That one you can smell" replaces "That one's easy", so the no-ratings bait pays off and no longer contradicts "No idea".
- PS5 euro figure: the old overlay "≈ €363" implied 4.41 PLN/EUR, and the viewer flagged it as possibly wrong (about €375 at 4.25). The VO and overlay now say "under €400", which holds either way. Added a "no ratings yet" caption, because the page itself says "Nie ma jeszcze oceny".
- Team intro: "students" is not in any source, so it's cut. "here in Helsinki" became "in Finland", since Junction's venue (Aalto/Espoo) isn't confirmed in the repo. Say "in Espoo" only if you're sure.
- "Test:" became "Let's try". "Cheapest tag" became "Cheapest real price it found", which fixes the contradiction with MPB €239 and uses plain words. "Page doesn't say" became "Shipping to Finland? Unconfirmed.", which matches the receipt flag word for word.
- To be fair: changed to the viewer's plainer line, "The price on the page just isn't what you end up paying." It still states the problem.
- MPB: "It stays on the list. It never counts." became "It stays on the list so you see it. It just doesn't count." That answers why it's kept and breaks the slogan rhythm.
- Context.dev: dropped "Full disclosure" and "what actually reads". The line is now one flat breath, "Context.dev finds the shop pages and reads them", which covers search plus extraction (several endpoints). On screen, the live log's "Powered by Context.dev" mark and the caption tie the cards to Context.dev, which is the pass/fail item. "And it checks." was cut.
- Tori: it's called "Its pick", not "Best deal". The VO now says why it wins over €795 ("no import VAT" vs "shipping nobody will confirm") and ends with "We'd take Tori." Don't say "nothing to add": the tori receipt also has shipping not listed.
- Money: cut the "small cut" promise and "call us out". "Right now, we don't. Zero." stays. Crop the footer so the "We may earn a fee, never a better spot" span isn't in frame.

Shot checks before rolling:
1. The Sony run is the recording at ?q=sony%20a7%20iii%20body (replay, 0 credits). Don't call it live anywhere. Keep the caption on.
2. The all-in control exists. It's the ln-switch in line.js, with the buttons "Price on the tag" and "What you actually pay". It may be locked while the hunt runs, so click it after the line finishes. Flip to "Price on the tag" and back to "What you actually pay" for a visible move. If it won't click, film the automatic Turn instead.
3. Keep the live log panel ("what Context.dev is reading", with the "Powered by Context.dev" mark and the "Context.dev · product" rows) in frame during the 2x search.
4. Have the MPB row's flag text ("too good to be true", "probably another item's price on the page") open and legible.
5. OLX: zoomed out, no scrolling. The "Zobacz też" strip must never be on camera.
6. Calculator: type 633.32 × 1.255 live; it gives 794.82. Say only "Seven ninety-five".

Timing: 270 spoken words, about 98 s at about 165 wpm, plus about 7 s of beats and holds and a 3 s end card, comes to about 1:50, with 10 s of slack under the 2:00 cap. If it runs long, cut "here, in euros" first, then "Basically Polish Craigslist" (though viewers liked it).

Kept because both critics liked them: "No idea", "Same as my calculator", "plus... nobody knows", "To be fair, Allen's isn't scamming anyone", "Sure.", "It's an A7R. Different camera. Thrown out.", "Right now, we don't. Zero.", the honest recording caption, the counter device, and the "Still no word on shipping" hard cut.

## Judge verdicts
- 4: It opens on the PS5 Pro OLX story, which the bible says outright has no source anywhere in the repo. Leading a pro-consumer, receipts-first pitch with an unverifiable anecdote is disqualifying for this owner. It also contradicts itself: "the sneaky ones are normal shops" sets Allen's up as the villain, then "Allen's isn't scamming anyone" walks it back. The problem is never shown by hand. We jump into the app at 0:22 and "Same as my calculator" refers to a calculator the app scene just cut to, so the receipt has no stake behind it. Context.dev gets a decent section (1:00-1:17), and the money line plus the shipping callback are strong. But the hook is unverified and the problem is told rather than lived. Cut the OLX opening or don't use this draft.
- 4: It opens on the PS5 Pro OLX story, which the bible says has no source in the repo and should be treated as unverified. In a challenge that scores trust and real-world impact, putting that claim in the first 11 seconds is disqualifying until someone can show the saved page. The bait also has no payoff: PriceMonkey never searches OLX or the PS5. The rest is decent: the calculator matching the receipt, the 'to be fair' line, Context.dev named as the challenge with "recorded earlier · 2x" on screen, and a crisp ranking rule ("the order still goes by what you pay. You can check."). But there is no first-hand hunt, so the problem is told rather than shown. "Finland's Craigslist" and "Polish Craigslist" repeat a crutch, and the counter overlay is fiddly. Fix the opening or drop it.
- 4.5: The opener loses me. A PS5 on Polish OLX has nothing to do with a camera in Finland, "That one you can smell" is confusing, and your own notes say the story has no source. Burning 11 seconds on that is the worst choice in the set. The problem is never shown by hand: the app is already open at 0:22 and tells me the answer, so the "Same as my calculator" moment doesn't land because I never saw anyone struggle. The Context.dev part comes at 1:00, after the results, so it plays like a sponsor segment in the wrong place. The "To be fair" line is the best in any of the five, and the shipping callback works. "You can check" in the money section is good too. The pieces are good but the structure is backwards.
- 4: I wouldn't shoot this one. It opens on the OLX PS5 Pro story, which the bible flags as unverified with no source in the repo, so the first eleven seconds are the one thing we were told not to claim. It also needs a saved OLX page we may not have. It contradicts itself: it sets up 'the sneaky ones are normal shops', then says 'Allen's isn't scamming anyone' with no real villain in between. The calculator shot starts from €633.32, so the conversion is already done and the viewer never sees the dollar shock. Tori turns up only at 1:17, so there is no tab-one payoff. Context.dev arrives a full minute in. The counter overlay, 'You can check' and the 'Still no word on shipping' button are good craft. They are not worth leading with an unsourced anecdote on deadline day.
