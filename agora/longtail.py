"""LONG TAIL: providers no registry lists (designjoy.co, a productized dev shop, a small tilitoimisto).
Written at Junction 2026.

Digital / B2B services, subscriptions and agencies live on their own small sites. Keyword search for the
need finds a few; the rest hide in "best X" / "X alternatives" articles and in look-alikes of a good one.
This lane finds them and reads their PRICING pages:

1. intent queries   the need phrased the way providers describe themselves ("unlimited graphic design
                    subscription", "design agency monthly retainer", "productized design service pricing"),
                    English + the local language (labels from agora.taxonomy when it is importable);
2. listicle mining  "best X / top X / X alternatives" articles (from our searches, and the ones the core
                    lanes skip as "not a shop": agora.discover calls note_listicle) are read ONCE with a free
                    fetch (a paid Context.dev markdown read only when the free one is blocked) and cut into
                    provider domains: outbound links (no social, affiliates, big media) and numbered headings
                    ("3. ManyPixels" -> manypixels.co, checked with a free fetch of the guessed home page);
3. similar sites    once a provider shows prices: Exa findSimilar (EXA_API_KEY, free of Context.dev tokens),
                    else ONE Context.dev search "<domain> alternatives";
4. pricing reader   home page links -> /pricing /plans /prices /hinnasto /preise /tarifs ... (free fetch), plans
                    parsed by code (JSON-LD, then price + period text: "$995 /mo", "49 €/kk"); a Context.dev
                    JSON read with PLAN_SCHEMA only when the free parse finds nothing;
5. registry         every provider + category + pricing URL + plans goes to agora.longtail_store, so the next
                    hunt for the same kind of thing starts there for free.

Budget: at most PAID_MAX (3) Context.dev requests per hunt, each taken only when the shared 10/min bucket has
a spare token (the core lanes' searches go first), all inside the hunt's deadline. Free fetches are bounded
by FETCH_TIMEOUT and FREE_CONCURRENCY.

Use (hunt hook):  async for item in longtail.lane(need, deadline=..., seen_urls=...): Event | Offer
Events: lane {lane: "longtail", queries, category, kind, via} · source {url, domain, lane: "longtail", via:
registry|search|listicle|similar, title, from?} · skip {url, reason, lane: "longtail"}
Offers: condition "service", unit = plan period (month | year | hour | job), read_via "longtail_free" |
"longtail_registry" | "contextdev_json", raw.longtail = True, raw.plans = every plan read on the page.
"""
from __future__ import annotations

import asyncio
import contextvars
import os
import re
import time
import unicodedata
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from agora import contextdev
from agora.models import Event, Need, Offer

PAID_MAX = 3                 # Context.dev requests per hunt for this lane (searches + reads together)
FIRST_PAID_SPARE = 1.0       # the first paid call waits until the shared bucket has this many tokens left
LATER_PAID_SPARE = 1.5       # later ones leave more for the core lanes' paid reads
PAID_START_DELAY = 1.2       # seconds: let the core lanes' searches take their tokens first
MAX_PROVIDERS = 10           # provider sites read per hunt
MAX_LISTICLES = 3            # articles mined per hunt
LOCAL_RESERVE = 3            # provider slots kept for the asked-for country's own sites
MAX_NAMES_PER_LISTICLE = 8   # numbered headings turned into domains per article
FREE_CONCURRENCY = 6
FETCH_TIMEOUT = 5.0
DEFAULT_LANE_S = 22.0        # without a hunt deadline
SEARCH_N = 15

# Tests inject httpx.MockTransport here.
_transport: httpx.AsyncBaseTransport | None = None

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-GB,en;q=0.9,fi;q=0.8,de;q=0.7"}

# Listicles the core lanes skipped as 'not a shop' during this hunt (agora.discover -> note_listicle).
# The hunt sets a fresh list; None = nobody is collecting.
LISTICLES: contextvars.ContextVar[list[dict[str, str]] | None] = contextvars.ContextVar(
    "agora_longtail_listicles", default=None)


def note_listicle(url: str, title: str = "", snippet: str = "") -> None:
    """agora.discover calls this for a skipped page; kept only when it looks like a 'best X' article."""
    bag = LISTICLES.get()
    if bag is None or not is_listicle(url, title):
        return
    if all(x["url"] != url for x in bag):
        bag.append({"url": url, "title": title, "snippet": snippet[:300]})


# --------------------------------------------------------------------------- does the lane apply?

# local home services already have the core service lane (directories, local rates): no long tail there
LOCAL_TRADES = {"cleaning", "plumbing", "electrician", "moving", "painting", "handyman", "haircut", "childcare",
                "gardening", "massage", "car wash", "tyre change", "pet care", "laundry", "physiotherapy", "repair",
                "gunsmith"}
B2B_WORDS = re.compile(
    r"\b(?:subscription|saas|software|app|agency|agencies|studio|freelanc\w*|consult\w*|retainer|productized|"
    r"design\w*|develop\w*|web\s?site|webflow|wordpress|shopify|seo|marketing|copywrit\w*|content|branding|logo|"
    r"bookkeep\w*|accounting|accountant|payroll|tax|legal|lawyer|translation|translator|hosting|vpn|"
    r"video\s?edit\w*|animation|illustrat\w*|ux|ui|virtual assistant|recruit\w*|coaching|course|tutor\w*|"
    r"kirjanpito\w*|tilitoimisto|verkkosivu\w*|mainostoimisto|buchhaltung|steuerberat\w*|webdesign|"
    r"boekhoud\w*|redovisning|bokföring)\b", re.I)
TAXO_ROOTS = ("digital", "professional", "software", "finance", "education", "marketing", "business")


def _taxonomy() -> Any | None:
    try:
        from agora import taxonomy   # optional: built by another agent, may be missing
        return taxonomy
    except Exception:
        return None


def _names(need: Need, c: dict[str, Any]) -> bool:
    """The classified node shares a word with the need (agora.need._names_node); True when that check is gone."""
    try:
        from agora.need import _names_node
    except ImportError:
        return True
    return _names_node(need.thing or need.raw, c)


def classify(need: Need) -> dict[str, Any] | None:
    """-> {id, label, labels{lang: label}, synonyms, kind, path} when the need is a digital / B2B service or
    subscription the long tail can price, else None. Taxonomy first (guarded), then words."""
    text = " ".join([need.thing, need.raw])
    try:
        from agora.discover import service_name
        if service_name(need) in LOCAL_TRADES:
            return None
    except Exception:
        pass
    cat = getattr(need, "category", None) or {}
    if cat.get("kind") == "service" and cat.get("path_ids"):
        try:   # a local-service node of the tree (a gunsmith, a tailor): rates and directories, not retainers
            from agora.need import priced_per_period
            if not priced_per_period(need):
                return None
        except Exception:
            pass
    words = bool(B2B_WORDS.search(text))
    if cat.get("id") and cat.get("kind") in ("service", "digital"):
        # the hunt already knows the node (from the tree, or need.categorize picked the service node for
        # 'unlimited graphic design subscription'): never re-classify into a software shelf
        return {"id": cat.get("id"), "label": cat.get("label") or need.thing, "labels": cat.get("labels") or {},
                "synonyms": list(cat.get("synonyms") or [])[:12], "kind": cat.get("kind"),
                "path": list(cat.get("path") or []), "via": "category"}
    tx = _taxonomy()
    c = None
    if tx is not None:
        try:
            c = tx.classify(need.raw or need.thing)
        except Exception:
            c = None
    if c and not _names(need, c) and not words:
        c = None                 # eval r1: 'gift for mom' -> 'Financial, Tax & Accounting Software' (no shared word)
    if c and c.get("kind") in ("service", "digital") and (c.get("confidence") or 0) >= 0.3:
        root = " ".join(str(p) for p in c.get("path_ids") or c.get("path") or []).lower()
        local = bool(c.get("lanes")) and any(r in root for r in ("home-services", "trades", "beauty", "health"))
        if not local or words:
            return {"id": c.get("id"), "label": c.get("label") or need.thing, "labels": c.get("labels") or {},
                    "synonyms": list(c.get("synonyms") or [])[:12], "kind": c.get("kind"),
                    "path": list(c.get("path") or []), "via": "taxonomy"}
    if words or need.kind == "service":
        return {"id": None, "label": need.thing, "labels": {}, "synonyms": [], "kind": "service", "path": [],
                "via": "words"}
    return None


# --------------------------------------------------------------------------- intent queries

ROLE_TO_WORK = {"developer": "development", "designer": "design", "accountant": "accounting",
                "bookkeeper": "bookkeeping", "copywriter": "copywriting", "translator": "translation",
                "illustrator": "illustration", "editor": "editing", "marketer": "marketing", "consultant": "consulting",
                "photographer": "photography", "lawyer": "legal"}
CORE_STOP = re.compile(r"\b(?:unlimited|subscriptions?|services?|provider|company|companies|agency|agencies|"
                       r"monthly|cheap(?:est)?|best|affordable|online|plans?|pricing|prices?|"
                       r"for (?:a |my )?(?:small )?(?:business(?:es)?|startups?|companies|company))\b", re.I)
LOCAL_PRICE = {"fi": "hinnasto", "de": "Preise", "sv": "priser", "se": "priser", "nl": "prijzen", "fr": "tarifs",
               "da": "priser", "dk": "priser", "nb": "priser", "no": "priser", "es": "precios", "it": "prezzi",
               "pl": "cennik", "pt": "preços", "cs": "ceník", "cz": "ceník", "et": "hinnakiri"}
LOCAL_MONTH = {"fi": "kuukausihinta", "de": "pro Monat", "sv": "per månad", "nl": "per maand", "fr": "par mois",
               "da": "pr. måned", "es": "al mes", "it": "al mese", "pl": "miesięcznie"}


def core_of(need: Need) -> str:
    """'unlimited graphic design subscription' -> 'graphic design'; 'web developer for small business' ->
    'web development'."""
    t = CORE_STOP.sub(" ", need.thing or need.raw)
    t = re.sub(r"\s+", " ", t).strip(" -,")
    words = [ROLE_TO_WORK.get(w.lower(), w) for w in t.split()]
    return " ".join(words).strip() or need.thing


def _lang_for(need: Need) -> tuple[str | None, str | None]:
    """(country code, ISO language) of the asked-for place; (None, None) when none."""
    try:
        from agora import discover, places
        from agora.need import national_service
        cc = discover.country_of(need)
        if not cc and national_service(need):
            cc = discover.home_country()      # insurance / loans / energy: bought at home (eval r2)
            return (cc, places.LANGUAGE.get(cc or "")) if cc else (None, None)
        if not cc:
            return None, None
        return cc, places.language_for(need.where, cc)
    except Exception:
        return None, None


def intent_queries(need: Need, cat: dict[str, Any] | None = None) -> list[tuple[str, str | None, str]]:
    """3-5 (query, country filter, purpose) variants: how providers describe themselves, a listicle hunt,
    and the local language. Purpose: provider | listicle | local."""
    cat = cat or {}
    core = core_of(need)
    raw = need.thing.lower()
    sub = "subscription" in raw or "unlimited" in raw or cat.get("kind") == "digital"
    cc, lang = _lang_for(need)
    out: list[tuple[str, str | None, str]] = []
    try:
        from agora.need import national_service
        national = national_service(need)
    except ImportError:
        national = False
    if national and cc:
        # insurance, loans, energy: no agencies or retainers (eval r2: 'car insurance agency monthly retainer
        # price'); the country's own providers in its language, and a comparison article to mine
        label = (cat.get("labels") or {}).get(lang or "") or ""
        out = [(f"{label} {LOCAL_PRICE.get(lang or '', 'price')}".strip(), cc, "local")] if label else []
        try:
            from agora.marketplaces import NAMES
            country = NAMES.get(cc, cc.upper())
        except ImportError:
            country = cc.upper()
        out.append((f"{core} price {need.where or country}", cc, "provider"))
        if label:
            out.append((f"{label} vertailu" if lang == "fi" else f"{label} compare", cc, "listicle"))
        return [(re.sub(r"\s+", " ", q).strip(), c, p) for q, c, p in out]
    if sub:
        out.append((f"unlimited {core} subscription pricing per month", None, "provider"))
    else:
        out.append((f"{core} services pricing plans per month", cc, "provider"))
    out.append((f"{core} agency monthly retainer price", None, "provider"))
    out.append((f"productized {core} service pricing", None, "provider"))
    year = time.gmtime().tm_year
    out.append((f"best {core} {'subscription ' if sub else ''}services {year} alternatives compared", None,
                "listicle"))
    if lang and lang != "en":
        label = (cat.get("labels") or {}).get(lang) or ""
        if label:
            out.insert(1, (f"{label} {LOCAL_PRICE.get(lang, '')}".strip(), cc, "local"))
        elif where := (need.where or ""):
            out.insert(1, (f"{core} {where} {LOCAL_PRICE.get(lang, 'price')}", cc, "local"))
    seen: set[str] = set()
    uniq = []
    for q, c, p in out:
        q = re.sub(r"\s+", " ", q).strip()
        if q.lower() not in seen:
            seen.add(q.lower())
            uniq.append((q, c, p))
    return uniq[:5]


# --------------------------------------------------------------------------- pages: listicle / provider / junk

LISTICLE_TITLE = re.compile(
    r"\b(?:best|top|leading|beste|parhaat|bästa|meilleurs?|migliori|mejores)\s+(?:\d+\s+)?\w+|"
    r"\b\d+\s+(?:best|top|great|leading)\b|\balternatives?\b|\bcompetitors\b|\bcompared\b|\bvs\.?\b|"
    r"\bversus\b|\branked\b|\breviewed\b|\bvaihtoehdot\b|\bvertailu\b|\bvergleich\b", re.I)
LISTICLE_PATH = re.compile(r"/(?:blog|blogs|articles?|guides?|news|resources|insights|post|posts|learn|magazine)/"
                           r"|alternatives|best-|top-\d+|-vs-", re.I)


def is_listicle(url: str, title: str = "") -> bool:
    """A 'best X / top X / alternatives to X' article (many providers named on one page)."""
    if title and LISTICLE_TITLE.search(title):
        return True
    path = urlsplit(url).path.lower()
    return bool(re.search(r"alternatives|(?:^|/)best-|top-\d+|-vs-|competitors", path))


SOCIAL = ("facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com", "youtu.be",
          "tiktok.com", "pinterest.", "reddit.com", "medium.com", "t.me", "wa.me", "threads.net", "github.com",
          "discord.gg", "discord.com", "behance.net", "dribbble.com", "vimeo.com", "producthunt.com", "substack.com")
TECH = ("google.", "gstatic.com", "googleapis.com", "googletagmanager.com", "doubleclick.net", "cloudflare.com",
        "jsdelivr.net", "unpkg.com", "website-files.com", "webflow.com", "wixstatic.com", "wix.com", "squarespace.com",
        "shopify.com", "wordpress.org", "wordpress.com", "wp.com", "gravatar.com", "typeform.com", "calendly.com",
        "hubspot.com", "hsforms.", "intercom.io", "stripe.com", "apple.com", "microsoft.com", "w3.org", "schema.org",
        "gmpg.org", "openai.com", "claude.ai", "anthropic.com", "perplexity.ai", "bing.com", "duckduckgo.com",
        "amazonaws.com", "cloudfront.net", "fonts.", "cdn.", "visualwebsiteoptimizer.com", "heyflow.com",
        "bit.ly", "linktr.ee", "trustpilot.com", "g2.com", "capterra.", "clutch.co", "sourceforge.net", "goodfirms.co",
        "getapp.", "softwareadvice.", "trustradius.com", "crunchbase.com", "glassdoor.", "indeed.", "wikipedia.org")
MEDIA = ("forbes.com", "nytimes.com", "theguardian.com", "bbc.", "cnn.com", "techcrunch.com", "wired.com",
         "businessinsider.com", "entrepreneur.com", "inc.com", "fastcompany.com", "hbr.org", "mckinsey.com",
         "bls.gov", "statista.com", "zapier.com", "hubspot.com", "shopify.com", "semrush.com", "ahrefs.com",
         "yle.fi", "hs.fi", "is.fi", "iltalehti.fi", "kauppalehti.fi", "spiegel.de", "zeit.de")
# freelance marketplaces / directories: the core lanes cover them; the long tail is about OWN sites
PLATFORMS = ("fiverr.com", "upwork.com", "freelancer.", "peopleperhour.com", "99designs.", "toptal.com",
             "malt.", "designcrowd.", "guru.com", "bark.com", "yelp.", "sortlist.", "designrush.com", "dribbble.com",
             "contra.com", "workana.com", "twago.", "amazon.", "ebay.", "etsy.com", "tori.fi", "kleinanzeigen.")
AFFILIATE = re.compile(r"[?&](?:ref|via|aff|affiliate|aff_id|partner|fpr|utm_source|irclickid|clickid)=|"
                       r"/(?:go|out|recommends|refer|visit|aff|affiliate|link)/|"
                       r"(?:shareasale|impact\.com|partnerstack|awin1|pntra|tkqlhce|anrdoezrs|sjv\.io|"
                       r"pxf\.io|prf\.hn|fpr\.io|rewardful|lemonsqueezy\.com/affiliates)", re.I)


def host(url: str) -> str:
    h = urlsplit(url if "//" in url else "//" + url).netloc.lower().split("@")[-1].split(":")[0]
    return h[4:] if h.startswith("www.") else h


def registrable(url_or_host: str) -> str:
    try:
        from agora.trust import registrable as reg
        r = reg(url_or_host)
        if r:
            return r
    except Exception:
        pass
    h = host(url_or_host)
    parts = h.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _match(dom: str, pats: tuple[str, ...]) -> bool:
    for p in pats:
        if p.endswith("."):
            if dom.startswith(p) or ("." + p) in dom:
                return True
        elif dom == p or dom.endswith("." + p):
            return True
    return False


def junk_domain(dom: str) -> str | None:
    """Why this domain is never a long-tail provider (social, tech/CDN, media, review site, platform)."""
    if not dom or "." not in dom:
        return "no domain"
    if _match(dom, SOCIAL):
        return "social"
    if _match(dom, TECH):
        return "tech or review site"
    if _match(dom, MEDIA):
        return "media"
    if _match(dom, PLATFORMS):
        return "marketplace (core lanes)"
    try:
        from agora.discover import JUNK_DOMAINS, dom_match, JOB_DOMAINS
        if any(dom_match(dom, d) for d in JUNK_DOMAINS + JOB_DOMAINS):
            return "not a provider"
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- fetch + text

async def fetch(url: str, timeout: float = FETCH_TIMEOUT) -> tuple[int, str, str]:
    """Free GET like a browser -> (status, html, final url). Offline without a test transport: (0, '', url)."""
    if contextdev.offline() and _transport is None:
        return 0, "", url
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=timeout, follow_redirects=True,
                                     headers=HEADERS) as c:
            r = await c.get(url)
    except (httpx.HTTPError, ValueError):
        return 0, "", url
    ctype = r.headers.get("content-type", "")
    if ctype and "html" not in ctype and "xml" not in ctype:
        return r.status_code, "", str(r.url)
    return r.status_code, r.text[:2_500_000], str(r.url)


def blocked(status: int, html: str) -> bool:
    if status in (401, 403, 429, 503) or (status == 0):
        return True
    head = html[:6000].lower()
    return len(html) < 20000 and any(m in head for m in ("captcha", "cf-chl", "are you a robot", "just a moment",
                                                          "access denied", "attention required"))


BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th", "section",
              "article", "header", "footer", "br", "table", "button", "a", "dt", "dd", "label", "figure", "main",
              "aside", "nav", "form", "blockquote", "summary", "details"}


def _doc(html: str) -> Any | None:
    try:
        import lxml.html
        return lxml.html.fromstring(html)
    except Exception:
        return None


def page_lines(html: str) -> list[str]:
    """Visible text as lines (one per block element), scripts and styles dropped."""
    doc = _doc(html)
    if doc is None:
        return []
    for bad in doc.xpath("//script|//style|//noscript|//svg|//template|//iframe"):
        bad.drop_tree()
    for el in doc.iter():
        if isinstance(el.tag, str) and el.tag.lower() in BLOCK_TAGS:
            el.text = "\n" + (el.text or "")
            el.tail = "\n" + (el.tail or "")
    text = doc.text_content()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    return [ln for ln in lines if ln]


def page_meta(html: str) -> dict[str, str]:
    doc = _doc(html)
    if doc is None:
        return {}
    def first(xp: str) -> str:
        v = doc.xpath(xp)
        return re.sub(r"\s+", " ", (v[0] if isinstance(v[0], str) else v[0].text_content())).strip() if v else ""
    return {"title": first("//title"), "site_name": first("//meta[@property='og:site_name']/@content"),
            "description": first("//meta[@name='description']/@content")
            or first("//meta[@property='og:description']/@content"), "h1": first("//h1")}


def links(html: str, base: str) -> list[tuple[str, str]]:
    """(absolute url, anchor text) of every <a href>."""
    doc = _doc(html)
    if doc is None:
        return []
    out = []
    for a in doc.xpath("//a[@href]"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        out.append((urljoin(base, href), re.sub(r"\s+", " ", a.text_content()).strip()))
    return out


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# --------------------------------------------------------------------------- listicle mining

HEADING_NAME = re.compile(r"^\s*(?:#\s*)?\d{1,2}\s*[.):\-–]\s*(.+)$")


def _clean_name(raw: str) -> str | None:
    s = re.split(r"\s+[–—|:-]\s+|:\s|\s\(", raw, maxsplit=1)[0].strip(" .:*#")
    s = re.sub(r"\s+(?:review|pricing|alternative)s?$", "", s, flags=re.I)
    if not (2 <= len(s) <= 40) or len(s.split()) > 4:
        return None
    if re.search(r"\b(?:how|why|what|when|which|faq|conclusion|summary|misconception|tips?|step)\b", s, re.I):
        return None
    return s


def listicle_names(html: str) -> list[str]:
    """Provider names from numbered headings ('3. ManyPixels', '#4 Kimp – best for video')."""
    doc = _doc(html)
    if doc is None:
        return []
    names: list[str] = []
    for h in doc.xpath("//h2|//h3|//h4"):
        m = HEADING_NAME.match(re.sub(r"\s+", " ", h.text_content()))
        if m and (n := _clean_name(m.group(1))) and n.lower() not in (x.lower() for x in names):
            names.append(n)
    return names


def markdown_names_and_links(md: str) -> tuple[list[str], list[tuple[str, str]]]:
    """The same from Context.dev markdown: '## 3. ManyPixels' headings and [text](url) links."""
    names: list[str] = []
    for ln in md.splitlines():
        m = re.match(r"^\s*#{1,4}\s*(.+)$", ln)
        if m and (h := HEADING_NAME.match(m.group(1))) and (n := _clean_name(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1",
                                                                                      h.group(1)))):
            if n.lower() not in (x.lower() for x in names):
                names.append(n)
    lk = [(u, t) for t, u in re.findall(r"\[([^\]]{0,80})\]\((https?://[^)\s]+)\)", md)]
    return names, lk


def provider_links(found: list[tuple[str, str]], page_url: str) -> list[str]:
    """Outbound provider home pages from an article's links: not the article's own site, no social / tech /
    media / platforms / affiliate redirects. Ordered by first appearance, one per registrable domain."""
    own = registrable(page_url)
    out: list[str] = []
    seen: set[str] = set()
    for url, _text in found:
        if not url.startswith("http"):
            continue
        dom = host(url)
        reg = registrable(dom)
        if reg == own or reg in seen or junk_domain(reg) or junk_domain(dom) or AFFILIATE.search(url):
            continue
        seen.add(reg)
        out.append(f"https://{dom}/")
    return out


def name_candidates(name: str) -> list[str]:
    slug = fold(name)
    if len(slug) < 3:
        return []
    return [f"https://{slug}.com/", f"https://{slug}.co/", f"https://{slug}.io/"]


def name_matches_page(name: str, url: str, html: str) -> bool:
    """A guessed home page belongs to the named provider: the name is in its domain, title or site name."""
    n = fold(name)
    meta = page_meta(html)
    hay = fold(" ".join([meta.get("title", ""), meta.get("site_name", ""), meta.get("h1", "")]))
    return bool(n) and (n in fold(registrable(url).split(".")[0]) and n in hay or n in hay[:200])


# --------------------------------------------------------------------------- pricing pages

PRICING_PATH = re.compile(r"(?:^|/)(?:pricing|plans?|prices?|price-list|hinnasto|hinnat|preise|preisliste|tarifs?|"
                          r"tarifas|tarieven|prijzen|priser|prislista|cennik|packages?|pakete|paketit|abonnement|"
                          r"subscriptions?|membership|rates)(?:[/#?.-]|$)", re.I)
PRICING_TEXT = re.compile(r"^(?:pricing|plans?|prices?|plans? (?:&|and) pricing|pricing (?:&|and) plans|hinnasto|"
                          r"hinnat|preise|tarifs?|tarifas|prijzen|priser|cennik|packages|pakete|paketit|"
                          r"see (?:pricing|plans)|view (?:pricing|plans)|abonnement)$", re.I)


def pricing_link(html: str, base: str) -> str | None:
    """The provider's own pricing page from its home page links ('#pricing' = the home page itself)."""
    own = registrable(base)
    best: tuple[int, str] | None = None
    for url, text in links(html, base):
        if registrable(url) != own:
            continue
        sp = urlsplit(url)
        frag = sp.fragment.lower()
        score = None
        if PRICING_TEXT.match(text or ""):
            score = 0
        elif PRICING_PATH.search(sp.path):
            score = 1
        elif frag and re.fullmatch(r"(?:pricing|plans|prices|hinnasto|preise)", frag):
            score = 2
        if score is None:
            continue
        if frag and sp.path in ("", "/") or url.split("#")[0].rstrip("/") == base.split("#")[0].rstrip("/"):
            target = base.split("#")[0]
        else:
            target = url.split("#")[0]
        if PRICING_PATH.search(urlsplit(target).path) and score > 0:
            score = 0.5  # type: ignore[assignment]
        if best is None or score < best[0]:
            best = (score, target)  # type: ignore[assignment]
    return best[1] if best else None


CUR_SYM = {"$": "USD", "us$": "USD", "€": "EUR", "£": "GBP", "chf": "CHF", "eur": "EUR", "usd": "USD", "gbp": "GBP",
           "sek": "SEK", "nok": "NOK", "dkk": "DKK", "zł": "PLN", "pln": "PLN", "czk": "CZK", "kč": "CZK"}
NUM = r"(\d{1,3}(?:[,.   ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
MONEY = re.compile(rf"(?<![\w$€£])(us\$|\$|€|£|chf|eur|usd|gbp)\s?{NUM}(?![\d%])|"
                   rf"(?<![\w.,]){NUM}\s?(€|eur\b|euro\b|kr\b|sek\b|nok\b|dkk\b|zł|pln\b|kč|czk\b|chf\b|\$|£|usd\b)",
                   re.I)
PERIODS: list[tuple[str, str]] = [
    ("month", r"mo|mos|month|months|mth|monthly|kk|kuukausi|kuukaudessa|kuussa|kuukaudelta|monat|monatlich|mon|"
              r"mois|mes|maand|månad|mån|mnd|måned|miesiąc|mies|měsíc"),
    ("year", r"yr|year|yearly|annually|annual|vuosi|vuodessa|vuodelta|jahr|jährlich|année|an|año|jaar|år|rok"),
    ("hour", r"h|hr|hrs|hour|hourly|tunti|tunnilta|t|stunde|std|heure|uur|timme|tim|time|godz"),
    ("job", r"project|projekti|projekt|projet|proyecto|one[- ]?time|once|kertamaksu|einmalig|kerta|site|website|"
            r"logo|page"),
]
PERIOD_AFTER = re.compile(
    r"^\s*(?:[*+]|\(?(?:\+|excl\.?|incl\.?|ex\.?|plus)\s*(?:vat|alv|moms|mwst|ust|btw|tva)[^/]{0,12}\)?|"
    r"(?:alv|vat)\s*0\s*%|usd|eur|€)?\s*(?:/\s*|per\s+|a\s+|an\s+|each\s+|pro\s+|par\s+|al\s+|i\s+|billed\s+)"
    r"(" + "|".join(f"(?P<{k}>{v})" for k, v in PERIODS) + r")\b", re.I)
PERIOD_WORD = re.compile(r"^\s*(?:billed\s+)?(monthly|yearly|annually|per\s+month|per\s+year|kuukaudessa|"
                         r"monatlich|jährlich|one[- ]time|one[- ]off|kertamaksu|einmalig)\b", re.I)
NAME_SKIP = re.compile(
    r"^(?:monthly|yearly|annual(?:ly)?|quarterly|weekly|billed .*|pay .*|save .*|\d+% off.*|.*\bdiscount\b.*|"
    r".*limited time.*|.*\bcancel\b.*|.*\bpause\b.*|most popular|popular|recommended|best value|best seller|"
    r"get started|start(?: now| today| free trial)?|choose(?: plan)?|book a call|contact(?: us| sales)?|buy now|"
    r"sign up|subscribe|features?|what'?s included|includes?|everything in .*|compare.*|from|starting at|"
    r"only|just|per month|/mo|/month|month|year|new|hot|sale|free trial|try .*|learn more|see more|show more|"
    r"starts?(?: at| from)?|starting(?: at| from)?|find the.*|sales tax|vat|alv|"
    r"suosituin|suositeltu|kuukausittain|vuosittain|beliebt|empfohlen|monatlich|jährlich|tilaa|aloita|osta)$",
    re.I)
BUTTON = re.compile(r"^(?:get started|start|choose|book a call|contact|buy|sign up|subscribe|learn more|"
                    r"see (?:more|all)|show (?:more|less)|try|join|select|tilaa|aloita|osta|jetzt)\b", re.I)


def _amount(s: str) -> float | None:
    s = s.replace(" ", " ").replace(" ", " ").strip()
    if re.fullmatch(r"\d{1,3}([ ,.]\d{3})+", s):
        s = re.sub(r"[ ,.]", "", s)
    elif re.fullmatch(r"\d{1,3}([ .]\d{3})+,\d{1,2}", s):
        s = re.sub(r"[ .]", "", s).replace(",", ".")
    elif re.fullmatch(r"\d{1,3}([ ,]\d{3})+\.\d{1,2}", s):
        s = re.sub(r"[ ,]", "", s)
    else:
        s = s.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _currency(tok: str, dom: str) -> str | None:
    t = tok.lower().strip()
    if t == "kr":
        return {"se": "SEK", "no": "NOK", "dk": "DKK"}.get(dom.rsplit(".", 1)[-1], "SEK")
    if t in ("euro",):
        return "EUR"
    return CUR_SYM.get(t)


def _period(after: str) -> str | None:
    m = PERIOD_AFTER.match(after)
    if m:
        for k, _ in PERIODS:
            if m.group(k):
                return k
    w = PERIOD_WORD.match(after)
    if w:
        x = w.group(1).lower()
        if "month" in x or "kuukau" in x or "monat" in x:
            return "month"
        if "year" in x or "annual" in x or "jähr" in x:
            return "year"
        return "job"
    return None


# a price quoted to compare with (hiring in-house, a freelancer, a competitor, 'the average agency'): not a plan
COMPARISON = re.compile(r"\b(?:in[- ]house|full[- ]time|freelancers?|hiring|hire an?|salary|salaries|traditional|"
                        r"typical|average|competitors?|other agencies|vs\.?|versus|compared|instead of|"
                        r"unpredictable|both include|you save|savings?)\b", re.I)


def _comparison(lines: list[str], i: int, before: str) -> bool:
    near = " ".join([before] + lines[max(0, i - 2):i])
    return bool(COMPARISON.search(near))


# words that head a pricing page's prose, never a plan's name ('Approach', 'Find the', 'Starts', 'Sales Tax')
NOT_A_NAME = re.compile(
    r"^(?:approach|overview|process|how it works|why\b.*|what\b.*|who\b.*|how\b.*|when\b.*|where\b.*|our\b.*|"
    r"your\b.*|the\b.*|a|an|this\b.*|that\b.*|these\b.*|those\b.*|find\b.*|get\b.*|see\b.*|compare\b.*|"
    r"pricing|prices?|plans?|costs?|fees?|rates?|packages?|options?|results?|benefits?|testimonials?|reviews?|"
    r"faq|faqs|questions?|support|guarantee|money[- ]back.*|total|subtotal|tax|taxes|sales tax|vat|per\b.*|"
    r"starts?|starting|from|only|just|save\b.*|billed\b.*|annual(?:ly)?|monthly|yearly|month|year|"
    r"in[- ]house\b.*|freelancers?|agency|agencies|employee|salary|hiring\b.*|both\b.*|unpredictable|average\b.*|"
    r"typical\b.*|traditional\b.*)$", re.I)
NAME_TAIL = re.compile(r"\b(?:the|a|an|of|to|for|and|or|with|your|our|at|from|per|in|on|by|is|are)$", re.I)


def valid_plan_name(name: str | None) -> bool:
    """A plan's name looks like one ('Monthly Club', 'Essentials', 'Starter Plan', 'Pro'), not page prose
    ('Approach', 'Find the', 'Both include the same', 'In-house designer')."""
    if not name:
        return False
    n = name.strip(" :-–|*")
    if not (2 <= len(n) <= 40) or len(n.split()) > 4 or not re.search(r"[A-Za-zÀ-ÿ]", n):
        return False
    if NAME_SKIP.match(n) or BUTTON.match(n) or NOT_A_NAME.match(n) or NAME_TAIL.search(n) or COMPARISON.search(n):
        return False
    if any(unicodedata.category(ch) == "So" for ch in n) or re.search(r"\(\d|\d{1,2}[-–:]\d{2}", n):
        return False          # '❇️ Support during (09-21)': opening hours / decoration, not a plan
    return not re.search(r"[.?!,;]$|[.?!]\s", n)


def _plan_name(lines: list[str], i: int, before: str) -> str | None:
    cands = [before] if before else []
    cands += [lines[j] for j in range(i - 1, max(-1, i - 7), -1)]
    for c in cands:
        c = c.strip(" :-–|")
        if not (2 <= len(c) <= 40) or len(c.split()) > 5 or MONEY.search(c) or c.endswith((".", "?", "!")) \
                or re.search(r"[.?!]\s|[→←»›]|\b(?:questions?|faq|estimate|quote|written|verified|author|read|case study|learn)\b", c, re.I):
            continue
        if not re.search(r"[A-Za-zÀ-ÿ]", c) or NAME_SKIP.match(c) or BUTTON.match(c):
            continue
        if COMPARISON.search(c):
            return "\x00comparison"      # the price under it is quoted to compare (in-house, 'both include')
        c = re.sub(r"\s+(?:at|from|for|only|just|starting|starts|ab|alk\.?|alkaen)$", "", c, flags=re.I).strip()
        if valid_plan_name(c):
            return c
    return None


def parse_plans_text(html: str, dom: str = "") -> list[dict[str, Any]]:
    """Plans from a pricing page's visible text: every price followed by a period ('$995 /mo', '49 €/kk',
    '€1,200 per project'), named by the nearest short heading above it, features = the short lines after.
    The first price per plan name wins (pages repeat plans for monthly / yearly toggles)."""
    lines = page_lines(html)
    plans: list[dict[str, Any]] = []
    names: set[str] = set()
    price_lines: list[int] = []
    for i, ln in enumerate(lines):
        for m in MONEY.finditer(ln):
            sym = m.group(1) or m.group(4)
            amt = _amount(m.group(2) or m.group(3) or "")
            if amt is None or amt <= 0 or amt > 1_000_000:
                continue
            after = ln[m.end():] + " " + " ".join(lines[i + 1:i + 3])
            per = _period(after)
            if per is None:
                continue
            before = ln[:m.start()].strip()
            if re.search(r"\b(?:save|off|was|instead of|regular|normally|säästä|statt)\W*$", before, re.I):
                continue
            if _comparison(lines, i, before):
                continue
            name = _plan_name(lines, i, before if len(before) <= 40 else "")
            if name == "\x00comparison":
                continue
            key = (name or f"plan {len(plans) + 1}").lower()
            if key in names:
                continue
            names.add(key)
            feats: list[str] = []
            for nxt in lines[i + 1:i + 14]:
                if MONEY.search(nxt) and _period(nxt[MONEY.search(nxt).end():]):   # type: ignore[union-attr]
                    break
                if 3 <= len(nxt) <= 90 and not BUTTON.match(nxt) and not NAME_SKIP.match(nxt) and not MONEY.search(nxt) \
                        and not PERIOD_AFTER.match(nxt) and nxt not in feats:
                    feats.append(nxt)
                if len(feats) >= 6:
                    break
            plans.append({"name": name or f"Plan {len(plans) + 1}", "price": amt,
                          "currency": _currency(sym, dom), "period": per, "features": feats})
            price_lines.append(i)
            break
    if any(not p["name"].startswith("Plan ") for p in plans):
        plans = [p for p in plans if not re.fullmatch(r"Plan \d+", p["name"])]   # stray prices in footers / FAQs
    return plans[:12]


def parse_plans_jsonld(html: str, url: str) -> list[dict[str, Any]]:
    """Plans from schema.org Offers on the page (Product / Service / SoftwareApplication with offers)."""
    try:
        import extruct
        data = extruct.extract(html, base_url=url, syntaxes=["json-ld"], uniform=True, errors="ignore")
    except Exception:
        return []
    plans: list[dict[str, Any]] = []

    def walk(node: Any, owner: str | None = None) -> None:
        if isinstance(node, list):
            for x in node:
                walk(x, owner)
            return
        if not isinstance(node, dict):
            return
        types = node.get("@type")
        types = {t.lower() for t in (types if isinstance(types, list) else [types]) if isinstance(t, str)}
        name = node.get("name") if isinstance(node.get("name"), str) else owner
        if types & {"offer", "aggregateoffer"}:
            spec = node.get("priceSpecification") or {}
            spec = spec[0] if isinstance(spec, list) and spec else spec
            price = node.get("price", node.get("lowPrice"))
            if price is None and isinstance(spec, dict):
                price = spec.get("price")
            amt = _amount(str(price)) if price is not None else None
            unit = " ".join(str(x) for x in ((spec.get("unitCode"), spec.get("unitText"), spec.get("billingDuration"),
                                              spec.get("referenceQuantity")) if isinstance(spec, dict) else ())
                            if x).lower()
            per = ("month" if re.search(r"\bmon\b|month|p1m", unit) else "year" if re.search(r"\bann\b|year|p1y", unit)
                   else "hour" if re.search(r"\bhur\b|hour", unit) else None)
            if amt and per:
                plans.append({"name": (node.get("name") if isinstance(node.get("name"), str) else owner) or "Plan",
                              "price": amt, "currency": node.get("priceCurrency")
                              or (spec.get("priceCurrency") if isinstance(spec, dict) else None),
                              "period": per, "features": []})
        for k, v in node.items():
            if k in ("offers", "@graph", "hasOfferCatalog", "itemListElement", "itemOffered", "makesOffer"):
                walk(v, name)
    walk(data.get("json-ld") or [])
    return plans[:12]


PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "provider": {"type": ["string", "null"]},
        "plans": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "price": {"type": ["number", "null"]},
            "currency": {"type": ["string", "null"]},
            "period": {"type": ["string", "null"], "enum": ["once", "hour", "month", "year", "project", None]},
            "features": {"type": "array", "items": {"type": "string"}},
        }, "required": ["name", "price", "currency", "period", "features"]}},
    },
    "required": ["plans"],
}
PLAN_INSTRUCTIONS = ("List the plans / packages on this pricing page exactly as stated: plan name, the price as a "
                     "number (the default billing shown, monthly when there is a toggle), its ISO currency, and what "
                     "the price is per (month, year, hour, project, or once). Up to 6 short feature lines per plan. "
                     "Skip add-ons, discounts and 'contact us' plans without a number. Do not invent prices.")


def normalize_plans(plans: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for p in plans or []:
        if not isinstance(p, dict):
            continue
        try:
            price = float(p.get("price"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        per = str(p.get("period") or "").lower()
        per = {"once": "job", "project": "job", "one-time": "job", "monthly": "month", "yearly": "year",
               "annual": "year", "hourly": "hour"}.get(per, per)
        if price <= 0 or per not in ("month", "year", "hour", "job"):
            continue
        name = str(p.get("name") or "").strip()
        if COMPARISON.search(name):
            continue          # 'In-house designer $8,400': a price quoted to compare (also in older registry rows)
        if not valid_plan_name(name) or len(name) > 60:
            name = f"Plan {len(out) + 1}"
        out.append({"name": name[:60], "price": price,
                    "currency": (str(p.get("currency") or "").upper() or None), "period": per,
                    "features": [str(f)[:120] for f in (p.get("features") or [])[:6]]})
    return out


def entry_plan(plans: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The plan to compare a provider by: the cheapest monthly one, else the cheapest of the commonest period."""
    if not plans:
        return None
    monthly = [p for p in plans if p["period"] == "month"]
    if monthly:
        return min(monthly, key=lambda p: p["price"])
    counts: dict[str, int] = {}
    for p in plans:
        counts[p["period"]] = counts.get(p["period"], 0) + 1
    per = max(counts, key=lambda k: counts[k])
    return min((p for p in plans if p["period"] == per), key=lambda p: p["price"])


def _to_eur(amount: float, currency: str | None) -> float | None:
    if (currency or "EUR").upper() == "EUR":
        return round(amount, 2)
    try:
        from agora import fx
        v = fx.to_eur(amount, currency)
        return round(v, 2) if v is not None else None
    except Exception:
        return None


def plans_to_offers(plans: list[dict[str, Any]], url: str, *, provider: str, tagline: str = "",
                    read_via: str = "longtail_free", found_via: str = "", category: str | None = None,
                    all_plans: bool = False) -> list[Offer]:
    """Plans -> Offers (condition 'service', unit = the plan's period). One offer per provider (its entry plan)
    unless `all_plans`; every plan stays in raw['plans'] so nothing read is lost."""
    plans = normalize_plans(plans)
    picked = plans if all_plans else [p for p in [entry_plan(plans)] if p]
    dom = host(url)
    out = []
    for p in picked:
        title = f"{provider} {p['name']}".strip()
        if tagline and fold(tagline) not in fold(title):
            title = f"{title} – {tagline}"
        others = [f"{q['name']}: {q['price']:g} {q['currency'] or ''}/{q['period']}".replace(" /", "/")
                  for q in plans if q is not p]
        out.append(Offer(
            url=url, source=dom, title=title[:200], price=p["price"], currency=p["currency"] or None,
            price_eur=_to_eur(p["price"], p["currency"]), condition="service", seller=provider,
            unit=p["period"], read_via=read_via,
            raw={"longtail": True, "plan": p, "plans": plans, "period": p["period"], "provider": provider,
                 "found_via": found_via, "category": category, "other_prices": others,
                 "features": p["features"], "step": "longtail_plans"}))
    return out


def provider_name(meta: dict[str, str], url: str) -> str:
    """'Designjoy - Design as a Subscription' -> 'Designjoy'; else the domain's first label."""
    for cand in (meta.get("site_name"), meta.get("title")):
        if cand:
            first = re.split(r"\s+[|–—:-]\s+|\s*\|\s*", cand)[0].strip()
            if 2 <= len(first) <= 40 and len(first.split()) <= 4 and not PRICING_TEXT.match(first):
                return first
    t = meta.get("title") or ""
    parts = [x.strip() for x in re.split(r"\s+[|–—-]\s+", t) if x.strip()]
    if len(parts) > 1 and 2 <= len(parts[-1]) <= 30:
        return parts[-1]
    lab = registrable(url).split(".")[0]
    return lab[:1].upper() + lab[1:]


def relevant(meta: dict[str, str], lines: list[str], need: Need, cat: dict[str, Any] | None) -> bool:
    """The provider's page is about the need: a core word (or a taxonomy label / synonym) in its title,
    description, h1 or the first lines."""
    hay = " ".join([meta.get("title", ""), meta.get("description", ""), meta.get("h1", ""),
                    meta.get("site_name", "")] + lines[:60]).lower()
    words = [w for w in re.findall(r"[a-zäöåüß]{4,}", core_of(need).lower())]
    stems = {w[:6] for w in words}
    for lab in list((cat or {}).get("labels", {}).values()) + list((cat or {}).get("synonyms") or []):
        stems |= {w[:6] for w in re.findall(r"[a-zäöåüß]{5,}", str(lab).lower())}
    return any(s in hay for s in stems) if stems else True


# --------------------------------------------------------------------------- the lane

class _Lane:
    def __init__(self, need: Need, cat: dict[str, Any], deadline: float, seen_urls: set[str] | None,
                 paid_max: int) -> None:
        self.need, self.cat, self.deadline = need, cat, deadline
        self.seen_urls = seen_urls if seen_urls is not None else set()
        self.paid_max, self.paid = paid_max, 0
        self.t_start = time.monotonic()
        self.q: asyncio.Queue[Any] = asyncio.Queue()
        self.domains: set[str] = set()         # registrable domains claimed by this lane
        self.mined: set[str] = set()
        self.sem = asyncio.Semaphore(FREE_CONCURRENCY)
        self.tasks: set[asyncio.Task[Any]] = set()
        self.strong: list[tuple[str, str]] = []    # (registrable, home url) of providers with prices
        self.unpriced: list[tuple[str, str, str]] = []   # (pricing url, provider, found_via): extract candidates
        self.stats = {"providers": 0, "priced": 0, "listicles": 0, "paid": 0, "registry": 0}
        self.similar_done = False
        # a service / digital need has no used or refurbished marketplace lanes: the shared bucket's tokens are
        # this lane's to use from the start, and look-alikes start as soon as one provider shows prices
        try:
            from agora.need import is_service
            self.early = is_service(need)
        except ImportError:
            self.early = False
        self.cc = _lang_for(need)[0]
        try:
            from agora.need import national_service
            self.national = national_service(need)
        except ImportError:
            self.national = False
        self.score: dict[str, int] = {}          # registrable -> core words its page title names
        words = re.findall(r"[a-zäöåüß]{4,}", " ".join([core_of(need)] + [str(v) for v in
                                                       (cat.get("labels") or {}).values()]).lower())
        self.stems = {w[:6] for w in words}
        from agora import longtail_store
        self.store = longtail_store
        self.terms = longtail_store.terms_of(" ".join([core_of(need), str(cat.get("label") or "")]))

    # ---- helpers
    def about(self, text: str) -> int:
        """How many of the need's core words (6-letter stems, taxonomy labels too) `text` names."""
        low = (text or "").lower()
        return sum(1 for st in self.stems if st in low)

    def left(self) -> float:
        return self.deadline - time.monotonic()

    def ev(self, type_: str, **data: Any) -> Event:
        return Event(type_, data, 0)

    async def put(self, item: Any) -> None:
        await self.q.put(item)

    def spawn(self, coro: Any) -> None:
        t = asyncio.ensure_future(coro)
        self.tasks.add(t)

    async def paid_slot(self, spare: float) -> bool:
        """Take one of this lane's paid requests once the shared bucket has `spare` tokens left
        (the core lanes keep theirs). False when the lane's share or the time is used up."""
        if self.paid >= self.paid_max:
            return False
        if contextdev.offline():
            self.paid += 1
            self.stats["paid"] = self.paid
            return True
        from agora.discover import tokens_available
        delay = (0.0 if self.early else PAID_START_DELAY) - (time.monotonic() - self.t_start)
        if delay > 0:
            await asyncio.sleep(delay)
        while self.left() > 6.0:
            if self.paid >= self.paid_max:
                return False
            if tokens_available() >= spare:
                self.paid += 1
                self.stats["paid"] = self.paid
                return True
            await asyncio.sleep(0.5)
        return False

    def claim(self, url: str) -> bool:
        reg = registrable(url)
        if reg in self.domains or junk_domain(reg) or junk_domain(host(url)):
            return False
        if len(self.domains) >= MAX_PROVIDERS + MAX_LISTICLES + 2:
            return False
        self.domains.add(reg)
        return True

    # ---- providers
    async def provider(self, home: str, via: str, title: str = "", origin: str | None = None,
                       pricing_hint: str | None = None) -> None:
        """Read one provider: home page -> pricing page -> plans (free) -> Offer(s)."""
        if self.stats["providers"] >= MAX_PROVIDERS or self.left() < 2.0:
            return
        if self.cc and not self.is_local(home) and self.stats["providers"] >= MAX_PROVIDERS - LOCAL_RESERVE:
            return               # the last slots are kept for providers in the asked-for country
        self.stats["providers"] += 1
        await self.put(self.ev("source", url=pricing_hint or home, domain=host(home), lane="longtail", via=via,
                               title=title, **({"from": origin} if origin else {})))
        async with self.sem:
            plans, purl, meta, why = await self._read_provider(home, pricing_hint)
        name = provider_name(meta, purl or home)
        reg = registrable(home)
        if plans:
            tag = meta.get("title", "")
            offers = plans_to_offers(plans, purl or home, provider=name, tagline=tag, found_via=via,
                                     category=self.cat.get("id"))
            for o in offers:
                o.raw["page_title"] = tag
                o.raw["description"] = meta.get("description", "")
            self.stats["priced"] += 1
            self.strong.append((reg, home))
            self.score[reg] = self.about(" ".join([meta.get("title", ""), meta.get("h1", ""),
                                                   meta.get("description", "")]))
            if self.early and not self.similar_done:
                self.spawn(self.similar())      # look-alikes of the first priced provider, right away
            for o in offers:
                await self.put(o)
        else:
            if why == "not about the need":
                await self.put(self.ev("skip", url=purl or home, reason=f"long tail: {why}", lane="longtail"))
                return
            if purl and why != "blocked" or why == "blocked":
                self.unpriced.append((purl or home, name, via))
            await self.put(self.ev("skip", url=purl or home, reason=f"long tail: {why}", lane="longtail"))
        await asyncio.to_thread(self._save, reg, name, home, purl, via, plans)

    def _save(self, reg: str, name: str, home: str, purl: str | None, via: str, plans: list[dict[str, Any]]) -> None:
        try:
            self.store.save_provider(reg, name=name, category_id=self.cat.get("id"),
                                     category=str(self.cat.get("label") or ""), terms=self.terms, home_url=home,
                                     pricing_url=purl, found_via=via, plans=normalize_plans(plans))
        except Exception:
            pass

    async def _read_provider(self, home: str, hint: str | None) -> tuple[list[dict[str, Any]], str | None,
                                                                           dict[str, str], str]:
        tmo = max(1.0, min(FETCH_TIMEOUT, self.left() - 1.0))
        first = hint or home
        status, html, final = await fetch(first, tmo)
        if blocked(status, html) or not html:
            return [], first, {}, "blocked" if status else "unreachable"
        meta = page_meta(html)
        lines = page_lines(html)
        if not relevant(meta, lines, self.need, self.cat):
            return [], final, meta, "not about the need"
        plans = parse_plans_jsonld(html, final) or parse_plans_text(html, host(final))
        if plans:
            return plans, final, meta, ""
        purl = pricing_link(html, final)
        if purl is None and not PRICING_PATH.search(urlsplit(final).path):
            purl = urljoin(final, "/pricing")
        if purl and purl.rstrip("/") != final.rstrip("/") and self.left() > 1.5:
            s2, h2, f2 = await fetch(purl, max(1.0, min(FETCH_TIMEOUT, self.left() - 1.0)))
            if h2 and not blocked(s2, h2) and s2 < 400:
                m2 = page_meta(h2)
                plans = parse_plans_jsonld(h2, f2) or parse_plans_text(h2, host(f2))
                if plans:
                    meta = {**meta, **{k: v for k, v in m2.items() if k == "title" and v}}
                    return plans, f2, meta, ""
                return [], f2, meta, "no plan prices on the pricing page"
            if purl.endswith("/pricing") and not pricing_link(html, final):
                return [], final, meta, "no pricing page found"
            return [], purl, meta, "pricing page unreadable"
        return [], final, meta, "no plan prices on the page"

    # ---- listicles
    async def listicle(self, url: str, title: str, via: str) -> None:
        key = url.split("#")[0].rstrip("/")
        if key in self.mined or self.stats["listicles"] >= MAX_LISTICLES or self.left() < 3.0:
            return
        if junk_domain(registrable(url)) or (title and not self.about(title)):
            self.mined.add(key)      # 'refurbished vs new laptops' from a core lane is not about this need
            return
        self.mined.add(key)
        self.stats["listicles"] += 1
        await self.put(self.ev("source", url=url, domain=host(url), lane="longtail", via="listicle", title=title,
                               listicle=True))
        async with self.sem:
            status, html, final = await fetch(url, max(1.0, min(FETCH_TIMEOUT, self.left() - 1.0)))
        names: list[str] = []
        found: list[tuple[str, str]] = []
        how = "free"
        if html and not blocked(status, html):
            names, found = listicle_names(html), links(html, final)
        elif await self.paid_slot(LATER_PAID_SPARE):
            how = "contextdev_markdown"
            try:
                from agora import reader
                md, _ = await reader.scrape_markdown(url, None)
                names, found = markdown_names_and_links(md)
            except Exception:
                names, found = [], []
        homes = self.local_first(provider_links(found, url))
        by_name: dict[str, str] = {}
        for n in names:            # a heading's own outbound link beats a guessed domain
            for h in homes:
                if fold(n) and fold(n) in fold(registrable(h)):
                    by_name[n] = h
        queued = 0
        for h in homes[:MAX_NAMES_PER_LISTICLE]:
            if self.claim(h):
                queued += 1
                self.spawn(self.provider(h, "listicle", origin=url))
        for n in names[:MAX_NAMES_PER_LISTICLE]:
            if n in by_name:
                continue
            self.spawn(self._guess(n, url))
        if not homes and not names:
            await self.put(self.ev("skip", url=url, reason=f"long tail: no providers named ({how} read)",
                                   lane="longtail"))

    async def _guess(self, name: str, origin: str) -> None:
        """'ManyPixels' -> manypixels.com / .co / .io, accepted when the page names itself so (free fetches)."""
        for cand in name_candidates(name):
            reg = registrable(cand)
            if reg in self.domains or self.left() < 3.0:
                return
            async with self.sem:
                status, html, final = await fetch(cand, max(1.0, min(3.5, self.left() - 2.0)))
            if html and not blocked(status, html) and status < 400 and name_matches_page(name, final, html):
                if self.claim(final):
                    await self.provider(f"https://{host(final)}/", "listicle", title=name, origin=origin)
                return

    # ---- searches
    async def search(self, query: str, country: str | None, purpose: str) -> list[dict[str, Any]]:
        spare = FIRST_PAID_SPARE if self.paid == 0 else LATER_PAID_SPARE
        if not await self.paid_slot(spare):
            return []
        try:
            from agora.discover import API_EXCLUDE
            excl = sorted(set(API_EXCLUDE) | {"fiverr.com", "upwork.com", "linkedin.com", "reddit.com"})[:30]
            return await asyncio.wait_for(contextdev.search(query, n=SEARCH_N, country=country, exclude_domains=excl),
                                          timeout=max(1.0, self.left() - 1.0))
        except Exception as exc:
            if not contextdev.offline():
                await self.put(self.ev("error", where="longtail", message=f"search '{query}': {str(exc)[:160]}"))
            return []

    def local_first(self, urls: list[Any], key: Any = lambda x: x) -> list[Any]:
        """A place was asked ('bookkeeping service finland'): that country's own sites first (stable order)."""
        if not self.cc:
            return list(urls)
        return sorted(urls, key=lambda x: not self.is_local(key(x)))

    def is_local(self, url: str) -> bool:
        return bool(self.cc) and (host(url).endswith("." + self.cc) or (self.cc == "gb" and host(url).endswith(".uk")))

    def take_results(self, results: list[dict[str, Any]], via: str, origin: str | None = None) -> None:
        for r in self.local_first(results, key=lambda r: str(r.get("url") or "")):
            url = str(r.get("url") or "")
            if not url.startswith("http"):
                continue
            title = str(r.get("title") or "")
            if is_listicle(url, title):
                self.spawn(self.listicle(url, title, via))
                continue
            if LISTICLE_PATH.search(urlsplit(url).path):
                continue                       # a blog post that is not a list: no provider, no price
            if getattr(self, "national", False) and self.cc and not self.is_local(url):
                continue                       # insurance / loans / energy: only the country's own providers
            if url in self.seen_urls or not self.claim(url):
                continue
            hint = url if PRICING_PATH.search(urlsplit(url).path) else None
            self.spawn(self.provider(f"https://{host(url)}/", via, title=title, origin=origin, pricing_hint=hint))

    async def similar(self) -> None:
        """Look-alikes of the first provider that showed prices."""
        if self.similar_done or not self.strong:
            return
        self.similar_done = True
        reg, home = max(self.strong, key=lambda x: (self.score.get(x[0], 0), -self.strong.index(x)))
        results: list[dict[str, Any]] = []
        via = "exa"
        try:
            from agora import exa
            if exa.enabled():
                results = await asyncio.wait_for(exa.find_similar(home, n=8, exclude_domains=sorted(self.domains)),
                                                 timeout=max(1.0, self.left() - 2.0))
        except Exception:
            results = []
        q = f"{reg} alternatives"
        if not results:
            via = "contextdev_search"
            results = await self.search(q, None, "similar")
        await self.put(self.ev("lane", lane="longtail", queries=[q if via != "exa" else f"like {reg}"],
                               via=via, similar_to=reg, step="similar"))
        self.take_results(results, "similar", origin=reg)

    async def extract_unpriced(self) -> None:
        """ONE paid JSON read of the most promising pricing page the free parse could not price."""
        for purl, name, via in self.unpriced:
            if not PRICING_PATH.search(urlsplit(purl).path):
                continue
            if not await self.paid_slot(LATER_PAID_SPARE):
                return
            try:
                data = await asyncio.wait_for(contextdev.extract(purl, PLAN_SCHEMA, PLAN_INSTRUCTIONS),
                                              timeout=max(1.0, self.left() - 0.5))
            except Exception:
                data = None
            plans = normalize_plans((data or {}).get("plans"))
            if plans:
                prov = (data or {}).get("provider") or name
                for o in plans_to_offers(plans, purl, provider=str(prov), read_via="contextdev_json", found_via=via,
                                         category=self.cat.get("id")):
                    await self.put(o)
                self.stats["priced"] += 1
                await asyncio.to_thread(self._save, registrable(purl), str(prov), f"https://{host(purl)}/", purl,
                                        via, plans)
            return

    # ---- registry
    async def registry(self) -> None:
        try:
            known = await asyncio.to_thread(self.store.providers_for, self.cat.get("id"), self.terms)
        except Exception:
            known = []
        for p in known:
            dom = p["domain"]
            if self.national and self.cc and not self.is_local(f"https://{dom}/"):
                continue      # an insurer abroad sells nothing here (eval r2: lemonade / progressive for a Finn)
            if not self.claim(f"https://{dom}/"):
                continue
            self.stats["registry"] += 1
            if p["fresh"] and p.get("pricing_url"):
                await self.put(self.ev("source", url=p["pricing_url"], domain=dom, lane="longtail", via="registry",
                                       title=p.get("name") or dom, cached=True))
                offers = plans_to_offers(p["plans"], p["pricing_url"], provider=p.get("name") or dom,
                                         read_via="longtail_registry", found_via="registry",
                                         category=self.cat.get("id"))
                for o in offers:
                    o.raw["registry_plans_at"] = p.get("plans_at")
                    # what the registry knows the provider for (it was matched by this category / these terms)
                    o.raw["description"] = " ".join(str(x) for x in [p.get("category") or "", *(p.get("terms") or [])])
                    await self.put(o)
                self.strong.append((dom, p.get("home_url") or f"https://{dom}/"))
                await asyncio.to_thread(self.store.save_provider, dom, terms=self.terms)
            else:
                self.spawn(self.provider(p.get("home_url") or f"https://{dom}/", "registry", title=p.get("name") or "",
                                         pricing_hint=p.get("pricing_url")))

    # ---- orchestration
    async def drive(self) -> None:
        plan = intent_queries(self.need, self.cat)
        await self.put(self.ev("lane", lane="longtail", queries=[q for q, _, _ in plan], via="search",
                               category=self.cat.get("label"), category_id=self.cat.get("id"),
                               kind=self.cat.get("kind"), paid_max=self.paid_max))
        await self.registry()
        # listicles the core lanes skipped, collected while they ran
        bag = LISTICLES.get()

        async def watch_bag() -> None:
            while self.left() > 4.0:
                for x in list(bag or []):
                    if x["url"].split("#")[0].rstrip("/") not in self.mined:
                        self.spawn(self.listicle(x["url"], x.get("title", ""), "core-skip"))
                await asyncio.sleep(0.5)
        if bag is not None:
            self.spawn(watch_bag())
        # paid #1: how providers describe themselves; #2: local language when asked, else the listicle query
        first = next((x for x in plan if x[2] == "provider"), plan[0])
        if self.early:
            # no marketplace lanes compete for tokens: the second query runs alongside the first
            second_q = next((x for x in plan if x[2] == "local"), None) or \
                next((x for x in plan if x[2] == "listicle"), None)
            got = await asyncio.gather(*(self.search(q, c, k) for q, c, k in [first] + ([second_q] if second_q else [])))
            for (q, _, _), res in zip([first] + ([second_q] if second_q else []), got):
                self.take_results(res, "search", origin=q)
            await self._settle(4.0)
            await self.similar()
            await self._settle(5.0)
            if not self.strong or self.stats["priced"] < 3:
                await self.extract_unpriced()
            await self._settle(None)
            return
        res = await self.search(first[0], first[1], first[2])
        self.take_results(res, "search", origin=first[0])
        await self._settle(4.0)
        # paid #2: the local-language query when a place was asked (its providers are what the person wants),
        # else the listicle query when nothing is priced yet
        second = next((x for x in plan if x[2] == "local"), None)
        if second is None and not self.strong:
            second = next((x for x in plan if x[2] == "listicle"), None)
        if second is not None:
            res = await self.search(second[0], second[1], second[2])
            self.take_results(res, "search", origin=second[0])
            await self._settle(4.0)
        await self.similar()
        await self._settle(5.0)
        if not self.strong or self.stats["priced"] < 3:
            await self.extract_unpriced()
        await self._settle(None)

    async def _settle(self, at_most: float | None) -> None:
        """Wait for the free work in flight (at most `at_most` s, never past the deadline)."""
        end = self.deadline - 0.3 if at_most is None else min(self.deadline - 0.3, time.monotonic() + at_most)
        while True:
            pending = [t for t in self.tasks if not t.done()]
            if not pending or time.monotonic() >= end:
                return
            await asyncio.wait(pending, timeout=max(0.05, end - time.monotonic()),
                               return_when=asyncio.FIRST_COMPLETED)
            if self.strong and not self.similar_done and at_most is not None:
                return


async def lane(need: Need, *, deadline: float | None = None, seen_urls: set[str] | None = None,
               paid_max: int | None = None, category: dict[str, Any] | None = None) -> AsyncIterator[Event | Offer]:
    """The long-tail lane: yields Events (lane, source, skip, error) and Offers (accept them like any read).
    `deadline` is a time.monotonic() value (the hunt's budget end); nothing is yielded after it."""
    if os.environ.get("AGORA_LONGTAIL", "1").strip().lower() in ("0", "off", "false", "no"):
        return
    cat = category if category is not None else await asyncio.to_thread(classify, need)
    if cat is None:
        return
    if need.kind == "product":
        try:
            from agora.need import product_head
            if product_head(need.thing):
                return          # 'laptop for web developer': an object, the core lanes price it
        except ImportError:
            pass
    if paid_max is None:
        paid_max = PAID_MAX + (1 if need.kind in ("service", "digital") else 0)   # no marketplace lanes to share with
    if need.kind == "product" and "service" not in need.conditions:
        need.conditions.append("service")     # provider plans are services: resolve must not mark them down
    end = deadline if deadline is not None else time.monotonic() + DEFAULT_LANE_S
    ln = _Lane(need, cat, end - 0.4, seen_urls, paid_max)
    driver = asyncio.ensure_future(ln.drive())
    t0 = time.monotonic()
    try:
        while True:
            if driver.done() and ln.q.empty() and all(t.done() for t in ln.tasks):
                break
            left = ln.deadline - time.monotonic()
            if left <= 0:
                break
            try:
                item = await asyncio.wait_for(ln.q.get(), timeout=min(left, 0.25))
            except TimeoutError:
                continue
            yield item
        while not ln.q.empty():          # whatever landed in the last moment
            item = ln.q.get_nowait()
            if isinstance(item, Offer) or item.type != "source":
                yield item
        yield Event("longtail", {**ln.stats, "domains": sorted(ln.domains),
                                 "priced_domains": [d for d, _ in ln.strong],
                                 "ms": int((time.monotonic() - t0) * 1000)}, 0)
    finally:
        driver.cancel()
        for t in ln.tasks:
            t.cancel()
