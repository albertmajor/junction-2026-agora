# The Ad Doesn't Say (cross-border, v3) (europe-fragmented) — round-1 avg judge score 7.5

**Runtime target:** 1:50 to 1:55 with the camera beat, about 1:43 without it. **Spoken words:** 311 with the camera beat, 276 without. Numbers are written the way they're said.
**Hard rule:** do a timed table read before filming. If it runs past 1:50, cut the camera beat (1:31 to 1:42) completely. Nothing else depends on it.
**Recording rule:** use only the replay at `http://localhost:8765/?q=city%20bike%20with%20basket` (load the URL directly), the Sony replay at `?q=sony%20a7%20iii%20body`, `tests/fixtures/`, and public marketplace pages opened in a normal browser. Live search stays off.

---

### 0:00 to 0:11 | Cold open: the ad
[SCREEN: The Blocket ad "Monark Orange stadscykel 56 cm – begagnad", 1 200 kr, Swedish UI (blocket.se item 28014245; if the ad is gone, use its tile photo from the replay). Scroll slowly to the bottom of the ad. Nothing on it mentions shipping. Hard cut to the replay's receipt for the same tile: price 1200 SEK → €108, plus "shipping SE→FI, est. €50–100".]

**VO:** This bike is in Sweden. Twelve hundred kronor, about a hundred and eight euros. Shipped to Finland, more like a hundred and eighty. If they'll even post it. The ad doesn't say.

[TEXT: none]

### 0:11 to 0:25 | The problem
[SCREEN: Webcam, plain room, no music. Then four hard cuts of about 2 s each, one per search page: `tori.fi/recommerce/forsale/search?q=kaupunkipyörä`, `blocket.se/recommerce/forsale/search?q=stadscykel`, `kleinanzeigen.de/s-citybike/k0`, `marktplaats.nl/q/stadsfiets/`. Hold one extra beat on the Dutch one.]

**VO:** Hey everybody. We tested this on the most boring thing we could think of. A city bike with a basket. Four marketplaces had nineteen thousand four hundred of them. Almost ten thousand are Dutch. I don't read Dutch.

[TEXT: lower-thirds with each site's own count, taken from the recording: "tori.fi · 1,320", "blocket.se · 569", "kleinanzeigen.de · 7,664", "marktplaats.nl · 9,852"]

### 0:25 to 0:39 | The villain: the ad never says
[SCREEN: Scroll the Swedish, German and Dutch tiles in the replay. Open three in a row and show each flag word for word: "abroad (SE): shipping €50–100 estimated, not quoted; the listing does not say it ships, ask the seller", then "abroad (NL): shipping €60–120 estimated, not quoted; the listing does not say it ships, ask the seller", then "pickup only, abroad (DE): the seller does not ship to Finland". On "Nur Abholung", cut to a real Kleinanzeigen listing page with its "Nur Abholung" label circled.]

**VO:** We went through a hundred and five of the Swedish, German and Dutch ones. Not one says it ships to Finland. Thirty-two say pickup only. Nur Abholung. You find that out after you've messaged someone. In German.

[TEXT: "105 listings from SE, DE, NL · say they ship to Finland: 0 · pickup only: 32"]

### 0:39 to 0:47 | The name, once
[SCREEN: Webcam for "Yes, the name is dumb", then the monkey icon for about one second. Then the search box with "city bike with basket" typed into it, and a cut to the four lane queries shown as chips or a jq-pretty-printed view of the lane event (not raw JSONL): `kaupunkipyörä`, `stadscykel`, `citybike`, `stadsfiets`.]

**VO:** So, PriceMonkey. Yes, the name is dumb. I typed city bike with basket once, in English, and it searched each site in its own language.

### 0:47 to 1:06 | How it reads: Context.dev
[SCREEN: Tiles land on the price line in real time. Open a Tori tile's receipt and crop to "via jsonld" (read for free). Open the Monark tile's receipt and crop to the evidence row "via contextdev_markdown_split · quote: price 1200 SEK". Then the receipt line "shipping SE→FI, est. €50–100 (parcel in a bike box)". Hold on the "est.".]

**VO:** Tori puts its prices in the page code, so that read is free. The other three go through Context.dev, which turns a Swedish page into text we can pull a price out of. Twelve hundred kronor, and here's the line it came from. Shipping's our guess, fifty to a hundred, and it says so.

[TEXT: corner stat for the whole section: "10 Context.dev requests · 32 pages · 322 offers · 213 from free reads"]

### 1:06 to 1:16 | What reaches your door
[SCREEN: The line turns to all-in prices. Scroll past German and Dutch tiles flagged "pickup only". They're still visible, just never highlighted.]

**VO:** Then it ranks by what reaches your door. The pickup ones stay on screen. They just never win, because nobody's driving to Germany for a bike.

[TEXT: none. The app's own flags are the caption.]

### 1:16 to 1:29 | The winner, to be fair
[SCREEN: Tap the winning tile: "Jopo kaupunkipyörä 3-vaihteinen viininpunainen", €60, tori.fi. Hold on the photo. On "check Germany", cut back to the Kleinanzeigen search page for one beat.]

**VO:** And the winner? A Jopo on Tori. Sixty euros. In Finland, the whole time. Fair enough. Before this, the only way to know Germany wasn't cheaper was to check Germany. In German.

### 1:29 to 1:40 | A "price" that isn't one (CUT FIRST if long)
[SCREEN: Switch to `?q=sony%20a7%20iii%20body`. Open the €239 tile and its flags: "too good to be true: 75% under the used median (€949)", "price disagrees … probably another item's price on the page", "not costed". It's greyed out and unranked.]

**VO:** Same with a camera. One shop lists a Sony A7 III at two hundred thirty-nine euros. Used ones go for about nine fifty. That's probably another item's price, so it's flagged and it doesn't count.

### 1:40 to 1:48 | Who we work for
[SCREEN: Scroll to the footer and hold on the real text: "Ranked by what you pay, all in. No paid placements. We may earn a fee, never a better spot."]

**VO:** We don't make affiliate money yet. If we ever do, it's a fee. It doesn't buy a higher spot.

### 1:48 to 1:53 | Sign-off
[SCREEN: Webcam. Deadpan, no smile.]

**VO:** That's PriceMonkey. Context.dev did the reading. We did the arguing about bike boxes.

[TEXT: "PriceMonkey · built on Context.dev · Junction 2026"]

## Judge verdicts
- score 7.5: The most original direction and the least like the Sony template. The real counts carry it: 19,400 listings, "say they ship to Finland: 0", "pickup only: 32". "I don't read Dutch" and "In German." are dry and real. The anticlimax ("In Finland, the whole time. Fair enough.") is honest the way Rossman is honest. Risks: the Blocket ad 28014245 may be gone on shoot day. A €60 bike is low stakes next to a camera. 311 words is too many with the camera beat, so cut it, as the script itself says. Context.dev comes across clearly as markdown_split on foreign pages. | best: "Context.dev did the reading. We did the arguing about bike boxes." | worst: The Sony €239 tag-on at 1:29 ("Same with a camera...") turns a clean cross-border story into a second video.
- score 8: Of the ten, this is the only one whose problem is clearly its own. Europe's second-hand market is split by country and language: one English query becomes four local ones (kaupunkipyörä, stadscykel, citybike, stadsfiets), and the hard numbers carry the case (105 foreign listings, 0 say they ship to Finland, 32 are pickup only). It shows Context.dev doing work that can be seen: the 'via contextdev_markdown_split · quote: price 1200 SEK' row against the free jsonld read on Tori, plus a budget stat. It also has the best business case, because cross-border used goods is a real gap. Risks: every count (19,400 listings, 1,320/569/7,664/9,852, 105/0/32) has to match the recording exactly or the video loses credibility. The winner being a €60 Jopo that was in Finland all along is an anticlimax, and the 'check Germany' line only partly rescues it. Cut the Sony beat outright rather than treating it as optional. Also drop 'Hey everybody' at 0:11. | best: Before this, the only way to know Germany wasn't cheaper was to check Germany. In German. | worst: Same with a camera. One shop lists a Sony A7 III at two hundred thirty-nine euros... (the whole 1:29-1:40 camera detour: it brings back the €239 beat that every other script uses and breaks a self-contained story)
- score 7: The only script that isn't the same Sony A7 III story, and it's the most relatable to European viewers: a bike, four marketplaces, four languages, 'Nur Abholung'. The anticlimax where the winner was in Finland the whole time is honest and fairly funny. 'We did the arguing about bike boxes' is a good closer. It loses me where it stacks numbers (19,400 / 105 / 32 / 322 / 213). The Sony €239 detour at 1:29 dilutes it, so cut that beat. The 0:00 hook (a bike in Sweden, €108 vs €180) is weaker than the Sony hooks. | best: Almost ten thousand are Dutch. I don't read Dutch. | worst: We went through a hundred and five of the Swedish, German and Dutch ones. (A stats paragraph read aloud at 0:25.)
