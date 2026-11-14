"""Round-5 service pricing: quote-only categories, calculator estimates, unstated terms, like with like, one vote
per provider, sold-out deals and the audience asked, as offline regressions.

Titles, prices and sites come from the saved live streams (eval r1-r4: car insurance finland, School catering,
bookkeeping service finland, plumbing, home cleaning Tilburg, wedding photographer, winter jacket women). Every rule
is judged per listing; no site is ever blocked.
"""
from __future__ import annotations

import pytest

from agora import hunt
from agora import judge as J
from agora import resolve as R
from agora.models import Need, Offer


def svc_need(thing: str, where: str = "Helsinki", cat: dict | None = None, raw: str | None = None) -> Need:
    return Need(raw=raw or f"{thing} {where}", thing=thing, kind="service", where=where, conditions=["service"],
                category=cat)


def page(url: str, title: str, price: float, unit: str | None = "job", **kw) -> Offer:
    raw = kw.pop("raw", {})
    return Offer(url=url, source=url.split("/")[2].removeprefix("www."), title=title, price=price, currency="EUR",
                 price_eur=price, condition="service", unit=unit, raw=dict(raw), **kw)


def run(n: Need, offers: list[Offer]):
    things = R.resolve(n, offers)
    return things, J.judge(n, things, history=False)


CAR_INS = svc_need("car insurance", "Finland", raw="car insurance finland")
SELKO_CALC = "https://selkoraha.fi/en/calculators/car-insurance-calculator?cv=20000&k=tayskasko&b=70&cap=0&y=0"


# ---------------------------------------------------------------- quote-only services
def test_insurance_with_a_listed_price_leads_with_quotes_not_buy_now():
    # eval r4: '€373/year at k-auto.fi' (a dealer's add-on) headed the verdict as 'buy now'
    kauto = page("https://www.k-auto.fi/autot/lisapalvelut/autovakuutus/", "Kiinteähintainen Kevytkasko", 373, "year")
    calc = page(SELKO_CALC, "Estimated annual car insurance (traffic insurance + kasko)", 350, "year")
    _, v = run(CAR_INS, [kauto, calc])
    assert v.headline.startswith("Car insurance is priced by quote: the price depends on the car")
    assert "Lowest listed price: €373/year" in v.headline and "an example or 'from' price" in v.headline
    assert "Compare quotes from If, OP Pohjola, LähiTapiola and Fennia" in v.headline
    assert v.buy_or_wait == "get quotes"
    assert "get a quote: If https://www.if.fi" in v.lines
    assert any(ln.startswith("calculator estimate (not a quote): €350/year") for ln in v.lines)
    assert not any("more not compared" in ln for ln in v.lines)      # the estimate has its own line


def test_insurance_without_prices_links_the_insurers_instead_of_a_watch():
    junk = page("https://www.lahitapiola.fi/henkilo/", "LähiTapiola Sijoittaminen", 30, "month")
    _, v = run(CAR_INS, [junk])
    assert "No priced offers" not in v.headline and "Set a watch" not in v.headline
    assert "priced by quote" in v.headline and "If, OP Pohjola, LähiTapiola and Fennia" in v.headline
    assert v.buy_or_wait == "get quotes" and v.best_offer_url == "https://www.if.fi"
    assert {"get a quote: Fennia https://www.fennia.fi", "get a quote: LähiTapiola https://www.lahitapiola.fi"} \
        <= set(v.lines)


@pytest.mark.parametrize("n", [
    svc_need("school catering", cat={"id": "cpv:55524", "label": "School catering", "kind": "service"},
             raw="School catering"),
    svc_need("staff catering for our company", raw="staff catering for our company helsinki"),
])
def test_school_and_b2b_catering_get_an_honest_quote_verdict(n):
    _, v = run(n, [])
    assert "No priced offers" not in v.headline
    assert "Amica (Compass Group), Fazer Food & Co and Sodexo" in v.headline
    assert v.buy_or_wait == "get quotes" and any("https://www.amica.fi" in ln for ln in v.lines)


# ---------------------------------------------------------------- calculator estimates
def test_a_calculator_estimate_is_an_estimate_offer_never_ranked():
    # eval r4: the selkoraha calculator page was dropped as a 'search or list page', and on the live leaderboard
    # 'selkoraha.fi €29/mo overtook service at ayvens.com'
    calc = page(SELKO_CALC, "Estimated annual car insurance (traffic insurance + kasko)", 350, "year")
    assert R.not_an_offer(calc) is None and R.explain(CAR_INS, calc)[1] is None
    things, v = run(CAR_INS, [calc])
    assert calc.raw["estimate"] == "calculator" and calc.true_cost is None
    assert any("calculator's estimate" in f for f in calc.flags)
    assert "A calculator estimates about €350/year (≈ €29/month)" in v.headline and v.best_true_cost_url is None
    assert J.pick_candidates(things) == []
    board = hunt.Leaderboard(CAR_INS, R.resolve)
    assert not (board.update([page(SELKO_CALC, "Estimated annual car insurance (traffic insurance + kasko)", 350,
                                   "year")]) or {}).get("top")


def test_an_estimate_titled_insurance_page_is_kept_but_a_leasing_add_on_is_not():
    est = page("https://selkoraha.fi/fi/autovakuutus", "Arvioitu autovakuutus (liikennevakuutus + kasko)", 350, "year")
    lease = page("https://www.ayvens.com/fi/autovakuutus-leasing", "Leasing autovakuutus kasko", 53, "month")
    assert R.explain(CAR_INS, est)[1] is None and R.insurance_estimate(est)
    assert "leasing" in (R.explain(CAR_INS, lease)[1] or "")


def test_a_calculator_product_is_never_an_estimate():
    n = Need(raw="casio calculator", thing="casio calculator")
    o = Offer(url="https://www.verkkokauppa.com/fi/product/123", source="verkkokauppa.com",
              title="Casio FX-82 calculator", price=19.9, currency="EUR", price_eur=19.9, condition="new")
    J.judge(n, R.resolve(n, [o]), history=False)
    assert not o.raw.get("estimate") and o.true_cost is not None


# ---------------------------------------------------------------- unstated call-out fee / minimum hours
PLUMBER = svc_need("plumber", raw="plumber helsinki")


def test_unstated_call_out_is_never_zero_and_ranks_after_stated_terms_at_equal_price():
    honest = page("https://putkihaka.fi/hinnasto", "Putkimies tuntihinta", 60, "hour",
                  raw={"callout_fee": 40, "min_hours": 1})
    silent = page("https://normiputki.fi/hinnasto", "Putkimies tuntihinta", 60, "hour")
    _, v = run(PLUMBER, [silent, honest])
    assert silent.true_cost.total_eur == honest.true_cost.total_eur == 100
    assert any(lbl.startswith("call-out fee (est.") for lbl, _ in silent.true_cost.receipt)
    assert silent.raw["assumed_terms"] and not honest.raw.get("assumed_terms")
    assert "call-out fee not stated on the page" in silent.true_cost.basis
    assert v.best_true_cost_url == honest.url


def test_alone_unstated_call_out_gets_the_typical_fee_labelled():
    o = page("https://manofix.fi/hinnasto", "Putkimies tuntihinta", 55, "hour")
    _, v = run(PLUMBER, [o])
    assert o.true_cost.extras_eur == J.TYPICAL_CALLOUT_EUR
    assert "call-out (est.)" in v.headline


def test_a_stated_per_km_travel_charge_is_the_providers_terms():
    km = page("http://www.suomalainenputkimies.fi/hinnat", "Plumbing service hourly rate", 40, "hour",
              raw={"other_prices": [{"title": "Travelling fee", "price_eur": 0.46}]})
    other = page("https://manofix.fi/hinnasto", "Putkimies tuntihinta", 55, "hour", raw={"callout_fee": 80})
    run(PLUMBER, [km, other])
    assert km.true_cost.extras_eur == 0 and "0.46 €/km" in km.true_cost.basis
    assert "est_callout_fee" not in km.raw


# ---------------------------------------------------------------- like with like
WEDDING = svc_need("wedding photographer", raw="wedding photographer helsinki")


def test_wedding_packages_are_never_ranked_against_hourly_rates():
    pk = [page(f"https://kuvaaja{i}.fi/hinnat", f"Hääkuvaus paketti {h} h", p) for i, (p, h)
          in enumerate([(550, 4), (900, 8), (1200, 8)])]
    hourly = page("https://hourly.fi/hinnat", "Hääkuvaus tuntihinta", 120, "hour")
    _, v = run(WEDDING, pk + [hourly])
    assert hourly.true_cost is None and hourly.raw["apart_kind"] == "hourly_vs_package"
    # round 6: packages are compared by coverage, so the 4 h package ranks after the 8 h (full-day) ones
    assert v.best_true_cost_url == pk[1].url
    assert any("not compared with full-day packages" in ln for ln in v.lines)


TILBURG = svc_need("home cleaning 24m2", "Tilburg", raw="home cleaning tilburg 24m2")


def test_a_deal_naming_its_hours_is_a_clean_but_a_tiny_fee_and_a_one_off_job_are_apart():
    # eval r4 (glazenwasser utrecht): 'Calling MrFix' €9.95 won as 'one clean'; a 3-hour deal must not be a 'fee'
    rates = [page("https://yoojo.nl/huishouden/schoonmaker/tilburg", "Thuis schoonmaken", 13, "hour"),
             page("https://greenmaidcleaners.nl/", "Essential Home Cleaning", 25, "hour"),
             page("https://www.ikzoekeenschoonmaker.nl/tilburg/profiel/anja", "Schoonmaak per uur", 18, "hour")]
    deal = page("https://www.socialdeal.nl/deals/tilburg/schoonmaak", "3 uur professionele schoonmaakhulp", 19)
    fee = page("https://mrfix.nl/en/professional-cleaner/tilburg/", "Calling MrFix", 9.95)
    one_off = page("https://schoonmaakbedrijf-x.nl/tilburg", "Eenmalige grote schoonmaak", 79)
    run(TILBURG, rates + [deal, fee, one_off])
    assert deal.true_cost is not None
    assert fee.true_cost is None and fee.raw["apart_kind"] == "tiny_job"
    assert one_off.true_cost is None and one_off.raw["apart_kind"] == "one_off"


# ---------------------------------------------------------------- one provider, one vote
BOOKKEEPING = svc_need("bookkeeping service", "Finland", raw="bookkeeping service finland")


def bk(url: str, title: str, price: float, seller: str) -> Offer:
    return page(url, title, price, "month", seller=seller)


def test_the_same_provider_is_never_counted_twice():
    # eval r4: tilitoimistonm.fi /en/pricing and its front page (€99 both) were two of '11 monthly plans compared'
    offers = [bk("https://tilipalveluzafaroy.fi/", "Tilipalvelu Zafar Oy Essential – kirjanpito", 49, "Zafar"),
              bk("https://tilitoimistonm.fi/en/pricing", "Tilitoimisto N.M Accounting Prices – bookkeeping", 99, "N.M"),
              bk("https://tilitoimistonm.fi/", "Tilitoimisto N.M Kirjanpito pienyritykselle", 99, "N.M"),
              bk("https://tilitoimistonm.fi/en/pricing#plus", "Tilitoimisto N.M Plus bookkeeping", 149, "N.M"),
              bk("https://www.holvi.com/fi/hinnoittelu/", "Kirjanpitopalvelut", 79, "Holvi"),
              bk("https://www.holvi.fi/hinnoittelu/", "Kirjanpitopalvelut", 79, "Holvi"),
              bk("https://bookkeeping.fi/", "Bookkeeping.fi Sole trader bookkeeping", 69, "Bookkeeping.fi")]
    assert J.provider_key(offers[4]) == J.provider_key(offers[5]) == "holvi"
    _, v = run(BOOKKEEPING, offers)
    count = next(ln for ln in v.lines if "providers compared" in ln)
    assert count.startswith("4 providers compared (5 monthly plans)")   # N.M: 2 tiers, 1 voice
    shown = [ln.split(":")[0] for ln in v.lines if ln.endswith("/month") or "/month (" in ln]
    assert shown.count("tilitoimistonm.fi") == 1 and len([s for s in shown if s.startswith("holvi")]) == 1


# ---------------------------------------------------------------- sold out
def test_sold_out_deals_are_never_costed_ranked_or_in_the_median():
    rates = [page("https://yoojo.nl/huishouden/schoonmaker/tilburg", "Thuis schoonmaken", 13, "hour"),
             page("https://greenmaidcleaners.nl/", "Essential Home Cleaning", 25, "hour")]
    gone = page("https://www.socialdeal.nl/deals/tilburg/schoonmaak", "3 uur professionele schoonmaakhulp", 9,
                in_stock=False)
    titled = page("https://www.socialdeal.nl/deals/tilburg/schoonmaak-2", "3 uur schoonmaak - Uitverkocht", 8)
    boxed = page("https://www.socialdeal.nl/deals/tilburg/schoonmaak-3", "3 uur schoonmaakhulp", 7,
                 raw={"description": "Helaas, deze deal is uitverkocht."})
    things, v = run(TILBURG, rates + [gone, titled, boxed])
    for o in (gone, titled, boxed):
        assert o.true_cost is None and o.raw["not_comparable"] == "sold out or the deal has ended"
        assert v.best_offer_url != o.url
    assert not {gone.url, titled.url, boxed.url} & {o.url for o in J.pick_candidates(things)}
    board = hunt.Leaderboard(TILBURG, R.resolve)
    top = board.update(rates + [gone, titled, boxed])["top"]
    assert {x["url"] for x in top} <= {o.url for o in rates}


def test_a_sold_out_monthly_plan_is_not_ranked():
    live = bk("https://bookkeeping.fi/", "Bookkeeping.fi Sole trader bookkeeping", 69, "Bookkeeping.fi")
    gone = bk("https://www.groupon.fi/deals/kirjanpito", "Kirjanpito 3 kk tarjous – loppuunmyyty", 19, "Deal")
    _, v = run(BOOKKEEPING, [live, gone])
    assert gone.true_cost is None and v.best_offer_url == live.url


def test_a_page_that_merely_mentions_sold_out_elsewhere_is_still_a_price():
    o = page("https://greenmaidcleaners.nl/", "Essential Home Cleaning", 25, "hour",
             raw={"description": "Our weekend slots sold out fast last year, book early."})
    assert not J.sold_out(o)


# ---------------------------------------------------------------- the audience asked, per listing
def row(title: str, price: float, desc: str | None = None) -> Offer:
    raw = {"site": "tori", "from_list_page": "https://www.tori.fi/search"}
    if desc:
        raw["description"] = desc
    return Offer(url=f"https://www.tori.fi/item/{abs(hash((title, price, desc))) % 10**9}", source="tori.fi",
                 title=title, price=price, currency="EUR", price_eur=price, condition="used", raw=raw)


@pytest.mark.parametrize("q,title,want", [
    ("talvitakki miehille", "Naisten talvitakki Luhta", "women"),
    ("talvitakki naisille", "Miesten talvitakki", "men"),
    ("talvitakki lapselle", "Damen Winterjacke", "women"),
])
def test_finnish_for_men_women_kids_words_are_an_audience(q, title, want):
    n = Need(raw=q, thing=q)
    assert f"another audience ({want})" in (R.explain(n, row(title, 40))[1] or "")


def test_a_listing_for_another_audience_by_its_description_is_never_the_pick_nor_the_typical_price():
    n = Need(raw="winter jacket women", thing="winter jacket women", must_have=["women"])
    women = [row(f"Naisten talvitakki {i}", p) for i, p in enumerate([60, 65, 70, 75, 80])]
    mens = [row("Talvitakki koko L", p, desc="Hyväkuntoinen miesten talvitakki") for p in (15, 16, 17, 18, 19, 20)]
    things, v = run(n, women + mens)
    assert all(o.raw.get("other_audience") == "for men's, you asked women's" for o in mens)
    assert v.best_offer_url in {o.url for o in women}
    assert min(J.market_prices([o for t in things for o in t.offers], "used")) >= 60
