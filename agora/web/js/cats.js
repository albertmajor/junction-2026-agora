// The category tree of everything you can buy (agora/taxonomy via /api/categories*): the shared bits for the
// landing explorer (tree.js), the search-box suggestions (suggest.js) and the hunt breadcrumb (main.js).
// Language: the browser's (fi/en/de/nl/sv), changed by the toggle in the explorer, remembered per viewer.
import * as core from './core.js';

export const LANGS = ['en', 'fi', 'de', 'nl', 'sv'];
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function detect() {
  try { const s = localStorage.getItem('agora.lang'); if (LANGS.includes(s)) return s; } catch {}
  const list = (typeof navigator !== 'undefined' && (navigator.languages || [navigator.language])) || [];
  for (const l of list) { const k = String(l || '').slice(0, 2).toLowerCase(); if (LANGS.includes(k)) return k; }
  return 'en';
}
let lang = detect();
export const getLang = () => lang;
export function setLang(l) {
  if (!LANGS.includes(l) || l === lang) return;
  lang = l;
  try { localStorage.setItem('agora.lang', l); } catch {}
  core.emit('lang', { lang: l });
}

// ---------- UI words (the tree's own labels come from the API in the same language) ----------
const T = {
  en: { catsH: 'Categories', thingsH: 'Things', servicesH: 'Services', kicker: 'Browse', head: 'Everything you can buy, in one tree.',
    sub: n => `${n} categories of things and services, from batteries to plumbers. Pick one and we hunt it across every shop, all in.`,
    find: 'Find a category: sofa, plumber, tyres…', all: 'All categories', hunt: 'Hunt', huntFor: x => `Hunt for ${x}`,
    popular: 'Popular right now', service: 'service', digital: 'digital', property: 'housing', vehicle: 'vehicle', food: 'food',
    things: 'kinds of things', services: 'kinds of services', none: q => `No category for “${q}”.`, free: q => `Search everything for “${q}”`,
    back: 'Back', cats: 'categories', inCat: 'in', replay: 'instant replay', liveOnly: 'live only', lang: 'Language',
    pick: 'Pick a category on the left, or one of these.' },
  fi: { catsH: 'Luokat', thingsH: 'Tavarat', servicesH: 'Palvelut', kicker: 'Selaa', head: 'Kaikki mitä voi ostaa, yhdessä puussa.',
    sub: n => `${n} tuote- ja palveluluokkaa, paristoista putkimiehiin. Valitse yksi, niin etsimme sen kaikista kaupoista, hinta kaikkineen.`,
    find: 'Etsi luokka: sohva, putkimies, renkaat…', all: 'Kaikki luokat', hunt: 'Etsi', huntFor: x => `Etsi: ${x}`,
    popular: 'Suosittua nyt', service: 'palvelu', digital: 'digitaalinen', property: 'asuminen', vehicle: 'ajoneuvo', food: 'ruoka',
    things: 'tuoteryhmää', services: 'palveluryhmää', none: q => `Ei luokkaa haulle ”${q}”.`, free: q => `Hae kaikkialta: ”${q}”`,
    back: 'Takaisin', cats: 'luokkaa', inCat: 'luokassa', replay: 'nauhoitettu haku', liveOnly: 'vain live', lang: 'Kieli',
    pick: 'Valitse luokka vasemmalta tai jokin näistä.' },
  de: { catsH: 'Kategorien', thingsH: 'Dinge', servicesH: 'Dienstleistungen', kicker: 'Stöbern', head: 'Alles, was man kaufen kann, in einem Baum.',
    sub: n => `${n} Kategorien für Dinge und Dienstleistungen, von Batterien bis Klempner. Wähle eine, und wir suchen sie in allen Shops, alles inklusive.`,
    find: 'Kategorie finden: Sofa, Klempner, Reifen…', all: 'Alle Kategorien', hunt: 'Suchen', huntFor: x => `${x} suchen`,
    popular: 'Gerade beliebt', service: 'Dienstleistung', digital: 'digital', property: 'Wohnen', vehicle: 'Fahrzeug', food: 'Essen',
    things: 'Warengruppen', services: 'Dienstleistungsgruppen', none: q => `Keine Kategorie für „${q}“.`, free: q => `Überall nach „${q}“ suchen`,
    back: 'Zurück', cats: 'Kategorien', inCat: 'in', replay: 'Aufzeichnung', liveOnly: 'nur live', lang: 'Sprache',
    pick: 'Wähle links eine Kategorie oder eine davon.' },
  nl: { catsH: 'Categorieën', thingsH: 'Spullen', servicesH: 'Diensten', kicker: 'Bladeren', head: 'Alles wat je kunt kopen, in één boom.',
    sub: n => `${n} categorieën producten en diensten, van batterijen tot loodgieters. Kies er een en we zoeken in elke winkel, alles inbegrepen.`,
    find: 'Zoek een categorie: bank, loodgieter, banden…', all: 'Alle categorieën', hunt: 'Zoeken', huntFor: x => `Zoek ${x}`,
    popular: 'Nu populair', service: 'dienst', digital: 'digitaal', property: 'wonen', vehicle: 'voertuig', food: 'eten',
    things: 'soorten producten', services: 'soorten diensten', none: q => `Geen categorie voor “${q}”.`, free: q => `Overal zoeken naar “${q}”`,
    back: 'Terug', cats: 'categorieën', inCat: 'in', replay: 'opname', liveOnly: 'alleen live', lang: 'Taal',
    pick: 'Kies links een categorie, of een van deze.' },
  sv: { catsH: 'Kategorier', thingsH: 'Saker', servicesH: 'Tjänster', kicker: 'Bläddra', head: 'Allt du kan köpa, i ett träd.',
    sub: n => `${n} kategorier av varor och tjänster, från batterier till rörmokare. Välj en så letar vi i alla butiker, allt inräknat.`,
    find: 'Hitta en kategori: soffa, rörmokare, däck…', all: 'Alla kategorier', hunt: 'Sök', huntFor: x => `Sök ${x}`,
    popular: 'Populärt just nu', service: 'tjänst', digital: 'digitalt', property: 'boende', vehicle: 'fordon', food: 'mat',
    things: 'varugrupper', services: 'tjänstegrupper', none: q => `Ingen kategori för ”${q}”.`, free: q => `Sök överallt efter ”${q}”`,
    back: 'Tillbaka', cats: 'kategorier', inCat: 'i', replay: 'inspelad sökning', liveOnly: 'bara live', lang: 'Språk',
    pick: 'Välj en kategori till vänster, eller någon av dessa.' },
};
export const t = (k, ...a) => { const v = (T[lang] && T[lang][k]) ?? T.en[k]; return typeof v === 'function' ? v(...a) : v; };
export const num = n => (Number(n) || 0).toLocaleString(lang === 'en' ? 'en-GB' : lang);

// a small word after the label for anything that is not a physical product (services visibly next to things)
export function kindTag(kind) {
  if (!kind || kind === 'product') return '';
  return `<span class="ct-kind k-${esc(kind)}">${esc(t(kind) || kind)}</span>`;
}

// ---------- API (in-memory cache per URL) ----------
const cache = new Map();
export function api(path, params = {}) {
  const u = new URLSearchParams({ ...params, lang });
  for (const [k, v] of [...u]) if (v === '' || v == null) u.delete(k);
  const url = `${path}?${u}`;
  if (cache.has(url)) return cache.get(url);
  const p = fetch(url, { headers: { accept: 'application/json' } })
    .then(r => (r.ok ? r.json() : null)).catch(() => null)
    .then(j => { if (!j) cache.delete(url); return j; });
  cache.set(url, p);
  return p;
}
export const children = parent => api('/api/categories', { parent: parent || '' });
export const search = (q, limit = 8) => api('/api/categories/search', { q, limit });
export const nodes = ids => api('/api/categories/nodes', { ids: ids.join(',') });

// ---------- ask for a hunt in this category (main.js listens for 'ask' {q, cat}) ----------
export function huntCategory(label, cat) {
  const q = String(label || '').replace(/­/g, '').trim();
  if (q) core.emit('ask', { q, cat: cat || null });
}

// ---------- icons: one calm line drawing per root (24 px grid, 1.5 px stroke; .f = filled dot) ----------
const P = {
  electronics: '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
  appliances: '<rect x="5" y="3" width="14" height="18" rx="2"/><circle cx="12" cy="13.5" r="4"/><path d="M8 6.5h2"/><circle class="f" cx="16" cy="6.5" r=".8"/>',
  fashion: '<path d="M12 8c0-1.4 2-1.8 2-3.2a2 2 0 0 0-4 0"/><path d="M12 8l-8.6 7.2a1 1 0 0 0 .6 1.8h16a1 1 0 0 0 .6-1.8z"/>',
  'home-garden': '<path d="M7 14h10l-1.5 7h-7z"/><path d="M12 14V9"/><path d="M12 10.5C9 10.5 7 8.5 7 5.5c3 0 5 2 5 5zM12 9.5c0-3 2-5 5-5 0 3-2 5-5 5z"/>',
  furniture: '<path d="M5 10V8a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2"/><path d="M3 12a1.5 1.5 0 0 1 3 0v1.5h12V12a1.5 1.5 0 0 1 3 0v4.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M6 17.5V20M18 17.5V20"/>',
  diy: '<path d="M14.6 3.5a4.6 4.6 0 0 0-4.4 6L3.8 15.9a2 2 0 0 0 2.9 2.9l6.4-6.4a4.6 4.6 0 0 0 6-4.4l-2.8 2.7-2.6-.6-.6-2.6z"/>',
  'health-beauty': '<rect x="7.5" y="10" width="9" height="11" rx="2"/><path d="M10 10V7h4v3"/><path d="M12 7V4h3.5"/><path d="M10 14.5h4"/>',
  'baby-kids': '<path d="M3.5 5.5h2.5l2 8.5h10.5a6 6 0 0 0-6-7.5h-1v7.5"/><circle cx="9" cy="18.5" r="1.6"/><circle cx="17" cy="18.5" r="1.6"/>',
  'toys-games': '<rect x="4" y="4" width="16" height="16" rx="3.5"/><circle class="f" cx="9" cy="9" r="1"/><circle class="f" cx="15" cy="15" r="1"/><circle class="f" cx="15" cy="9" r="1"/><circle class="f" cx="9" cy="15" r="1"/><circle class="f" cx="12" cy="12" r="1"/>',
  'sports-outdoors': '<circle cx="12" cy="12" r="8.5"/><path d="M6 6c3 3 3 9 0 12M18 6c-3 3-3 9 0 12"/>',
  hobbies: '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.2 0 1.9-.8 1.9-1.8 0-1.5-1.3-1.7-1.3-2.9 0-1 .8-1.6 1.9-1.6h2.4a3.6 3.6 0 0 0 3.6-3.6c0-4-3.8-7.1-8.5-7.1z"/><circle class="f" cx="7.8" cy="11.5" r="1"/><circle class="f" cx="10.5" cy="7.6" r="1"/><circle class="f" cx="15" cy="8" r="1"/>',
  media: '<path d="M3.5 5.5A1.5 1.5 0 0 1 5 4h6v15.5H5A1.5 1.5 0 0 0 3.5 21z"/><path d="M20.5 5.5A1.5 1.5 0 0 0 19 4h-6v15.5h6a1.5 1.5 0 0 1 1.5 1.5z"/>',
  'food-drink': '<path d="M4.5 9.5h11.5v4.5a5 5 0 0 1-5 5h-1.5a5 5 0 0 1-5-5z"/><path d="M16 11h1.5a2.5 2.5 0 0 1 0 5H16"/><path d="M8.5 3.5c-1 1.2 1 2 0 3.5M12 3.5c-1 1.2 1 2 0 3.5"/>',
  pets: '<circle cx="6.5" cy="10.5" r="1.7"/><circle cx="10" cy="6.5" r="1.7"/><circle cx="14" cy="6.5" r="1.7"/><circle cx="17.5" cy="10.5" r="1.7"/><path d="M12 12.5c-2.6 0-5 3-5 5.2 0 1.7 1.4 2.6 3 2.1 1.3-.4 2.7-.4 4 0 1.6.5 3-.4 3-2.1 0-2.2-2.4-5.2-5-5.2z"/>',
  office: '<path d="M6 3h8.5L19 7.5V21H6z"/><path d="M14.5 3v4.5H19"/><path d="M9 12h7M9 15.5h7M9 8.5h3"/>',
  vehicles: '<path d="M3.5 15.5V12l2.2-5h12.6l2.2 5v3.5a1 1 0 0 1-1 1H4.5a1 1 0 0 1-1-1z"/><path d="M3.5 12h17"/><path d="M6 16.5v2M18 16.5v2"/><circle class="f" cx="7" cy="14" r=".9"/><circle class="f" cx="17" cy="14" r=".9"/>',
  business: '<path d="M2.5 20.5h19"/><path d="M4 20.5v-9l5 3v-3l5 3V4.5h4v16"/><path d="M8 17.5h1.5M12 17.5h1.5"/>',
  software: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18"/><path d="M10 12.5L8 14.5l2 2M14 12.5l2 2-2 2"/>',
  property: '<path d="M3.5 11L12 4l8.5 7"/><path d="M6 9.5V20h12V9.5"/><path d="M10 20v-5h4v5"/>',
  'home-services': '<path d="M9 8.5h5l1 3V20a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1v-8.5z"/><path d="M9.5 8.5V4.5h4.5l2 2h-2"/><circle class="f" cx="19" cy="5" r=".8"/><circle class="f" cx="20" cy="8.5" r=".8"/><circle class="f" cx="19" cy="12" r=".8"/>',
  trades: '<rect x="3.5" y="4" width="13" height="5" rx="1.5"/><path d="M16.5 6.5h3V12H11v3"/><rect x="9.5" y="15" width="3" height="6" rx="1"/>',
  'auto-services': '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3"/><path d="M12 3.5V9M12 15v5.5M3.5 12H9M15 12h5.5"/>',
  'beauty-wellness': '<circle cx="6.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/><path d="M8.3 15.7L18 4M15.7 15.7L6 4"/>',
  'health-services': '<rect x="4" y="4" width="16" height="16" rx="4.5"/><path d="M12 8v8M8 12h8"/>',
  education: '<path d="M2.5 9.5L12 5l9.5 4.5L12 14z"/><path d="M6.5 11.5V16c3 2.5 8 2.5 11 0v-4.5"/><path d="M21.5 9.5V14"/>',
  'events-leisure': '<path d="M3 8a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v2.2a1.8 1.8 0 0 0 0 3.6V16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-2.2a1.8 1.8 0 0 0 0-3.6z"/><path d="M14.5 7.5v1.5M14.5 11.25v1.5M14.5 15v1.5"/>',
  travel: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.4 3.4 5.4 3.4 8.5s-1 6.1-3.4 8.5c-2.4-2.4-3.4-5.4-3.4-8.5s1-6.1 3.4-8.5z"/>',
  transport: '<path d="M2.5 6h11.5v10.5H2.5z"/><path d="M14 9.5h4l3.5 3.5v3.5H14"/><circle cx="6.5" cy="17.5" r="1.8"/><circle cx="17.5" cy="17.5" r="1.8"/>',
  professional: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M3 12.5h18"/>',
  'digital-services': '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/><path d="M12 7.2l.9 1.9 1.9.9-1.9.9-.9 1.9-.9-1.9-1.9-.9 1.9-.9z"/>',
  'finance-insurance': '<path d="M12 3l7 3v5c0 4.5-3 8.4-7 10-4-1.6-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
  utilities: '<path d="M13.5 2.5L5 13.5h6.2l-1 8 8.3-11.2h-6.2z"/>',
  'personal-services': '<circle cx="9" cy="8" r="3"/><path d="M3.5 19.5c.5-3.3 2.8-5 5.5-5s5 1.7 5.5 5"/><circle cx="17" cy="9" r="2.3"/><path d="M15.6 14.2c2.6-.4 4.5 1.3 4.9 4.3"/>',
};
export function icon(root, cls = 'ct-ic') {
  const p = P[root] || '<circle cx="12" cy="12" r="3"/>';
  return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${p}</svg>`;
}
