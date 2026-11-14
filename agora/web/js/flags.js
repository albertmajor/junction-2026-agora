// flags.js: where an offer ships from, as a small country flag (line, ledger, sheet, verdict).
// The engine sends `origin` on offer and truecost events (docs/UI_ROUND_A.md section 6). Until it does,
// and for old recordings, we make a quiet guess here from the domain, the currency and the listing's
// location, and always mark it as a guess. See section 5 for the look and the tooltip wording.
import { domainOf } from './core.js';

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const EU = new Set('AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE'.split(' '));
// names that read better with "the" in a sentence ("Probably the United States: …")
const THE = new Set(['US', 'GB', 'NL', 'AE', 'PH', 'BS', 'DO']);
const NAMES = { FI: 'Finland', SE: 'Sweden', NO: 'Norway', DK: 'Denmark', DE: 'Germany', NL: 'Netherlands', BE: 'Belgium',
  FR: 'France', IT: 'Italy', ES: 'Spain', PT: 'Portugal', PL: 'Poland', AT: 'Austria', CH: 'Switzerland', IE: 'Ireland',
  GB: 'United Kingdom', EE: 'Estonia', LV: 'Latvia', LT: 'Lithuania', CZ: 'Czechia', SK: 'Slovakia', HU: 'Hungary',
  GR: 'Greece', US: 'United States', CA: 'Canada', AU: 'Australia', JP: 'Japan', ZA: 'South Africa', CN: 'China' };
let dn = null;
try { dn = new Intl.DisplayNames(['en'], { type: 'region' }); } catch { dn = null; }

/** English short name for an ISO code ("FI" → "Finland"). */
export function countryName(cc) {
  cc = String(cc || '').toUpperCase();
  if (!cc) return '';
  if (NAMES[cc]) return NAMES[cc];
  try { const n = dn && dn.of(cc); if (n && n !== cc) return n; } catch { /* unknown code */ }
  return cc;
}

// ---------- the client guess (only when the engine has not sent an origin) ----------
const TLD = { fi: 'FI', de: 'DE', se: 'SE', ee: 'EE', nl: 'NL', fr: 'FR', it: 'IT', es: 'ES', uk: 'GB', pl: 'PL', dk: 'DK',
  no: 'NO', at: 'AT', be: 'BE', ie: 'IE', pt: 'PT', cz: 'CZ', sk: 'SK', hu: 'HU', gr: 'GR', lt: 'LT', lv: 'LV', ch: 'CH',
  za: 'ZA', jp: 'JP', ca: 'CA', au: 'AU', lu: 'LU', si: 'SI', hr: 'HR', ro: 'RO', bg: 'BG' };
const CUR = { USD: 'US', GBP: 'GB', ZAR: 'ZA', JPY: 'JP', CAD: 'CA', AUD: 'AU', CHF: 'CH', SEK: 'SE', NOK: 'NO', DKK: 'DK',
  PLN: 'PL', CZK: 'CZ', HUF: 'HU' };
const CUR_WORD = { USD: 'US dollars', GBP: 'pounds', ZAR: 'rand', JPY: 'yen', CAD: 'Canadian dollars', AUD: 'Australian dollars',
  CHF: 'Swiss francs', SEK: 'Swedish kronor', NOK: 'Norwegian kroner', DKK: 'Danish kroner', PLN: 'złoty', CZK: 'koruna', HUF: 'forint' };
const KNOWN = { 'bhphotovideo.com': 'US', 'adorama.com': 'US', 'keh.com': 'US', 'walmart.com': 'US', 'newegg.com': 'US',
  'buydig.com': 'US', 'mpex.com': 'US', 'allenscamera.net': 'US', 'swappa.com': 'US', 'gazelle.com': 'US',
  'jessops.com': 'GB', 'wexphotovideo.com': 'GB', 'cvp.com': 'GB' };
const FI_CITIES = ['Helsinki', 'Espoo', 'Vantaa', 'Tampere', 'Turku', 'Oulu', 'Jyväskylä', 'Lahti', 'Kuopio', 'Pori',
  'Joensuu', 'Lappeenranta', 'Hämeenlinna', 'Vaasa', 'Rovaniemi', 'Seinäjoki', 'Kotka', 'Porvoo', 'Kerava', 'Tuusula'];

function flagsOf(item) {
  const tc = item && item.tc;
  return [].concat((tc && tc.flags) || [], (tc && tc.true_cost && tc.true_cost.flags) || [], (item && item.offer && item.offer.flags) || [])
    .map(f => typeof f === 'string' ? f : JSON.stringify(f));
}
function shipsFor(item, cc) {
  const fl = flagsOf(item);
  if (fl.some(f => /does not ship/i.test(f))) return [false, 'no, the shop does not ship to Finland'];
  if (fl.some(f => /shipping to Finland unconfirmed/i.test(f))) return [null, 'not confirmed by the shop'];
  if (fl.some(f => /\bships to Finland\b/i.test(f))) return [true, 'yes, the shop says so'];
  if (cc === 'FI') return [true, 'yes, domestic'];
  if (!cc || EU.has(cc)) return [null, 'not stated'];
  return [null, 'not confirmed by the shop'];
}

/** A guess at the origin from what the browser can see. Always confident: false. */
export function guessOrigin(item) {
  if (!item) return null;
  const o = item.offer || {};
  const host = String(o.source || domainOf(item.url) || '').toLowerCase().replace(/^www\./, '');
  const isJob = !!(item.tc && item.tc.true_cost && item.tc.true_cost.per === 'job') || /^serv/i.test(String(o.condition || ''));
  const parts = host.split('.');
  const tld = parts[parts.length - 1] || '';
  const tldCc = TLD[tld] || null;
  const known = KNOWN[host] || KNOWN[parts.slice(-2).join('.')] || null;
  const cur = String(o.currency || '').toUpperCase();
  const curCc = CUR[cur] || null;
  const loc = String(o.location || '');
  const city = FI_CITIES.map(c => [c, loc.indexOf(c)]).filter(([, i]) => i >= 0).sort((a, b) => a[1] - b[1])[0];
  const tldWord = host.endsWith('.co.uk') ? '.co.uk' : host.endsWith('.com.au') ? '.com.au' : '.' + tld;
  let cc = null, basis = 'unknown', text = 'not stated', cityName = null;
  if (city && (!tldCc || tldCc === 'FI')) {
    cc = 'FI'; cityName = city[0];
    basis = isJob ? 'service_area' : 'listing_location';
    text = isJob ? `from the provider's service area: ${loc.length > 48 ? cityName + ' region' : loc}` : "from the listing's location";
  } else if (tldCc && curCc === tldCc) {
    cc = tldCc; basis = 'domain_currency'; text = `from the ${tldWord} domain and prices in ${CUR_WORD[cur] || cur}`;
  } else if (tldCc) {
    cc = tldCc; basis = 'domain'; text = `from the ${tldWord} domain`;
  } else if (known) {
    cc = known; basis = 'known_shop'; text = 'from what we know about this shop';
  } else if (curCc) {
    cc = curCc; basis = 'currency';
    text = (tld === 'com' || tld === 'net') && curCc ? `from the .${tld} domain and prices in ${CUR_WORD[cur] || cur}` : `from prices in ${CUR_WORD[cur] || cur}`;
  }
  const [ships, shipsText] = shipsFor(item, cc);
  return {
    country_code: cc, country_name: cc ? countryName(cc) : null, city: cityName,
    basis, basis_text: text, confident: false, eu: cc ? EU.has(cc) : null,
    ships_to_fi: ships, ships_text: shipsText, _client: true,
  };
}

/** The engine's origin for an item: truecost first (recomputed after judge), then the offer's. */
export function originOf(item) {
  return (item && item.tc && item.tc.origin) || (item && item.offer && item.offer.origin) || null;
}
/** The origin to show: the engine's, or our guess. */
export function originFor(item) {
  const o = originOf(item);
  if (o && (o.country_code || o.basis)) return o;
  return guessOrigin(item);
}

const ccOf = o => (o && o.country_code ? String(o.country_code).toUpperCase().replace(/^UK$/, 'GB') : null);

/** The basis in plain words; a guess says so ("a guess from the .com domain and prices in US dollars"). */
export function basisWords(o) {
  const t = String((o && o.basis_text) || '').trim();
  if (!t) return o && o.confident === false ? 'a guess' : '';
  if (o.confident === false && !/^a guess\b/i.test(t)) return 'a guess ' + t;
  return t;
}

/** Tooltip / aria-label: two plain sentences (section 5). */
export function originTitle(origin) {
  const o = origin || {};
  const cc = ccOf(o);
  const ships = `Ships to Finland: ${o.ships_text || 'not stated'}.`;
  if (!cc) return `Where it ships from is not stated. ${ships}`;
  const name = (THE.has(cc) ? 'the ' : '') + (o.country_name || countryName(cc));
  const where = name + (o.city ? ` (${o.city})` : '');
  if (o.confident === false) return `Probably ${where}: ${basisWords(o)}. ${ships}`;
  const lead = o.basis === 'seller_address' || o.basis === 'known_shop' ? 'Shop based in'
    : o.basis === 'service_area' ? 'Provider in' : 'Seller in';
  return `${lead} ${where}, ${String(o.basis_text || '').trim() || 'as the listing says'}. ${ships}`;
}

/** The flag markup for an item, or '' when the origin is unknown. While an offer is still being costed
 *  and nothing is known, a blank slot keeps the width so nothing moves when the flag arrives. */
export function flagHtml(item, { size = 14, noFi = false, origin = null } = {}) {
  const o = origin || originFor(item);
  const cc = ccOf(o);
  const w = size >= 18 ? 18 : size, h = size >= 18 ? 13 : 10;
  if (!cc) return item && !item.tc && !origin ? `<span class="flag is-pending" data-size="${w}" aria-hidden="true"></span>` : '';
  const sure = o.confident === false ? '0' : '1';
  const fi = o.ships_to_fi === true ? 'yes' : o.ships_to_fi === false ? 'no' : 'unknown';
  const title = originTitle(o);
  return `<span class="flag" data-size="${w}" data-sure="${sure}" data-fi="${fi}" data-cc="${esc(cc)}" role="img" title="${esc(title)}" aria-label="${esc(title)}">` +
    `<img src="https://flagcdn.com/${esc(cc.toLowerCase())}.svg" alt="" width="${w}" height="${h}" loading="lazy" decoding="async" referrerpolicy="no-referrer">` +
    `<span class="flag-cc">${esc(cc)}</span>${sure === '0' ? '<sup class="flag-q" aria-hidden="true">?</sup>' : ''}` +
    `${noFi && fi === 'no' ? '<span class="flag-nofi" aria-hidden="true">no FI</span>' : ''}</span>`;
}

/** Same as flagHtml, as an element (for modules that build DOM). */
export function flagEl(item, opts) {
  const html = flagHtml(item, opts);
  if (!html || typeof document === 'undefined') return null;
  const t = document.createElement('template');
  t.innerHTML = html;
  return t.content.firstElementChild;
}

// a flag image that does not load (offline, blocked) becomes its two-letter code in a small pill
if (typeof document !== 'undefined') {
  document.addEventListener('error', e => {
    const img = e.target;
    if (img && img.tagName === 'IMG' && img.parentNode && img.parentNode.classList && img.parentNode.classList.contains('flag')) {
      img.parentNode.classList.add('noimg');
    }
  }, true);
}
