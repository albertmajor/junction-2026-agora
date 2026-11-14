"""WATCH engine: standing orders on a Need.

Watch = Need + Rule + action (notify | one_tap | auto_buy) + optional Mandate.
check_watch re-runs the hunt (and/or reads pinned pages), snapshots every offer into the price
history, judges each candidate against the rule, writes a decision line for EVERY candidate
("skipped: trust 0.40 < 0.70", "match: €872 <= €900") and acts on the best match through agora.buy.
Also: Context.dev semantic page monitors + their webhook, and a buy-or-wait forecast from history.

Rule upgrades (ideas from changedetection.io's restock/conditions processors, our own code):
- `logic`: an extra condition in JSON Logic (panzi-json-logic), so agents can author rules as data.
- `min_move_pct`: ignore wiggles smaller than this vs the last price we actually judged.
- `on_restock`: fire only when an offer comes back in stock (out -> in).
- page unchanged -> skip: a fingerprint of what we read; an unchanged skipped page is not re-judged.
- sold-out lie detector: visible "sold out / loppuunmyyty / ausverkauft / slutsåld" text beats
  structured data that still says InStock.
Haggle loop (ACP intent-trace idea): a price-skipped mock-shop offer gets a structured reason sent
to the shop; a counter-offer comes back and goes through the same rule. Every step is logged.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Callable

from agora import buy, lease, mockshop, proof, store
from agora.models import Event, Need, Offer, to_dict

Hunt = Callable[[str], AsyncIterator[Event]]
ACTIONS = ("notify", "one_tap", "auto_buy")


@dataclass
class Rule:
    max_price_eur: float | None = None
    max_true_cost_eur: float | None = None
    min_trust: float | None = None
    conditions: list[str] = field(default_factory=list)   # empty = any
    max_km: float | None = None
    logic: dict | None = None            # extra JSON Logic condition over offer_vars(); agents can write it
    min_move_pct: float | None = None    # ignore moves smaller than this % vs the last judged price
    on_restock: bool = False             # only fire when the offer comes back in stock
    haggle: bool = False                 # tell a skipped (mock) shop why, and judge its counter-offer


@dataclass
class Mandate:
    """What the agent may spend by itself. AP2-inspired, our own shape."""
    cap_eur: float
    expires_at: str | float | None = None                 # ISO date/time or epoch seconds
    merchants: list[str] = field(default_factory=list)     # domain allowlist, empty = any
    require_confirm_above_eur: float | None = None
    id: str = ""


def _eur(x: float) -> str:
    return buy._eur(x)


def _need(need: Need | str) -> Need:
    if isinstance(need, Need):
        return need
    try:
        from agora.need import parse_need
        return parse_need(need)
    except Exception:   # module not there yet, or parse failed: keep the raw text
        return Need(raw=need, thing=need)


# ---- create / read ----------------------------------------------------------

def _narrow_constraints(server: dict, asked: Any) -> dict:
    """Server-computed constraints, optionally narrowed (never widened) by the caller's own lists."""
    out = dict(server)
    if not isinstance(asked, dict):
        return out
    for key in ("conditions", "product_ids"):
        want = asked.get(key)
        if not isinstance(want, list) or not want:
            continue
        have = out.get(key) or []
        out[key] = sorted(set(have) & set(want)) if have else sorted(set(map(str, want)))
        if have and not out[key]:
            raise ValueError(f"mandate constraints.{key} must narrow, not replace, {have}")
    return out


def create_watch(need: Need | str, rule: Rule | dict | None = None, action: str = "notify",
                 mandate: Mandate | dict | None = None, pinned_urls: list[str] | None = None,
                 use_hunt: bool = True, baseline_eur: float | None = None,
                 max_price_eur: float | None = None) -> dict:
    """Save a new watch and return it as a dict (what the API returns).

    `max_price_eur` is a shortcut for rule={"max_price_eur": ...} (API / MCP callers)."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    n = _need(need)
    r = rule if isinstance(rule, Rule) else Rule(**(rule or {}))
    if r.logic is not None:
        validate_logic(r.logic)
    if max_price_eur is not None:
        r.max_price_eur = max_price_eur
    if r.max_price_eur is None and r.max_true_cost_eur is None and n.budget:
        r.max_price_eur = n.budget
    m = None
    if mandate is not None:
        m = asdict(mandate) if isinstance(mandate, Mandate) else dict(mandate)
        # The server owns the mandate id and its constraints: a caller can never reuse another watch's
        # mandate id (and its spend ledger) or widen what the agent may buy.
        for k in ("id", "signature", "alg", "need", "kind"):
            m.pop(k, None)
        m["id"] = store.new_id("mandate")
        if m.get("cap_eur") is not None:
            m["cap_eur"] = float(m["cap_eur"])
        if action == "auto_buy" and not (m.get("cap_eur") and m["cap_eur"] > 0):
            raise ValueError("auto_buy needs a mandate with cap_eur > 0")
        # The OPEN mandate (AP2-style): only constraints. The agent signs a CLOSED one per cart at buy time.
        pids = sorted({pid for u in pinned_urls or [] if (pid := mockshop.product_id_from_url(u))})
        m["kind"] = "open"
        m.setdefault("currency", "EUR")
        m["constraints"] = _narrow_constraints(
            {"thing": n.thing, "conditions": list(r.conditions), "product_ids": pids}, m.get("constraints"))
        m = proof.sign_mandate(m, n.raw)
        store.save_mandate(m["id"], m)
    if action == "auto_buy" and m is None:
        raise ValueError("auto_buy needs a mandate")
    for url in pinned_urls or []:   # remember "the day you set the watch" for the savings line
        if pid := mockshop.product_id_from_url(url):
            price = mockshop.get_product(pid).price_eur
            store.snapshot(url, price, True)
            baseline_eur = price if baseline_eur is None else baseline_eur
    wid = store.new_id("watch")
    w = {"id": wid, "need": to_dict(n), "rule": asdict(r), "action": action, "mandate": m,
         "pinned_urls": list(pinned_urls or []), "use_hunt": use_hunt, "baseline_eur": baseline_eur,
         "created_at": time.time(), "status": "watching", "monitors": [], "last_action": None,
         "fingerprints": {}, "ref_prices": {}, "haggles": {}, "closed_mandates": []}
    store.save_watch(wid, w)
    store.log_decision(wid, None, None, "created", describe_rule(w))
    return store.get_watch(wid)


def list_watches() -> list[dict]:
    return [w | {"rule_text": describe_rule(w)} for w in store.list_watches()]


def describe_rule(w: dict) -> str:
    r, bits = w["rule"], []
    if r.get("max_price_eur") is not None:
        bits.append(f"price <= {_eur(r['max_price_eur'])}")
    if r.get("max_true_cost_eur") is not None:
        bits.append(f"true cost <= {_eur(r['max_true_cost_eur'])}")
    if r.get("min_trust") is not None:
        bits.append(f"trust >= {r['min_trust']:.2f}")
    if r.get("conditions"):
        bits.append("condition in " + "/".join(r["conditions"]))
    if r.get("max_km") is not None:
        bits.append(f"<= {r['max_km']:g} km")
    if r.get("logic"):
        bits.append(describe_logic(r["logic"]))
    if r.get("min_move_pct"):
        bits.append(f"moves >= {r['min_move_pct']:g}%")
    if r.get("on_restock"):
        bits.append("back in stock")
    rule = " AND ".join(bits) or "any offer"
    return f"watch '{w['need']['thing']}': {rule} -> {w['action']}"


# ---- rule -------------------------------------------------------------------

def _true_cost_total(o: dict) -> float | None:
    tc = o.get("true_cost")
    return tc.get("total_eur") if isinstance(tc, dict) else None


def _km(o: dict) -> float | None:
    for d in (o, o.get("raw") or {}):
        for k in ("km", "distance_km"):
            if isinstance(d.get(k), (int, float)):
                return float(d[k])
    return None


def evaluate(rule: dict, o: dict, ctx: dict | None = None) -> tuple[bool, str]:
    """Judge one offer against the rule. Returns (match, decision line).
    `ctx` (optional): {"ref_price": last judged price, "prev_in_stock": last snapshot's stock}."""
    ok, line, _ = _evaluate(rule, o, ctx or {})
    return ok, line


def _evaluate(rule: dict, o: dict, ctx: dict) -> tuple[bool, str, str]:
    """(match, line, code). code says which part failed: price | true_cost | trust | condition | stock |
    logic | move | restock | unknown | match."""
    price = o.get("price_eur")
    if price is None:
        return False, "skipped: price unknown", "unknown"
    if o.get("in_stock") is False:
        lie = (o.get("raw") or {}).get("lie_detector")
        if lie:
            return False, f"skipped: sold out: page says '{lie['phrase']}' although its structured data says in stock", "stock"
        return False, "skipped: out of stock", "stock"
    if rule.get("on_restock"):
        prev = ctx.get("prev_in_stock")
        if prev is not False:
            why = "no stock history yet" if prev is None else "was already in stock"
            return False, f"skipped: restock-only and {why}", "restock"
    conds = rule.get("conditions") or []
    if conds and o.get("condition", "unknown") not in conds:
        return False, f"skipped: condition {o.get('condition', 'unknown')} not in {'/'.join(conds)}", "condition"
    why = []
    if (mt := rule.get("min_trust")) is not None:
        t = o.get("trust")
        if t is None:
            return False, f"skipped: trust unknown (needs >= {mt:.2f})", "trust"
        if t < mt:
            return False, f"skipped: trust {t:.2f} < {mt:.2f}", "trust"
        why.append(f"trust {t:.2f} >= {mt:.2f}")
    if (mp := rule.get("max_price_eur")) is not None:
        if price > mp:
            return False, f"skipped: {_eur(price)} > {_eur(mp)}", "price"
        why.insert(0, f"{_eur(price)} <= {_eur(mp)}")
    if (mtc := rule.get("max_true_cost_eur")) is not None:
        tc = _true_cost_total(o)
        if tc is None:
            return False, "skipped: true cost unknown", "true_cost"
        if tc > mtc:
            return False, f"skipped: true cost {_eur(tc)} > {_eur(mtc)}", "true_cost"
        why.append(f"true cost {_eur(tc)} <= {_eur(mtc)}")
    if (mk := rule.get("max_km")) is not None:
        km = _km(o)
        if km is not None and km > mk:
            return False, f"skipped: {km:g} km > {mk:g} km", "km"
        why.append(f"{km:g} km <= {mk:g} km" if km is not None else "distance unknown")
    if rule.get("logic"):
        ok, text = run_logic(rule["logic"], offer_vars(o))
        if not ok:
            return False, f"skipped: {text}", "logic"
        why.append(text)
    if (mv := rule.get("min_move_pct")) and (ref := ctx.get("ref_price")):
        moved = abs(price - ref) / ref * 100
        if moved < mv:
            return False, f"skipped: moved {moved:.1f}% since {_eur(ref)} (< {mv:g}%)", "move"
        why.append(f"moved {moved:.1f}% since {_eur(ref)}")
    return True, "match: " + (", ".join(why) or f"{_eur(price)}, no limits set"), "match"


# ---- JSON Logic rules (agent-writable) ---------------------------------------------------------

def offer_vars(o: dict) -> dict:
    """The variables a JSON Logic rule can read (all plain values)."""
    tc = _true_cost_total(o)
    return {"price_eur": o.get("price_eur"), "shipping_eur": o.get("shipping_eur"),
            "total_eur": (o.get("price_eur") or 0) + (o.get("shipping_eur") or 0) if o.get("price_eur") is not None else None,
            "true_cost_eur": tc, "trust": o.get("trust"), "condition": o.get("condition", "unknown"),
            "in_stock": o.get("in_stock"), "source": o.get("source"), "title": (o.get("title") or "").lower(),
            "km": _km(o), "flags_text": " | ".join(str(f) for f in o.get("flags") or []).lower(),
            "counter_offer": bool((o.get("raw") or {}).get("counter_offer"))}


LOGIC_VARS = tuple(offer_vars({}).keys())


def _logic_vars(logic: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(logic, dict):
        for op, args in logic.items():
            if op == "var":
                name = args[0] if isinstance(args, list) and args else args
                if isinstance(name, str):
                    out.add(name.split(".")[0])
            else:
                out |= _logic_vars(args)
    elif isinstance(logic, list):
        for x in logic:
            out |= _logic_vars(x)
    return out


def validate_logic(logic: Any) -> None:
    """Raise ValueError if the rule is not usable JSON Logic over offer_vars()."""
    if not isinstance(logic, dict) or not logic:
        raise ValueError("logic must be a JSON Logic object, e.g. {\"<=\": [{\"var\": \"price_eur\"}, 900]}")
    unknown = _logic_vars(logic) - set(LOGIC_VARS)
    if unknown:
        raise ValueError(f"unknown variable(s) {sorted(unknown)}; use {list(LOGIC_VARS)}")
    sample = {k: 0 for k in LOGIC_VARS} | {"condition": "new", "source": "", "title": "", "flags_text": "",
                                           "in_stock": True, "counter_offer": False}
    try:
        _apply_logic(logic, sample)
    except Exception as e:   # unknown operator, bad arity...
        raise ValueError(f"invalid JSON Logic: {e}") from None


def _apply_logic(logic: dict, data: dict) -> Any:
    try:
        from json_logic import jsonLogic   # panzi-json-logic (MIT)
    except ImportError:                    # tiny fallback for the operators we document
        return _mini_logic(logic, data)
    return jsonLogic(logic, data)


def _mini_logic(node: Any, data: dict) -> Any:
    if isinstance(node, list):
        return [_mini_logic(x, data) for x in node]
    if not isinstance(node, dict):
        return node
    (op, args), = node.items()
    if op == "var":
        name = args[0] if isinstance(args, list) else args
        return data.get(name)
    args = args if isinstance(args, list) else [args]
    if op == "and":
        return all(_mini_logic(a, data) for a in args)
    if op == "or":
        return any(_mini_logic(a, data) for a in args)
    v = [_mini_logic(a, data) for a in args]
    ops = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
           "==": lambda a, b: a == b, "!=": lambda a, b: a != b, "in": lambda a, b: a in b}
    if op == "!":
        return not v[0]
    if op in ops:
        return ops[op](v[0], v[1])
    raise ValueError(f"unsupported operator {op}")


def run_logic(logic: dict, data: dict) -> tuple[bool, str]:
    """Evaluate a JSON Logic rule safely: a variable the rule needs but we don't know = no match."""
    missing = sorted(k for k in _logic_vars(logic) if data.get(k) is None)
    if missing:
        return False, f"rule needs {', '.join(missing)} (unknown)"
    try:
        ok = bool(_apply_logic(logic, data))
    except Exception as e:
        return False, f"rule error: {e}"
    return ok, ("rule ok: " if ok else "rule failed: ") + describe_logic(logic)


_OPS = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "==": "=", "===": "=", "!=": "!=", "!==": "!="}


def describe_logic(node: Any) -> str:
    """JSON Logic -> one line of plain text ("price_eur <= 900 AND NOT ('grey import' in flags_text)")."""
    if isinstance(node, dict) and len(node) == 1:
        (op, args), = node.items()
        if op == "var":
            return str(args[0] if isinstance(args, list) else args)
        args = args if isinstance(args, list) else [args]
        if op in ("and", "or"):
            return "(" + f" {op.upper()} ".join(describe_logic(a) for a in args) + ")"
        if op in ("!", "not"):
            return "NOT " + describe_logic(args[0])
        if op in _OPS and len(args) == 2:
            return f"{describe_logic(args[0])} {_OPS[op]} {describe_logic(args[1])}"
        if op in ("<", "<=") and len(args) == 3:
            return f"{describe_logic(args[0])} {op} {describe_logic(args[1])} {op} {describe_logic(args[2])}"
        if op == "in" and len(args) == 2:
            return f"{describe_logic(args[0])} in {describe_logic(args[1])}"
        return f"{op}({', '.join(describe_logic(a) for a in args)})"
    if isinstance(node, str):
        return repr(node)
    if isinstance(node, list):
        return "[" + ", ".join(describe_logic(x) for x in node) + "]"
    return str(node)


def rule_logic(rule: dict) -> dict:
    """The whole rule as one JSON Logic object (what an agent sees and can edit)."""
    parts: list[dict] = []
    if rule.get("max_price_eur") is not None:
        parts.append({"<=": [{"var": "price_eur"}, rule["max_price_eur"]]})
    if rule.get("max_true_cost_eur") is not None:
        parts.append({"<=": [{"var": "true_cost_eur"}, rule["max_true_cost_eur"]]})
    if rule.get("min_trust") is not None:
        parts.append({">=": [{"var": "trust"}, rule["min_trust"]]})
    if rule.get("conditions"):
        parts.append({"in": [{"var": "condition"}, list(rule["conditions"])]})
    if rule.get("max_km") is not None:
        parts.append({"<=": [{"var": "km"}, rule["max_km"]]})
    if rule.get("logic"):
        parts.append(rule["logic"])
    return {"and": parts} if len(parts) != 1 else parts[0]


# ---- sold-out lie detector ----------------------------------------------------------------------

SOLD_OUT_PHRASES = (
    # en
    "sold out", "out of stock", "currently unavailable", "no longer available", "temporarily unavailable",
    # fi
    "loppuunmyyty", "myyty", "ei varastossa", "tilapäisesti loppu", "loppu varastosta", "tuote on loppu",
    # de
    "ausverkauft", "nicht auf lager", "derzeit nicht verfügbar", "nicht vorrätig", "nicht lieferbar",
    # sv / da / no
    "slutsåld", "slutsålt", "slut i lager", "ej i lager", "tillfälligt slut", "udsolgt", "utsolgt",
    # fr / nl / es / it / pl
    "rupture de stock", "épuisé", "uitverkocht", "niet op voorraad", "agotado", "sin stock", "esaurito",
    "wyprzedane", "brak w magazynie",
)
_NEGATED = re.compile(r"(?:\bnot|\bnever|\bei|\bnicht|\binte)\s+$", re.I)


def sold_out_phrase(text: str | None, limit: int = 6000) -> str | None:
    """The first sold-out phrase visible in the page text ('not sold out' does not count)."""
    if not text:
        return None
    low = text[:limit].lower()
    for ph in SOLD_OUT_PHRASES:
        for m in re.finditer(r"(?<![\w])" + re.escape(ph) + r"(?![\w])", low):
            if not _NEGATED.search(low[max(0, m.start() - 12):m.start()]):
                return text[m.start():m.end()]
    return None


def _page_text(o: dict) -> str | None:
    raw = o.get("raw") or {}
    for k in ("page_text", "visible_text", "text"):
        if isinstance(raw.get(k), str) and raw[k].strip():
            return raw[k]
    return None


def lie_detector(o: dict) -> dict:
    """Structured data says in stock, the visible page says sold out: trust the page. Mutates `o`."""
    if o.get("in_stock") is False:
        return o
    phrase = sold_out_phrase(_page_text(o))
    if phrase:
        said = "InStock" if o.get("in_stock") else "no stock info"
        o["in_stock"] = False
        o.setdefault("raw", {})["lie_detector"] = {"phrase": phrase, "structured_said": said}
        o["flags"] = list(o.get("flags") or []) + [f"sold out on the page ('{phrase}'), structured data said {said}"]
    return o


# ---- fingerprint: page unchanged -> skip ---------------------------------------------------------

def fingerprint(o: dict, rule: dict) -> str:
    """Hash of everything the rule could look at + the rule itself. Same hash = nothing new to judge."""
    text = _page_text(o)
    body = {"price": o.get("price_eur"), "stock": o.get("in_stock"), "cond": o.get("condition"),
            "trust": o.get("trust"), "tc": _true_cost_total(o), "ship": o.get("shipping_eur"),
            "flags": sorted(str(f) for f in o.get("flags") or []), "km": _km(o),
            "text": hashlib.sha256(text.encode()).hexdigest() if text else None, "rule": rule}
    return hashlib.sha256(proof.canonical(body).encode()).hexdigest()


# ---- gather offers ----------------------------------------------------------

def _accepts(fn: Any, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params


async def _read_pinned(url: str, need: Need) -> Offer | dict | None:
    """Re-read a pinned page. Watch checks want FRESH data: Context.dev caches scrapes (up to 3 days by
    default), so we ask for maxAgeMs=0 via the reader's `fresh` flag when the reader supports it."""
    if pid := mockshop.product_id_from_url(url):
        o = mockshop.as_offer(pid)
        o.raw["page_text"] = mockshop.page_text(pid)
        return o
    try:
        from agora import reader
        kw: dict[str, Any] = {}
        if _accepts(getattr(reader, "read_with_reason", reader.read), "fresh") or _accepts(reader.read, "fresh"):
            kw["fresh"] = True
        return await reader.read(url, need, **kw)
    except Exception:
        return None


async def gather_offers(w: dict, hunt: Hunt | None = None, only_pinned: bool = False) -> list[dict]:
    """Offers for this watch: pinned pages + a fresh hunt. Latest data per URL wins."""
    need = Need(**w["need"])
    found: dict[str, Any] = {}
    true_costs: dict[str, Any] = {}
    if w.get("use_hunt", True) and not only_pinned:
        if hunt is None:
            from agora.hunt import hunt as real_hunt   # lazy: heavy module, other owner
            hunt = real_hunt
        async for ev in hunt(need.raw):
            if ev.type == "offer" and ev.data.get("offer") is not None:
                o = ev.data["offer"]
                found[to_dict(o)["url"]] = o           # keep the object: judge may mutate it later
            elif ev.type == "truecost" and ev.data.get("url"):
                true_costs[ev.data["url"]] = ev.data   # hunt sends true_cost + trust + flags here
    for url in w.get("pinned_urls") or []:
        if (o := await _read_pinned(url, need)) is not None:
            found[to_dict(o)["url"]] = o
    out = []
    for url, o in found.items():
        d = to_dict(o)
        judged = true_costs.get(url) or {}
        if judged.get("true_cost") is not None:
            d["true_cost"] = to_dict(judged["true_cost"])
        for k in ("trust", "flags", "haggle", "thing_id"):
            if judged.get(k) is not None:
                d[k] = to_dict(judged[k])
        out.append(d)
    return out


# ---- check ------------------------------------------------------------------

def _rank(o: dict) -> float:
    return _true_cost_total(o) or o.get("price_eur") or float("inf")


async def check_watch(watch_id: str, hunt: Hunt | None = None, only_pinned: bool = False,
                      notify_client: Any = None) -> list[Event]:
    """One pass of a watcher. Every step is an Event (decision | haggle | counter | action | forecast |
    done | error) and every decision is a line in the watch's hash chain."""
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)   # noqa: E731
    w = store.get_watch(watch_id)
    if w is None:
        return [Event("error", {"where": "watch", "message": f"no watch {watch_id}"})]
    if not w["active"]:
        return [Event("done", {"watch_id": watch_id, "status": w["status"], "ms": 0})]
    for k in ("fingerprints", "ref_prices", "haggles"):
        w.setdefault(k, {})
    events: list[Event] = []
    try:
        offers = await gather_offers(w, hunt, only_pinned)
    except Exception as e:
        store.log_decision(watch_id, None, None, "error", f"hunt failed: {e}")
        return [Event("error", {"where": "watch.hunt", "message": str(e)})]
    matches: list[dict] = []
    skipped: list[tuple[dict, str]] = []
    for o in offers:
        ok, code = await _judge_one(w, o, events, ms)
        if ok:
            matches.append(o)
        elif code:
            skipped.append((o, code))
    if not offers:
        store.log_decision(watch_id, None, None, "skip", "no offers found this pass")
    if not matches and w["rule"].get("haggle"):
        for counter in await _haggle(w, offers, skipped, events, ms):
            ok, _ = await _judge_one(w, counter, events, ms)
            if ok:
                matches.append(counter)
    target = w["rule"].get("max_price_eur")
    if matches:
        best = min(matches, key=_rank)
        events += await _act_once(w, best, ms, notify_client)
    elif offers and target is not None:
        cheapest = min((o for o in offers if o.get("price_eur") is not None), key=_rank, default=None)
        if cheapest:
            f = buy_or_wait(cheapest["url"], target)
            events.append(Event("forecast", {"watch_id": watch_id, "url": cheapest["url"]} | f, ms()))
    store.save_watch(watch_id, {k: v for k, v in w.items() if k != "active"},
                     active=w["active"] and w.get("status") != "filled")
    await _publish(w, events)
    events.append(Event("done", {"watch_id": watch_id, "offers": len(offers), "matches": len(matches),
                                 "ms": ms()}, ms()))
    return events


async def _judge_one(w: dict, o: dict, events: list[Event], ms: Callable[[], int]) -> tuple[bool, str | None]:
    """Snapshot, register, lie-detect, fingerprint and judge one offer. Returns (match, skip code)."""
    wid, url = w["id"], o["url"]
    lie_detector(o)
    last = store.history(url)[-1:] or [{}]
    prev_price, prev_stock = last[0].get("price_eur"), last[0].get("in_stock")
    store.save_offer(dict(o))   # copy: save_offer drops "raw" from the dict it is given
    store.snapshot(url, o.get("price_eur"), o.get("in_stock"))
    o["offer_id"] = buy.register_offer(wid, o)   # provenance: only these ids can be bought for this watch
    drop = None
    if prev_price and o.get("price_eur") is not None and o["price_eur"] < prev_price:
        drop = {"from_eur": prev_price, "to_eur": o["price_eur"]}
    if (co := (o.get("raw") or {}).get("counter_offer")) and drop is None:
        drop = {"from_eur": co["was_eur"], "to_eur": co["price_eur"], "via": "counter_offer"}
    fp = fingerprint(o, w["rule"])
    seen = w["fingerprints"].get(url)
    if seen and seen.get("fp") == fp and not seen.get("match"):
        line = f"skipped: page unchanged since last check (sha256 {fp[:12]})"
        store.log_decision(wid, url, o.get("price_eur"), "skip", line)
        events.append(Event("decision", {"watch_id": wid, "url": url, "match": False, "line": line,
                                         "price_eur": o.get("price_eur"), "unchanged": True,
                                         "offer_id": o["offer_id"]}, ms()))
        return False, None
    ctx = {"ref_price": w["ref_prices"].get(url), "prev_in_stock": prev_stock}
    ok, line, code = _evaluate(w["rule"], o, ctx)
    if code != "move" and o.get("price_eur") is not None:
        w["ref_prices"][url] = o["price_eur"]
    w["fingerprints"][url] = {"fp": fp, "match": ok}
    store.log_decision(wid, url, o.get("price_eur"), "match" if ok else "skip", line)
    data = {"watch_id": wid, "url": url, "match": ok, "line": line, "price_eur": o.get("price_eur"),
            "offer_id": o["offer_id"]}
    if (o.get("raw") or {}).get("lie_detector"):
        data["lie_detector"] = o["raw"]["lie_detector"]
    if (o.get("raw") or {}).get("counter_offer"):
        data["counter_offer"] = o["raw"]["counter_offer"]["code"]
    if drop:
        data["price_drop"] = drop
    events.append(Event("decision", data, ms()))
    return ok, (None if ok else code)


# ---- haggle loop (ACP intent traces -> counter-offer) -------------------------------------------

def _reason_code(o: dict, rule: dict, code: str) -> str:
    mp = rule.get("max_price_eur")
    ship = o.get("shipping_eur") or 0
    if code == "price" and ship and mp is not None and o["price_eur"] - ship <= mp:
        return "shipping_cost"
    return "price_sensitivity"


def competitor(w: dict, offers: list[dict], exclude_url: str) -> dict | None:
    """The cheapest other offer of the same kind the person would consider (condition + trust filters),
    in stock. It is the shop's reason to move."""
    r = w["rule"]
    conds, mt = r.get("conditions") or [], r.get("min_trust")
    pool = [o for o in offers if o["url"] != exclude_url and o.get("price_eur") is not None
            and o.get("source") != mockshop.DOMAIN and o.get("in_stock") is not False
            and (not conds or o.get("condition") in conds)
            and (mt is None or (o.get("trust") is not None and o["trust"] >= mt))]
    return min(pool, key=lambda o: o["price_eur"], default=None)


async def _haggle(w: dict, offers: list[dict], skipped: list[tuple[dict, str]], events: list[Event],
                  ms: Callable[[], int]) -> list[dict]:
    """For each price-skipped mock-shop offer: send the shop an intent trace (why we walk away + the
    competitor price). A counter-offer comes back as a new offer for the same rule. Once per URL+price."""
    out: list[dict] = []
    wid, rule = w["id"], w["rule"]
    for o, code in skipped:
        pid = mockshop.product_id_from_url(o["url"])
        if code not in ("price", "true_cost") or not pid or mockshop.counter_code_from_url(o["url"]):
            continue
        done = w["haggles"].get(o["url"])
        if done and done.get("price_eur") == o["price_eur"]:
            continue
        comp = competitor(w, offers, o["url"])
        reason = _reason_code(o, rule, code)
        trace = {"intent": "decline", "reason_code": reason,
                 "metadata": {"watch_id": wid, "offered_price_eur": o["price_eur"],
                              "target_price_eur": rule.get("max_price_eur") or rule.get("max_true_cost_eur"),
                              "competitor_price_eur": comp["price_eur"] if comp else None,
                              "competitor_url": comp["url"] if comp else None,
                              "competitor_source": comp.get("source") if comp else None}}
        answer = mockshop.intent_feedback(pid, trace)
        c = answer["counter_offer"]
        comp_txt = f", competitor {_eur(comp['price_eur'])} at {comp.get('source')}" if comp else ", no competitor"
        line = f"haggle: declined {_eur(o['price_eur'])} ({reason}{comp_txt}) -> intent trace sent to {mockshop.DOMAIN}"
        store.log_decision(wid, o["url"], o["price_eur"], "haggle", line)
        events.append(Event("haggle", {"watch_id": wid, "url": o["url"], "line": line, "trace": trace}, ms()))
        w["haggles"][o["url"]] = {"price_eur": o["price_eur"], "at": time.time(),
                                  "counter": c["code"] if c else None}
        if not c:
            line = f"counter: none ({answer['answer']})"
            store.log_decision(wid, o["url"], o["price_eur"], "counter", line)
            events.append(Event("counter", {"watch_id": wid, "url": o["url"], "line": line, "counter_offer": None}, ms()))
            continue
        line = (f"counter: shop offers {_eur(c['price_eur'])} (was {_eur(c['was_eur'])}, -{c['discount_pct']:g}%, "
                f"{c['why']}), code {c['code']}, valid 15 min")
        store.log_decision(wid, c["url"], c["price_eur"], "counter", line)
        events.append(Event("counter", {"watch_id": wid, "url": c["url"], "line": line, "counter_offer": c}, ms()))
        co = to_dict(mockshop.as_counter_offer(c["code"]))
        co["trust"] = o.get("trust", co.get("trust"))
        out.append(co)
    return out


# ---- leases: signed callbacks for agents --------------------------------------------------------

async def _publish(w: dict, events: list[Event]) -> None:
    """watch.match / price.drop to every live lease on this watch. Never breaks the watch."""
    try:
        for e in events:
            if e.type == "action":
                res = e.data.get("result") or {}
                await lease.publish("watch.match", w["id"], {
                    "watch_id": w["id"], "url": e.data["url"], "line": e.data["line"],
                    "status": res.get("status"), "level": res.get("level"),
                    "price_eur": (res.get("receipt") or {}).get("paid_eur")})
        drops = [e for e in events if e.type == "decision" and e.data.get("price_drop")]
        for e in drops:
            await lease.publish("price.drop", w["id"], {"watch_id": w["id"], "url": e.data["url"]}
                                | e.data["price_drop"])
    except Exception as exc:   # a broken callback must never stop a watcher
        store.log_decision(w["id"], None, None, "error", f"lease delivery failed: {type(exc).__name__}")


async def _act_once(w: dict, best: dict, ms: Callable[[], int], notify_client: Any) -> list[Event]:
    """Act on the best match, unless we already acted on this URL at this price or lower."""
    last = w.get("last_action") or {}
    if last.get("url") == best["url"] and last.get("price_eur") is not None \
            and best["price_eur"] >= last["price_eur"]:
        line = f"held: already acted at {_eur(last['price_eur'])} on this offer"
        store.log_decision(w["id"], best["url"], best["price_eur"], "hold", line)
        return [Event("decision", {"watch_id": w["id"], "url": best["url"], "match": True, "line": line,
                                   "price_eur": best["price_eur"]}, ms())]
    result = await buy.act(w, best, client=notify_client)
    line = f"{result['level']} {result['status']}: {result.get('savings_line') or result.get('reason', '')}"
    refused = result["status"] == "refused"
    store.log_decision(w["id"], best["url"], best["price_eur"], "refuse" if refused else "act", line)
    if not refused:   # a refused checkout is not "acted on": the next fair checkout may still go through
        w["last_action"] = {"url": best["url"], "price_eur": best["price_eur"], "at": time.time(),
                            "level": result["level"], "status": result["status"]}
    active = True
    if result["status"] == "bought":
        w["status"], active = "filled", False
    store.save_watch(w["id"], {k: v for k, v in w.items() if k != "active"}, active=active)
    return [Event("action", {"watch_id": w["id"], "url": best["url"], "line": line, "result": result}, ms())]


async def check_pinned(url: str, notify_client: Any = None) -> list[Event]:
    """Re-check every active watch pinned to this URL (mock-shop price change, monitor webhook)."""
    events: list[Event] = []
    for w in store.list_watches(active_only=True):
        if url in (w.get("pinned_urls") or []):
            events += await check_watch(w["id"], only_pinned=True, notify_client=notify_client)
    return events


async def run_all(hunt: Hunt | None = None) -> dict[str, list[Event]]:
    """One pass over every active watch (and a retry of lease deliveries that are due)."""
    out = {w["id"]: await check_watch(w["id"], hunt) for w in store.list_watches(active_only=True)}
    try:
        await lease.retry_due()
    except Exception:
        pass
    return out


def watch_proof(watch_id: str) -> dict | None:
    """GET /watches/{id}/proof: open mandate -> closed mandates -> hash chain (see agora.proof)."""
    return proof.watch_proof(watch_id)


async def run_forever(every_s: float = 3600, hunt: Hunt | None = None) -> None:
    """Background loop for the API process (cheap: hunts use the shared Context.dev cache/limiter)."""
    while True:
        await run_all(hunt)
        await asyncio.sleep(every_s)


# ---- Context.dev semantic monitors -----------------------------------------

def monitor_instructions(w: dict) -> str:
    r = w["rule"]
    parts = []
    if r.get("max_price_eur") is not None:
        parts.append(f"alert only if the price of {w['need']['thing']} drops below {_eur(r['max_price_eur'])} "
                     f"(or the equivalent in another currency)")
    else:
        parts.append(f"alert only if the price of {w['need']['thing']} drops")
    parts.append("or if it comes back in stock. Ignore layout, reviews, ads, dates and recommendations.")
    return " ".join(parts)


async def create_page_monitor(watch_id: str, url: str, webhook_url: str | None = None,
                              every_hours: int = 6, creator: Callable[..., Any] | None = None) -> dict:
    """Ask Context.dev to watch one offer page semantically and call our webhook on a real drop."""
    w = store.get_watch(watch_id)
    if w is None:
        raise KeyError(watch_id)
    if creator is None:
        from agora import contextdev
        creator = getattr(contextdev, "create_monitor", None) or getattr(contextdev, "watch_page")
    instructions = monitor_instructions(w)
    res = creator(name=f"agora {watch_id}", url=url, instructions=instructions, webhook=webhook_url,
                  every_hours=every_hours)
    if inspect.isawaitable(res):
        res = await res
    mon = {"monitor_id": (res or {}).get("id"), "url": url, "instructions": instructions,
           "created_at": time.time()}
    w["monitors"] = (w.get("monitors") or []) + [mon]
    if url not in w["pinned_urls"]:
        w["pinned_urls"].append(url)
    store.save_watch(watch_id, {k: v for k, v in w.items() if k != "active"}, active=w["active"])
    store.log_decision(watch_id, url, None, "monitor", f"Context.dev monitor {mon['monitor_id']}: {instructions}")
    return mon


_SEEN_DELIVERIES: set[str] = set()


def _dig(d: Any, *paths: tuple[str, ...]) -> Any:
    for path in paths:
        cur = d
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if cur:
            return cur
    return None


async def handle_monitor_webhook(payload: dict, delivery_id: str | None = None,
                                 notify_client: Any = None) -> dict:
    """Context.dev `change.detected` webhook -> find the watch -> re-check its pinned pages now."""
    if delivery_id:
        if delivery_id in _SEEN_DELIVERIES:
            return {"ok": True, "duplicate": True}
        _SEEN_DELIVERIES.add(delivery_id)
    mon_id = _dig(payload, ("monitor_id",), ("data", "monitor_id"), ("data", "monitor", "id"), ("monitor", "id"))
    url = _dig(payload, ("url",), ("data", "url"), ("data", "target", "url"), ("data", "monitor", "target", "url"))
    summary = _dig(payload, ("data", "change", "summary"), ("data", "summary"), ("summary",)) or "page changed"
    hits = [w for w in store.list_watches(active_only=True)
            if any(m.get("monitor_id") == mon_id for m in w.get("monitors") or [])
            or (url and url in (w.get("pinned_urls") or []))]
    out: dict[str, Any] = {"ok": True, "monitor_id": mon_id, "watches": []}
    for w in hits:
        store.log_decision(w["id"], url, None, "monitor", f"monitor says: {summary}")
        evs = await check_watch(w["id"], only_pinned=True, notify_client=notify_client)
        out["watches"].append({"watch_id": w["id"], "events": [{"type": e.type, "data": e.data} for e in evs]})
    return out


# ---- buy or wait ------------------------------------------------------------

def forecast(points: list[tuple[float, float]], target_eur: float, now: float | None = None) -> dict:
    """Least-squares line through (ts, price). Days until the trend crosses the target. Honest when thin."""
    pts = sorted((t, p) for t, p in points if p is not None)
    n = len(pts)
    if n == 0:
        return {"advice": None, "days": None, "confidence": "none", "n": 0, "basis": "no price history yet"}
    current = pts[-1][1]
    if current <= target_eur:
        return {"advice": "buy now", "days": 0, "confidence": "high", "n": n, "current_eur": current,
                "basis": f"current {_eur(current)} already <= target {_eur(target_eur)}"}
    span_days = (pts[-1][0] - pts[0][0]) / 86400
    if n < 3 or span_days < 1:
        return {"advice": None, "days": None, "confidence": "none", "n": n, "current_eur": current,
                "basis": f"only {n} price point(s) over {span_days * 24:.0f} h: too little history to forecast"}
    t0 = pts[0][0]
    xs = [(t - t0) / 86400 for t, _ in pts]
    ys = [p for _, p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    base = {"n": n, "current_eur": current, "slope_eur_per_day": round(slope, 2)}
    if slope >= -0.01:
        return base | {"advice": "buy now" if slope > 0 else None, "days": None, "confidence": "low",
                       "basis": f"trend {slope:+.2f} €/day over {n} points in {span_days:.0f} d: no drop in sight"}
    days = (current - target_eur) / -slope
    conf = "medium" if n >= 7 and span_days >= 14 else "low"
    if days > 90:
        return base | {"advice": "buy now", "days": round(days), "confidence": "low",
                       "basis": f"at {slope:.2f} €/day it takes ~{days:.0f} days to reach {_eur(target_eur)}"}
    return base | {"advice": f"wait ~{max(1, round(days))} days", "days": round(days), "confidence": conf,
                   "basis": f"trend {slope:.2f} €/day over {n} points in {span_days:.0f} d -> "
                            f"{_eur(target_eur)} in ~{days:.0f} days"}


def buy_or_wait(url: str, target_eur: float, now: float | None = None) -> dict:
    """Forecast from this URL's snapshot history."""
    return forecast([(h["seen_at"], h["price_eur"]) for h in store.history(url)], target_eur, now)


handle_webhook = handle_monitor_webhook   # name agora.api looks for


# ---- price to beat -> ready-made watches -----------------------------------

def suggest_watches(offers: list[Offer | dict], min_trust: float = 0.7) -> list[dict]:
    """Every losing offer already knows the sticker at which it would win (judge: raw['beat_eur']).
    That number IS a watch rule: pin the page, fire when it drops to its price to beat."""
    out = []
    for o in offers:
        d = to_dict(o) if not isinstance(o, dict) else o
        raw = (o.raw if isinstance(o, Offer) else d.get("raw")) or {}
        beat, gap = raw.get("beat_eur"), raw.get("gap_eur")
        if beat is None or not gap or gap <= 0 or (d.get("trust") or 0) < min_trust:
            continue
        out.append({
            "url": d["url"], "source": d.get("source"), "condition": d.get("condition"),
            "price_eur": d.get("price_eur"), "beat_eur": beat, "gap_eur": gap,
            "rule": {"max_price_eur": beat, "min_trust": min_trust},
            "label": f"{d.get('source')} ({d.get('condition')}): wins at <= {_eur(beat)}, now {_eur(d.get('price_eur') or 0)}",
        })
    return sorted(out, key=lambda s: s["gap_eur"])
