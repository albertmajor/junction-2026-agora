# PriceMonkey quality report

Covers evaluation rounds 1 and 2. Each round ran real hunts for products, services and tree categories, logged the defects, and then fixers worked offline against the saved streams. No live hunts were rerun after the fixes.

**Test suite today:** `.venv/bin/pytest -q` gives **1683 passed in 26 s** (run 2026-11-14). Test files from later rounds (`test_discovery_r3.py`, `test_discovery_r4.py`, `test_relevance_r4.py`) are also in the suite. This report covers only rounds 1 and 2.

## Short version

- **Product hunts with a clear model name are now good.** Examples are iPhone 13, AirPods Pro 2, Nintendo Switch OLED, Sony A7 III and LEGO Technic. They get the right item, the right price band, photos and plain-words verdicts.
- **Broad searches were the main weakness**, for example "road bike", "sofa", "puhelin", "kitchen table", "winter jacket women" and tree categories. Price rules built for a single model wrongly called hundreds of normal used listings "too good to be true", and the pick was often a part, an accessory or a giveaway. Round 2 fixed the cause: mixed-model detection now comes from the search itself.
- **Services, quote-only categories and cars are still the weakest areas.** These include insurance, school catering, wedding photography, gunsmith and Volvo V70 / bright red car.

## Round 1: 46 defects

| Area | High | Medium | Low |
|---|---|---|---|
| Relevance (wrong items kept or right ones dropped) | 14 | 9 | 1 |
| Pricing | 1 | 5 | 0 |
| Intent (what the query means) | 2 | 5 | 0 |
| Discovery (where it searches) | 2 | 3 | 0 |
| Verdict text | 0 | 1 | 2 |
| Images | 0 | 0 | 1 |

**Fixed (relevance and pricing fixer, 66 regression tests in `tests/test_relevance_r1.py`):**
- Road bike: 3-speed city bikes no longer slip in through small groups with made-up names. A road-bike kind check was added, and price rules built for one model no longer run on mixed searches.
- LEGO Technic: sets with a set number are no longer treated as accessories, and keychains and search-result pages are rejected.
- MacBook Air M2: broken listings (knust, waterschade, defekt) are flagged, screens are treated as parts, iPads are rejected, and "M2-chip" and "8/256" are now read correctly.
- AirPods Pro 2: "2e generatie", "2. Generation", "2:a" and "pro2" now all read as the same model.
- IKEA Kallax and kitchen table: inserts and Finnish case endings are handled, the maker's own price is exempt from the "too good" rule, and coffee tables, desks and stools are rejected.
- Also fixed: fiets parts, OVP / "with box" in many languages, and PS5 Slim no longer treated as "another version".

**Fixed (discovery and intent fixer, 22 tests in `tests/test_discovery_r1.py`):**
- lunch now means lunch places near home.
- gift for mom is a product. The Danish "moms" (VAT) no longer matches "mom".
- Tree service hunts default to Helsinki and Finnish queries.
- bright red car and volvo v70 now get the Cars category.
- unlimited graphic design subscription now gets a design-service node.
- kinderwagen gebraucht is detected as German, and a new `query_lang` field was added.
- wedding photographer and car insurance get clean queries and the right leading meaning.
- School catering is priced per person.
- Sofas: Finnish shops come first and IKEA links point to the Finnish site.

**Left open after round 1:** quote-only insurer verdict, selkoraha.fi estimate rejected as a list page, out-of-stock deals still ranked in services, resale line on gift and vague hunts, a €1,913 LEGO stool kept, and the nettiauto search and wrong-make car fixes (these touch other fixers' files).

## Round 2: 34 defects (21 high)

Main themes:
1. **Mixed-model searches flagged as fakes** (road bike, winter jacket, sofa, kitchen table, puhelin). The "mixed" check required every offer to carry a generic mark, and late or new-lane offers lacked it.
2. **Accessories and parts as the pick.** Examples: a diaper bag for a stroller, a phone case from the phones category, a PS5 headset, Dyson V15 batteries, a bike frame and a French press for "kahvinkeitin".
3. **Finnish and other local words missed.** Examples: "pelikonsoli" read as a game, prams written as compounds ("yhdistelmävaunut") not matched, and salons and trade firms (Parturi, Sähkö, Putki) rejected as "not that service".
4. **Services.** Add-on lines (an extra hour, a full gallery) were taken as the base price, wedding work was costed as hourly × 2 h, and statistics pages and directories were treated as providers. Service sites were picked by country only (plumber Berlin got pet-sitting sites), and Berlin, CT was taken for Berlin, Germany.
5. **Cars and quote-only categories.** No real cars were found, and dealer list pages were sold as a "new" car. Insurance and school catering ended with 0 offers and a pointless "set a watch".

**Fixed (relevance and pricing fixer, offline replays of the r2 streams):** 22 of 26 defects in its scope were fully fixed and 3 more partly.
- `judge._mixed()` now decides from the search (`resolve.is_generic`) or from most of the offers. Generic searches get no single new-price reference. Replays: road bike now picks €250 (was €45), puhelin a €139 Galaxy A33, sofa €150.
- For vague and category searches, the pick must cost at least 35% of its group's median and 50% of the hunt's median. The headline now names the pick ("€139 all in: used Samsung Galaxy A33 5G … at tori.fi").
- Road Bikes category: frames, kids', women's and plain "Polkupyörä" listings are rejected unless a road-bike maker is named.
- Switch "pelikonsoli" is fixed. For PS5, "pro", "slim" and "digital" count as console evidence only after the platform name, so the headset is rejected. Shop "new" prices below half the marketplace level are ignored.
- Dyson V15: the pick comes only from the asked model's group, and multi-model parts and cases are accessories.
- Phone cases, wallets, lenses and gimbals are rejected in the phones category. "su", "ar", "s", "con" and "avec" now count as "with the box".
- Kahvinkeitin: presses, moka pots, gaskets, jugs and drink packs are rejected, while a coffee maker sold with its jug is kept.
- Strollers: diaper bags, curtains, canopies, footmuffs and suitcases are rejected, and Finnish pram compounds now match.
- Fiets: bike parts are rejected.

The four defects outside this fixer's files went to the other fixers as cross-file requests. They need discovery or lane-query changes.

## Still weak

- **Cars:** this is the least mature area. Discovery has to route searches to vehicle listing searches (autot.tori.fi, nettiauto with filters, a colour parameter), treat dealer and aggregator pages as used list pages, drop US car sites, and stop giving nettiauto a 5 s timeout. The verdict also needs to say plainly when few real cars were found.
- **Quote-only services (insurance, catering, B2B):** the verdict should explain quote-based pricing and link to If, OP, LähiTapiola and Fennia, instead of "No priced offers yet". Calculator estimates such as selkoraha.fi should count as estimate offers.
- **Service pricing details:**
  - When a provider does not state its call-out fee or minimum hours, it is costed as zero, which beats honest providers.
  - Wedding packages are compared with hourly rates.
  - Fixed one-off jobs are mixed with standard visits.
  - The same provider can be counted twice (bookkeeping).
  - Out-of-stock deals still rank in services.
- **Service discovery:**
  - Service sites are chosen by country, not by trade.
  - Category domains are inherited from the wrong parent (gunsmith under care sites).
  - The 2-pages-per-domain cap gets spent on the wrong city (lounaat.info pages for Tampere and Lahti).
  - The 24 s budget runs out before the best local pages are read.
- **Audience words:** "women", "naisten" and "Damen" are dropped from local marketplace queries, and kids' brands and sizes (Reima, 150 cm) are not mapped to "kids".
- **New-price references for bulky goods:** IKEA and Finnish furniture shops often fail to parse or time out, so "new from" comes from US pages or is missing.
- **gift for mom:** this still needs a fan-out into real gift categories and no resale line.
- **Market totals:** totals are missing for kleinanzeigen.de, and small EU refurb shops are read thinly (refurbed.fi 1 of 5) while amazon.co.uk is used.
- **Verification gap:** all round 2 fixes were checked offline. Saved streams do not include internal `raw` data, so service results are approximate. A live rerun of the r2 queries is the next step.

## Already works well

- **Specific products:**
  - iPhone 13: 1,029 kept out of about 41.8k across 11 marketplaces, and the pick check read the battery health.
  - AirPods Pro 2: the whole top 20 is the right model, and 524 cases and single earbuds were rejected.
  - Switch OLED: a €141 all-in pick, with sensible refurbished and new prices.
  - Sony A7 III: the right model across 8 EU marketplaces, with shipping included.
- **Scale and coverage:** hundreds to thousands of real listings per hunt (PS5 2,618 read from a 124k market, fiets 2,198 from 1.2M, kinderwagen 2,187 across 8 marketplaces).
- **Photos:** almost every kept product offer has a matching image (LEGO 1,910/1,910, kitchen table 582/582, MacBook 496/496, Sofas 0 missing).
- **Rejections with reasons:** cases, parts, wanted ads, "for parts" listings, other versions (Pro/mini/Max, A7R/A7S), job ads, wage pages and guides are all rejected with a reason shown.
- **Interpretation:**
  - puhelin maps to Phones and ps5 to Consoles.
  - kinderwagen gebraucht is read as German and used-only.
  - fiets maps to the bike concept.
  - lunch means lunch places per person.
  - home cleaning tilburg 24m2 gets the city and the m².
  - Bulky items are correctly kept to the home market.
- **Services that work:**
  - Electrician Helsinki: 13 providers, prices without VAT grossed up at 25.5%, and the household deduction applied correctly.
  - Bookkeeping: 16 Finnish monthly plans in plain words.
  - Design subscriptions: Designjoy, Penji and others, compared per month.
  - Plumber Berlin: a clear rate × hours estimate.
  - Wedding photographer category: 14 local photographers, each with a photo.
