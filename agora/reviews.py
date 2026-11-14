"""SELLER REVIEWS: is the shop behind the price any good? Written at Junction 2026.

After a hunt's offers are in, Agora looks up what buyers say about the sites that matter most (the pick
first, then the cheapest all-in shops, plus marketplaces and service providers) and streams one `review`
event per site. Cheapest sources first:

  1. FREE  review pages read with a plain fetch + extruct: Trustpilot (www.trustpilot.com/review/<domain>,
           often behind a bot wall, then skipped for a while), SmartCustomer / Sitejabber
           (sitejabber.com/reviews/<domain>), and the shop's own home page (AggregateRating on its
           Organization/LocalBusiness JSON-LD, self-reported, so it counts for little).
  2. PAID  one Context.dev web search with highlights per site that still has no solid rating
           ("<domain> reviews" / "kokemuksia" / "ervaringen" / "Erfahrungen", by the shop's country), only
           while the shared 10 req/min bucket has tokens to spare; Reddit for the pick if there is more room;
           one Context.dev JSON read of the Trustpilot page for the pick as a last resort.

NEGATIVITY BIAS. Review sites over-represent angry buyers: happy ones rarely write. So a raw star average
is never the verdict:
  * every source has a BASELINE (what a normal shop scores there: Trustpilot ~3.6, SmartCustomer ~2.6,
    a shop's own widget ~4.4), shifted by category (a marketplace platform collects every seller's
    gripes: -0.7; local services score high everywhere: +0.3). We score the distance from that baseline;
  * a Bayesian prior (PRIOR_N reviews at the baseline) pulls small review counts toward neutral;
  * sources are weighted by review count, and recent reviews (last 12 months) count more;
  * RED FLAGS (scam, never delivered, no refund, fake/counterfeit, account closed) are told apart from
    normal GRUMBLES (slow delivery, customer service waits, returns hassle). Only red flags that repeat in
    low-star, mostly recent reviews make a shop "watch out"; a big shop with a few such reviews among
    thousands is normal. Grumbles never do.

Labels: "solid" | "mixed" | "watch out" | "unknown". Results are cached per registrable domain in SQLite
(store.reviews) for CACHE_TTL_S; AGORA_OFFLINE=1 reads the cache only. The judge reads the same cache:
a "watch out" seller is never the pick (see `signals_for`).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from datetime import date, datetime
from typing import Any

from agora import trust

CACHE_TTL_S = 7 * 24 * 3600     # a site's reviews are re-checked after a week
NONE_TTL_S = 2 * 24 * 3600      # "nothing found" is retried sooner
PHASE_BUDGET_S = 40.0           # the whole reviews phase after a hunt
MAX_DOMAINS = 10
TOP_BY_PRICE = 6
FREE_TIMEOUT_S = 9.0
MAX_PAID = 6                    # Context.dev requests the reviews phase may spend
TOKEN_NEED = 1.0                # a paid review request waits (polling, inside the phase budget) for this many
                                # tokens; then it queues in the shared limiter like any other request
PAID_WAIT_S = 8.0               # never queue longer than this for one paid review request
PAID_MIN_LEFT_S = 6.0
TP_BATCH = 4                    # shops per batched Trustpilot search           # stop waiting for bucket tokens this long before the phase ends
PRIOR_N = 30.0                  # Bayesian prior: this many reviews at the baseline
MIN_COUNT = 10                  # fewer reviews than this: too few to say
BIG_SHOP = 500                  # reviews: a shop this size always has some angry ones
TP_BLOCK_S = 600.0              # Trustpilot's bot wall answered: do not knock again for 10 minutes

# what a normal online shop scores on each source (stars out of 5)
BASELINE = {"trustpilot": 3.6, "smartcustomer": 2.6, "sitejabber": 2.6, "own site": 4.4, "kiyoh": 4.3,
            "trustedshops": 4.3, "feedbackcompany": 4.3, "google": 4.2, "reviews.io": 4.2, "klantenvertellen": 4.3,
            "werkspot": 4.4, "trustami": 4.3, "ekomi": 4.4, "web": 3.6}
# only these sites' star ratings are taken from a search snippet (a blogger's own "3.8 / 5" is not a review count)
RATING_SITES = set(BASELINE) - {"web", "own site"}
WEIGHT = {"own site": 0.3, "web": 0.6, "badge": 0.3}   # everything else 1.0; snippet-read ratings x SNIPPET_W
BADGE_MAX_N = 100               # a rating badge on the shop's own page never counts for more than this many reviews
MAX_BIG_TP = 2                  # extra Trustpilot searches for big shops the batch missed
SNIPPET_W = 0.8
SCAM_WORD_W = 0.5               # the bare word "scam" counts half a concrete red flag
SENTIMENT_W = 0.6               # a review site's summary sentence, without stars
SENTIMENT_DELTA = 0.6           # ... counts as this many stars above / below normal
SHIFT_PLATFORM = -1.5           # a marketplace collects every buyer's and seller's gripes (eBay, Vinted ~1.5★)
SHIFT_SERVICE = 0.3
SOURCE_NAMES = {"trustpilot": "Trustpilot", "smartcustomer": "SmartCustomer", "sitejabber": "Sitejabber",
                "own site": "the shop's own site", "kiyoh": "Kiyoh", "trustedshops": "Trusted Shops",
                "feedbackcompany": "Feedback Company", "google": "Google", "reviews.io": "Reviews.io",
                "klantenvertellen": "Klantenvertellen", "werkspot": "Werkspot", "trustami": "Trustami", "ekomi": "eKomi",
                "reddit": "Reddit", "web": "the web", "feefo": "Feefo", "reevoo": "Reevoo"}
BASELINE.setdefault("feefo", 4.5)
BASELINE.setdefault("reevoo", 4.3)

BIAS_NOTE = ("Review sites over-represent unhappy buyers, so we compare a shop with what is normal on each "
             "site, pull small review counts toward neutral, and only let serious complaints (scams, "
             "orders that never came, refunds refused) count against it.")

# ---------------------------------------------------------------- red flags vs grumbles

_NEG = r"(?<!not a )(?<!no )(?<!isn't a )(?<!is not a )(?<!never a )(?<!ei ole )(?<!geen )(?<!kein )(?<!keine )"
RED = {
    "scams": re.compile(_NEG + r"\b(scam(?:mers?|med|s)?|fraud(?:ulent|sters?)?|rip[- ]?off artists?|"
                               r"huijau?s\w*|huijari\w*|petos\w*|oplicht\w*|betrug|betrüger\w*|abzocke\w*)\b", re.I),
    "orders never delivered": re.compile(
        r"\b(never (?:arrived|received|delivered|came|showed up|got (?:it|my|the))|(?:have|has)n'?t (?:yet )?"
        r"(?:arrived|been delivered)|still (?:haven'?t|have not|not) (?:received|got)|not (?:yet )?received|"
        r"ei (?:ole )?(?:koskaan )?(?:saapunut|tullut|toimitettu)|nooit (?:ontvangen|geleverd|aangekomen)|"
        r"niet (?:ontvangen|geleverd)|nie (?:angekommen|geliefert|erhalten)|nicht (?:angekommen|geliefert|erhalten))\b",
        re.I),
    "refunds refused": re.compile(
        r"\b(no refund|never (?:got (?:my|a) )?refund(?:ed)?|refus\w* (?:to )?(?:give (?:me )?)?(?:a )?refund|"
        r"won'?t refund|will not refund|still waiting for (?:my |a |the )?refund|refund (?:never|still)|"
        r"rahoja? ei (?:ole )?palautettu|ei palauttanut rahoja|geen (?:geld )?terug(?:betaling|gekregen)|"
        r"geld (?:nooit|niet) terug|keine (?:rückerstattung|erstattung)|geld nicht zurück)\b", re.I),
    "fake or counterfeit goods": re.compile(
        r"\b(counterfeit|fake (?:product|item|goods|airpods|iphone|phone|one|parts?)|knock[- ]?offs?|"
        r"väärennö\w*|feikki\w*|namaak|nep(?:product)?|fälschung\w*|gefälscht\w*|plagiat)\b", re.I),
    "subscription traps or surprise invoices": re.compile(
        r"\b(hidden (?:annual |yearly |monthly )?subscriptions?|subscription trap|unwanted subscription|"
        r"charged (?:me )?without (?:my )?(?:consent|permission|asking)|invoices? (?:due )?(?:for|despite)[^.]{0,60}"
        r"(?:never|not) (?:used|ordered|hired)|received invoices|abonnementsval|ongevraagd abonnement|"
        r"verborgen abonnement|piilotettu tilaus|ungewollte[sn]? abo\w*|abofalle)\b", re.I),
    "accounts closed with money held": re.compile(
        r"\b(account (?:was |got |has been )?(?:closed|blocked|suspended|banned|frozen)|closed my account|"
        r"froze my (?:account|money|funds)|tili(?:ni)? (?:suljettiin|jäädytettiin)|account (?:geblokkeerd|opgeheven)|"
        r"konto (?:gesperrt|geschlossen))\b", re.I),
}
GRUMBLE = {
    "slow delivery": re.compile(r"\b(slow|late|delay\w*|took (?:\d+|two|three|several) (?:days|weeks)|weeks to|"
                                r"hidas\w*|myöhä\w*|viivä\w*|traag|vertraag\w*|te laat|verspät\w*|langsam\w*|"
                                r"lieferzeit)\b", re.I),
    "customer service waits": re.compile(r"\b(customer (?:service|support)|support|on hold|no (?:answer|reply|response)|"
                                         r"asiakaspalvelu\w*|klantenservice|kundenservice|kundendienst)\b", re.I),
    "returns hassle": re.compile(r"\b(returns?|returning|palautu?s\w*|retour\w*|rücksend\w*|umtausch)\b", re.I),
    "price changes": re.compile(r"\b(price (?:went up|changed)|hidden (?:fees?|costs?)|extra charges?)\b", re.I),
}

# ---------------------------------------------------------------- small helpers

def offline() -> bool:
    return os.environ.get("AGORA_OFFLINE", "").lower() in ("1", "true", "yes")


def domain_of(url_or_host: str) -> str:
    return trust.registrable(url_or_host)


def fmt_count(n: int | float | None) -> str:
    n = int(n or 0)
    if n >= 10_000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def _num(x: Any) -> float | None:
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().replace(" ", " ")
        m = re.fullmatch(r"(\d+)[.,](\d)", s)
        if m:
            return float(f"{m.group(1)}.{m.group(2)}")
        s = re.sub(r"[\s,.](?=\d{3}\b)", "", s)
        try:
            return float(s.replace(",", "."))
        except ValueError:
            return None
    return None


def _date(x: Any) -> date | None:
    if isinstance(x, str):
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", x)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _country(domain: str) -> str:
    return domain.rsplit(".", 1)[-1].lower() if "." in domain else ""


def review_query(domain: str) -> str:
    """'<domain> reviews' in the shop's own language (by its TLD)."""
    word = {"fi": "kokemuksia", "nl": "ervaringen", "be": "ervaringen", "de": "Erfahrungen", "at": "Erfahrungen",
            "ch": "Erfahrungen", "se": "omdömen", "dk": "anmeldelser", "no": "erfaringer"}.get(_country(domain), "reviews")
    return f"{domain} {word}"


def source_key(host: str, domain: str) -> str:
    """Which review source a page belongs to."""
    h = trust.registrable(host)
    if h == domain:
        return "own site"
    name = h.split(".")[0]
    if name in ("trustpilot", "smartcustomer", "sitejabber", "kiyoh", "trustedshops", "feedbackcompany", "reddit",
                "klantenvertellen", "werkspot", "trustami", "ekomi"):
        return name
    if name == "reviews" and h.endswith(".io"):
        return "reviews.io"
    if name == "google":
        return "google"
    return "web"


# ---------------------------------------------------------------- parsing pages (free reads)

ORG_HINT = re.compile(r"organization|business|store|shop|corporation|service|company|brand", re.I)
NOT_SELLER = re.compile(r"^(product|productgroup|offer|book|movie|softwareapplication|recipe|event|course|"
                        r"creativework|article|webpage|videogame)$", re.I)


def _nodes(data: Any) -> Iterable[dict[str, Any]]:
    if isinstance(data, list):
        for x in data:
            yield from _nodes(x)
    elif isinstance(data, dict):
        yield data
        for k, v in data.items():
            if k in ("@graph", "mainEntity", "itemListElement", "about", "publisher", "provider", "seller"):
                yield from _nodes(v)


def _types(n: dict[str, Any]) -> list[str]:
    t = n.get("@type")
    return [str(x) for x in (t if isinstance(t, list) else [t]) if x]


def _rating_value(r: Any) -> float | None:
    if not isinstance(r, dict):
        return _num(r)
    v = _num(r.get("ratingValue"))
    best = _num(r.get("bestRating")) or 5.0
    if v is None:
        return None
    if best and best != 5:
        v = v * 5.0 / best
    return round(v, 2) if 0 < v <= 5 else None


def _jsonld_blocks(html: str, url: str) -> list[Any]:
    try:
        import extruct
        return list(extruct.extract(html, base_url=url, syntaxes=["json-ld"], errors="ignore").get("json-ld") or [])
    except Exception:
        out = []
        for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
            try:
                out.append(json.loads(m.group(1)))
            except ValueError:
                continue
        return out


def parse_rating_page(html: str, url: str) -> dict[str, Any] | None:
    """A review page (or a shop's own page) -> {rating (of 5), count, reviews:[{rating, date, text}]} from
    schema.org AggregateRating on the SELLER (Organization / LocalBusiness / Store ...; never a Product's
    rating). Trustpilot's __NEXT_DATA__ trustScore is a fallback. None when the page states no rating."""
    if not html:
        return None
    best: dict[str, Any] | None = None
    reviews: list[dict[str, Any]] = []
    for n in _nodes(_jsonld_blocks(html, url)):
        types = _types(n)
        if "Review" in types:
            reviews.append(n)
        if isinstance(n.get("review"), list):
            reviews += [r for r in n["review"] if isinstance(r, dict)]
        agg = n.get("aggregateRating")
        if not isinstance(agg, dict):
            continue
        if any(NOT_SELLER.match(t) for t in types) or not any(ORG_HINT.search(t) for t in types):
            continue
        r = _rating_value(agg)
        c = _num(agg.get("reviewCount")) or _num(agg.get("ratingCount")) or 0
        if r is None:
            continue
        if best is None or c > best["count"]:
            best = {"rating": r, "count": int(c), "name": n.get("name")}
    if best is None:
        m = re.search(r'"trustScore"\s*:\s*([\d.]+)\s*,\s*"(?:stars"\s*:\s*[\d.]+\s*,\s*")?numberOfReviews"\s*:\s*'
                      r'(?:\{\s*"total"\s*:\s*)?(\d+)', html)
        if m and 0 < float(m.group(1)) <= 5:
            best = {"rating": float(m.group(1)), "count": int(m.group(2)), "name": None}
    if best is None:
        return None
    seen: set[str] = set()
    out_reviews = []
    for r in reviews:
        text = " ".join(str(r.get(k) or "") for k in ("headline", "name", "reviewBody")).strip()
        key = text[:120]
        if not text or key in seen:
            continue
        seen.add(key)
        out_reviews.append({"rating": _rating_value(r.get("reviewRating")), "date": str(r.get("datePublished") or "")[:10],
                            "text": text[:1200]})
    best["reviews"] = out_reviews[:40]
    return best


# ---------------------------------------------------------------- rating badges on the shop's own page
# Wex's header says "4.8 Trustpilot Rating"; others embed a TrustBox, a Feefo / Reevoo / Google badge. The shop
# chose to show it, so it is a weak, labelled signal ("shown on the shop's own page"), never enough on its own,
# but it is not "no reviews found". The TrustBox's own link names the shop's real Trustpilot page
# (uk.trustpilot.com/review/www.wexphotovideo.com), which the paid steps then read.

_BADGE_SITE = r"trust\s?pilot|google(?:\s+reviews)?|feefo|reevoo|trusted\s?shops|kiyoh|ekomi|reviews\.io"
_BADGE_KEY = {"trustpilot": "trustpilot", "google": "google", "feefo": "feefo", "reevoo": "reevoo",
              "trustedshops": "trustedshops", "kiyoh": "kiyoh", "ekomi": "ekomi", "reviews.io": "reviews.io"}
_BADGE_PATS = [
    # "4.8 Trustpilot Rating", "4.7/5 on Feefo", "Rated 4.8 out of 5 on Trustpilot", "4.6 ★ Google reviews"
    re.compile(r"(?<![\d.,])(\d[.,]\d{1,2})\s*(?:/\s*(5|10)|out of (5|10)|★|stars?)?\s*(?:on|from|at)?\s*"
               r"(" + _BADGE_SITE + r")\s*(?:rating|score|reviews?|trustscore|average)", re.I),
    re.compile(r"(?<![\d.,])(\d[.,]\d{1,2})\s*(?:/\s*(5|10)|out of (5|10)|★|stars?)\s*(?:on|from|at)?\s*"
               r"(" + _BADGE_SITE + r")\b", re.I),
    # "Trustpilot rating 4.8", "TrustScore 4.6 out of 5", "Feefo: 4.7/5"
    re.compile(r"(" + _BADGE_SITE + r")\s*(?:rating|score|trustscore|average)?\s*[:\-]?\s*(?:of\s*)?"
               r"(\d[.,]\d{1,2})\s*(?:/\s*(5|10)|out of (5|10)|★|stars?)", re.I),
    re.compile(r"(" + _BADGE_SITE + r")\s*(?:rating|score|trustscore|average)\s*[:\-]?\s*(\d[.,]\d{1,2})(?![\d.,])", re.I),
]
_BADGE_COUNT = re.compile(r"(?:based on|from|of|over)\s+(\d{1,3}(?:[ ,.\u00a0]\d{3})+|\d+(?:[.,]\d)?\s*k|\d+)\+?\s*"
                          r"(?:verified\s+)?(?:customer\s+)?reviews", re.I)
_TP_LINK = re.compile(r"https?://(?:([a-z]{2})\.|www\.)?trustpilot\.com/review/([a-z0-9][a-z0-9.\-]+\.[a-z]{2,})", re.I)
_TRUSTBOX = re.compile(r"<div\b[^>]*class=[\"']?[^\"'>]*trustpilot-widget[^>]*>", re.I)
# a TrustBox / custom widget that states its score in attributes (rare; most load it with JavaScript)
_TB_SCORE = re.compile(r"data-(?:score|trustscore|rating)\s*=\s*[\"']?(\d(?:[.,]\d{1,2})?)", re.I)
_TB_COUNT = re.compile(r"data-(?:number-of-reviews|review-count|reviews)\s*=\s*[\"']?(\d+)", re.I)


def _site_key(name: str) -> str:
    n = re.sub(r"\s+", "", name.lower()).replace("googlereviews", "google")
    return _BADGE_KEY.get(n, n)


def parse_badges(html: str, url: str = "") -> dict[str, Any]:
    """The shop's own page -> {badges: [{site, rating (of 5), count|None, quote}], tp_urls: [trustpilot review
    URLs it links to]}. Only explicit '<number> <review site> rating'-style claims; no claim, no badge."""
    if not html:
        return {"badges": [], "tp_urls": []}
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html[:1_500_000], flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    import html as htmllib
    text = htmllib.unescape(text).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    badges: dict[str, dict[str, Any]] = {}
    for i, pat in enumerate(_BADGE_PATS):
        for m in pat.finditer(text):
            if i < 2:
                v, scale, site = _num(m.group(1)), m.group(2) or m.group(3), m.group(4)
            else:
                site, v, scale = m.group(1), _num(m.group(2)), (m.group(3) or m.group(4)) if i == 2 else None
            if v is None:
                continue
            key = _site_key(site)
            if scale == "10" or (v > 5 and (scale is None and key == "reevoo")):
                v = v / 2
            if not 1.0 <= v <= 5.0 or key in badges:
                continue
            tail = text[m.end():m.end() + 140]
            cm = _BADGE_COUNT.search(text[max(0, m.start() - 80):m.start()] + " " + tail)
            count = None
            if cm:
                c = cm.group(1).strip().lower()
                count = int((_num(c[:-1].strip()) or 0) * 1000) if c.endswith("k") else \
                    int(_num(re.sub(r"[ ,.\u00a0](?=\d{3}\b)", "", c)) or 0) or None
            badges[key] = {"site": key, "rating": round(v, 2), "count": count,
                           "quote": text[max(0, m.start() - 10):m.end() + 10].strip()[:120]}
    for tb in _TRUSTBOX.finditer(html):
        sm, cm = _TB_SCORE.search(tb.group(0)), _TB_COUNT.search(tb.group(0))
        v = _num(sm.group(1)) if sm else None
        if v is not None and 1.0 <= v <= 5.0 and "trustpilot" not in badges:
            badges["trustpilot"] = {"site": "trustpilot", "rating": round(v, 2),
                                    "count": int(cm.group(1)) if cm else None, "quote": "TrustBox widget"}
    tp_urls: list[str] = []
    for m in _TP_LINK.finditer(html):
        sub = (m.group(1) or "www").lower()
        u = f"https://{sub}.trustpilot.com/review/{m.group(2).lower().rstrip('.')}"
        if u not in tp_urls:
            tp_urls.append(u)
    return {"badges": list(badges.values()), "tp_urls": tp_urls[:3]}


def badge_sources(html: str, url: str) -> list[dict[str, Any]]:
    """Badge claims as weak sources (key 'badge', weight 0.3, at most BADGE_MAX_N reviews, never counted as
    independent reviews) plus a non-rating 'tp_link' entry per linked Trustpilot page."""
    got = parse_badges(html, url)
    out: list[dict[str, Any]] = []
    for b in got["badges"]:
        out.append({"key": "badge", "claims": b["site"], "badge": True,
                    "name": f"{SOURCE_NAMES.get(b['site'], b['site'].title())} (shown on the shop's own page)",
                    "url": url, "rating": b["rating"], "count": b["count"], "quote": b["quote"],
                    "tp_url": got["tp_urls"][0] if b["site"] == "trustpilot" and got["tp_urls"] else None})
    for u in got["tp_urls"]:
        out.append({"key": "tp_link", "url": u, "rating": None, "count": None})
    return out


# ratings stated in a search snippet / highlight
_RATE_PATS = [
    re.compile(r"trust\s*score\s*(?:of\s*)?(\d(?:[.,]\d)?)", re.I),
    re.compile(r"(\d[.,]\d{1,2}|\d(?=\s*(?:out of|uit|van|von)\b))\s*(?:/|out of|of|uit|van|von|kautta|av)\s*"
               r"(5|10)\b(?!\s*(?:%|€|eur|days|päivä))", re.I),
    re.compile(r"(?:rated|rating|arvosana|beoordeling|bewertung|score)\s*:?\s*(\d[.,]\d)\b", re.I),
    re.compile(r"(\d[.,]\d)\s*(?:★|stars?|tähteä|sterren|sterne)", re.I),
]
_COUNT_PAT = re.compile(r"(\d{1,3}(?:[ ., ]\d{3})+|\d+(?:[.,]\d)?\s*k|\d+)\s*\+?\s*(?:verified\s+)?"
                        r"(?:reviews?|beoordelingen|ervaringen|recensies|arvostelu[a-z]*|arvio[a-z]*|bewertungen|"
                        r"ratings|reviewers|omdömen|anmeldelser)\b", re.I)


def parse_snippet_rating(text: str) -> tuple[float, int] | None:
    """'TrustScore 4.1 out of 5 · 12,345 reviews' -> (4.1, 12345). Scale 10 -> 5. None if no rating."""
    if not text:
        return None
    rating = None
    for i, pat in enumerate(_RATE_PATS):
        m = pat.search(text)
        if not m:
            continue
        v = _num(m.group(1))
        if v is None:
            continue
        scale = float(m.group(2)) if i == 1 else 5.0
        if i == 1 and scale == 10:
            v = v / 2
        if 0.9 <= v <= 5:
            rating = round(v, 2)
            break
    if rating is None:
        return None
    count = 0
    for m in _COUNT_PAT.finditer(text):
        s = m.group(1).strip().lower()
        if s.endswith("k"):
            n = (_num(s[:-1].strip()) or 0) * 1000
        else:
            n = _num(re.sub(r"[ ., ](?=\d{3}\b)", "", s)) or 0
        count = max(count, int(n))
    return rating, count


# ---------------------------------------------------------------- scoring (pure)

def classify(text: str) -> tuple[list[str], list[str]]:
    """-> (red flag kinds, grumble kinds) named in a piece of review text."""
    t = text or ""
    red = [k for k, p in RED.items() if p.search(t)]
    if red and re.search(r"\b(legit|not a scam|is (?:it|this|\S+) a scam\?|no scam|ei huijaus|geen oplichting|"
                         r"kein betrug|seriös)\b", t, re.I) and red == ["scams"]:
        red = []
    grumble = [k for k, p in GRUMBLE.items() if p.search(t)]
    return red, grumble


def _recency(d: date | None, today: date) -> float:
    if d is None:
        return 0.5
    age = (today - d).days
    return 1.0 if age <= 183 else 0.6 if age <= 365 else 0.3


def score(sources: list[dict[str, Any]], texts: list[dict[str, Any]], *, platform: bool = False,
          service: bool = False, today: date | None = None) -> dict[str, Any]:
    """Pure scoring. `sources`: [{key, name, url, rating (of 5), count, snippet?, reviews?}];
    `texts`: [{text, rating (of 5) | None, date 'YYYY-MM-DD' | None, weight}] (reviews and search highlights).
    -> {rating, count, adjusted_score, label, red_flags, grumbles, main, recent_rating, baseline}."""
    today = today or date.today()
    shift = (SHIFT_PLATFORM if platform else 0.0) + (SHIFT_SERVICE if service else 0.0)
    num = den = raw_num = 0.0
    total = 0
    recent_all: list[float] = []
    main = None
    for s in sources:
        r, n = s.get("rating"), int(s.get("count") or 0)
        key = s.get("key") or "web"
        if r is None:
            # a review site's own summary with no stars ("Evaluating 59 reviews, reviewers had a great
            # experience"): a weak, count-weighted nudge, never a made-up star rating
            if s.get("sentiment") is not None and n:
                w = SENTIMENT_W
                num += w * n * SENTIMENT_DELTA * float(s["sentiment"])
                den += w * n
                total += n
                if main is None or (main[1].get("rating") is None and w * n > main[0]):
                    main = (w * n, s)
            continue
        w = WEIGHT.get(key, 1.0) * (SNIPPET_W if s.get("snippet") else 1.0)
        rated = [x for x in (s.get("reviews") or []) if x.get("rating") is not None]
        recent = [x["rating"] for x in rated if (d := _date(x.get("date"))) and (today - d).days <= 365]
        recent_all += recent
        r_eff = 0.7 * r + 0.3 * (sum(recent) / len(recent)) if len(recent) >= 5 else r
        n_eff = max(n, len(rated), 1)
        if key == "badge":
            n_eff = min(n_eff, BADGE_MAX_N)     # the shop's own claim: weak, however many reviews it names
        base = max(1.5, BASELINE.get(s.get("claims") or key, BASELINE["web"]) + shift)
        num += w * n_eff * (r_eff - base)
        den += w * n_eff
        raw_num += r * n_eff
        total += n_eff if key not in ("own site", "badge") else 0
        if main is None or main[1].get("rating") is None or w * n_eff > main[0]:
            main = (w * n_eff, s)
    delta = num / (PRIOR_N + den) if den else 0.0
    adjusted = round(max(0.03, min(0.97, 0.5 + 0.3 * delta)), 2) if den else None
    rated_n = sum(max(int(s.get("count") or 0), len([x for x in (s.get("reviews") or []) if x.get("rating") is not None]), 1)
                  for s in sources if s.get("rating") is not None)
    rating = round(raw_num / rated_n, 1) if rated_n else None

    # red flags vs grumbles, from low-star (or unrated) texts, weighted by recency
    red_w: dict[str, float] = {}
    red_n: dict[str, int] = {}
    grumble_w: dict[str, float] = {}
    sample = 0.0
    recent_concrete = 0.0      # recent reviews with a CONCRETE red flag (not just the word "scam")
    for t in texts:
        stars = t.get("rating")
        d = _date(t.get("date"))
        w = float(t.get("weight", 1.0)) * _recency(d, today)
        sample += w
        if stars is not None and stars >= 4:
            continue           # a happy review that says "not a scam" or "fast delivery" is no complaint
        red, grumble = classify(t.get("text") or "")
        for k in red:
            # "scam!" is often an angry customer's word for a slow refund: it counts half
            red_w[k] = red_w.get(k, 0.0) + w * (SCAM_WORD_W if k == "scams" else 1.0)
            red_n[k] = red_n.get(k, 0) + 1
        if any(k != "scams" for k in red):
            recent_concrete += (1.0 if d is not None and (today - d).days <= 183 else 0.5 if d is None else 0.0) \
                * min(1.0, float(t.get("weight", 1.0)) * 2)
        for k in grumble:
            grumble_w[k] = grumble_w.get(k, 0.0) + w
    red_total = sum(red_w.values())
    red_share = red_total / sample if sample else 0.0
    big = total >= BIG_SHOP
    repeated = [k for k, n in red_n.items() if n >= 2] or ([max(red_w, key=red_w.get)] if len(red_w) >= 2 else [])
    # "watch out" needs concrete red flags (never delivered, refund refused, fake, account closed) that repeat
    # in RECENT low-star reviews; a big shop or a marketplace needs far more, since they always have some
    watch = bool(repeated) and red_total >= 1.5 and recent_concrete >= 2 and (
        platform and adjusted is not None and adjusted < 0.2 and red_share >= 0.4
        or not platform and not big and (red_share >= 0.2 or adjusted is None or adjusted < 0.45)
        or not platform and big and adjusted is not None and adjusted < 0.3 and red_share >= 0.35)
    red_flags = [f"{k} ({red_n[k]} {'recent ' if red_w[k] / red_n[k] >= 0.8 else ''}review"
                 f"{'s' if red_n[k] != 1 else ''})" for k in sorted(red_w, key=lambda k: -red_w[k])]
    grumbles = [k for k in sorted(grumble_w, key=lambda k: -grumble_w[k]) if grumble_w[k] >= 0.5]

    if watch:
        label = "watch out"
    elif adjusted is None or total < MIN_COUNT:
        label = "unknown"
        red_flags = []          # stray "scam" hits in articles about a site nobody rated say nothing
    elif adjusted >= 0.5:
        label = "solid"
    else:
        label = "mixed"
    return {"rating": rating, "count": total, "adjusted_score": adjusted, "label": label,
            "red_flags": red_flags if watch else [f for f, k in zip(red_flags, sorted(red_w, key=lambda k: -red_w[k]))
                                                  if red_n[k] >= 2],
            "red_flag_kinds": sorted(red_w),
            "watch": watch, "grumbles": grumbles, "main": main[1] if main else None, "big": big,
            "recent_rating": round(sum(recent_all) / len(recent_all), 1) if len(recent_all) >= 5 else None,
            "baseline": round(max(1.5, BASELINE.get((main[1].get("key") if main else "web") or "web", 3.6) + shift), 1)}


def summarize(domain: str, sc: dict[str, Any], *, platform: bool = False, seller_rating: float | None = None) -> str:
    """One plain sentence (two for a marketplace) saying what the reviews mean."""
    main = sc.get("main")
    lead = ""
    if main and main.get("rating") is None and main.get("sentiment") is not None:
        mood = {1: "mostly happy buyers", 0: "mixed experiences", -1: "mostly unhappy buyers"}[int(main["sentiment"])]
        lead = f"{SOURCE_NAMES.get(main.get('key') or 'web', 'review site')}'s summary of {fmt_count(main.get('count'))} reviews: {mood}"
    elif main and main.get("rating") is not None:
        name = SOURCE_NAMES.get(main.get("key") or "web", "review")
        if "same brand" in str(main.get("name") or ""):
            name = main["name"]
        n = int(main.get("count") or 0)
        if main.get("key") == "badge":
            site = SOURCE_NAMES.get(main.get("claims") or "", str(main.get("claims") or "a review site").title())
            lead = (f"{main['rating']:.1f}★ on {site}" + (f" from {fmt_count(n)} reviews" if n else "")
                    + ", as shown on the shop's own page (not checked independently)")
        elif main.get("key") != "own site":
            lead = f"{main['rating']:.1f}★ from {fmt_count(n)} {name} review{'s' if n != 1 else ''}"
        else:
            lead = f"{main['rating']:.1f}★ from {fmt_count(n)} reviews shown on its own site (self-reported, not checked)"
    label = sc["label"]
    grumbles = sc.get("grumbles") or []
    if label == "watch out":
        kinds = [f.split(" (")[0] for f in sc.get("red_flags") or []][:2]
        body = (f"{lead}; " if lead else "") + f"recent reviews repeat {' and '.join(kinds)}: pay with buyer protection or pick another shop"
    elif label == "unknown":
        if lead and main and main.get("key") in ("own site", "badge"):
            body = f"{lead}; no independent reviews found"
        elif lead and sc.get("count", 0) < MIN_COUNT:
            body = f"{lead}: too few reviews to say"
        else:
            body = f"No useful reviews found for {domain}"
    else:
        if lead and sc.get("adjusted_score") is not None and main and main.get("rating") is not None \
                and main["rating"] < sc.get("baseline", 3.6) + 0.3 and label == "solid":
            lead += f", about normal there (shops average ~{sc['baseline']:.1f}★ on it)"
        if grumbles:
            g = " and ".join(grumbles[:2])
            tail = f"complaints are mostly {g}, normal for a {'big ' if sc.get('big') else ''}{'platform' if platform else 'shop'}" \
                if label == "solid" else f"complaints are mostly {g}, nothing serious"
        elif label == "mixed":
            tail = "rated below what is normal there, but no pattern of serious complaints"
        else:
            tail = "no pattern of serious complaints"
        if sc.get("red_flags"):
            kinds = " and ".join(f.split(" (")[0] for f in sc["red_flags"][:2])
            tail = ("" if label == "solid" else "rated below what is normal there; ")
            tail += (f"a few complaints of {kinds}, " + ("use the platform's buyer protection" if platform else
                                                           f"not unusual at {fmt_count(sc.get('count'))} reviews"))
        body = f"{lead}; {tail}" if lead else tail[0].upper() + tail[1:]
    s = body.rstrip(".") + "."
    if platform:
        who = f" This seller is rated {seller_rating:g} there." if seller_rating else " The individual seller is not rated here."
        s = f"The {domain} platform: {s[0].lower() + s[1:]}{who}"
    return s


# ---------------------------------------------------------------- targets

def _landed(o: Any) -> float | None:
    tc = getattr(o, "true_cost", None)
    if tc is not None and getattr(tc, "per", "month") == "job":
        return tc.total_eur
    if tc is not None:
        return tc.sticker_eur + tc.extras_eur
    return o.price_eur


def targets_from_offers(offers: list[Any], pick_url: str | None = None, *, service: bool = False,
                        max_n: int = MAX_DOMAINS) -> list[dict[str, Any]]:
    """The sites worth checking, most important first: the pick, the TOP_BY_PRICE cheapest all-in shops,
    then marketplaces / service providers. One entry per registrable domain, with the hosts it covers."""
    by_dom: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def add(o: Any, why: str) -> None:
        dom = domain_of(o.url)
        if not dom or "." not in dom:
            return
        t = by_dom.get(dom)
        if t is None:
            t = by_dom[dom] = {"domain": dom, "hosts": set(), "platform": trust.is_marketplace(o.url),
                               "service": service or o.condition == "service", "why": why, "seller_rating": None}
            order.append(dom)
        t["hosts"].add(o.source or trust.host_of(o.url))
        sr = (o.raw or {}).get("seller_rating") if hasattr(o, "raw") else None
        if isinstance(sr, (int, float)) and t["seller_rating"] is None and dom == domain_of(pick_url or ""):
            t["seller_rating"] = float(sr)

    priced = [o for o in offers if _landed(o) is not None]
    pick = next((o for o in offers if o.url == pick_url), None)
    if pick is not None:
        add(pick, "pick")
    for o in sorted(priced, key=lambda o: _landed(o) or 0):
        if len(order) >= TOP_BY_PRICE + (1 if pick is not None else 0) and domain_of(o.url) not in by_dom:
            break
        add(o, "cheap")
    for o in priced:
        if trust.is_marketplace(o.url) or o.condition == "service":
            if len(order) >= max_n and domain_of(o.url) not in by_dom:
                continue
            add(o, "platform" if trust.is_marketplace(o.url) else "provider")
    out = [by_dom[d] for d in order[:max_n]]
    for t in out:
        t["hosts"] = sorted(t["hosts"])
    return out


DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}\.)+[a-z]{2,24}$")


def targets_from_hosts(hosts: list[str], *, service: bool = False, max_n: int = MAX_DOMAINS) -> list[dict[str, Any]]:
    """Targets from a list of shop hosts (a replayed hunt): in the given order, grouped by registrable domain."""
    by_dom: dict[str, dict[str, Any]] = {}
    for h in hosts:
        h = trust.host_of(str(h))
        if not DOMAIN_RE.match(h):
            continue
        dom = domain_of(h)
        if dom not in by_dom:
            if len(by_dom) >= max_n:
                continue
            by_dom[dom] = {"domain": dom, "hosts": set(), "platform": trust.is_marketplace(dom),
                           "service": service, "why": "listed", "seller_rating": None}
        by_dom[dom]["hosts"].add(h)
    out = list(by_dom.values())
    for t in out:
        t["hosts"] = sorted(t["hosts"])
    return out


# ---------------------------------------------------------------- cache (SQLite) + the judge's view

_MEM: dict[str, dict[str, Any]] = {}


def _fresh(rec: dict[str, Any] | None, now: float | None = None) -> bool:
    if not rec:
        return False
    ttl = NONE_TTL_S if rec.get("status") == "none" else CACHE_TTL_S
    return (now or time.time()) - float(rec.get("checked_at") or 0) <= ttl


def cached(domains: list[str], *, any_age: bool = False) -> dict[str, dict[str, Any]]:
    try:
        from agora import store
        got = store.get_reviews(sorted(set(domains)))
    except Exception:
        return {}
    return {d: r for d, r in got.items() if any_age or offline() or _fresh(r)}


def save(rec: dict[str, Any]) -> None:
    rec = dict(rec)
    rec.pop("hosts", None)
    rec.pop("cached", None)
    _MEM[rec["domain"]] = rec | {"checked_at": time.time()}
    try:
        from agora import store
        store.save_review(rec["domain"], rec)
    except Exception:
        pass


_LOOKED: dict[str, float] = {}     # domain -> when the cache was last asked about it (judge runs often)
LOOK_EVERY_S = 30.0


def preload(urls: Iterable[str]) -> None:
    """The judge calls this per verdict: at most one SQLite read for the shops not asked about lately."""
    now = time.monotonic()
    doms = sorted({domain_of(u) for u in urls if u} - {d for d, t in _LOOKED.items() if now - t < LOOK_EVERY_S})
    if not doms:
        return
    for d in doms:
        _LOOKED[d] = now
    got = cached(doms)
    for d in doms:
        if d in got:
            _MEM[d] = got[d]
        elif d in _MEM and not _fresh(_MEM[d]):
            _MEM.pop(d, None)


def signals_for(o: Any) -> list[tuple[str, float, float | None]]:
    """Trust signals from cached reviews (same shape as agora.trust.assess). Never raises, never fetches.
    A 'watch out' shop gets trust capped under the judge's risky line, so it is never the pick."""
    try:
        rec = _MEM.get(domain_of(o.url))
    except Exception:
        return []
    if not rec or rec.get("status") != "done":
        return []
    label = rec.get("label")
    if label == "watch out":
        kinds = ", ".join(f.split(" (")[0] for f in (rec.get("red_flags") or [])[:2]) or "serious complaints"
        return [(f"reviews: red flags in recent reviews ({kinds})", 0.45, 0.4)]
    if label == "mixed" and (rec.get("adjusted_score") or 0.5) < 0.3:
        return [(f"reviews: rated low ({rec.get('rating')}★ from {fmt_count(rec.get('count'))})", 0.1, None)]
    return []


# ---------------------------------------------------------------- fetching

Fetch = Callable[[str], Awaitable[tuple[int, str]]]
Search = Callable[..., Awaitable[list[dict[str, Any]]]]

_tp_blocked_until = 0.0


async def _default_fetch(url: str) -> tuple[int, str]:
    from agora import reader
    return await reader.fetch_html(url)


def _blocked(status: int, html: str) -> bool:
    if status in (401, 403, 429, 503):
        return True
    head = (html or "")[:4000].lower()
    return len(html or "") < 20000 and any(m in head for m in ("verifying your connection", "captcha", "cf-chl",
                                                                 "just a moment", "access denied"))


async def free_sources(domain: str, *, platform: bool, fetch: Fetch | None = None) -> tuple[list[dict], list[dict], int]:
    """Plain fetches of the free review pages. -> (sources, texts, pages read)."""
    global _tp_blocked_until
    fetch = fetch or _default_fetch
    pages: list[tuple[str, str]] = []
    if time.monotonic() >= _tp_blocked_until:
        pages.append(("trustpilot", f"https://www.trustpilot.com/review/{domain}"))
    pages.append(("smartcustomer", f"https://www.sitejabber.com/reviews/{domain}"))
    if not platform:
        pages.append(("own site", f"https://{domain}/"))

    badges: list[dict[str, Any]] = []

    async def one(key: str, url: str) -> tuple[str, str, dict[str, Any] | None]:
        global _tp_blocked_until
        try:
            status, html = await asyncio.wait_for(fetch(url), timeout=FREE_TIMEOUT_S)
        except Exception:
            return key, url, None
        if key == "trustpilot" and _blocked(status, html):
            _tp_blocked_until = time.monotonic() + TP_BLOCK_S
            return key, url, None
        if status != 200 or not html:
            return key, url, None
        try:
            if key == "own site":
                badges.extend(await asyncio.to_thread(badge_sources, html, url))
            return key, url, await asyncio.to_thread(parse_rating_page, html, url)
        except Exception:
            return key, url, None

    got = await asyncio.gather(*(one(k, u) for k, u in pages))
    n_pages = len(pages)
    # the shop links its real Trustpilot page (www.<domain>, a uk. / de. subdomain): read that one too, free
    tried_tp = {u for k, u in pages if k == "trustpilot"}
    linked = next((b["url"] for b in badges if b["key"] == "tp_link"
                   and domain_of(_TP_PATH.search(b["url"]).group(1)) == domain), None) if badges else None
    if linked and time.monotonic() >= _tp_blocked_until and not any(k == "trustpilot" and r for k, _, r in got):
        www = "https://www.trustpilot.com/review/" + _TP_PATH.search(linked).group(1)
        if www not in tried_tp:
            got = list(got) + [await one("trustpilot", www)]
            n_pages += 1
    sources, texts = [], []
    for key, url, res in got:
        if not res:
            continue
        sources.append({"key": key, "name": SOURCE_NAMES[key], "url": url, "rating": res["rating"],
                        "count": res["count"], "reviews": res.get("reviews") or []})
        if key != "own site":
            texts += [{"text": r["text"], "rating": r.get("rating"), "date": r.get("date"), "weight": 1.0}
                      for r in res.get("reviews") or []]
    sources += badges
    return sources, texts, n_pages


_TP_PATH = re.compile(r"trustpilot\.com/review/([^/?#]+)", re.I)
_TP_COUNT = re.compile(r"(?:evaluating|arvioitaessa|op basis van|basierend auf|en évaluant|baserat på|baseret på|"
                       r"basert på|sulla base di|na podstawie)\s+(\d{1,3}(?:[\s\u00a0\u202f,.]\d{3})+|\d+)", re.I)
_SENT_NEG = re.compile(r"\b(dissatisfied|disappointed|unhappy|negative experience|bad experience|frustrat\w+|"
                       r"tyytymättömiä|pettyneitä|pettyneet|negatiivi\w*|ontevreden|teleurgesteld|unzufrieden|"
                       r"enttäuscht|missnöjda|utilfredse|insatisfaits|déçus|mauvaise expérience)\b", re.I)
_SENT_POS = re.compile(r"\b(great experience|good experience|positive experience|exceptional experience|"
                       r"excellent experience|were (?:very )?satisfied|expérience exceptionnelle|"
                       r"(?:très )?bonne expérience|excellente expérience|très satisfaits|"
                       r"(?:generally |very )?happy with|erinomai\w+ kokemu\w+|hyvä\w* kokemu\w+|olivat tyytyväisiä|"
                       r"positiivi\w+ kokemu\w+|tevreden|positieve ervaring|zufrieden|positive erfahrung|nöjda|"
                       r"tilfredse|satisfaits)\b", re.I)
_SENT_MIX = re.compile(r"\b(mixed|vaihtelev\w+|ristiriitai\w+|gemengd|gemischt|blandade|blandede)\b", re.I)


def tp_sentiment(text: str) -> int | None:
    """Trustpilot's own review summary sentence -> +1 / 0 / -1 (None when there is none)."""
    m = re.search(r"(?:evaluating|arvioitaessa|op basis van|basierend auf|baserat på|baseret på|en évaluant)[^.]{0,220}",
                  text or "", re.I)
    if not m:
        return None
    t = m.group(0)
    if _SENT_NEG.search(t):
        return -1
    if _SENT_MIX.search(t):
        return 0
    if _SENT_POS.search(t):
        return 1
    return None


def sources_from_search(domain: str, results: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """One site's sources + texts from search results (see `sources_by_domain`)."""
    return sources_by_domain([domain], results).get(domain, ([], []))


def sources_by_domain(domains: list[str], results: list[dict[str, Any]]) -> dict[str, tuple[list[dict], list[dict]]]:
    """Context.dev search results (with highlights) -> per shop: snippet ratings by source (only from review
    sites, never a blog's own score), Trustpilot's summary (review count + mood, no stars) and texts for the
    flag scan. A Trustpilot page belongs to the shop in its /review/<domain> path; any other result only
    counts for a shop whose domain or name it mentions."""
    from agora.contextdev import highlight_text
    out: dict[str, tuple[dict[str, dict], list[dict], set[str]]] = {d: ({}, [], set()) for d in domains}
    for r in results or []:
        url = str(r.get("url") or "")
        host = trust.host_of(url)
        text = " ".join(x for x in (str(r.get("title") or ""), str(r.get("description") or ""), highlight_text(r)) if x)
        m = _TP_PATH.search(url)
        sibling = None
        if m:
            tp_dom = domain_of(m.group(1).lower())
            owners = [d for d in domains if tp_dom == d]
            if not owners:
                # the same brand on another TLD (yoojo.nl's reviews live on trustpilot.com/review/yoojo.fr)
                owners = [d for d in domains if _same_brand(d, tp_dom)]
                sibling = tp_dom if owners else None
        else:
            flat = re.sub(r"[^a-z0-9]", "", (url + " " + text).lower())
            owners = [d for d in domains if d in url.lower() or d in text.lower()
                      or (len(d.split(".")[0]) >= 4 and re.sub(r"[^a-z0-9]", "", d.split(".")[0]) in flat)]
        for dom in owners:
            sources, texts, seen = out[dom]
            key = source_key(host, dom)
            if key == "own site":
                continue
            body = highlight_text(r) or text
            if body[:160] not in seen:
                seen.add(body[:160])
                texts.append({"text": text[:2000], "rating": None, "date": None,
                              "weight": 1.0 if key == "reddit" else 0.5, "url": url})
            got = parse_snippet_rating(text) if key in RATING_SITES else None
            if key == "trustpilot" and m:
                cm = _TP_COUNT.search(text)
                count = int(_num(re.sub(r"[\s\u00a0\u202f,.](?=\d{3}\b)", "", cm.group(1))) or 0) if cm else 0
                sent = tp_sentiment(text)
                prev = sources.get(key)
                base_url = f"https://www.trustpilot.com/review/{m.group(1)}"
                tp_name = f"Trustpilot ({sibling}, same brand)" if sibling else "Trustpilot"
                if sibling and prev is not None and not prev.get("sibling") and (prev.get("count") or prev.get("rating")):
                    continue        # the shop's own page beats a sister site's
                if got:
                    rating, c2 = got
                    if prev is None or prev.get("rating") is None or max(count, c2) > (prev.get("count") or 0):
                        sources[key] = {"key": key, "name": tp_name, "url": base_url, "rating": rating,
                                        "count": max(count, c2), "snippet": True, "sibling": sibling}
                elif prev is None or (prev.get("rating") is None and (sent is not None or count > (prev.get("count") or 0))):
                    sources[key] = {"key": key, "name": tp_name, "url": base_url, "rating": None, "sibling": sibling,
                                    "count": max(count, (prev or {}).get("count") or 0) or None,
                                    "sentiment": sent if sent is not None else (prev or {}).get("sentiment"),
                                    "snippet": True}
                continue
            if got:
                rating, count = got
                prev = sources.get(key)
                if prev is None or count > (prev.get("count") or 0):
                    sources[key] = {"key": key, "name": SOURCE_NAMES.get(key, host), "url": url, "rating": rating,
                                    "count": count, "snippet": True}
            elif key == "reddit" and "reddit" not in sources:
                sources["reddit"] = {"key": "reddit", "name": "Reddit", "url": url, "rating": None, "count": None}
    return {d: (list(v[0].values()), v[1]) for d, v in out.items()}


def _same_brand(a: str, b: str) -> bool:
    """yoojo.nl ~ yoojo.fr: the same distinctive name on another country TLD."""
    na, nb = a.split(".")[0], b.split(".")[0]
    return na == nb and len(na) >= 5 and na not in trust.GENERIC_NAMES and a != b


def tp_batch_query(domains: list[str]) -> str:
    return " ".join(domains) + " reviews"


TP_SCHEMA = {"type": "object", "properties": {
    "trust_score": {"type": ["number", "null"], "description": "TrustScore or average stars out of 5"},
    "review_count": {"type": ["integer", "null"]},
    "recent_reviews": {"type": "array", "items": {"type": "object", "properties": {
        "stars": {"type": ["number", "null"]}, "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "text": {"type": ["string", "null"]}}}}}}


# ---------------------------------------------------------------- the phase

def _event(t: dict[str, Any], status: str, **extra: Any) -> dict[str, Any]:
    return {"domain": t["domain"], "hosts": t.get("hosts") or [t["domain"]], "status": status,
            "platform": bool(t.get("platform")), "why": t.get("why")} | extra


def finalize(t: dict[str, Any], sources: list[dict], texts: list[dict], *, today: date | None = None) -> dict[str, Any]:
    """Score what was found for one target -> the `review` event body (status done | none)."""
    sources = [s for s in sources if _useful(s)]
    rated = [s for s in sources if s.get("rating") is not None or (s.get("sentiment") is not None and s.get("count"))]
    if not rated and not any(classify(x.get("text") or "")[0] for x in texts):
        return _event(t, "none", rating=None, count=0, sources=[_pub(s) for s in sources], adjusted_score=None,
                      label="unknown", red_flags=[], grumbles=[], bias_note=BIAS_NOTE,
                      summary=(f"No reviews found for {t['domain']}." if not t.get("platform") else
                               f"No reviews found for the {t['domain']} platform. The individual seller is not rated here."))
    sc = score(sources, texts, platform=bool(t.get("platform")), service=bool(t.get("service")), today=today)
    return _event(t, "done", rating=sc["rating"], count=sc["count"], adjusted_score=sc["adjusted_score"],
                  label=sc["label"], red_flags=sc["red_flags"], grumbles=sc["grumbles"],
                  recent_rating=sc["recent_rating"], baseline=sc["baseline"],
                  sources=[_pub(s) for s in sorted(sources, key=lambda s: -(s.get("count") or 0))],
                  summary=summarize(t["domain"], sc, platform=bool(t.get("platform")),
                                    seller_rating=t.get("seller_rating")),
                  seller_rating=t.get("seller_rating"), bias_note=BIAS_NOTE)


def _useful(s: dict[str, Any]) -> bool:
    """A source worth listing: it has stars, a review count or a mood (a Reddit thread link counts too)."""
    return s.get("rating") is not None or bool(s.get("count")) or s.get("sentiment") is not None or s.get("key") == "reddit"


def _pub(s: dict[str, Any]) -> dict[str, Any]:
    mood = {1: "mostly happy", 0: "mixed", -1: "mostly unhappy"}.get(s.get("sentiment")) if s.get("rating") is None else None
    return {"name": s.get("name"), "url": s.get("url"), "rating": s.get("rating"), "count": s.get("count"),
            "via": "search snippet" if s.get("snippet") else ("self-reported" if s.get("key") == "own site" else
                                                              "shown on the shop's own page" if s.get("key") == "badge"
                                                              else "page"),
            **({"mood": mood} if mood else {})}


# Trustpilot's local sites by the shop's country (uk.trustpilot.com for a British shop)
TP_LOCAL = {"gb": "uk", "uk": "uk", "de": "de", "at": "at", "ch": "ch", "fr": "fr", "nl": "nl", "be": "be",
            "dk": "dk", "se": "se", "no": "no", "it": "it", "es": "es", "pl": "pl", "ie": "ie", "pt": "pt",
            "au": "au", "ca": "ca", "nz": "nz"}


def shop_country(domain: str) -> str | None:
    try:
        from agora.origin import KNOWN_SHOPS
        if domain in KNOWN_SHOPS:
            return KNOWN_SHOPS[domain]
    except ImportError:
        pass
    tld = _country(domain)
    return tld if tld in TP_LOCAL else None


def big_shop(domain: str, sources: list[dict[str, Any]]) -> bool:
    """A shop that surely has reviews somewhere: a well-known retailer, or one showing a rating badge /
    linking its Trustpilot page on its own site."""
    if any(s.get("key") in ("badge", "tp_link") for s in sources):
        return True
    try:
        from agora.judge import KNOWN_SHOPS as J
        from agora.origin import KNOWN_SHOPS as O
    except ImportError:
        return False
    return domain in O or any(domain.startswith(k) for k in J)


def tp_name(domain: str, sources: list[dict[str, Any]]) -> str:
    """The name Trustpilot files the shop under: from the link on its page (often www.<domain>), else the domain."""
    for s in sources:
        if s.get("key") in ("tp_link", "badge") and s.get("url" if s.get("key") == "tp_link" else "tp_url"):
            m = _TP_PATH.search(s.get("url") if s.get("key") == "tp_link" else s["tp_url"])
            if m and domain_of(m.group(1)) == domain:
                return m.group(1)
    return domain


def tp_domains(domain: str) -> list[str]:
    cc = shop_country(domain)
    loc = TP_LOCAL.get(cc or "")
    return ["trustpilot.com"] + ([f"{loc}.trustpilot.com"] if loc else [])


def tp_page(domain: str, sources: list[dict[str, Any]]) -> str | None:
    """A Trustpilot page worth one paid read: the one the shop links, else (big shops) the local site's page."""
    for s in sources:
        u = s.get("url") if s.get("key") == "tp_link" else s.get("tp_url")
        m = _TP_PATH.search(u or "")
        if m and domain_of(m.group(1)) == domain:
            return u
    if big_shop(domain, sources):
        loc = TP_LOCAL.get(shop_country(domain) or "")
        return f"https://{loc or 'www'}.trustpilot.com/review/{domain}"
    return None


def _tokens() -> float:
    try:
        from agora import discover
        return float(discover.tokens_available())
    except Exception:
        return 0.0


async def run(targets: list[dict[str, Any]], *, paid: bool = True, budget_s: float = PHASE_BUDGET_S,
              fetch: Fetch | None = None, search: Search | None = None,
              extract: Callable[..., Awaitable[dict | None]] | None = None,
              tokens: Callable[[], float] | None = None, stats: dict[str, Any] | None = None,
              today: date | None = None) -> AsyncIterator[dict[str, Any]]:
    """The reviews phase: yields `review` event bodies. Cached sites first (instant, free), then every
    other site as `checking`, then each one `done` / `none` as it is scored. Bounded by `budget_s`."""
    t_end = time.monotonic() + max(1.0, budget_s)
    stats = stats if stats is not None else {}
    stats.update(cached=0, free_pages=0, paid=0, domains=len(targets))
    hits = cached([t["domain"] for t in targets])
    todo = []
    for t in targets:
        rec = hits.get(t["domain"])
        if rec is not None:
            stats["cached"] += 1
            yield {k: v for k, v in rec.items() if k != "checked_at"} | {
                "hosts": t.get("hosts") or [t["domain"]], "why": t.get("why"), "cached": True,
                "checked_at": rec.get("checked_at")}
        else:
            todo.append(t)
    if not todo:
        return
    if offline():
        for t in todo:
            yield _event(t, "none", rating=None, count=0, sources=[], adjusted_score=None, label="unknown",
                         red_flags=[], grumbles=[], summary="Offline: no saved reviews for this site.",
                         bias_note=BIAS_NOTE, offline=True)
        return
    for t in todo:
        yield _event(t, "checking")

    if search is None or extract is None:
        from agora import contextdev
        search = search or contextdev.search
        extract = extract or contextdev.extract
    tokens = tokens or _tokens

    found: dict[str, tuple[list[dict], list[dict]]] = {}

    async def free_one(t: dict[str, Any]) -> tuple[dict[str, Any], list[dict], list[dict], int]:
        try:
            src, txt, n = await free_sources(t["domain"], platform=bool(t.get("platform")), fetch=fetch)
        except Exception:
            src, txt, n = [], [], 0
        return t, src, txt, n

    free_tasks = [asyncio.create_task(free_one(t)) for t in todo]
    pending_paid: list[dict[str, Any]] = []
    try:
        for fut in asyncio.as_completed(free_tasks, timeout=max(1.0, min(FREE_TIMEOUT_S + 3, t_end - time.monotonic()))):
            t, src, txt, n = await fut
            stats["free_pages"] += n
            found[t["domain"]] = (src, txt)
            solid_free = any((s.get("count") or 0) >= PRIOR_N and s.get("key") not in ("own site", "badge", "tp_link")
                             for s in src)
            if solid_free or not paid:
                rec = finalize(t, src, txt, today=today)
                _keep(rec, complete=solid_free)
                yield rec
            else:
                pending_paid.append(t)
    except TimeoutError:
        pass
    for task in free_tasks:
        if not task.done():
            task.cancel()
    for t in todo:
        if t["domain"] in found:
            continue
        found[t["domain"]] = ([], [])
        if paid:
            pending_paid.append(t)
        else:
            rec = finalize(t, [], [], today=today)
            _keep(rec, complete=False)
            yield rec

    # paid steps, most important first (the targets' own order), paced by the shared bucket:
    #   A  one batched Trustpilot search per TP_BATCH sites (its pages say how many reviews and how they
    #      feel, plus recent review text, for several shops for one token);
    #   B  ONE Context.dev JSON read of the Trustpilot page of the most important site still without stars;
    #   C  a local-language "<domain> reviews" search for sites nothing has covered yet.
    order = {t["domain"]: i for i, t in enumerate(targets)}
    pending_paid.sort(key=lambda t: order.get(t["domain"], 99))
    tried: set[str] = set()

    async def spend(make: Callable[[], Awaitable[Any]], need: float = TOKEN_NEED, min_left: float = 3.0) -> Any:
        """One paid request when the bucket allows it (waits for a refill, never past the budget)."""
        if stats["paid"] >= MAX_PAID:
            return None
        await _wait_tokens(tokens, need, t_end - PAID_MIN_LEFT_S)
        left = t_end - time.monotonic()
        if left <= min_left or tokens() < need:
            return None
        stats["paid"] += 1
        try:
            return await asyncio.wait_for(make(), timeout=min(PAID_WAIT_S + 12, left))
        except Exception:
            return None

    def settled(dom: str) -> bool:
        return any(s.get("rating") is not None and (s.get("count") or 0) >= PRIOR_N
                   and s.get("key") not in ("own site", "badge", "tp_link") for s in found.get(dom, ([], []))[0])

    def finish(t: dict[str, Any]) -> dict[str, Any]:
        src, txt = found.get(t["domain"], ([], []))
        rec = finalize(t, src, txt, today=today)
        _keep(rec, complete=t["domain"] in tried)
        return rec

    left_over = list(pending_paid)
    # A
    all_doms = [t["domain"] for t in pending_paid]
    covered: set[str] = set()
    while True:
        chunk = [d for d in all_doms if d not in covered][:TP_BATCH]
        if not chunk:
            break
        res = await spend(lambda c=chunk: search(tp_batch_query(c), n=10, highlights=True,
                                                 include_domains=["trustpilot.com"], highlight_chars=900))
        if res is None:
            break
        covered.update(chunk)
        for dom, (s2, t2) in sources_by_domain(all_doms, res).items():   # a page may answer for any pending site
            if not s2 and not t2:
                continue
            src, txt = found.get(dom, ([], []))
            found[dom] = (_merge(src, s2), txt + t2)
            if any(x.get("key") == "trustpilot" for x in s2):
                covered.add(dom)
        tried.update(chunk)
    # A2: a big shop (a known retailer, or one showing a rating badge) the batch missed: its own Trustpilot
    # search, under the name its page links ("www.wexphotovideo.com"), the local Trustpilot site included
    big_tries = 0
    for t in pending_paid:
        dom = t["domain"]
        if big_tries >= MAX_BIG_TP or t.get("platform") or not big_shop(dom, found.get(dom, ([], []))[0]):
            continue
        if any(x.get("key") == "trustpilot" for x in found.get(dom, ([], []))[0]):
            continue
        name = tp_name(dom, found.get(dom, ([], []))[0])
        big_tries += 1
        res = await spend(lambda n=name, d=dom: search(f"{n} reviews", n=8, highlights=True,
                                                       include_domains=tp_domains(d), highlight_chars=900))
        if res is None:
            break
        tried.add(dom)
        s2, t2 = sources_from_search(dom, res)
        src, txt = found.get(dom, ([], []))
        found[dom] = (_merge(src, s2), txt + t2)

    async def local(t: dict[str, Any]) -> None:
        dom = t["domain"]
        res = await spend(lambda d=dom: search(review_query(d), n=10, highlights=True, highlight_chars=1500))
        if res is None:
            return
        tried.add(dom)
        s2, t2 = sources_from_search(dom, res)
        src, txt = found.get(dom, ([], []))
        found[dom] = (_merge(src, s2), txt + t2)

    # the pick still without a rating: its local-language search first (it may surface its Trustpilot page)
    pick_t = next((t for t in left_over if t.get("why") == "pick"), None)
    if pick_t is not None and not any(s.get("rating") is not None or s.get("key") == "trustpilot"
                                      for s in found.get(pick_t["domain"], ([], []))[0]):
        await local(pick_t)
        pick_t["_local"] = True
    # B: the most important site that has a Trustpilot page but no stars yet
    cand = next((t for t in sorted(left_over, key=lambda t: t.get("why") != "pick") if not settled(t["domain"]) and any(
        s.get("key") == "trustpilot" for s in found.get(t["domain"], ([], []))[0])), None)
    if cand is None:
        # no Trustpilot result, but the shop links its Trustpilot page (or is a big shop): read that page
        cand = next((t for t in sorted(left_over, key=lambda t: t.get("why") != "pick") if not settled(t["domain"])
                     and not t.get("platform") and tp_page(t["domain"], found.get(t["domain"], ([], []))[0])), None)
    for t in [x for x in left_over if x is not cand and (settled(x["domain"]) or found.get(x["domain"], ([], []))[0])]:
        left_over.remove(t)
        yield finish(t)
    if cand is not None:
        url = next((s["url"] for s in found[cand["domain"]][0] if s.get("key") == "trustpilot"), None) \
            or tp_page(cand["domain"], found.get(cand["domain"], ([], []))[0])
        data = await spend(lambda: extract(url, TP_SCHEMA, "The company's TrustScore (stars out of 5), its total "
                                           "number of reviews and up to 15 most recent reviews."),
                           min_left=8.0)
        if data is not None:
            s4, t4 = _from_tp_json(url, data, cand["domain"])
            src, txt = found.get(cand["domain"], ([], []))
            found[cand["domain"]] = (_merge(src, s4), txt + t4)
        left_over.remove(cand)
        yield finish(cand)
    # C: nothing found yet: one search in the shop's language (and Reddit for the pick if there is room)
    for t in list(left_over):
        dom = t["domain"]
        if not t.pop("_local", False):
            await local(t)
        if dom in tried:
            if t.get("why") == "pick":
                res = await spend(lambda d=dom: search(f"{d} reddit", n=5, highlights=True,
                                                       include_domains=["reddit.com"], highlight_chars=1200),
                                  need=TOKEN_NEED + 1)
                if res is not None:
                    s3, t3 = sources_from_search(dom, res)
                    src, txt = found.get(dom, ([], []))
                    found[dom] = (_merge(src, s3), txt + t3)
        left_over.remove(t)
        yield finish(t)


def _keep(rec: dict[str, Any], complete: bool) -> None:
    """Cache a result. 'Nothing found' is only cached when every source was tried (a replay without paid
    reads, or a phase that ran out of bucket tokens, must not hide a site for days)."""
    if rec.get("status") == "done" or complete:
        save(rec)


async def _wait_tokens(tokens: Callable[[], float], need: float, until: float) -> None:
    while tokens() < need and time.monotonic() + 1 < until:
        await asyncio.sleep(1.0)


def _merge(a: list[dict], b: list[dict]) -> list[dict]:
    """One entry per source: the one with the most reviews (a page read beats a snippet at equal count)."""
    out: dict[Any, dict] = {}
    for s in a + b:
        k = (s.get("key") or s.get("name"), s.get("claims"), s.get("url") if s.get("key") == "tp_link" else None)
        cur = out.get(k)
        if cur is None or (s.get("rating") is not None and (cur.get("rating") is None or
                                                             (s.get("count") or 0) > (cur.get("count") or 0))):
            out[k] = s
    return list(out.values())


def _from_tp_json(url: str, data: dict | None, domain: str | None = None) -> tuple[list[dict], list[dict]]:
    if not isinstance(data, dict):
        return [], []
    r = _num(data.get("trust_score"))
    n = int(_num(data.get("review_count")) or 0)
    revs = [x for x in data.get("recent_reviews") or [] if isinstance(x, dict) and x.get("text")]
    texts = [{"text": str(x["text"])[:1200], "rating": _num(x.get("stars")), "date": x.get("date"), "weight": 1.0}
             for x in revs]
    if r is None or not 0 < r <= 5:
        return [], texts
    m = _TP_PATH.search(url)
    tp_dom = domain_of(m.group(1)) if m else None
    name = f"Trustpilot ({tp_dom}, same brand)" if domain and tp_dom and tp_dom != domain else "Trustpilot"
    return [{"key": "trustpilot", "name": name, "url": url, "rating": r, "count": n,
             "reviews": [{"rating": t["rating"], "date": t["date"], "text": t["text"]} for t in texts]}], texts


def hunt_targets(result: Any) -> list[dict[str, Any]]:
    """Targets for a finished hunt (agora.hunt.HuntResult)."""
    v = getattr(result, "verdict", None)
    pick = (getattr(v, "best_offer_url", None) or getattr(v, "best_true_cost_url", None)) if v else None
    need = getattr(result, "need", None)
    return targets_from_offers(list(getattr(result, "offers", []) or []), pick,
                               service=getattr(need, "kind", "product") == "service")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
