/* Agora lab viewer: renders the /hunt event stream, the watch stage and share links.
   Vanilla JS, no build step. Written at Junction 2026. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  // ---------- formatting ----------
  function eur(x, dec) {
    if (x == null || isNaN(x)) return "€—";
    const v = Number(x);
    const d = dec ?? (Math.abs(v - Math.round(v)) < 0.005 ? 0 : 2);
    return (v < 0 ? "−€" : "€") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  const eurShort = (x) => eur(x, Math.abs(x) >= 100 ? 0 : Math.abs(x) >= 10 ? 0 : 2);
  const perLabel = (per) => (per === "job" ? "/job" : "/mo");
  const unitLabel = { hour: "/h", m2: "/m²", job: "/job" };
  const CUR = { USD: "$", GBP: "£", EUR: "€", SEK: "kr ", NOK: "kr ", DKK: "kr ", CHF: "CHF ", PLN: "zł " };
  const slugify = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
  const domainOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
  const b64url = (s) => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const goLink = (url) => `/go/${S.shareId || "-"}/${b64url(url)}`;
  const WARN = /too good|risky|grey|does not ship|not costed|disputed|unconfirmed|outside the eu|mismatch|scam|new seller|stock photo/i;

  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("on"), 2600);
  }

  async function api(method, path, body) {
    const r = await fetch(path, {
      method, headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await r.json(); } catch { /* empty */ }
    if (!r.ok) throw new Error((data && (data.detail || data.message)) || `${r.status} ${r.statusText}`);
    return data;
  }

  // ---------- state ----------
  const COLS = ["new", "refurbished", "used", "rental", "service"];
  const LANE_ORDER = ["new", "refurbished", "used", "rental", "service", "lookalike", "sibling"];
  const S = {
    es: null, run: 0, q: "", mode: "auto", speed: 1, axis: "price",
    recordings: [], shareId: null, sharedBy: null, myShare: null,
    offers: new Map(), tiles: new Map(), lanes: new Map(), order: 0,
    leadUrl: null, bestUrl: null, final: false, t0: 0, done: false, events: 0,
    live: { free: 0, paid: 0, cache: 0 }, budget: null,
    replay: false, idle: "skip", skipped: 0, capped: new Map(), prevLead: null,
  };

  // ---------- segmented controls ----------
  function seg(id, key, onChange) {
    const root = $(id);
    root.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      $$("button", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      onChange(b.dataset[key]);
    });
  }
  seg("#modeSeg", "mode", (v) => { S.mode = v; store.set("agora.mode", v); });
  seg("#speedSeg", "speed", (v) => { S.speed = Number(v); store.set("agora.speed", v); });
  seg("#axisSeg", "axis", (v) => { S.axis = v; layoutLadder(); });
  seg("#idleSeg", "idle", (v) => { S.idle = v; store.set("agora.idle", v); });
  function restoreSeg(id, key, val) {
    if (!val) return;
    const b = $(`${id} button[data-${key}="${val}"]`);
    if (b) b.click();
  }
  restoreSeg("#modeSeg", "mode", store.get("agora.mode"));
  restoreSeg("#speedSeg", "speed", store.get("agora.speed"));
  restoreSeg("#idleSeg", "idle", store.get("agora.idle"));

  // ---------- clock ----------
  function tick() {
    if (S.es && !S.done) {
      $("#clock").textContent = ((performance.now() - S.t0) / 1000).toFixed(1) + "s";
      requestAnimationFrame(tick);
    }
  }

  // ---------- hunt lifecycle ----------
  function stop() {
    if (S.es) { S.es.close(); }
    S.es = null;
    $("#clock").classList.remove("live");
    $("#go").textContent = "Hunt";
  }

  function reset() {
    S.offers.clear(); S.tiles.clear(); S.lanes.clear();
    S.order = 0; S.leadUrl = S.bestUrl = null; S.final = false; S.done = false; S.events = 0;
    S.live = { free: 0, paid: 0, cache: 0 }; S.budget = null;
    S.skipped = 0; S.capped = new Map(); S.prevLead = null;
    $("#lanes").innerHTML = "";
    $("#cards").innerHTML = "";
    $("#wire").innerHTML = "";
    $("#needline").innerHTML = "";
    $("#lead").textContent = "";
    $("#errBanner").hidden = true;
    $("#depPanel").hidden = true;
    $("#srcCount").textContent = "0 pages";
    $("#offerCount").textContent = "0";
    $("#wireCount").textContent = "0 events";
    $("#shareOut").innerHTML = ""; $("#shareStats").textContent = "";
    renderVerdict(null);
    delete $(".ladder-wrap").dataset.touched;
    buildLadder();
    renderMeter();
  }

  function start(q) {
    q = (q || "").trim();
    if (q.length < 2) { $("#q").focus(); return; }
    stop();
    reset();
    S.q = q;
    $("#q").value = q;
    $("#shareBtn").disabled = false;
    const slug = slugify(q);
    const recorded = S.recordings.includes(slug);
    let replay = S.mode === "replay" || (S.mode === "auto" && recorded);
    if (S.mode === "replay" && !recorded) {
      showErr(`No recording for “${q}”. Recorded: ${S.recordings.join(", ") || "none"}. Switch to Live or Auto.`);
      return;
    }
    const params = new URLSearchParams({ q });
    S.replay = replay;
    if (replay) {
      params.set("replay", slug); params.set("speed", String(S.speed));
      if (S.idle === "skip") params.set("max_gap", "1.5");
    }
    document.body.classList.add("hunting");
    const page = new URLSearchParams({ q });
    if (S.shareId) { page.set("share", S.shareId); if (S.sharedBy) page.set("by", S.sharedBy); }
    history.replaceState(null, "", "/?" + page.toString());
    $("#budgetState").textContent = replay ? `replay ${S.speed}×${S.idle === "skip" ? " · idle time skipped" : ""} · 0 credits` : "live";
    $("#kCacheLbl").textContent = replay ? "replayed from recording" : "cache hits";
    if (!replay) loadLedger();
    const run = ++S.run;
    S.t0 = performance.now();
    S.es = new EventSource("/hunt?" + params.toString());
    $("#clock").classList.add("live");
    $("#go").textContent = "Stop";
    requestAnimationFrame(tick);
    S.es.onmessage = (m) => {
      if (run !== S.run) return;
      let ev;
      try { ev = JSON.parse(m.data); } catch { return; }
      try { handle(ev); } catch (err) { console.error(err, ev); }
    };
    S.es.onerror = () => {
      if (run !== S.run) return;
      if (!S.done) showErr("The stream closed before the hunt finished.");
      S.done = true;
      stop();
    };
  }

  function showErr(msg) {
    const b = $("#errBanner");
    b.textContent = msg;
    b.hidden = false;
  }

  // ---------- event router ----------
  function handle(ev) {
    const d = ev.data || {};
    S.events++;
    if (d.idle_skipped_ms != null) S.skipped = d.idle_skipped_ms;
    wire(ev);
    switch (ev.type) {
      case "need": return onNeed(d.need || {});
      case "lane": return ensureLane(d.lane, d);
      case "source": return onSource(d);
      case "skip": return onSkip(d);
      case "offer": return d.offer && onOffer(d.offer);
      case "truecost": return onTrueCost(d);
      case "rank": return onRank(d);
      case "verdict": return onVerdict(d);
      case "late": return flashLead(esc(d.note || "late page"));
      case "thing":
        $("#needline").insertAdjacentHTML("beforeend", ` · <b>${esc(d.n_offers)}</b> offers resolve to <b>${esc(d.name)}</b>`);
        return;
      case "depreciation": return onDepreciation(d);
      case "budget": S.budget = d; return renderMeter();
      case "done":
        S.done = true;
        // a replay with idle time skipped shows the replayed clock, not the recorded one
        $("#clock").textContent = ((S.replay && S.skipped ? ev.t_ms : d.ms) / 1000 || 0).toFixed(1) + "s";
        $("#budgetState").textContent = S.replay
          ? `replayed · 0 credits${S.skipped > 500 ? ` · ${(S.skipped / 1000).toFixed(1)}s idle skipped` : ""}`
          : `done · ${((d.ms || 0) / 1000).toFixed(1)}s`;
        if (S.replay && S.skipped > 500) $("#clock").title = `recorded hunt took ${((d.ms || 0) / 1000).toFixed(1)}s; idle waits for slow pages were skipped`;
        stop();
        sortCards();
        return;
      case "error":
        return showErr(`${d.where || "hunt"}: ${d.message || "error"}`);
      default: return;
    }
  }

  function wire(ev) {
    const d = ev.data || {};
    const msg = {
      need: () => `${d.need?.kind || ""} · ${d.need?.thing || ""}`,
      lane: () => `${d.lane}${d.via ? " via " + d.via : ""} · ${(d.queries || []).join(" | ")}`,
      source: () => `${d.domain || domainOf(d.url)} → ${d.lane}`,
      skip: () => `${domainOf(d.url)}: ${d.reason}`,
      offer: () => `${d.offer?.source} ${eur(d.offer?.price_eur)} ${d.offer?.condition} (${d.offer?.read_via})`,
      truecost: () => `${domainOf(d.url)} ${d.true_cost ? eurShort(d.true_cost.per_month_eur) + perLabel(d.true_cost.per) : "not costed"}`,
      rank: () => d.reason || "rank",
      verdict: () => (d.provisional ? "PROVISIONAL " : "FINAL ") + (d.verdict?.headline || ""),
      late: () => d.note,
      thing: () => `${d.name} (${d.n_offers})`,
      depreciation: () => d.basis,
      budget: () => `${d.credits_used} credits · ${d.requests} req · ${d.cache_hits ?? 0} cached`,
      done: () => `${((d.ms || 0) / 1000).toFixed(1)}s`,
      error: () => `${d.where}: ${d.message}`,
    }[ev.type];
    const row = document.createElement("div");
    const cls = { rank: "hot", verdict: "hot", error: "hot", skip: "dim" }[ev.type];
    if (cls) row.className = cls;
    row.innerHTML = `<span class="t">${((ev.t_ms || 0) / 1000).toFixed(2)}</span><span class="k">${esc(ev.type)}</span><span class="m" title="${esc(msg ? msg() : "")}">${esc(msg ? msg() : "")}</span>`;
    const w = $("#wire");
    const stick = w.scrollTop + w.clientHeight >= w.scrollHeight - 30;
    w.appendChild(row);
    while (w.children.length > 200) w.firstChild.remove();
    if (stick) w.scrollTop = w.scrollHeight;
    $("#wireCount").textContent = `${S.events} events`;
  }

  // ---------- need / lanes / tiles ----------
  function onNeed(n) {
    const bits = [`<b>${esc(n.kind || "product")}</b>`, esc(n.thing || n.raw || "")];
    if (n.where) bits.push(esc(n.where));
    if (n.budget) bits.push(`budget ${esc(eur(n.budget))}`);
    if (n.conditions?.length) bits.push(esc(n.conditions.join(" / ")));
    $("#needline").innerHTML = bits.join(" · ");
  }

  function ensureLane(name, d = {}) {
    name = name || "other";
    let lane = S.lanes.get(name);
    if (!lane) {
      lane = document.createElement("div");
      lane.className = "lane";
      lane.dataset.lane = name;
      lane.innerHTML = `<div class="lname">${esc(name)}<small></small></div><div class="tiles"></div>`;
      const host = $("#lanes");
      const rank = (n) => { const i = LANE_ORDER.indexOf(n); return i < 0 ? 99 : i; };
      const after = [...host.children].find((el) => rank(el.dataset.lane) > rank(name));
      host.insertBefore(lane, after || null);
      S.lanes.set(name, lane);
    }
    const hint = d.why ? d.why : d.via ? `via ${d.via}` : (d.queries || [])[0];
    if (hint) $("small", lane).textContent = hint;
    return lane;
  }

  function addTile(url, laneName, label) {
    const lane = ensureLane(laneName);
    const t = document.createElement("span");
    t.className = "tile";
    t.textContent = label || domainOf(url);
    t.title = url;
    $(".tiles", lane).appendChild(t);
    S.tiles.set(url, t);
    $("#srcCount").textContent = `${S.tiles.size} pages`;
    return t;
  }

  function onSource(d) {
    if (S.tiles.has(d.url)) return;
    const t = addTile(d.url, d.lane, d.domain || domainOf(d.url));
    if (d.via) t.title += ` (via ${d.via}${d.similar_to ? ", like " + d.similar_to : ""})`;
  }

  const CAPPED = /^already \d+ pages? (?:from|on) /i;
  function onSkip(d) {
    if (CAPPED.test(d.reason || "") && !S.tiles.has(d.url)) {   // per-shop cap: one "+N shop" tile, not N failures
      const dom = domainOf(d.url);
      let c = S.capped.get(dom);
      if (!c) {
        const lane = ensureLane(d.lane || "skipped");
        c = { n: 0, el: document.createElement("span") };
        c.el.className = "tile more";
        $(".tiles", lane).appendChild(c.el);
        S.capped.set(dom, c);
      }
      c.n++;
      c.el.textContent = `+${c.n} ${dom}`;
      c.el.title = `${c.n} more page${c.n === 1 ? "" : "s"} from ${dom} not read: Agora already has enough from this shop (saves credits)`;
      return;
    }
    let t = S.tiles.get(d.url);
    if (!t) t = addTile(d.url, d.lane || "skipped");
    t.classList.remove("read");
    t.classList.add(d.timeout ? "slow" : "skip");
    t.title = `${d.url}\nskipped: ${d.reason || ""}`;
  }

  function tileFor(offer) {
    const direct = S.tiles.get(offer.url) || S.tiles.get(offer.raw?.final_url) || S.tiles.get(offer.raw?.redirected_from);
    if (direct) return direct;
    const dom = domainOf(offer.url);
    return [...S.tiles.values()].find((t) => !t.classList.contains("read") && domainOf(t.title.split("\n")[0]) === dom);
  }

  // ---------- offers ----------
  function rec(url) {
    let r = S.offers.get(url);
    if (!r) { r = { url, offer: null, tc: null, order: S.order++, open: false }; S.offers.set(url, r); }
    return r;
  }

  function onOffer(o) {
    const r = rec(o.url);
    r.offer = o;
    const t = tileFor(o);
    if (t) {
      t.classList.remove("skip", "slow");
      t.classList.add("read");
      if (o.read_via === "jsonld") t.classList.add("free");
    }
    if (o.read_via === "jsonld" || o.read_via === "mockshop") S.live.free++;
    else if (!S.replay && String(o.read_via).startsWith("contextdev")) S.live.paid++;
    else S.live.cache++;      // a replay pays nothing: every non-free read counts as "replayed from recording"
    renderMeter();
    renderCard(r);
    layoutLadder();
    $("#offerCount").textContent = String([...S.offers.values()].filter((x) => x.offer).length);
  }

  function onTrueCost(d) {
    const r = rec(d.url);
    const same = d.unchanged && r.tc;
    r.tc = d;
    if (same) return;                     // the provisional card already shows these numbers
    if (r.offer) { renderCard(r); layoutLadder(); }
  }

  const who = (t) => t ? `${t.cond || ""} ${eur(t.price_eur, 0)} at ${t.source}` : "";
  function onRank(d) {
    const top = (d.top || [])[0];
    if (top) S.leadUrl = top.url;
    if (d.leader_changed && top) {
      const old = S.prevLead && S.prevLead.url !== top.url ? S.prevLead : null;
      flashLead(`<span class="tag">leader</span>${old ? `<s>${esc(who(old))}</s><span class="arrow">→</span>` : ""}<b>${esc(who(top))}</b> ${esc(top.per_month != null ? eurShort(top.per_month) + "/mo" : "")}`);
      caption(old ? `New leader: ${who(top)}` : `First leader: ${who(top)}, ${eurShort(top.per_month)}/mo to own`);
    } else if (d.reason) flashLead(`<span class="tag">leader</span>${esc(d.reason)}`);
    if (top) S.prevLead = top;
    refreshHighlights();
  }

  function flashLead(html) {
    const el = $("#lead");
    el.innerHTML = html;
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }

  // ---------- verdict ----------
  function renderVerdict(d) {
    const v = $("#verdict");
    const lead = $("#lead");
    if (!d) {
      v.className = "verdict";
      v.innerHTML = `<div class="state"><span class="pill">${S.q ? "hunting" : "waiting"}</span><span>${S.q ? "reading the web…" : "pick a chip or type a thing"}</span></div>
        <div class="headline">${S.q ? esc(S.q) : "One box. New, refurbished, used, rental and services on one ladder, ranked by what owning it really costs."}</div>`;
      v.appendChild(lead);
      return;
    }
    const vd = d.verdict || {};
    const prov = !!d.provisional;
    v.className = "verdict " + (prov ? "prov" : "final");
    const state = prov
      ? `<span class="pill">provisional</span><span>${esc(d.pending_reads ?? 0)} reads pending · ${esc(d.offers_so_far ?? "")} offers so far</span>`
      : `<span class="pill">final</span>${vd.buy_or_wait ? `<span>${esc(vd.buy_or_wait)}</span>` : ""}`;
    const was = !prov && d.changed_from
      ? `<div class="was">changed from: <s>${esc(d.changed_from.headline || "")}</s></div>`
      : (!prov && d.changed_from === null ? `<div class="was">the provisional pick held</div>` : "");
    v.innerHTML = `<div class="state">${state}</div><div class="headline">${esc(vd.headline || "")}</div>${was}
      <ul>${(vd.lines || []).map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
    v.appendChild(lead);
  }

  function onVerdict(d) {
    renderVerdict(d);
    const vd = d.verdict || {};
    S.leadUrl = vd.best_true_cost_url || S.leadUrl;
    S.bestUrl = vd.best_offer_url || null;
    if (!d.provisional) { S.final = true; sortCards(); }
    refreshHighlights();
    if (d.changed_from && d.changed_from.headline) {
      flashLead(`<span class="tag">verdict changed</span><s>${esc(d.changed_from.headline)}</s>`);
    } else {
      // the naive pick (cheapest sticker you can trust) struck through, the real winner next to it
      const win = S.offers.get(vd.best_true_cost_url);
      const cheap = [...S.offers.values()].filter((r) => r.offer && r.tc?.true_cost && (r.tc.trust ?? 1) >= 0.6)
        .sort((a, b) => a.offer.price_eur - b.offer.price_eur)[0];
      if (win?.offer && cheap && cheap !== win && cheap.offer.price_eur < win.offer.price_eur) {
        const w = win.tc?.true_cost, c = cheap.tc.true_cost;
        flashLead(`<span class="tag">${d.provisional ? "so far" : "verdict"}</span><s>${esc(eur(cheap.offer.price_eur, 0))} ${esc(cheap.offer.source)} (cheapest sticker, ${esc(eurShort(c.per_month_eur))}/mo)</s><span class="arrow">→</span><b>${esc(eur(win.offer.price_eur, 0))} ${esc(win.offer.source)}</b> ${w ? esc(eurShort(w.per_month_eur) + "/mo to own") : ""}`);
      }
    }
  }

  // ---------- cards ----------
  function renderCard(r) {
    const o = r.offer;
    if (!o) return;
    let el = r.el;
    if (!el) {
      el = document.createElement("article");
      el.className = "card";
      el.dataset.url = r.url;
      $("#cards").querySelector(".empty-note")?.remove();
      $("#cards").appendChild(el);
      r.el = el;
      el.addEventListener("mouseenter", () => r.rung?.classList.add("hl"));
      el.addEventListener("mouseleave", () => r.rung?.classList.remove("hl"));
    }
    const tcd = r.tc || {};
    const tc = tcd.true_cost;
    const trust = tcd.trust ?? o.trust;
    // flags: "seen before" goes into a tooltip, the EU/import line becomes a badge, at most 2 shown
    const allFlags = [...(tcd.flags || o.flags || [])];
    const seen = allFlags.find((f) => /^seen before/i.test(f));
    const imp = allFlags.find((f) => /^outside the EU/i.test(f));
    const flags = allFlags.filter((f) => f !== seen && f !== imp)
      .sort((a, b) => Number(WARN.test(b)) - Number(WARN.test(a)));
    const cond = o.condition || "unknown";
    const via = { jsonld: "free read", contextdev_product: "cd product", contextdev_json: "cd json", search_highlight: "search", mockshop: "mock shop" }[o.read_via] || o.read_via || "";
    const orig = o.currency && o.currency !== "EUR" && o.price != null
      ? `<small>${esc((CUR[o.currency] || o.currency + " ") + Number(o.price).toLocaleString("en-US"))}</small>` : "";
    const unit = o.unit ? `<small>${esc(unitLabel[o.unit] || "/" + o.unit)}</small>` : "";
    const landedEur = tc && tc.per !== "job" ? Number(tc.sticker_eur || 0) + Number(tc.extras_eur || 0) : null;
    const landed = landedEur != null && o.price_eur != null && landedEur - o.price_eur >= 1
      ? `<span class="landed"><b>${esc(eur(landedEur, 0))}</b> landed${imp ? " (import VAT)" : ""}</span>` : "";
    let tcHtml;
    if (tc) {
      tcHtml = `<div class="tc"><div class="v">${esc(eurShort(tc.per_month_eur))}${perLabel(tc.per)}</div>
        <div class="k">true cost${tc.per === "job" ? "" : ` · ${esc(tc.months)} mo`} · ${esc(tc.confidence)}</div></div>`;
    } else if (r.tc) {
      tcHtml = `<div class="tc pending"><div class="v">—</div><div class="k">not costed</div></div>`;
    } else {
      tcHtml = `<div class="tc pending"><div class="v">…</div><div class="k">costing</div></div>`;
    }
    const trustHtml = trust != null
      ? `<div class="trust ${trust < 0.6 ? "low" : ""}"><span>trust ${Number(trust).toFixed(2)}</span><span class="bar"><i style="width:${Math.round(trust * 100)}%"></i></span>${tcd.price_check ? `<span>price ${esc(tcd.price_check)}</span>` : ""}</div>` : "";
    const shown = flags.slice(0, 2), rest = flags.slice(2);
    const flagsHtml = flags.length ? `<ul class="flags">${shown.map((f) => `<li class="${WARN.test(f) ? "warn" : ""}">${esc(f)}</li>`).join("")}${rest.length ? `<li class="more" title="${esc(rest.join("\n"))}">+${rest.length} more</li>` : ""}</ul>` : "";
    const band = tcd.band || (tc && tc.band) || null;
    // "typical" + "-13% vs typical" reads as a contradiction: inside the band, only non-median badges show
    const badges = (band?.badges || []).filter((b) => band.label !== "typical" || !/ vs typical /.test(b));
    const bandHtml = band ? `<div class="band ${esc(band.label)}" title="${esc(band.basis || "")}"><span class="lbl">${esc(band.label)}</span><span>${esc(eur(band.p25, 0))}–${esc(eur(band.p75, 0))} typical ${esc(band.what || "")}</span>${badges.map((b) => `<span class="bdg">${esc(b)}</span>`).join("")}</div>` : "";
    const extraFlags = [
      ...(tcd.injection || []).length ? [`page tried to instruct AI agents (${tcd.injection.join(", ")}): ignored`] : [],
      ...(tcd.coupons || []).slice(0, 2).map((c) => `code ${c.code} on the ${c.where} (${c.percent ? c.percent + "% off" : eur(c.amount, 0) + " off"}, unverified)`),
    ];
    const h0 = tcd.haggle || o.haggle;
    // only a real counter-offer: "offer €825" on an €825 listing is not haggling
    const h = h0 && h0.suggested_offer_eur != null && o.price_eur != null && h0.suggested_offer_eur < o.price_eur - 0.5 ? h0 : null;
    const haggleHtml = h ? `<div class="haggle">Haggle: offer <b>${esc(eur(h.suggested_offer_eur, 0))}</b> · fair ${esc(eur(h.fair_low_eur, 0))}–${esc(eur(h.fair_high_eur, 0))}
        <button class="btn small" data-act="copy" title="${esc(h.message)}">copy message</button></div>` : "";
    let beatHtml = "";
    if (r.url === S.leadUrl) beatHtml = `<div class="beat"><b>leads</b> on true cost</div>`;
    else if (tcd.beat_eur != null && tcd.gap_eur > 0) beatHtml = `<div class="beat">wins at <b>${esc(eur(tcd.beat_eur, 0))}</b> · needs −${esc(eur(tcd.gap_eur, 0))}</div>`;
    else if ("beat_eur" in tcd && tcd.beat_eur == null && tc) beatHtml = `<div class="beat">cannot win on true cost at any price</div>`;
    el.innerHTML = `
      <div class="top"><span class="badge ${esc(cond)}">${esc(cond === "refurbished" ? "refurb" : cond)}</span>${imp ? `<span class="badge imp" title="${esc(imp)}">import</span>` : ""}<span class="src${seen ? " seen" : ""}"${seen ? ` title="${esc(seen)}"` : ""}>${esc(o.source)}</span><span class="via">${esc(via)}</span></div>
      <div class="title" title="${esc(o.title)}">${esc(o.title)}</div>
      <div class="nums"><div class="price">${esc(eur(o.price_eur))}${unit}${orig}${landed}</div>${tcHtml}</div>
      ${trustHtml}${bandHtml}${extraFlags.length ? `<ul class="flags">${extraFlags.map((f) => `<li class="warn">${esc(f)}</li>`).join("")}</ul>` : ""}${flagsHtml}${haggleHtml}${beatHtml}
      ${tc ? receiptHtml(o, tcd, r.open) : ""}
      <div class="acts">
        <a class="btn" href="${esc(goLink(o.url))}" target="_blank" rel="noopener" data-act="out">Open ↗</a>
        <button class="btn" data-act="watch">Watch</button>
      </div>`;
    const det = $("details", el);
    if (det) det.addEventListener("toggle", () => { r.open = det.open; });
    $('[data-act="copy"]', el)?.addEventListener("click", () => {
      navigator.clipboard?.writeText(h.message).then(() => toast("Haggle message copied"), () => toast(h.message));
    });
    $('[data-act="watch"]', el).addEventListener("click", () => prefillWatch(r));
    $('[data-act="out"]', el).addEventListener("click", () => setTimeout(refreshShareStats, 900));
    el.classList.toggle("lead", r.url === S.leadUrl);
  }

  function receiptHtml(o, tcd, open) {
    const tc = tcd.true_cost;
    const ev = tcd.evidence || [];
    const byLine = new Map();
    ev.forEach((e, i) => { if (e.line_index != null && !byLine.has(e.line_index)) byLine.set(e.line_index, i + 1); });
    const lines = (tc.receipt || []).map(([label, amt], i) =>
      `<div class="ln"><span>${esc(label)}${byLine.has(i) ? `<sup>[${byLine.get(i)}]</sup>` : ""}</span><span>${esc(eur(amt))}</span></div>`).join("");
    const evs = ev.map((e, i) => `<div class="ev">[${i + 1}] ${esc(e.via || "")}${e.quote ? ` · “${esc(String(e.quote).slice(0, 140))}”` : ""} · <a href="${esc(goLink(e.url))}" target="_blank" rel="noopener">${esc(domainOf(e.url))}</a></div>`).join("");
    return `<details class="rc"${open ? " open" : ""}><summary>True cost receipt</summary>
      <div class="receipt">
        <div class="rh">${esc(o.source)} · ${tc.per === "job" ? "one job" : `${esc(tc.months)} months owned`}</div>
        ${lines}
        <div class="ln tot"><span>you are out</span><span>${esc(eur(tc.total_eur))}</span></div>
        <div class="per">${esc(eur(tc.per_month_eur))}${perLabel(tc.per)}</div>
        <div class="basis">${esc(tc.basis || "")} (${esc(tc.confidence)} confidence)</div>
        ${evs}
      </div></details>`;
  }

  function refreshHighlights() {
    for (const r of S.offers.values()) {
      if (!r.offer) continue;
      if (r.el) {
        const wasLead = r.el.classList.contains("lead");
        const isLead = r.url === S.leadUrl;
        if (wasLead !== isLead) renderCard(r);
      }
    }
    layoutLadder();
  }

  function sortKey(r) {
    const tc = r.tc?.true_cost;
    if (r.url === S.leadUrl) return -1;
    return tc ? tc.per_month_eur : 1e9 + (r.offer?.price_eur ?? 1e9);
  }

  function sortCards() {
    const host = $("#cards");
    const recs = [...S.offers.values()].filter((r) => r.el);
    const first = new Map(recs.map((r) => [r, r.el.getBoundingClientRect()]));
    recs.sort((a, b) => sortKey(a) - sortKey(b)).forEach((r) => host.appendChild(r.el));
    for (const r of recs) {   // FLIP: slide each card from where it was
      const a = first.get(r), b = r.el.getBoundingClientRect();
      const dx = a.left - b.left, dy = a.top - b.top;
      if (!dx && !dy) continue;
      r.el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
        { duration: 650, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
  }

  // ---------- ladder ----------
  let ladderRaf = 0;
  function ladderHeight() { return window.innerWidth < 680 ? 340 : 440; }

  function buildLadder() {
    const L = $("#ladder");
    const cols = [...COLS];
    if ([...S.offers.values()].some((r) => r.offer && !COLS.includes(r.offer.condition))) cols.push("other");
    L.style.setProperty("--cols", cols.length);
    L.style.setProperty("--h", ladderHeight() + "px");
    L.innerHTML = `<div></div>${cols.map((c) => `<div class="chead" data-c="${c}">${c === "refurbished" ? "refurb" : c} <b>0</b></div>`).join("")}
      <div class="axis"></div>${cols.map((c) => `<div class="col" data-c="${c}"></div>`).join("")}
      <div class="legend"><span><i class="l"></i>cheapest to own</span><span><i class="b"></i>best you can surely buy</span><span>hollow dot = low trust</span><span id="ladderEmpty"></span></div>`;
    L.dataset.cols = cols.join(",");
    for (const r of S.offers.values()) r.rung = null;
  }

  function colOf(o) { return COLS.includes(o.condition) ? o.condition : "other"; }

  function value(r) {
    if (S.axis === "tc") return r.tc?.true_cost?.per_month_eur ?? null;
    return r.offer?.price_eur ?? null;
  }

  function niceStep(span) {
    const raw = span / 5;
    const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const m = raw / p;
    return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
  }

  function layoutLadder() {
    cancelAnimationFrame(ladderRaf);
    ladderRaf = requestAnimationFrame(doLayout);
  }

  function doLayout() {
    const L = $("#ladder");
    const recs = [...S.offers.values()].filter((r) => r.offer);
    if (recs.some((r) => !COLS.includes(r.offer.condition)) && !L.dataset.cols.includes("other")) buildLadder();
    const H = ladderHeight();
    L.style.setProperty("--h", H + "px");
    const vals = recs.map(value).filter((v) => v != null && isFinite(v));
    $("#ladderNote").textContent = S.axis === "tc" ? "true cost per month (services: per job), EUR" : "sticker price, EUR";
    const emptyNote = $("#ladderEmpty");
    if (emptyNote) emptyNote.textContent = vals.length ? "" : (recs.length ? "nothing costed yet" : "");
    let lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 1000;
    if (hi - lo < 1) { hi += 10; lo = Math.max(0, lo - 10); }
    const step = niceStep(hi - lo);
    lo = Math.max(0, Math.floor(lo / step) * step);
    hi = Math.ceil(hi / step) * step;
    if (hi === lo) hi = lo + step;
    const pad = 18;
    const y = (v) => pad + (1 - (v - lo) / (hi - lo)) * (H - 2 * pad);

    const axis = $(".axis", L);
    const ticks = [];
    for (let v = lo; v <= hi + 1e-9; v += step) ticks.push(v);
    axis.innerHTML = ticks.map((v) => `<div class="tick" style="top:${y(v)}px">${esc(eur(v, step < 1 ? 2 : 0))}</div>`).join("");
    for (const col of $$(".col", L)) {
      $$(".gridline", col).forEach((g) => g.remove());
      col.insertAdjacentHTML("afterbegin", ticks.map((v) => `<div class="gridline" style="top:${y(v)}px"></div>`).join(""));
    }

    const byCol = new Map();
    for (const r of recs) {
      const c = colOf(r.offer);
      if (!byCol.has(c)) byCol.set(c, []);
      byCol.get(c).push(r);
    }
    for (const head of $$(".chead", L)) $("b", head).textContent = String((byCol.get(head.dataset.c) || []).length);
    // empty columns shrink to a narrow strip, so the lanes that have offers get the room (phones especially)
    const colNames = L.dataset.cols.split(",");
    const filled = colNames.filter((c) => byCol.has(c)).length;
    L.style.gridTemplateColumns = "58px " + colNames.map((c) => (byCol.has(c) || !recs.length ? "minmax(120px, 1fr)" : "64px")).join(" ");
    L.style.minWidth = recs.length ? `${58 + filled * 130 + (colNames.length - filled) * 64}px` : "";
    const wrap = L.parentElement;
    const firstFilled = colNames.find((c) => byCol.has(c));
    if (firstFilled && wrap.scrollWidth > wrap.clientWidth + 4 && !wrap.dataset.touched) {
      const col = $(`.col[data-c="${firstFilled}"]`, L);
      wrap.scrollTo({ left: Math.max(0, col.offsetLeft - 58), behavior: "smooth" });
    }

    for (const [c, list] of byCol) {
      const col = $(`.col[data-c="${c}"]`, L);
      if (!col) continue;
      const placed = list.map((r) => {
        const v = value(r);
        return { r, v, y: v == null || !isFinite(v) ? H - pad : y(v) };
      }).sort((a, b) => a.y - b.y);
      const gap = 26;   // keep rungs from overlapping, then pull the stack back inside the column
      for (let i = 1; i < placed.length; i++) placed[i].y = Math.max(placed[i].y, placed[i - 1].y + gap);
      const over = placed.length ? placed[placed.length - 1].y - (H - 12) : 0;
      if (over > 0) placed.forEach((p) => { p.y = Math.max(12, p.y - over); });
      for (let i = 1; i < placed.length; i++) placed[i].y = Math.max(placed[i].y, placed[i - 1].y + Math.min(gap, (H - 24) / placed.length));
      for (const p of placed) placeRung(p.r, col, p.y, p.v);
    }
  }

  function placeRung(r, col, top, v) {
    let el = r.rung;
    const fresh = !el || el.parentNode !== col;
    if (fresh) {
      el?.remove();
      el = document.createElement("div");
      el.className = "rung";
      el.style.top = "-20px";
      el.style.opacity = "0";
      col.appendChild(el);
      r.rung = el;
      el.addEventListener("click", () => {
        if (!r.el) return;
        r.el.scrollIntoView({ behavior: "smooth", block: "center" });
        r.el.classList.add("hl");
        setTimeout(() => r.el.classList.remove("hl"), 1600);
      });
    }
    const o = r.offer;
    const per = S.axis === "tc" ? perLabel(r.tc?.true_cost?.per) : (o.unit ? unitLabel[o.unit] || "" : "");
    el.innerHTML = `<span class="p">${v == null ? "—" : esc(eurShort(v)) + esc(per)}</span><span class="s">${esc(o.source)}</span>`;
    el.title = `${o.title}\n${eur(o.price_eur)} · ${o.source}${r.tc?.true_cost ? `\ntrue cost ${eur(r.tc.true_cost.per_month_eur)}${perLabel(r.tc.true_cost.per)}` : ""}`;
    const trust = r.tc?.trust ?? o.trust;
    el.classList.toggle("lead", r.url === S.leadUrl);
    el.classList.toggle("best", r.url === S.bestUrl);
    el.classList.toggle("risky", trust != null && trust < 0.6);
    el.classList.toggle("ghost", v == null);
    if (fresh) {
      requestAnimationFrame(() => requestAnimationFrame(() => { el.style.top = top + "px"; el.style.opacity = ""; }));
    } else {
      el.style.top = top + "px";
    }
  }

  window.addEventListener("resize", () => layoutLadder());
  // once someone scrolls the ladder by hand, stop auto-scrolling it
  $(".ladder-wrap").addEventListener("pointerdown", (e) => { e.currentTarget.dataset.touched = "1"; });

  // ---------- budget meter ----------
  let shownCredits = 0;
  function renderMeter() {
    const b = S.budget;
    const free = b ? (b.saved_by_free_reads ?? 0) : S.live.free;
    const cache = b ? (b.cache_hits ?? 0) : S.live.cache;
    const paid = b ? (b.requests ?? 0) : (S.replay ? 0 : S.live.paid);
    const credits = b ? Number(b.credits_used || 0) : 0;
    const total = Math.max(1, free + cache + paid);
    const [f, c, p] = $$("#stack i");
    f.style.width = (100 * free / total) + "%";
    c.style.width = (100 * cache / total) + "%";
    p.style.width = (100 * paid / total) + "%";
    $("#kFree").textContent = String(free);
    $("#kCache").textContent = String(cache);
    $("#kPaid").textContent = String(paid);
    $("#kPages").textContent = b ? `${b.pages ?? "—"} · ${b.offers ?? "—"}` : `${S.tiles.size} · ${[...S.offers.values()].filter((r) => r.offer).length}`;
    if (b?.free_reads?.length) $("#kFree").title = b.free_reads.join(", ");
    tweenCredits(credits, b);
    if (S.replay) $("#ledgerNote").textContent = "Replayed from a recording of a live hunt: 0 credits, 0 requests. Live hunts share Context.dev's 10 requests/minute.";
  }

  function tweenCredits(to, b) {
    const from = shownCredits;
    const t0 = performance.now();
    const el = $("#credits");
    const unit = b?.credit_eur != null ? ` credits · ${eur(b.credit_eur)}` : " credits";
    const stepFn = (now) => {
      const k = Math.min(1, (now - t0) / 700);
      const v = from + (to - from) * (1 - Math.pow(1 - k, 3));
      el.innerHTML = `${Math.round(v * 10) / 10}<small>${esc(unit)}</small>`;
      if (k < 1) requestAnimationFrame(stepFn);
    };
    shownCredits = to;
    requestAnimationFrame(stepFn);
  }

  async function loadLedger() {
    try {
      const l = await api("GET", "/ledger");
      const all = l.all_time || {};
      const used = all.credits_used ?? l.credits_used;
      const left = l.credits_remaining ?? all.credits_remaining;
      const bits = [];
      if (used != null) bits.push(`${Math.round(used)} credits used on this machine`);
      if (left != null) bits.push(`${Number(left).toLocaleString("en-US")} left`);
      if (bits.length) $("#ledgerNote").textContent = `${bits.join(" · ")}. Context.dev allows 10 requests/minute for the whole account. Replays cost nothing.`;
    } catch { /* ledger is optional */ }
  }

  // ---------- depreciation ----------
  function onDepreciation(d) {
    const pts = (d.points || []).filter((p) => p.median_eur != null && p.year != null);
    $("#depPanel").hidden = false;
    $("#depSrc").textContent = `${d.source || ""}${d.rate != null ? ` · −${Math.round(d.rate * 100)}%/yr` : ""}`;
    if (!pts.length) { $("#dep").innerHTML = `<div class="basis">${esc(d.basis)}</div>`; return; }
    const W = 300, H = 160, px = 42, py = 34;
    const xs = pts.map((p) => p.year), ys = pts.map((p) => p.median_eur);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y1 = Math.max(...ys) * 1.1;
    const X = (v) => px + (x1 === x0 ? 0.5 : (v - x0) / (x1 - x0)) * (W - 2 * px);
    const Y = (v) => H - py - (v / y1) * (H - 2 * py);
    const path = pts.map((p, i) => `${i ? "L" : "M"}${X(p.year).toFixed(1)},${Y(p.median_eur).toFixed(1)}`).join(" ");
    const dots = pts.map((p) => {
      const me = p.model === d.model;
      return `<g><circle cx="${X(p.year)}" cy="${Y(p.median_eur)}" r="${me ? 5 : 3.5}" fill="${me ? "var(--acc)" : "var(--paper)"}"/>
        <text x="${X(p.year)}" y="${Y(p.median_eur) - 10}" text-anchor="middle" fill="var(--paper-2)" font-family="Geist Mono, monospace" font-size="10">${esc(eur(p.median_eur, 0))}</text>
        <text x="${X(p.year)}" y="${H - 16}" text-anchor="middle" fill="${me ? "var(--paper)" : "var(--mute)"}" font-family="Geist Mono, monospace" font-size="9.5">${esc(String(p.model).split(" ").slice(-2).join(" "))}</text>
        <text x="${X(p.year)}" y="${H - 4}" text-anchor="middle" fill="var(--mute-2)" font-family="Geist Mono, monospace" font-size="8.5">${esc(p.year)} · n${esc(p.n)}</text></g>`;
    }).join("");
    $("#dep").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="used price by generation">
      <line x1="${px}" x2="${W - px}" y1="${H - py}" y2="${H - py}" stroke="var(--line-2)"/>
      <path d="${path}" fill="none" stroke="var(--paper-2)" stroke-width="1.2" stroke-dasharray="3 3"/>${dots}</svg>
      <div class="basis">${esc(d.basis)}</div>`;
  }

  // ---------- share ----------
  $("#sharer").value = store.get("agora.sharer") || "";
  $("#shareBtn").addEventListener("click", async () => {
    if (!S.q) return;
    const sharer = $("#sharer").value.trim() || "anonymous";
    store.set("agora.sharer", sharer);
    try {
      const s = await api("POST", "/share", { query: S.q, sharer });
      S.myShare = s.id;
      S.shareId = s.id;
      const url = location.origin + s.path;
      $("#shareOut").innerHTML = `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>`;
      navigator.clipboard?.writeText(url).then(() => toast("Share link copied"), () => {});
      for (const r of S.offers.values()) if (r.el) renderCard(r);   // outbound links now carry the share id
      refreshShareStats();
    } catch (e) { toast("Share failed: " + e.message); }
  });

  async function refreshShareStats() {
    const id = S.shareId;
    if (!id) return;
    try {
      const s = await api("GET", "/share/" + id);
      const top = Object.entries(s.by_domain || {}).slice(0, 3).map(([d, n]) => `${d} ${n}`).join(" · ");
      $("#shareStats").textContent = `${s.clicks} click${s.clicks === 1 ? "" : "s"} credited to ${s.sharer}${top ? " · " + top : ""}`;
    } catch { /* share may be gone */ }
  }
  window.addEventListener("focus", refreshShareStats);

  // ---------- watch stage ----------
  const W = { products: [], pid: null, watchId: null, feeOn: false, story: null };

  async function loadShop(keepPid) {
    try {
      W.products = await api("GET", "/mockshop/products");
    } catch {
      $("#pTitle").textContent = "Mock shop is not mounted on this server.";
      $$("#dropBtn, #feeBtn, #resetBtn, #armBtn").forEach((b) => { b.disabled = true; });
      return;
    }
    const sel = $("#shopProduct");
    const pid = keepPid || W.pid || W.products[0]?.id;
    sel.innerHTML = W.products.map((p) => `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join("");
    sel.value = pid;
    renderShop();
  }

  function product() { return W.products.find((p) => p.id === W.pid) || W.products[0]; }

  function renderShop(dropped) {
    W.pid = $("#shopProduct").value || W.products[0]?.id;
    const p = product();
    if (!p) return;
    $("#pTitle").textContent = p.title;
    const pr = $("#pPrice");
    pr.textContent = eur(p.price_eur);
    if (dropped) { pr.classList.remove("drop"); void pr.offsetWidth; pr.classList.add("drop"); }
    $("#pMeta").textContent = `${p.condition} · ${p.stock} in stock · agora-mockshop.local`;
    const log = p.price_log || [];
    if (!$("#dropTo").value) $("#dropTo").value = Math.max(1, Math.round(Number($("#wBeat").value || p.price_eur) - 11));
    const svg = $("#pSpark");
    if (log.length < 2) { svg.innerHTML = ""; return; }
    const vs = log.map((x) => x.price_eur);
    const mn = Math.min(...vs), mx = Math.max(...vs), span = mx - mn || 1;
    const pts = vs.map((v, i) => `${(i / (vs.length - 1)) * 296 + 2},${40 - ((v - mn) / span) * 34}`);
    svg.innerHTML = `<polyline points="${pts.join(" ")}" fill="none" stroke="var(--paper-2)" stroke-width="1.4" vector-effect="non-scaling-stroke"/>
      <circle cx="${pts[pts.length - 1].split(",")[0]}" cy="${pts[pts.length - 1].split(",")[1]}" r="3" fill="var(--acc)"/>`;
  }
  $("#shopProduct").addEventListener("change", () => renderShop());

  function guessProduct(q) {
    q = (q || "").toLowerCase();
    if (/85|lens|fe\b/.test(q)) return "sony-fe-85";
    if (/macbook|laptop/.test(q)) return "macbook-air-m3";
    return "sony-a7iii";
  }

  function prefillWatch(r) {
    const o = r.offer;
    const tcd = r.tc || {};
    const beat = Math.round(tcd.beat_eur ?? (o.price_eur ? o.price_eur * 0.9 : 771));
    $("#wNeed").value = S.q || o.title;
    $("#wBeat").value = beat;
    $("#wCap").value = beat + 9;
    $("#dropTo").value = Math.max(1, beat - 11);
    const pid = guessProduct(S.q + " " + o.title);
    if (W.products.some((p) => p.id === pid)) { $("#shopProduct").value = pid; renderShop(); }
    $("#wFrom").innerHTML = `From <b>${esc(o.source)}</b> ${esc(eur(o.price_eur))} (${esc(o.condition)})${tcd.beat_eur != null ? `: it wins on true cost at ${esc(eur(tcd.beat_eur, 0))}` : ""}. On stage the agent may only buy from our mock shop.`;
    $("#watch").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  $("#armBtn").addEventListener("click", async () => {
    const p = product();
    if (!p) return;
    const beat = Number($("#wBeat").value), cap = Number($("#wCap").value), days = Number($("#wDays").value || 7);
    if (!(beat > 0) || !(cap > 0)) { toast("Set a price and a cap"); return; }
    const body = {
      query: $("#wNeed").value.trim() || p.title, max_eur: beat, action: $("#wAction").value,
      mandate: { cap_eur: cap, expires_at: Date.now() / 1000 + days * 86400, merchants: ["agora-mockshop.local"] },
      pinned_urls: [p.url], use_hunt: false,
    };
    try {
      const w = await api("POST", "/watches", body);
      W.watchId = w.id;
      const sig = w.mandate?.signature || "";
      $("#armed").innerHTML = `<b>${esc(w.id)}</b> armed: ${esc(w.action)} at ≤ ${esc(eur(beat))}, cap ${esc(eur(cap))}, ${esc(days)} days · mandate ${esc(w.mandate?.alg || "")} ${esc(sig.slice(0, 12))}…`;
      $("#receipt").innerHTML = "";
      if (!$("#dropTo").value || Number($("#dropTo").value) > beat) $("#dropTo").value = Math.max(1, beat - 11);
      await loadProof();
      toast("Watch armed. Now drop the price.");
    } catch (e) { toast("Could not arm: " + e.message); }
  });

  $("#dropBtn").addEventListener("click", async () => {
    const p = product();
    const price = Number($("#dropTo").value);
    if (!p || !(price > 0)) return;
    const btn = $("#dropBtn");
    btn.disabled = true;
    try {
      const res = await api("POST", `/mockshop/products/${encodeURIComponent(p.id)}/price`, { price_eur: price, fire: true });
      const i = W.products.findIndex((x) => x.id === p.id);
      if (i >= 0) W.products[i] = res.product;
      renderShop(true);
      const evs = res.watch_events || [];
      const mine = evs.filter((e) => !W.watchId || e.data?.watch_id === W.watchId);
      const act = mine.find((e) => e.type === "action");
      if (act) showAction(act.data);
      else if (!W.watchId) toast(`Price now ${eur(price)}. ${evs.length ? evs.length + " watcher events" : "No watch armed."}`);
      else {
        const dec = mine.find((e) => e.type === "decision");
        toast(dec ? dec.data.line : `Price now ${eur(price)}: watcher looked`);
      }
      await loadProof();
      await loadShop(p.id);
    } catch (e) { toast("Price change failed: " + e.message); }
    btn.disabled = false;
  });

  $("#feeBtn").addEventListener("click", async () => {
    const p = product();
    if (!p) return;
    try {
      await api("POST", `/mockshop/products/${encodeURIComponent(p.id)}/hidden_fee`, { fee_eur: W.feeOn ? 0 : 39, label: "handling fee" });
      W.feeOn = !W.feeOn;
      $("#feeBtn").textContent = W.feeOn ? "Remove the hidden fee" : "Slip in a €39 hidden fee";
      toast(W.feeOn ? "Checkout now adds a €39 handling fee the page never showed" : "Hidden fee removed");
    } catch (e) { toast(e.message); }
  });

  $("#resetBtn").addEventListener("click", async () => {
    try {
      await api("POST", "/mockshop/reset");
      W.feeOn = false;
      $("#feeBtn").textContent = "Slip in a €39 hidden fee";
      $("#dropTo").value = "";
      await loadShop();
      syncMandateForm();
      toast("Shop reset: opening prices, full stock");
    } catch (e) { toast(e.message); }
  });

  function showAction(a) {
    const res = a.result || {};
    if (res.receipt) {
      const r = res.receipt;
      $("#receipt").innerHTML = `<div class="paper">
        <div class="rh">Agora agent · receipt</div>
        <div>${esc(r.item || "")}</div>
        <div>${esc(r.merchant || "")} · order ${esc(r.order_id || "")}</div>
        <div class="big">${esc(eur(r.paid_eur))}</div>
        <div>target ${esc(eur(r.target_eur))}${r.baseline_eur != null ? ` · was ${esc(eur(r.baseline_eur))} when you set it` : ""}</div>
        <div class="save">${esc(r.savings_line || res.savings_line || "")}</div>
        <div class="sig">mandate ${esc(r.mandate_id || "")} · sig ${esc((r.mandate_signature || "").slice(0, 24))}…<br>cart sig ${esc((r.cart_signature || "").slice(0, 24))}… · session ${esc(r.session_id || "")}</div>
      </div>`;
      toast("The agent bought it");
    } else if (res.status === "refused") {
      $("#receipt").innerHTML = `<div class="paper"><div class="rh">Agora agent · refused</div>
        <div class="big">€0 paid</div><div class="save">${esc(res.reason || "")}</div>
        <div class="sig">session ${esc(res.session_id || "")} · agreed cart ${esc(eur(res.cart_total_eur))}</div></div>`;
      toast("Refused: checkout did not match the signed cart");
    } else {
      $("#receipt").innerHTML = `<div class="paper"><div class="rh">${esc(res.level || "")} · ${esc(res.status || "")}</div>
        <div class="save">${esc(res.reason || a.line || "")}</div>${res.link ? `<div class="sig">${esc(res.link)}</div>` : ""}</div>`;
    }
  }

  function chainBlock(row, i, broken) {
    const o = row.outcome || row.decision || "";
    const cls = broken ? "broken" : o;
    const price = row.price_eur != null ? ` · ${eur(row.price_eur)}` : "";
    return `<div class="blk ${esc(cls)}"><div class="dot">${esc(i)}</div><div>
      <div class="what"><span class="o">${esc(o)}</span>${esc(row.reason || "")}${esc(price)}</div>
      <div class="h"><b>#</b>${esc((row.hash || "").slice(0, 12))} <b>← prev</b> ${esc((row.prev_hash || "").slice(0, 12))}</div></div></div>`;
  }

  function seals(p) {
    const bits = [];
    if (p.signature_ok != null) bits.push(`<span class="seal ${p.signature_ok ? "ok" : "bad"}">mandate signature</span>`);
    if (p.chain_ok != null) bits.push(`<span class="seal ${p.chain_ok ? "ok" : "bad"}">${p.chain_ok ? "chain intact" : `chain broken at #${p.first_broken_index}`}</span>`);
    const n = Array.isArray(p.chain) ? p.chain.length : p.rows;
    if (n != null) bits.push(`<span class="seal">${esc(n)} rows</span>`);
    const np = Array.isArray(p.purchases) ? p.purchases.length : p.purchases;
    if (np != null) bits.push(`<span class="seal">${esc(np)} purchase${np === 1 ? "" : "s"}</span>`);
    if (p.head) bits.push(`<span class="seal mono">head ${esc(p.head.slice(0, 10))}</span>`);
    return bits.join("");
  }

  async function loadProof() {
    if (!W.watchId) return;
    try {
      const p = await api("GET", `/watches/${encodeURIComponent(W.watchId)}/proof`);
      $("#proofbar").innerHTML = seals(p);
      $("#log").innerHTML = (p.chain || []).map((r, i) => chainBlock(r, i, p.first_broken_index != null && i >= p.first_broken_index)).join("")
        || `<div class="empty-note">no decisions yet</div>`;
      const last = (p.purchases || []).slice(-1)[0];
      if (last && !$("#receipt").innerHTML) showAction({ result: { receipt: last.data } });
    } catch (e) { $("#proofbar").innerHTML = `<span class="seal bad">${esc(e.message)}</span>`; }
  }

  $("#storyBtn").addEventListener("click", () => {
    if (W.story) { W.story.close(); W.story = null; }
    W.watchId = null;
    $("#log").innerHTML = "";
    $("#proofbar").innerHTML = "";
    $("#receipt").innerHTML = "";
    $("#armed").innerHTML = "Scripted story: skip at €980 → buy at €760 → refuse a hidden fee → catch a tampered log.";
    const blocks = new Map();   // watch_id:index -> element
    const es = new EventSource("/demo/story/refusal?pause=1.6");
    W.story = es;
    $("#storyBtn").disabled = true;
    const finish = () => { es.close(); W.story = null; $("#storyBtn").disabled = false; loadShop(); };
    es.onmessage = (m) => {
      let ev;
      try { ev = JSON.parse(m.data); } catch { return; }
      const d = ev.data || {};
      const log = $("#log");
      if (ev.type === "story") {
        log.insertAdjacentHTML("beforeend", `<div class="blk story"><div class="dot">${esc(d.step)}</div><div><div class="what">${esc(d.title)}</div><div class="txt">${esc(d.text)}</div></div></div>`);
        if (/^Bought/.test(d.title)) toast("The agent bought it");
        if (/^Refused/.test(d.title)) toast("Refused: nothing paid");
        loadShop();
      } else if (ev.type === "watch") {
        log.insertAdjacentHTML("beforeend", chainBlock({ ...d, outcome: d.decision }, d.index));
        blocks.set(`${d.watch_id}:${d.index}`, log.lastElementChild);
      } else if (ev.type === "proof") {
        $("#proofbar").innerHTML = seals(d);
        if (d.chain_ok === false && d.first_broken_index != null) {
          const el = blocks.get(`${d.watch_id}:${d.first_broken_index}`);
          if (el) { el.classList.add("broken"); el.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
          toast(`Tamper caught at decision #${d.first_broken_index}`);
        }
      } else if (ev.type === "done") {
        finish();
      }
      log.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    };
    es.onerror = finish;
  });

  // plain-words captions for the haggle story (the Stage reads them out on screen)
  function storyCaption(d) {
    const t = d.text || "";
    if (d.title === "decision" && /sold out/i.test(t)) return "The shop's page says sold out while its data says in stock: the agent believes the page and skips";
    if (d.title === "haggle") return "€1,099 is over the limit: the agent says no and tells the shop why";
    if (d.title === "counter") { const m = t.match(/offers (€[\d,]+)/); return `We said no to €1,099. The shop came back at ${m ? m[1] : "a lower price"}`; }
    if (d.title === "order") return "Bought inside your signed limit: a closed mandate for exactly this cart";
    if (d.title === "callback") return "The agent that leased this watch gets a signed callback";
    if (d.title === "verdict" && /verified/.test(t)) return "Every step is signed and hash-chained: anyone can check it";
    return null;
  }

  function playHaggle(pause = 1.4, onCaption = null) {
    return new Promise((resolve) => {
      if (W.story) { W.story.close(); W.story = null; }
      W.watchId = null;
      const log = $("#log");
      log.innerHTML = "";
      log.classList.remove("show-detail");
      $("#detailBtn").hidden = false;
      $("#detailBtn").textContent = "show technical detail";
      $("#proofbar").innerHTML = "";
      $("#receipt").innerHTML = "";
      $("#armed").innerHTML = "Haggle story (offline replay of the live Sony hunt): sold-out lie caught → €1,099 declined → the shop counters → the agent buys under a closed mandate.";
      const es = new EventSource(`/demo/buy?pause=${pause}`);
      W.story = es;
      $("#haggleBtn").disabled = true;
      let ended = false, gotDone = false;
      const finish = async (watchId) => {
        if (ended) return;
        ended = true;
        es.close(); W.story = null; $("#haggleBtn").disabled = false;
        await loadShop();
        syncMandateForm();
        resolve(watchId || null);
      };
      es.onmessage = async (m) => {
        let ev;
        try { ev = JSON.parse(m.data); } catch { return; }
        const d = ev.data || {};
        if (ev.type === "story") {
          const head = !d.text;
          const cls = head ? "" : d.detail ? "sub detail" : "sub";
          if (head) loadShop();     // the shop panel follows the story's price and banner
          log.insertAdjacentHTML("beforeend", `<div class="blk story ${cls}"><div class="dot">${esc(head ? d.step : "")}</div><div><div class="what">${esc(d.title)}</div>${head ? "" : `<div class="txt">${esc(d.text)}</div>`}</div></div>`);
          const cap = storyCaption(d);
          if (cap) { if (onCaption) onCaption(cap); else toast(cap); }
          log.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        } else if (ev.type === "proof") {
          $("#proofbar").innerHTML = seals(d) + `<span class="seal ${d.mandate_chain_ok ? "ok" : "bad"}">open → closed mandate</span>`;
        } else if (ev.type === "error") {
          toast("Story failed: " + (d.message || ""));
          finish(null);
        } else if (ev.type === "done") {
          gotDone = true;
          es.close();               // the server ends the stream next: that close is not an error
          if (d.watch_id) {
            W.watchId = d.watch_id;     // "Arm"/"Drop" and a later loadProof() now show this watch's full chain
            try {
              const p = await api("GET", `/watches/${encodeURIComponent(d.watch_id)}/proof`);
              const last = (p.purchases || []).slice(-1)[0];
              if (last) showAction({ result: { receipt: last.data } });
              addTamperButton(d.watch_id);
            } catch (e) { toast(e.message); }
          }
          finish(d.watch_id);
        }
      };
      es.onerror = () => { if (!gotDone) finish(null); };
    });
  }

  $("#haggleBtn").addEventListener("click", () => { playHaggle(1.4); });
  $("#detailBtn").addEventListener("click", () => {
    const on = $("#log").classList.toggle("show-detail");
    $("#detailBtn").textContent = on ? "hide technical detail" : "show technical detail";
  });

  // the mandate form follows the shop: after a story or a reset it never shows a stale €771 vs a €999 shop
  function syncMandateForm() {
    const p = product();
    if (!p) return;
    const beat = Math.max(1, Math.round(p.price_eur * 0.95));
    $("#wBeat").value = beat;
    $("#wCap").value = beat + 9;
    $("#dropTo").value = Math.max(1, beat - 11);
  }

  // tamper: rewrite one stored decision on the server, then let the proof find it
  function addTamperButton(watchId) {
    $("#proofbar").insertAdjacentHTML("beforeend", `<button class="btn small tamper" id="tamperBtn" title="edit one stored decision behind the agent's back">tamper with the log</button>`);
    $("#tamperBtn").addEventListener("click", () => tamper(watchId));
  }

  async function tamper(watchId) {
    try {
      const t = await api("POST", "/demo/tamper", { watch_id: watchId });
      await loadProof();
      const blk = $$("#log .blk")[t.first_broken_index];
      if (blk) { blk.classList.add("broken"); blk.scrollIntoView({ behavior: "smooth", block: "center" }); }
      const msg = t.chain_ok === false ? `Someone edited decision #${t.index}: the hash chain breaks right there` : "Edited, but the chain still verifies (unexpected)";
      caption(msg, "proof");
      return t;
    } catch (e) { toast("Tamper failed: " + e.message); return null; }
  }

  // ---------- captions + Stage (the whole demo as one take) ----------
  let capTimer;
  function caption(text, step, ms = 4200) {
    const c = $("#caption");
    if (!text) { c.classList.remove("on"); return; }
    c.innerHTML = `${step ? `<span class="step">${esc(step)}</span>` : ""}${esc(text)}`;
    c.classList.add("on");
    clearTimeout(capTimer);
    capTimer = setTimeout(() => c.classList.remove("on"), ms);
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (cond, timeoutMs) => {
    const t0 = performance.now();
    while (!cond() && performance.now() - t0 < timeoutMs) await sleep(120);
    return cond();
  };

  let staging = false;
  async function stage() {
    if (staging) return;
    staging = true;
    $("#stageBtn").disabled = true;
    $("#watch .finale")?.remove();
    try {
      const q = "sony a7 iii body";
      if (!S.recordings.includes(slugify(q))) { toast("No recording of the Sony hunt on this server"); return; }
      // 1. the hunt, replayed with idle time skipped
      const mode = S.mode, idle = S.idle;
      S.mode = "replay"; S.idle = "skip";
      caption("One search box. Agora reads new, refurbished and used shops at once", "1 · hunt");
      window.scrollTo({ top: 0, behavior: "smooth" });
      start(q);
      S.mode = mode; S.idle = idle;
      await waitFor(() => S.done, 30000);
      await sleep(600);
      // 2. the verdict, with the naive pick struck through
      $("#verdict").scrollIntoView({ behavior: "smooth", block: "start" });
      const win = S.offers.get(S.leadUrl);
      const tc = win?.tc?.true_cost;
      caption(tc ? `The cheapest sticker loses. ${win.offer.condition} ${eur(win.offer.price_eur, 0)} at ${win.offer.source} costs least to own: ${eurShort(tc.per_month_eur)}/mo`
        : "Verdict in", "2 · verdict", 5200);
      await sleep(4200);
      // 3. the winner's true-cost receipt unrolls
      if (win?.el && tc) {
        win.open = true;
        renderCard(win);
        win.el.scrollIntoView({ behavior: "smooth", block: "center" });
        const resale = (tc.receipt || []).find(([l]) => /resale/i.test(l));
        caption(`True cost: ${eur(tc.sticker_eur, 0)} now${resale ? `, ${eur(-resale[1], 0)} back when you resell` : ""} = ${eurShort(tc.per_month_eur)}/mo, every number with its source`, "3 · true cost", 5200);
        await sleep(5000);
      }
      // 4. the standing order: haggle, buy, prove
      $("#watch").scrollIntoView({ behavior: "smooth", block: "start" });
      caption("A buyer who wants it NEW with an EU warranty sets a standing order", "4 · standing order");
      await sleep(1800);
      const wid = await playHaggle(1.6, (text) => caption(text, "4 · agent"));
      if (!wid) return;
      $("#receipt").scrollIntoView({ behavior: "smooth", block: "center" });
      caption("The receipt: what it paid, under which signed mandate, for which exact cart", "5 · receipt");
      await sleep(4200);
      // 5. tamper: one edited row and the chain shows where
      $("#proofbar").scrollIntoView({ behavior: "smooth", block: "center" });
      caption("Now someone quietly edits one line of the agent's log…", "6 · proof");
      await sleep(2600);
      await tamper(wid);
      await sleep(3800);
      $("#watch .logbox").insertAdjacentHTML("beforeend", `<div class="finale">It found it, costed it <em>to the end</em>, haggled, bought within your limit, and can prove every step.</div>`);
      $("#watch .finale").scrollIntoView({ behavior: "smooth", block: "center" });
      caption(null);
    } finally {
      staging = false;
      $("#stageBtn").disabled = false;
    }
  }
  $("#stageBtn").addEventListener("click", stage);

  // ---------- search wiring ----------
  $("#form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (S.es && !S.done) { S.done = true; stop(); $("#budgetState").textContent = "stopped"; return; }
    start($("#q").value);
  });
  $("#chips").addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (c) start(c.dataset.q);
  });

  async function boot() {
    try { S.recordings = (await api("GET", "/recordings")).recordings || []; } catch { S.recordings = []; }
    for (const c of $$(".chip")) {
      if (S.recordings.includes(slugify(c.dataset.q))) c.insertAdjacentHTML("beforeend", `<span class="rec">● REC</span>`);
    }
    buildLadder();
    renderMeter();
    loadLedger();
    loadShop().then(syncMandateForm);
    const params = new URLSearchParams(location.search);
    if (params.get("share")) {
      S.shareId = params.get("share");
      S.sharedBy = params.get("by");
      const b = $("#sharedBanner");
      b.innerHTML = `Shared by <b>${esc(S.sharedBy || "someone")}</b>. Shop clicks from this page are credited to them.`;
      b.hidden = false;
      refreshShareStats();
    }
    if (params.get("q")) start(params.get("q"));
    if (params.get("stage") === "1") stage();
  }
  boot();
})();
