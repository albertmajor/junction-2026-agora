"""Terminal door: `python -m agora "used sony a7 iii under 900"`

Events scroll live while the hunt runs, then a PRICE LADDER puts new / refurbished / used
on one EUR axis with the true cost per month next to every offer. Plain ANSI, no deps.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from agora.models import Event, to_dict

# ---------- colour ----------

_CODES = {"reset": 0, "bold": 1, "dim": 2, "red": 31, "green": 32, "yellow": 33, "blue": 34,
          "magenta": 35, "cyan": 36, "grey": 90, "bgreen": 92, "byellow": 93, "bcyan": 96, "bmagenta": 95}


class Paint:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text
        codes = ";".join(str(_CODES[s]) for s in styles)
        return f"\033[{codes}m{text}\033[0m"


def _visible_len(s: str) -> int:
    out, i = 0, 0
    while i < len(s):
        if s[i] == "\033":
            i = s.find("m", i) + 1 or len(s)
            continue
        out += 1
        i += 1
    return out


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _visible_len(s))


def _clip(s: str, width: int) -> str:
    return s if len(s) <= width else s[: max(0, width - 1)] + "…"


def eur(v: float | None, decimals: int = 0) -> str:
    return "?" if v is None else f"€{v:,.{decimals}f}"


COND_STYLE = {"new": "bcyan", "refurbished": "byellow", "used": "bmagenta", "rental": "blue", "service": "blue"}
COLUMNS = [("new", "NEW"), ("refurbished", "REFURB"), ("used", "USED")]

# ---------- live event lines ----------

TAGS = {"need": ("NEED", "bold"), "lane": ("LANE", "blue"), "source": ("SRC", "grey"), "offer": ("OFFER", "bgreen"),
        "skip": ("SKIP", "dim"), "thing": ("THING", "cyan"), "truecost": ("TRUE", "yellow"),
        "verdict": ("VERDICT", "bold"), "budget": ("BUDGET", "grey"), "done": ("DONE", "bgreen"), "error": ("ERROR", "red"),
        "rank": ("RANK", "bmagenta"), "late": ("LATE", "byellow"), "depreciation": ("DEPR", "cyan")}


def event_line(e: Event, p: Paint, width: int = 100) -> str | None:
    """One Event -> one terminal line (None = don't print)."""
    d = e.data
    tag, style = TAGS.get(e.type, (e.type.upper(), "grey"))
    head = p(f"{e.t_ms / 1000:6.2f}s ", "dim") + p(f"{tag:<7}", style, "bold") + " "
    body: str
    if e.type == "need":
        n = d.get("need", {})
        bits = [n.get("thing", "")]
        if n.get("budget"):
            bits.append(f"budget {n.get('currency', 'EUR')} {n['budget']:,.0f}")
        if n.get("where"):
            bits.append(f"near {n['where']}")
        bits.append("/".join(n.get("conditions", [])))
        body = p(" · ".join(b for b in bits if b), "bold")
    elif e.type == "lane":
        qs = d.get("queries") or []
        body = f"{p(str(d.get('lane', '')), COND_STYLE.get(str(d.get('lane')), 'blue'))}  {len(qs)} {'query' if len(qs) == 1 else 'queries'}" + (
            p(f"  “{qs[0]}”", "dim") if qs else "")
    elif e.type == "source":
        body = p(f"{d.get('domain', '')}  {d.get('lane') or ''}", "grey")
    elif e.type == "offer":
        o = d.get("offer", {})
        cond = str(o.get("condition", "unknown"))
        price = p(f"{eur(o.get('price_eur'), 2):>11}", "bold")
        via = o.get("read_via", "")
        via_s = p("free", "green") if via == "jsonld" else p(via.replace("contextdev_", "cd:"), "dim")
        title = _clip(str(o.get("title", "")), max(20, width - 62))
        body = f"{price}  {p(f'{cond:<11}', COND_STYLE.get(cond, 'grey'))} {_clip(o.get('source', ''), 18):<18} {title}  {via_s}"
    elif e.type == "skip":
        body = p(f"{_clip(d.get('url', ''), 60)}  {d.get('reason', '')}", "dim")
    elif e.type == "thing":
        body = f"{p(str(d.get('name')), 'cyan')}  {d.get('n_offers')} offers"
    elif e.type == "truecost":
        tc = d.get("true_cost") or {}
        if not tc:
            return None
        cost = (f"{eur(tc.get('total_eur'), 0)} per job" if tc.get("per") == "job" or tc.get("months") == 0
                else f"{eur(tc.get('per_month_eur'), 0)}/mo over {tc.get('months')} mo")
        check = {"verified": p("  ✓ price x2", "green"), "disputed": p("  ✗ price disputed", "red"),
                 "consistent": p("  = matches its listing", "grey")}.get(
            str(d.get("price_check")), "")
        gap = d.get("gap_eur")
        beat = p(f"  beats the leader at ≤{eur(d.get('beat_eur'))}", "dim") if gap else ""
        body = f"{cost}  {p(_clip(d.get('url', ''), 50), 'dim')}  {p(str(tc.get('confidence', '')), 'grey')}{check}{beat}"
    elif e.type == "rank":
        if not d.get("leader_changed"):
            return None
        body = p(str(d.get("reason") or ""), "bmagenta", "bold")
    elif e.type == "verdict":
        if not d.get("provisional") and not d.get("changed_from"):
            return None  # rendered as a box at the end
        if d.get("provisional"):
            body = p(f"provisional ({d.get('pending_reads', 0)} pages still reading): ", "dim") + p(
                _clip(str((d.get("verdict") or {}).get("headline", "")), max(30, width - 60)), "bgreen")
        else:
            body = p("final verdict moved from: " + _clip(str(d["changed_from"].get("headline", "")),
                                                          max(30, width - 50)), "byellow")
    elif e.type == "late":
        body = p(_clip(str(d.get("note", "")), max(30, width - 20)), "byellow" if d.get("changed_verdict") else "dim")
    elif e.type == "depreciation":
        pts = ", ".join(f"{x.get('model')} {eur(x.get('median_eur'))} (n={x.get('n')})" for x in d.get("points") or [])
        body = p(f"{d.get('source')} -{(d.get('rate') or 0):.0%}/yr  ", "bold") + p(_clip(pts, max(30, width - 40)), "dim")
    elif e.type == "budget":
        euro = f" (≈€{d['credit_eur']:.3f})" if d.get("credit_eur") is not None else ""
        free = d.get("free_reads") or []
        body = p(f"{d.get('credits_used', 0) or 0:g} credits{euro} · {d.get('requests', 0)} requests · "
                 f"{d.get('saved_by_free_reads', 0)} free reads" + (f" ({', '.join(free[:4])})" if free else ""), "grey")
    elif e.type == "done":
        body = p(f"{d.get('ms', 0) / 1000:.1f}s", "bgreen")
    elif e.type == "error":
        body = p(f"[{d.get('where')}] {d.get('url', '')} {d.get('message', '')}".strip(), "red")
    else:
        body = json.dumps(d, default=str)[:width]
    return head + body


# ---------- price ladder ----------

@dataclass
class Rung:
    price: float
    source: str
    per_month: float | None
    condition: str
    url: str
    trust: float | None = None


def _nice_step(span: float, rows: int) -> float:
    raw = max(span / max(rows, 1), 1.0)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _rungs(offers: list[dict[str, Any]]) -> list[Rung]:
    out = []
    for o in offers:
        if o.get("price_eur") is None:
            continue
        tc = o.get("true_cost") or {}
        out.append(Rung(price=float(o["price_eur"]), source=str(o.get("source", "")),
                        per_month=tc.get("per_month_eur"), condition=str(o.get("condition", "unknown")),
                        url=str(o.get("url", "")),
                        trust=0.0 if any(str(f).startswith("too good") for f in o.get("flags") or []) else o.get("trust")))
    return out


def render_ladder(offers: list[dict[str, Any]], p: Paint, *, width: int = 100, budget: float | None = None,
                  best_url: str | None = None, best_tc_url: str | None = None, rows: int = 10) -> str:
    """Offers (as dicts) -> ASCII ladder: EUR axis down the side, one column per condition."""
    rungs = _rungs(offers)
    if not rungs:
        return p("  (no priced offers to put on the ladder)", "dim")
    cols = list(COLUMNS)
    if all(r.condition == "service" for r in rungs):
        cols = [("service", "SERVICE  (price per unit · what one job costs)")]
    elif any(r.condition not in dict(COLUMNS) for r in rungs):
        cols.append(("other", "OTHER"))
    known = {c for c, _ in cols if c != "other"}
    axis_w = 9
    col_w = max(22, (width - axis_w - 2) // len(cols) - 1)

    lo = min(r.price for r in rungs)
    hi = max(r.price for r in rungs)
    if budget:
        lo, hi = min(lo, budget), max(hi, budget)
    step = _nice_step(hi - lo, rows)
    top = math.floor(hi / step) * step
    bottom = math.floor(lo / step) * step

    def cell(r: Rung) -> str:
        star = ""
        if r.url and r.url == best_tc_url:
            star = p(" ★", "bgreen", "bold")
        elif r.url and r.url == best_url:
            star = p(" ◆", "bcyan")
        per = "/job" if r.condition == "service" else "/mo"
        pm = p(f" {eur(r.per_month)}{per}", "yellow") if r.per_month is not None else ""
        dot = p("!", "red", "bold") if (r.trust is not None and r.trust < 0.5) else p("●", COND_STYLE.get(r.condition, "grey"))
        room = col_w - 5 - len(f"{r.price:,.0f}") - _visible_len(pm) - _visible_len(star)
        return f"{dot} {p(f'{r.price:,.0f}', 'bold')} {_clip(r.source, max(4, room))}{pm}{star}"

    sep = p("│", "grey")
    lines = [p(f"{'EUR':>{axis_w - 1}} ", "bold") + sep
             + sep.join(p(_pad(f" {label}", col_w), COND_STYLE.get(key, "grey"), "bold") for key, label in cols)]
    lines.append(p("─" * axis_w + ("┼" + "─" * col_w) * len(cols), "grey"))

    def budget_line() -> str:
        label = f" your budget {eur(budget)} "
        return " " * axis_w + p("╌" * 2 + label + "╌" * max(0, (col_w + 1) * len(cols) - len(label) - 2), "green")

    budget_drawn = budget is None
    tick = top
    while tick >= bottom - 1e-9:
        in_bucket = [r for r in rungs if tick <= r.price < tick + step or (tick == top and r.price >= top)]
        if not budget_drawn and budget is not None and budget >= tick + step - 1e-9:
            lines.append(budget_line())  # budget sits on the boundary below the previous row
            budget_drawn = True
        per_col = []
        for key, _ in cols:
            here = [r for r in in_bucket if (r.condition == key) or (key == "other" and r.condition not in known)]
            per_col.append(sorted(here, key=lambda r: r.price, reverse=True))
        height = max(1, max(len(c) for c in per_col))
        for i in range(height):
            axis = f"{tick:>{axis_w - 1},.0f} " if i == 0 else " " * axis_w
            row = [(" " + cell(c[i])) if i < len(c) else "" for c in per_col]
            lines.append(p(axis, "dim") + sep + sep.join(_pad(x, col_w) for x in row))
        tick -= step
    if not budget_drawn:
        lines.append(budget_line())
    legend = (p("  ★ lowest true cost", "bgreen") + p("   ◆ cheapest sticker", "bcyan") + p("   ! low trust", "red")
              + p("   €/mo = true cost per month of ownership" if not any(r.condition == "service" for r in rungs)
                  else "   €/job = what one job really costs you", "yellow"))
    lines.append(legend)
    return "\n".join(lines)


def render_verdict(verdict: dict[str, Any], p: Paint, width: int = 100, haggle: dict[str, Any] | None = None) -> str:
    inner = min(width, 100) - 4
    head = _clip(str(verdict.get("headline", "")), inner)
    rows = [p(head, "bold", "bgreen")]
    if verdict.get("buy_or_wait"):
        rows.append(p(f"→ {verdict['buy_or_wait']}", "byellow", "bold"))
    lines = [ln for ln in verdict.get("lines", []) if not (haggle and str(ln).startswith("haggle:"))]
    rows += [_clip(f"· {ln}", inner) for ln in lines]
    if haggle:
        rows.append(p(_clip(f"haggle: offer {eur(haggle.get('suggested_offer_eur'))} "
                            f"(fair {eur(haggle.get('fair_low_eur'))}–{eur(haggle.get('fair_high_eur'))})", inner), "bmagenta"))
        rows.append(p(_clip(f"  “{haggle.get('message', '')}”", inner), "dim"))
    top = p("╭" + "─" * (inner + 2) + "╮", "green")
    bot = p("╰" + "─" * (inner + 2) + "╯", "green")
    mid = [p("│ ", "green") + _pad(r, inner) + p(" │", "green") for r in rows]
    return "\n".join([top, *mid, bot])


# ---------- main ----------

async def run(query: str, out: TextIO, *, color: bool, as_json: bool, hunt_kwargs: dict[str, Any] | None = None) -> int:
    from agora.hunt import hunt  # lazy: keeps `--help` instant

    p = Paint(color)
    width = shutil.get_terminal_size((110, 30)).columns
    offers: dict[str, dict[str, Any]] = {}
    need: dict[str, Any] = {}
    verdict: dict[str, Any] = {}
    budget: dict[str, Any] = {}
    errors = 0

    if not as_json:
        out.write("\n" + p("  AGORA ", "bold", "bgreen") + p(" hunting: ", "dim") + p(query, "bold") + "\n\n")
    kw = dict(hunt_kwargs or {})
    if "replay" in kw:
        from agora.hunt import replay
        stream = replay(kw.pop("replay"), kw.pop("speed", 1.0))
    else:
        stream = hunt(query, **kw)
    async for e in stream:
        if as_json:
            out.write(json.dumps(to_dict(e), default=str, ensure_ascii=False) + "\n")
            out.flush()
            continue
        d = e.data
        if e.type == "need":
            need = d.get("need", {})
        elif e.type == "offer":
            o = d.get("offer", {})
            offers[o.get("url", str(len(offers)))] = o
        elif e.type == "truecost" and d.get("url") in offers:
            o = offers[d["url"]]
            o["true_cost"] = d.get("true_cost")
            for k in ("trust", "flags", "haggle", "thing_id"):
                if d.get(k) is not None:
                    o[k] = d[k]
            if d.get("haggle") is None:
                o["haggle"] = None
        elif e.type == "skip" and d.get("rejected") and d.get("url") in offers:
            offers.pop(d["url"])          # read fine, but resolve says it is not the thing asked for
        elif e.type == "verdict":
            verdict = d.get("verdict", {})
        elif e.type == "budget":
            budget = d
        elif e.type == "error":
            errors += 1
        line = event_line(e, p, width)
        if line:
            out.write(line + "\n")
            out.flush()

    if as_json:
        return 0
    b = need.get("budget") if (need.get("currency") or "EUR") == "EUR" else None
    out.write("\n" + p(f"  PRICE LADDER  {need.get('thing', query)}", "bold") + "\n\n")
    out.write(render_ladder(list(offers.values()), p, width=width, budget=b,
                            best_url=verdict.get("best_offer_url"), best_tc_url=verdict.get("best_true_cost_url")) + "\n\n")
    if verdict:
        best = offers.get(verdict.get("best_true_cost_url") or "") or {}
        h = best.get("haggle")
        real_counter = h and (h.get("suggested_offer_eur") or 0) < (best.get("price_eur") or 0)
        out.write(render_verdict(verdict, p, width, haggle=h if real_counter else None) + "\n")
    credits = budget.get("credits_used", 0) or 0
    out.write(p(f"  {credits:g} Context.dev credits · {budget.get('requests', 0)} requests · "
                f"{budget.get('saved_by_free_reads', 0)} pages read free · {len(offers)} offers"
                + (f" · {errors} errors" if errors else ""), "grey") + "\n\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "demo-buy":          # `python -m agora demo-buy [--pause N] [--tmp-db]`
        from agora.demo_buy import main as demo_buy
        return demo_buy(args[1:])
    argv = args
    ap = argparse.ArgumentParser(prog="agora", description="Hunt the live web for the true cost of a thing.")
    ap.add_argument("query", nargs="+", help='what you want, e.g. "used sony a7 iii under 900"')
    ap.add_argument("--json", action="store_true", help="print raw events as JSON lines")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--max-sources", type=int, default=None, help="cap pages read (saves credits)")
    ap.add_argument("--concurrency", type=int, default=None)
    ap.add_argument("--replay", metavar="SLUG", help="replay a recorded hunt (tests/fixtures/live_SLUG.jsonl)")
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed")
    a = ap.parse_args(argv)
    color = not a.no_color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    kw: dict[str, Any] = {}
    if a.max_sources:
        kw["max_sources"] = a.max_sources
    if a.concurrency:
        kw["concurrency"] = a.concurrency
    if a.replay:
        kw = {"replay": a.replay, "speed": a.speed}
    try:
        return asyncio.run(run(" ".join(a.query), sys.stdout, color=color, as_json=a.json, hunt_kwargs=kw))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
