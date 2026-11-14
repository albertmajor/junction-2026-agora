"""Onboard the European source registry: find how to search each site, verify it, write agora/sources/registry.json.

    .venv/bin/python scripts/onboard_sources.py                 # free plain-HTTP pass over every seed (resumable)
    .venv/bin/python scripts/onboard_sources.py --only tori_fi  # one or a few keys (comma separated)
    .venv/bin/python scripts/onboard_sources.py --force         # re-check sources already in the registry
    .venv/bin/python scripts/onboard_sources.py --contextdev 20 # then <= N paid Context.dev checks (<= 3/min)
    .venv/bin/python scripts/onboard_sources.py --report        # print counts only

Polite: <= 4 sites at a time, one request at a time per site with a pause, 12 s timeouts, a normal browser UA,
robots.txt honoured (a search path it disallows is recorded but never fetched).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import os
import pathlib
import sys
import time
from collections import Counter
from urllib.parse import urlsplit

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agora import sources as S                     # noqa: E402
from agora.sources import discovery as D           # noqa: E402

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-GB,en;q=0.9,de;q=0.7,fr;q=0.6,fi;q=0.5"}
CONCURRENCY = 4
TIMEOUT = 12.0
PAUSE_S = 0.6                     # between two requests to the same site
MAX_TRIES = 8                     # candidate result pages fetched per site
MAX_BYTES = 2_500_000
CACHE = pathlib.Path(os.environ.get("ONBOARD_CACHE") or ROOT / ".cache" / "onboard")
SUMMARY = S.HERE / "registry_summary.csv"

# important sites, in order, for the few paid Context.dev checks (only if the plain fetch did not verify)
IMPORTANT = ("leboncoin.fr", "wallapop.com", "subito.it", "willhaben.at", "allegro.pl", "bol.com", "otto.de",
             "mediamarkt.de", "coolblue.nl", "zalando.de", "fnac.com", "darty.com", "kleinanzeigen.de",
             "marktplaats.nl", "vinted.fi", "vinted.de", "gigantti.fi", "elgiganten.se", "amazon.de", "olx.pl",
             "blocket.se", "finn.no", "dba.dk", "emag.ro", "alza.cz", "backmarket.de", "refurbed.de", "idealo.de",
             "ebay.de", "milanuncios.com", "werkspot.nl", "helpling.de", "my-hammer.de", "checkatrade.com")


def known_templates() -> dict[str, dict]:
    """Search templates already tested by hand (agora.marketplaces.SITES), by host."""
    from agora import marketplaces as M
    out = {}
    for s in M.SITES.values():
        out.setdefault(s.domain, {"template": s.template, "listing": s.listing, "itemlist": s.itemlist,
                                  "site_key": s.key})
    return out


def match_known(rec: dict, known: dict[str, dict]) -> dict | None:
    dom = rec["domain"]
    if dom in known:
        return known[dom]
    for host, k in known.items():
        if D.root_domain(host) == D.root_domain(dom) and host.split(".")[-1] == dom.split(".")[-1] \
                and not urlsplit(rec["home"]).path.strip("/"):
            return k
    return None


# --------------------------------------------------------------------------- polite fetching

class Fetcher:
    def __init__(self, client: httpx.AsyncClient):
        self.c = client
        self.requests = 0

    async def get(self, url: str) -> tuple[int, str, str]:
        """(status, text, final url); status 0 = network error."""
        self.requests += 1
        try:
            async with self.c.stream("GET", url) as r:
                ctype = r.headers.get("content-type", "")
                if ctype and not any(t in ctype for t in ("html", "xml", "text")):
                    return r.status_code, "", str(r.url)
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        break
                enc = r.encoding or "utf-8"
                try:
                    text = buf.decode(enc, errors="replace")
                except LookupError:
                    text = buf.decode("utf-8", errors="replace")
                return r.status_code, text, str(r.url)
        except (httpx.HTTPError, ValueError, UnicodeError):
            return 0, "", url
        finally:
            await asyncio.sleep(PAUSE_S)


def _cache_put(key: str, name: str, text: str) -> None:
    d = CACHE / key
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text[:MAX_BYTES])


def _fill(tpl: str, q: str) -> str:
    return S.build_url({"template": tpl}, q)


async def onboard(rec: dict, f: Fetcher, known: dict[str, dict]) -> dict:
    out = dict(rec)
    out.update({"status": "no_search", "reason": None, "template": None, "method": "get", "template_via": None,
                "free_fetch": False, "listing": None, "sample": [], "links": 0, "prices": 0, "itemlist": False,
                "jsonld_products": 0, "embedded_prices": 0, "next_data": False, "pagination": {}, "yield": 0.0,
                "robots_disallowed": [], "test_query": S.test_query(rec), "tried": 0, "contextdev": False,
                "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    home_url = rec["home"]
    p = urlsplit(home_url)
    origin = f"{p.scheme}://{p.netloc}"
    rs, rtext, _ = await f.get(origin + "/robots.txt")
    rules = D.parse_robots(rtext) if rs == 200 else []
    hs, home, final_home = await f.get(home_url)
    if hs == 0:
        alt = "https://" + rec["domain"] + "/"
        if alt != home_url:
            hs, home, final_home = await f.get(alt)
    if hs == 0 and not known_for(rec, known):
        out["reason"] = "unreachable"
        return out
    home_blocked = D.looks_blocked(hs, home)
    if hs == 200 and home:
        _cache_put(rec["key"], "home.html", home)
    base = final_home or home_url

    cands: list[tuple[str, str, str]] = []           # (template, via, method)
    k = known_for(rec, known)
    if k:
        cands.append((k["template"], "known", "get"))
    for osd in D.opensearch_links(home, base)[:2]:
        s2, xml, _ = await f.get(osd)
        tpl = D.parse_opensearch(xml) if s2 == 200 else None
        if tpl:
            cands.append((tpl, "opensearch", "get"))
    cands += [(t, "searchaction", "get") for t in D.searchaction_templates(home, base)]
    cands += [(d["template"], "form", d["method"]) for d in D.form_templates(home, base)[:2]]
    strong = len(cands)
    lang = (rec.get("languages") or ["en"])[0]
    cands += [(t, "pattern", "get") for t in D.common_templates(base if not urlsplit(home_url).path.strip("/")
                                                                 else home_url, lang)]
    seen: set[str] = set()
    best: tuple[float, dict, str, str, str] | None = None
    blocked_hits = 0
    found_strong: tuple[str, str, str] | None = None
    q = out["test_query"]
    for i, (tpl, via, method) in enumerate(cands):
        if tpl in seen or out["tried"] >= MAX_TRIES:
            continue
        seen.add(tpl)
        if not D.same_site(tpl, base) and via == "pattern":
            continue
        if i < strong and found_strong is None:
            found_strong = (tpl, via, method)
        if method == "post":
            continue
        url = _fill(tpl, q)
        if rules and not D.robots_allows(rules, url):
            if i < strong:                            # a pattern guess under a disallowed path proves nothing
                out["robots_disallowed"].append(tpl)
            continue
        out["tried"] += 1
        st, page, final = await f.get(url)
        if D.looks_blocked(st, page):
            blocked_hits += 1
            if via == "pattern" and found_strong is None:
                found_strong = (tpl, via, method)
            if blocked_hits >= 2:
                break
            continue
        if st != 200 or not page:
            continue
        ev = D.evaluate(page, final or url, q, home, service="service" in rec["lanes"] and not
                        set(rec["lanes"]) & {"new", "used", "refurb"})
        if via == "pattern" and not (_more_echo(page, home, q) and ev["links"] >= 3):
            continue                                  # a 200 that is not a results page (home, soft 404)
        if best is None or ev["yield"] > best[0]:
            best = (ev["yield"], ev, tpl, via, method)
            _cache_put(rec["key"], "results.html", page)
        if ev["verified"]:
            break
    if best is not None and best[1]["links"] < 5 and out["robots_disallowed"]:
        best = None                                   # the real search is the one robots.txt keeps us out of
    if best is not None:
        _, ev, tpl, via, method = best
        out.update({"template": tpl, "template_via": via, "method": method, "listing": ev["listing"],
                    "sample": ev["sample"], "links": ev["links"], "prices": ev["prices"], "itemlist": ev["itemlist"],
                    "jsonld_products": ev["jsonld_products"], "embedded_prices": ev["embedded_prices"],
                    "next_data": ev["next_data"], "pagination": ev["pagination"], "yield": ev["yield"]})
        if ev["verified"]:
            out["status"], out["free_fetch"] = "verified_free", True
            return out
        out["status"] = "search_found_unverified"
        out["reason"] = ("results drawn by JavaScript (prices in app state)" if ev["embedded_prices"] >= 5
                         else "results page without listing links for a plain fetch")
        return out
    if found_strong is not None or out["robots_disallowed"]:
        tpl, via, method = found_strong or (out["robots_disallowed"][0], "robots", "get")
        out.update({"template": tpl, "template_via": via, "method": method})
        if blocked_hits and tpl not in out["robots_disallowed"]:
            out["status"], out["reason"] = "blocked", "bot wall on the results page"
        else:
            out["status"] = "search_found_unverified"
            out["reason"] = ("search form posts (no GET URL)" if method == "post" else
                             "robots.txt disallows the search path" if tpl in out["robots_disallowed"]
                             else "results page did not load for a plain fetch")
        return out
    if home_blocked or blocked_hits:
        out["status"], out["reason"] = "blocked", "bot wall on the home page" if home_blocked else "bot wall"
        return out
    out["reason"] = "no search form, OpenSearch or SearchAction; common patterns failed"
    return out


def _more_echo(page: str, home: str, q: str) -> bool:
    w = (q.split() or [""])[0].lower()
    return bool(w) and page.lower().count(w) > home.lower().count(w) + 1


def known_for(rec: dict, known: dict[str, dict]) -> dict | None:
    return match_known(rec, known)


# --------------------------------------------------------------------------- paid checks (Context.dev)

async def contextdev_pass(reg: dict[str, dict], n: int) -> int:
    from agora import reader
    n = min(n, 20)
    order = {d: i for i, d in enumerate(IMPORTANT)}
    pool = [s for s in reg.values() if s["status"] in ("blocked", "search_found_unverified") and s.get("template")
            and s.get("method") == "get" and not s.get("contextdev_checked")]
    pool.sort(key=lambda s: (order.get(s["domain"], order.get(D.root_domain(s["domain"]), 999)), -len(s["lanes"])))
    pool = [s for s in pool if (s["domain"] in order or D.root_domain(s["domain"]) in order)][:n]
    spent = 0
    for i, s in enumerate(pool):
        if i:
            await asyncio.sleep(21)                   # <= 3 per minute
        url = S.build_url(s, s.get("test_query") or S.test_query(s))
        cc = next((c for c in s["countries"] if c != "eu"), None)
        try:
            md, page = await reader.scrape_markdown(url, cc)
        except Exception as e:                        # noqa: BLE001 - record and move on
            s["contextdev_checked"] = f"error: {type(e).__name__}"
            spent += 1
            continue
        spent += 1
        home = ""
        hp = CACHE / s["key"] / "home.html"
        if hp.exists():
            home = hp.read_text()
        ev = D.evaluate(page, url, s.get("test_query", ""), home)
        if ev["links"] < 5 and md:
            mdlinks = D.evaluate("".join(f'<a href="{u}">x</a>' for u in _md_links(md)), url, "", home)
            if mdlinks["links"] > ev["links"]:
                ev.update({k: mdlinks[k] for k in ("links", "listing", "sample")})
                ev["prices"] = len(D.PRICE.findall(md))
                ev["verified"] = ev["links"] >= 5 and ev["prices"] >= 3
        s["contextdev_checked"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        s["contextdev"] = True
        print(f"  contextdev {s['key']}: links={ev['links']} prices={ev['prices']} verified={ev['verified']}")
        if ev["verified"]:
            s.update({"status": "verified_contextdev", "listing": ev["listing"], "sample": ev["sample"],
                      "links": ev["links"], "prices": ev["prices"], "itemlist": ev.get("itemlist", False),
                      "yield": ev.get("yield", 0.0), "reason": "plain fetch blocked or JS; Context.dev scrape works"})
            if ev.get("pagination"):
                s["pagination"] = ev["pagination"]
    return spent


def _md_links(md: str) -> list[str]:
    import re
    return [m.group(1) for m in re.finditer(r"\]\((https?://[^\s)]+)", md)]


# --------------------------------------------------------------------------- registry io

def read_registry() -> dict:
    if S.REGISTRY.exists():
        return json.loads(S.REGISTRY.read_text())
    return {"meta": {}, "sources": []}


FIELDS_ORDER = ("key", "name", "domain", "home", "countries", "languages", "lanes", "categories", "kind", "status",
                "reason", "template", "method", "template_via", "free_fetch", "listing", "sample", "links", "prices",
                "itemlist", "jsonld_products", "embedded_prices", "next_data", "pagination", "yield",
                "robots_disallowed", "test_query", "tried", "contextdev", "contextdev_checked", "checked_at", "seed",
                "market", "group")


def write_registry(reg: dict[str, dict], meta: dict) -> None:
    rows = [{k: s.get(k) for k in FIELDS_ORDER if k in s} for s in sorted(reg.values(), key=lambda s: s["key"])]
    meta = dict(meta, counts=dict(Counter(s.get("status") for s in rows)), total=len(rows),
                updated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    tmp = S.REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps({"meta": meta, "sources": rows}, ensure_ascii=False, indent=1))
    tmp.replace(S.REGISTRY)
    with SUMMARY.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "name", "domain", "countries", "lanes", "categories", "kind", "status", "template",
                     "template_via", "free_fetch", "listing", "links", "prices", "itemlist", "yield", "reason"])
        for s in rows:
            w.writerow([s["key"], s["name"], s["domain"], " ".join(s["countries"]), " ".join(s["lanes"]),
                        " ".join(s["categories"]), s["kind"], s.get("status"), s.get("template") or "",
                        s.get("template_via") or "", s.get("free_fetch"), s.get("listing") or "", s.get("links"),
                        s.get("prices"), s.get("itemlist"), s.get("yield"), s.get("reason") or ""])


def report(reg: dict[str, dict], meta: dict) -> None:
    rows = list(reg.values())
    print(f"total {len(rows)}")
    print("status ", dict(Counter(s.get("status") for s in rows).most_common()))
    print("via    ", dict(Counter(s.get("template_via") for s in rows).most_common()))
    for lane in S.LANES:
        print(f"lane {lane:8}", dict(Counter(s.get("status") for s in rows if lane in s["lanes"]).most_common()))
    by_cc = Counter()
    free_cc = Counter()
    for s in rows:
        for c in s["countries"]:
            by_cc[c] += 1
            if s.get("status") == "verified_free":
                free_cc[c] += 1
    print("country (free/total):", ", ".join(f"{c} {free_cc[c]}/{n}" for c, n in by_cc.most_common()))
    print("contextdev requests spent:", meta.get("contextdev_requests", 0))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--contextdev", type=int, default=0)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    data = read_registry()
    meta = data.get("meta", {})
    reg = {s["key"]: s for s in data.get("sources", [])}
    seeds = {r["key"]: r for r in S.seed_records()}
    if a.report:
        report(reg, meta)
        return
    for k, r in seeds.items():                       # seed fields (lanes, cats ...) always follow the seed files
        if k in reg:
            reg[k].update({f: r[f] for f in ("name", "countries", "languages", "lanes", "categories", "kind", "home")})
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    todo = [r for k, r in seeds.items() if (k in only if only else (a.force or k not in reg))]
    if a.limit:
        todo = todo[: a.limit]
    known = known_templates()
    print(f"onboarding {len(todo)} of {len(seeds)} sources", flush=True)
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    t0 = time.time()
    limits = httpx.Limits(max_connections=CONCURRENCY * 2, max_keepalive_connections=CONCURRENCY)
    async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, connect=8.0), follow_redirects=True,
                                 headers=HEADERS, limits=limits, http2=False) as client:
        f = Fetcher(client)

        async def one(rec: dict) -> None:
            nonlocal done
            async with sem:
                try:
                    res = await asyncio.wait_for(onboard(rec, f, known), timeout=150)
                except (asyncio.TimeoutError, Exception) as e:   # noqa: BLE001 - one bad site never stops the run
                    res = dict(rec, status="no_search", reason=f"onboarding error: {type(e).__name__}",
                               template=None, test_query=S.test_query(rec))
            reg[rec["key"]] = res
            done += 1
            print(f"[{done}/{len(todo)}] {res['status']:24} {rec['key']:32} {res.get('template_via') or '':12} "
                  f"links={res.get('links', 0)} prices={res.get('prices', 0)} {res.get('reason') or ''}", flush=True)
            if done % 20 == 0:
                write_registry(reg, dict(meta, requests=meta.get("requests", 0) + f.requests))

        await asyncio.gather(*(one(r) for r in todo))
        meta["requests"] = meta.get("requests", 0) + f.requests
    meta["seconds_last_run"] = round(time.time() - t0)
    if a.contextdev:
        meta["contextdev_requests"] = meta.get("contextdev_requests", 0) + await contextdev_pass(reg, a.contextdev)
    write_registry(reg, meta)
    report(reg, meta)


if __name__ == "__main__":
    asyncio.run(main())
