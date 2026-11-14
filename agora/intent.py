"""INTENT: a vague request -> the 2-5 concrete things the person most likely means, each with a search plan.

Owner, 14 Nov: "went to school catering and just typed lunch and its giving straight bullshit. not even services.
like it should somehow interpret for what you are looking for most likely and search for those".

"lunch" is not a product. It is (1) somewhere to eat lunch near you, (2) lunch delivered, or (3) a lunch box. A hunt
that takes the word literally reads tori.fi and prices €4 lunch boxes. This module says what a request most likely
means BEFORE the hunt, so the viewer can hunt the likeliest meaning and offer the others as one-tap switches.

    from agora import intent
    intent.interpret("lunch", country="fi", lang="en")
    # -> {"q": "lunch", "dominant": False, "intents": [
    #       {"id": "c:lunch.places", "label": "Lunch places near you", "kind": "service",
    #        "node": "nace:56101", "hunt": {"q": "lunch restaurant", "cat": "nace:56101", "intent": "c:lunch.places"},
    #        "queries": {"fi": ["lounas", "lounasravintola"], ...}, "lanes": ["service"],
    #        "domains": ["lounaat.info", ...], "look": ["lunch menu sites", ...], "why": "...", "confidence": 0.52}, ...]}

Three sources, combined:
1. a curated INTENT MAP for the very common vague words (lunch, catering, cleaning, phone, gift, car, insurance ...)
   with their words in en/fi/sv/de/nl, where to look per country and what kind of thing each meaning is;
2. agora.taxonomy (search + classify over the tree's labels and synonyms in many languages) for everything else,
   one meaning per distinct branch (a phone vs a phone plan vs phone repair);
3. the need's context: a place in the words ("haircut helsinki") makes local services likelier than products;
   a category the hunt started from (School catering) plans providers, its broader and sibling services, and a
   "search providers near you" step, so a category page with nothing in it is never a dead end.
Optional: when GEMINI_API_KEY is set (and AGORA_OFFLINE is not), Gemini may add or re-rank meanings (strict JSON,
2 s timeout). Without it the rules answer alone, instantly and offline.

Hunt hook: `apply(need, intent_id)` fits a parsed Need to one meaning (its category node, kind, lanes, local words,
where-to-look domains). agora.hunt calls it when GET /hunt carries &intent=<id> (see the patch in the report).
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from typing import Any

LANGS = ("en", "fi", "sv", "de", "nl")
MAX_INTENTS = 5
DOMINANT_CONF = 0.62          # the top meaning is "clearly it" from this confidence ...
DOMINANT_MARGIN = 0.3         # ... when it is also this far ahead of the second
GEMINI_TIMEOUT_S = 2.0

# ---------------------------------------------------------------- small helpers


def fold(s: str) -> str:
    s = (s or "").lower().replace("ß", "ss")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s'-]", " ", s)).strip()


def _L(text: str) -> dict[str, str]:
    """'en|fi|sv|de|nl' -> {lang: label}; an empty slot falls back to English."""
    parts = [p.strip() for p in text.split("|")]
    out = {lang: (parts[i] if i < len(parts) and parts[i] else parts[0]) for i, lang in enumerate(LANGS)}
    return out


def _I(key: str, w: float, kind: str, node: str | None, label: str, hunt: str, *,
       q: dict[str, list[str]] | None = None, lanes: list[str] | None = None,
       domains: dict[str, list[str]] | None = None, look: list[str] | None = None, why: str = "",
       local: bool = False, travel: bool | str = False) -> dict[str, Any]:
    """One curated meaning. w = prior weight within its word; kind = product | service | digital | food | vehicle;
    node = the agora.taxonomy node it hunts in; label = 'en|fi|sv|de|nl' with {near} / {to} / {rest} slots;
    hunt = plain English words the hunt searches with; q = local-language search queries per language ({place});
    domains = where to look per country code ('*' = everywhere); local = a provider near the person;
    travel = the place in the words is a destination: True / "to" ('flights to Berlin'), "at" ('hotels in Berlin')."""
    return {"key": key, "w": w, "kind": kind, "node": node, "label": _L(label), "hunt": hunt, "q": q or {},
            "lanes": lanes or (["service"] if kind in ("service", "digital") else ["new", "used"]),
            "domains": domains or {}, "look": look or [], "why": why, "local": local, "travel": ("to" if travel is True else travel or "")}


# ---------------------------------------------------------------- the curated INTENT MAP
# Each entry: the words that name it (any of en/fi/sv/de/nl, folded, longest phrase wins) -> its meanings, the
# likeliest first. Domains are hints of where those meanings are sold or listed, not an exhaustive list.

CONCEPTS: list[dict[str, Any]] = [
    {"key": "school-catering",
     "words": ["school catering", "school meals", "school meal", "school lunch", "school lunches", "school food",
               "kouluruokailu", "kouluruoka", "kouluateria", "kouluateriat", "kouluateriapalvelu",
               "kouluruokailupalvelu", "skolmat", "skolmaltider", "skolbespisning", "skolmaltid",
               "schulverpflegung", "schulcatering", "schulessen", "schulmensa", "schoolcatering",
               "schoolmaaltijden", "schoolmaaltijd", "schoollunch", "overblijflunch"],
     "nodes": ["cpv:55524", "cpv:555231"],
     "intents": [
         _I("providers", 0.62, "service", "cpv:55524",
            "School catering companies{near}|Kouluruokailun palveluntarjoajat{near}|Skolmatsleverantörer{near}|"
            "Schulcaterer{near}|Schoolcateraars{near}",
            "school catering company",
            q={"en": ["school catering company", "school meal provider"],
               "fi": ["kouluruokailu palvelu", "ateriapalvelu koulu", "kouluruokailun palveluntuottaja"],
               "sv": ["skolmåltider cateringföretag", "skolmat leverantör"],
               "de": ["Schulverpflegung Caterer", "Schulcatering Anbieter"],
               "nl": ["schoolcatering aanbieder", "schoolmaaltijden leverancier"]},
            domains={"fi": ["compass-group.fi", "palmia.fi", "sodexo.fi", "hankintailmoitukset.fi"],
                     "de": ["apetito.de", "dussmann.com"], "se": ["sodexo.se", "compass-group.se"],
                     "nl": ["hutten.nl"]},
            look=["catering companies' own sites", "municipal food services", "public tenders"],
            why="School meals are bought by schools and municipalities from catering companies, usually by "
                "tender and priced per meal: providers, not things on a marketplace.", local=True),
         _I("catering", 0.2, "service", "events-leisure.catering",
            "Catering companies{near}|Pitopalvelut ja catering-yritykset{near}|Cateringföretag{near}|"
            "Catering-Firmen{near}|Cateringbedrijven{near}",
            "catering company",
            q={"fi": ["pitopalvelu", "catering yritys"], "sv": ["cateringföretag"], "de": ["Catering Firma"],
               "nl": ["cateringbedrijf"]},
            look=["caterers' own sites", "local directories"],
            why="Any catering company can quote for regular meals, not only school specialists.", local=True),
         _I("delivery", 0.1, "service", "cpv:555212",
            "Meal delivery for groups{near}|Ateriapalvelu ryhmille{near}|Matleverans för grupper{near}|"
            "Essenslieferung für Gruppen{near}|Maaltijdbezorging voor groepen{near}",
            "meal delivery service",
            q={"fi": ["ateriapalvelu", "ateriakuljetus"], "sv": ["matleverans företag"],
               "de": ["Essenslieferung Firmen"], "nl": ["maaltijdbezorging bedrijven"]},
            look=["meal delivery companies"], why="Smaller schools and daycares often get meals delivered.",
            local=True),
         _I("lunchbox", 0.08, "product", "sp:hg-11-3-7",
            "School lunch boxes|Eväsrasiat kouluun|Matlådor till skolan|Brotdosen für die Schule|"
            "Broodtrommels voor school",
            "lunch box",
            q={"fi": ["eväsrasia"], "sv": ["matlåda barn"], "de": ["Brotdose Kinder"], "nl": ["broodtrommel"]},
            look=["shops", "marketplaces"], why="A parent may mean the box a child takes to school."),
     ]},
    {"key": "catering",
     "words": ["catering", "caterer", "caterers", "catering service", "catering company", "pitopalvelu",
               "pitopalvelut", "juhlatarjoilu", "catering yritys", "cateringfirma", "cateringforetag",
               "partyservice", "cateringbedrijf", "cateraar"],
     "nodes": ["events-leisure.catering", "nace:562"],
     "intents": [
         _I("event", 0.55, "service", "events-leisure.catering",
            "Catering for a party or event{near}|Pitopalvelu juhliin{near}|Catering till fest{near}|"
            "Catering für Feier oder Event{near}|Catering voor feest of evenement{near}",
            "event catering",
            q={"en": ["event catering"], "fi": ["pitopalvelu", "juhlatarjoilu"], "sv": ["catering fest"],
               "de": ["Partyservice", "Catering Feier"], "nl": ["catering feest"]},
            domains={"fi": ["pitopalvelut.fi"]},
            look=["caterers' own sites", "local directories"],
            why="Most people who type catering want food for a party, wedding or company event, priced per person.",
            local=True),
         _I("office", 0.25, "service", "nace:562",
            "Office lunch and meeting catering{near}|Lounas- ja kokoustarjoilu työpaikalle{near}|"
            "Lunch- och mötescatering{near}|Büro- und Meeting-Catering{near}|Kantoorlunch en vergadercatering{near}",
            "office lunch catering",
            q={"fi": ["kokoustarjoilu", "lounaskuljetus työpaikalle"], "sv": ["företagscatering"],
               "de": ["Firmencatering"], "nl": ["bedrijfscatering"]},
            look=["caterers", "lunch delivery services"],
            why="Companies order lunches and meeting food on a schedule.", local=True),
         _I("school", 0.12, "service", "cpv:55524",
            "School and daycare catering{near}|Koulu- ja päiväkotiruokailu{near}|Skol- och förskolemat{near}|"
            "Schul- und Kita-Verpflegung{near}|School- en kinderopvangcatering{near}",
            "school catering company",
            q={"fi": ["kouluruokailu palvelu", "ateriapalvelu koulu"], "sv": ["skolmat leverantör"],
               "de": ["Schulverpflegung Caterer"], "nl": ["schoolcatering"]},
            domains={"fi": ["compass-group.fi", "palmia.fi", "hankintailmoitukset.fi"]},
            look=["catering companies", "public tenders"], why="Institutions buy catering by contract.", local=True),
         _I("equipment", 0.08, "product", "cpv:3931",
            "Catering equipment|Suurtalouslaitteet|Storköksutrustning|Gastronomiebedarf|Horeca-apparatuur",
            "catering equipment", look=["shops", "marketplaces"],
            why="A caterer may be shopping for kit, not food."),
     ]},
    {"key": "lunch",
     "words": ["lunch", "lunches", "lunch time", "lunchtime", "lounas", "lounasta", "lounaalle", "lounaspaikka",
               "lounaspaikat", "lounasravintola", "lounasravintolat", "lounasbuffet", "lunchrestaurang",
               "dagens lunch", "mittagessen", "mittagstisch", "mittagsmenu", "mittagsmenue", "lunchen",
               "lunchroom", "middageten"],
     "nodes": [],
     "intents": [
         _I("places", 0.6, "service", "nace:56101",
            "Lunch places{near}|Lounaspaikat{near}|Lunchställen{near}|Mittagstisch{near}|Lunchplekken{near}",
            "lunch restaurant",
            q={"en": ["lunch restaurant {place}", "lunch menu {place}"],
               "fi": ["lounas {place}", "lounasravintola {place}", "lounaslista {place}"],
               "sv": ["dagens lunch {place}", "lunchrestaurang {place}"],
               "de": ["Mittagstisch {place}", "Mittagsmenü {place}"], "nl": ["lunchroom {place}", "lunch {place}"]},
            domains={"fi": ["lounaat.info", "lounasaika.net", "lounasinfo.fi"], "se": ["kvartersmenyn.se"],
                     "*": ["restaurant sites"]},
            look=["lunch menu sites", "restaurants' own lunch lists"],
            why="A lunch is usually bought at a restaurant near you: today's menus and prices.", local=True),
         _I("delivery", 0.25, "service", "food-drink.restaurants-takeaway.food-delivery",
            "Lunch delivered{near}|Lounas kotiin tai töihin{near}|Lunch levererad{near}|"
            "Mittagessen liefern lassen{near}|Lunch laten bezorgen{near}",
            "lunch delivery",
            q={"fi": ["lounas kotiinkuljetus {place}"], "sv": ["lunch hemleverans {place}"],
               "de": ["Mittagessen Lieferservice {place}"], "nl": ["lunch bezorgen {place}"]},
            domains={"fi": ["wolt.com", "foodora.fi"], "se": ["wolt.com", "foodora.se"], "de": ["lieferando.de", "wolt.com"],
                     "nl": ["thuisbezorgd.nl", "ubereats.com"], "*": ["wolt.com", "ubereats.com"]},
            look=["delivery apps"], why="Lunch to your desk or door: delivery apps list prices and fees.", local=True),
         _I("box", 0.15, "product", "sp:hg-11-3-7",
            "Lunch boxes and bento|Eväsrasiat ja bento|Matlådor och bento|Brotdosen und Bento|Lunchboxen en bento",
            "lunch box",
            q={"fi": ["eväsrasia", "lounasrasia"], "sv": ["matlåda"], "de": ["Brotdose", "Bento Box"],
               "nl": ["lunchbox", "broodtrommel"]},
            look=["shops", "marketplaces"], why="Or the box you carry your own lunch in."),
     ]},
    {"key": "dinner",
     "words": ["dinner", "supper", "illallinen", "illalliselle", "paivallinen", "middag", "abendessen",
               "diner", "avondeten", "dinner tonight"],
     "nodes": [],
     "intents": [
         _I("restaurants", 0.55, "service", "nace:56101",
            "Restaurants for dinner{near}|Illallisravintolat{near}|Middagsrestauranger{near}|"
            "Restaurants zum Abendessen{near}|Restaurants voor het diner{near}",
            "dinner restaurant",
            q={"fi": ["illallinen ravintola {place}"], "sv": ["middag restaurang {place}"],
               "de": ["Restaurant Abendessen {place}"], "nl": ["restaurant diner {place}"]},
            domains={"fi": ["eat.fi", "dinnerbooking.com"], "*": ["thefork.com", "restaurant sites"]},
            look=["restaurant booking sites", "restaurants' own menus"], why="Eating out: menus and prices near you.",
            local=True),
         _I("delivery", 0.3, "service", "food-drink.restaurants-takeaway.food-delivery",
            "Dinner delivered{near}|Ruoka kotiin{near}|Middag levererad{near}|Essen liefern lassen{near}|"
            "Avondeten bezorgen{near}",
            "food delivery",
            domains={"fi": ["wolt.com", "foodora.fi"], "de": ["lieferando.de"], "nl": ["thuisbezorgd.nl"],
                     "*": ["wolt.com", "ubereats.com"]},
            look=["delivery apps"], why="Dinner at home: delivery apps.", local=True),
         _I("kits", 0.15, "service", "food-drink.restaurants-takeaway.meal-kits",
            "Meal kits|Ateriakassit|Matkassar|Kochboxen|Maaltijdboxen", "meal kit",
            domains={"fi": ["ruokaboksi.fi"], "de": ["hellofresh.de"], "nl": ["hellofresh.nl"]},
            look=["meal kit services"], why="Cooking yourself, ingredients delivered."),
     ]},
    {"key": "haircut",
     "words": ["haircut", "hair cut", "barber", "hairdresser", "hiustenleikkuu", "parturi", "kampaamo",
               "parturi-kampaamo", "klippning", "frisor", "harklippning", "haarschnitt", "friseur", "kapper",
               "knippen", "herenkapper"],
     "nodes": ["beauty-wellness.hair-salons-barbers.haircut"],
     "intents": [
         _I("salon", 0.72, "service", "beauty-wellness.hair-salons-barbers.haircut",
            "Haircut at a salon or barber{near}|Hiustenleikkuu{near}|Klippning{near}|Haarschnitt{near}|"
            "Knippen bij de kapper{near}",
            "haircut",
            q={"fi": ["parturi {place}", "hiustenleikkuu hinta {place}"], "sv": ["frisör {place}"],
               "de": ["Friseur {place}"], "nl": ["kapper {place}"]},
            domains={"fi": ["varaaheti.fi", "timma.fi"], "se": ["bokadirekt.se"], "de": ["treatwell.de"],
                     "nl": ["treatwell.nl"], "*": ["salons' own price lists"]},
            look=["booking sites", "salons' price lists"], why="A haircut is a local service with a price list.",
            local=True),
         _I("barber", 0.16, "service", "beauty-wellness.hair-salons-barbers.barber-beard-trim",
            "Barber and beard trim{near}|Parturi ja parranajo{near}|Barberare{near}|Barbier{near}|Barbier{near}",
            "barber", look=["booking sites"], why="Short cuts and beards: barbers price differently.", local=True),
         _I("clippers", 0.12, "product", "sp:hb-3-14-6",
            "Hair clippers to cut at home|Hiustenleikkuukoneet|Hårklippningsmaskiner|Haarschneidemaschinen|"
            "Tondeuses",
            "hair clippers", look=["shops"], why="Or cut it yourself."),
     ]},
    {"key": "cleaning",
     "words": ["cleaning", "cleaner", "cleaners", "cleaning service", "siivous", "siivooja", "siivouspalvelu",
               "kotisiivous", "stadning", "stadhjalp", "hemstadning", "reinigung", "putzen", "putzfrau",
               "putzhilfe", "reinigungskraft", "schoonmaak", "schoonmaker", "schoonmaakster"],
     "nodes": ["home-services.cleaning"],
     "intents": [
         _I("home", 0.62, "service", "home-services.cleaning.home-cleaning",
            "Home cleaning{near}|Kotisiivous{near}|Hemstädning{near}|Haushaltsreinigung{near}|"
            "Huishoudelijke schoonmaak{near}",
            "home cleaning",
            q={"fi": ["kotisiivous {place}", "siivouspalvelu hinta {place}"], "sv": ["hemstädning {place}"],
               "de": ["Haushaltsreinigung {place}", "Putzhilfe {place}"], "nl": ["schoonmaker {place}"]},
            domains={"fi": ["tori.fi"], "de": ["helpling.de"], "nl": ["helpling.nl", "werkspot.nl"],
                     "se": ["hemfrid.se"]},
            look=["cleaning companies", "service marketplaces"], why="Someone to clean your home, priced per hour.",
            local=True),
         _I("office", 0.14, "service", "home-services.cleaning.office-cleaning",
            "Office cleaning{near}|Toimistosiivous{near}|Kontorsstädning{near}|Büroreinigung{near}|"
            "Kantoorschoonmaak{near}",
            "office cleaning", look=["cleaning companies"], why="Cleaning for a workplace.", local=True),
         _I("windows", 0.1, "service", "home-services.cleaning.window-cleaning",
            "Window cleaning{near}|Ikkunanpesu{near}|Fönsterputs{near}|Fensterreinigung{near}|Glazenwasser{near}",
            "window cleaning", look=["cleaning companies"], why="Windows are often priced on their own.",
            local=True),
         _I("supplies", 0.14, "product", "sp:hg-10-6",
            "Cleaning supplies|Siivoustarvikkeet|Städartiklar|Reinigungsmittel|Schoonmaakmiddelen",
            "cleaning supplies", look=["shops"], why="Or the things to clean with."),
     ]},
    {"key": "moving",
     "words": ["moving", "move", "movers", "removals", "removal company", "moving company", "muutto", "muuttofirma",
               "muuttopalvelu", "flytt", "flytthjalp", "flyttfirma", "umzug", "umzugsfirma", "verhuizing",
               "verhuizen", "verhuisbedrijf"],
     "nodes": ["home-services.moving-removals"],
     "intents": [
         _I("movers", 0.6, "service", "home-services.moving-removals",
            "Movers{near}|Muuttofirmat{near}|Flyttfirmor{near}|Umzugsfirmen{near}|Verhuisbedrijven{near}",
            "moving company",
            q={"fi": ["muuttofirma {place}", "muuttopalvelu hinta {place}"], "sv": ["flyttfirma {place}"],
               "de": ["Umzugsfirma {place}"], "nl": ["verhuisbedrijf {place}"]},
            domains={"fi": ["tori.fi"], "de": ["my-hammer.de"], "nl": ["werkspot.nl"]},
            look=["moving companies", "service marketplaces"], why="People and a truck, priced per hour or job.",
            local=True),
         _I("van", 0.25, "service", "transport.van-truck-hire",
            "Van hire to move yourself{near}|Pakettiauton vuokraus{near}|Hyra flyttbil{near}|"
            "Transporter mieten{near}|Bestelbus huren{near}",
            "van rental", look=["rental companies"], why="Do it yourself with a rented van.", local=True),
         _I("boxes", 0.15, "product", "sp:os-14-1",
            "Moving boxes|Muuttolaatikot|Flyttkartonger|Umzugskartons|Verhuisdozen", "moving boxes",
            look=["shops", "marketplaces"], why="Boxes and packing."),
     ]},
    {"key": "phone",
     "words": ["phone", "phones", "mobile", "mobile phone", "cell phone", "smartphone", "puhelin", "kannykka",
               "alypuhelin", "matkapuhelin", "telefon", "mobil", "mobiltelefon", "handy", "telefoon",
               "mobiele telefoon"],
     "nodes": ["sp:el-4-8-5"],
     "intents": [
         _I("device", 0.58, "product", "sp:el-4-8-5",
            "A phone to buy|Puhelin|En telefon|Ein Handy|Een telefoon", "phone",
            look=["shops", "marketplaces", "refurbished sellers"], why="Most people mean the phone itself."),
         _I("plan", 0.22, "service", "utilities.mobile-phone-plans",
            "A phone plan|Puhelinliittymä|Mobilabonnemang|Handyvertrag|Telefoonabonnement",
            "mobile phone plan",
            q={"fi": ["puhelinliittymä"], "sv": ["mobilabonnemang"], "de": ["Handyvertrag"], "nl": ["sim only"]},
            domains={"fi": ["puhelinliittymat.fi", "elisa.fi", "dna.fi", "telia.fi"], "de": ["check24.de", "verivox.de"],
                     "nl": ["bellen.com"], "se": ["mobilabonnemang.se"]},
            look=["operators", "comparison sites"], why="Or a monthly plan for the phone you have."),
         _I("repair", 0.16, "service", "home-services.appliance-electronics-repair.phone-repair",
            "Phone repair{near}|Puhelimen korjaus{near}|Mobilreparation{near}|Handyreparatur{near}|"
            "Telefoonreparatie{near}",
            "phone repair", look=["repair shops"], why="Or fixing the one you have.", local=True),
     ]},
    {"key": "laptop",
     "words": ["laptop", "laptops", "notebook", "kannettava", "lappari", "kannettava tietokone", "bärbar dator",
               "barbar dator", "laptop computer"],
     "nodes": ["sp:el-6-6"],
     "intents": [
         _I("device", 0.75, "product", "sp:el-6-6", "A laptop|Kannettava tietokone|En bärbar dator|Ein Laptop|"
            "Een laptop", "laptop", look=["shops", "marketplaces", "refurbished sellers"], why="The laptop itself."),
         _I("repair", 0.15, "service", "home-services.appliance-electronics-repair.computer-repair",
            "Laptop repair{near}|Tietokoneen korjaus{near}|Datorreparation{near}|Laptop-Reparatur{near}|"
            "Laptopreparatie{near}", "laptop repair", look=["repair shops"], why="Or fixing one.", local=True),
         _I("bags", 0.1, "product", "sp:lb-15", "Laptop bags|Läppärilaukut|Datorväskor|Laptoptaschen|Laptoptassen",
            "laptop bag", look=["shops"], why="Or something to carry it in."),
     ]},
    {"key": "gift",
     "words": ["gift", "gifts", "present", "presents", "gift idea", "gift ideas", "lahja", "lahjat", "lahjaidea",
               "lahjaideat", "presentide", "presenter", "geschenk", "geschenke", "geschenkidee", "cadeau",
               "cadeautje", "kado"],
     "nodes": ["sp:ae-3-1"],
     "intents": [
         _I("ideas", 0.5, "product", None,
            "Gift ideas{rest}|Lahjaideat{rest}|Presentidéer{rest}|Geschenkideen{rest}|Cadeau-ideeën{rest}",
            "gift ideas",
            q={"fi": ["lahjaidea{rest}"], "sv": ["present tips{rest}"], "de": ["Geschenkidee{rest}"],
               "nl": ["cadeau idee{rest}"]},
            look=["gift shops", "department stores"], why="A thing to give: the hunt compares gift shops."),
         _I("experience", 0.25, "service", "events-leisure.activities-experiences",
            "An experience to give{rest}|Elämyslahja{rest}|Upplevelsepresent{rest}|Erlebnisgeschenk{rest}|"
            "Belevenis cadeau{rest}",
            "experience gift",
            q={"fi": ["elämyslahja"], "sv": ["upplevelsepresent"], "de": ["Erlebnisgeschenk"], "nl": ["belevenis cadeau"]},
            domains={"fi": ["elamyslahjat.fi", "lahjaksi.fi"], "se": ["upplevelsepresent.se"],
                     "de": ["jochen-schweizer.de", "mydays.de"], "nl": ["vivabox.nl"]},
            look=["experience gift sites"], why="A day out, a dinner, a spa: often the better present."),
         _I("cards", 0.15, "digital", None,
            "A gift card{rest}|Lahjakortti{rest}|Presentkort{rest}|Gutschein{rest}|Cadeaukaart{rest}",
            "gift card", q={"fi": ["lahjakortti"], "sv": ["presentkort"], "de": ["Gutschein"], "nl": ["cadeaukaart"]},
            look=["shops' gift cards"], why="When you are not sure what they want."),
         _I("flowers", 0.1, "product", "sp:hg-17-2",
            "Flowers delivered{rest}|Kukkalähetys{rest}|Blommor med bud{rest}|Blumen verschicken{rest}|"
            "Bloemen bezorgen{rest}",
            "flower delivery", q={"fi": ["kukkalähetys"], "sv": ["skicka blommor"], "de": ["Blumenversand"],
                                  "nl": ["bloemen bezorgen"]},
            domains={"fi": ["interflora.fi"], "de": ["fleurop.de"], "nl": ["bloompost.nl"]},
            look=["florists"], why="The classic."),
     ]},
    {"key": "birthday",
     "words": ["birthday", "birthday party", "bday", "syntymapaiva", "syntymapaivat", "synttarit", "synttari",
               "fodelsedag", "kalas", "geburtstag", "geburtstagsfeier", "kindergeburtstag", "verjaardag",
               "verjaardagsfeest", "kinderfeestje"],
     "nodes": [],
     "intents": [
         _I("gift", 0.38, "product", None,
            "A birthday present{rest}|Syntymäpäivälahja{rest}|Födelsedagspresent{rest}|Geburtstagsgeschenk{rest}|"
            "Verjaardagscadeau{rest}",
            "birthday gift", look=["gift shops"], why="Most often: something to give."),
         _I("venue", 0.24, "service", "events-leisure.event-venues",
            "A place for the party{near}|Juhlatila{near}|Festlokal{near}|Location für die Feier{near}|"
            "Feestlocatie{near}",
            "party venue", q={"fi": ["juhlatila vuokra {place}"], "sv": ["festlokal {place}"],
                              "de": ["Partyraum mieten {place}"], "nl": ["feestlocatie {place}"]},
            domains={"fi": ["tilamisu.fi", "venuu.fi"], "de": ["eventlocations.com"]},
            look=["venue listings"], why="Hosting it somewhere other than home.", local=True),
         _I("cake", 0.2, "service", "yelp:customcakes",
            "A birthday cake{near}|Täytekakku tilaus{near}|Tårta beställning{near}|Geburtstagstorte{near}|"
            "Verjaardagstaart{near}",
            "birthday cake order", q={"fi": ["täytekakku tilaus {place}"], "sv": ["beställa tårta {place}"],
                                      "de": ["Torte bestellen {place}"], "nl": ["taart bestellen {place}"]},
            look=["bakeries"], why="A cake made to order.", local=True),
         _I("supplies", 0.18, "product", "sp:ae-3-2",
            "Party supplies|Juhlatarvikkeet|Festartiklar|Partyzubehör|Feestartikelen", "party supplies",
            look=["shops"], why="Balloons, candles and plates."),
     ]},
    {"key": "car",
     "words": ["car", "cars", "auto", "autot", "henkiloauto", "bil", "bilar", "wagen", "pkw", "personenwagen"],
     "nodes": [],
     "intents": [
         _I("buy", 0.55, "vehicle", None, "A car to buy|Auto|En bil|Ein Auto|Een auto", "car",
            lanes=["used", "new"], domains={"fi": ["nettiauto.com", "autotalli.com"], "de": ["mobile.de", "autoscout24.de"],
                                            "se": ["blocket.se"], "nl": ["autoscout24.nl", "marktplaats.nl"]},
            look=["car marketplaces", "dealers"], why="Most people mean a car itself, often used."),
         _I("rental", 0.18, "service", "travel.car-rental",
            "Car rental{near}|Autonvuokraus{near}|Hyrbil{near}|Mietwagen{near}|Autoverhuur{near}", "car rental",
            look=["rental companies", "comparison sites"], why="A car for a few days.", local=True),
         _I("leasing", 0.12, "service", "auto-services.vehicle-leasing",
            "Car leasing|Yksityisleasing|Privatleasing|Auto-Leasing|Private lease", "car leasing",
            q={"fi": ["yksityisleasing"], "sv": ["privatleasing bil"], "de": ["Auto Leasing privat"],
               "nl": ["private lease"]},
            look=["leasing companies"], why="A car for a fixed monthly price."),
         _I("insurance", 0.08, "service", "finance-insurance.insurance.car-insurance",
            "Car insurance|Autovakuutus|Bilförsäkring|Kfz-Versicherung|Autoverzekering", "car insurance",
            look=["insurers", "comparison sites"], why="Insuring the car you have."),
         _I("repair", 0.07, "service", "auto-services.car-repair-servicing",
            "Car repair and servicing{near}|Auton huolto{near}|Bilverkstad{near}|Autowerkstatt{near}|Garage{near}",
            "car service", domains={"fi": ["fixu.fi"], "de": ["autobutler.de"]},
            look=["garages"], why="Fixing or servicing it.", local=True),
     ]},
    {"key": "insurance",
     "words": ["insurance", "insurances", "vakuutus", "vakuutukset", "forsakring", "forsakringar", "versicherung",
               "versicherungen", "verzekering", "verzekeringen"],
     "nodes": ["finance-insurance.insurance"],
     "intents": [
         _I("home", 0.32, "service", "finance-insurance.insurance.home-contents-insurance",
            "Home insurance|Kotivakuutus|Hemförsäkring|Hausratversicherung|Inboedelverzekering", "home insurance",
            domains={"fi": ["vertaa.fi"], "de": ["check24.de", "verivox.de"], "nl": ["independer.nl"],
                     "se": ["compricer.se"]},
            look=["insurers", "comparison sites"], why="The most common policy people shop for."),
         _I("car", 0.3, "service", "finance-insurance.insurance.car-insurance",
            "Car insurance|Autovakuutus|Bilförsäkring|Kfz-Versicherung|Autoverzekering", "car insurance",
            domains={"fi": ["vertaa.fi"], "de": ["check24.de"], "nl": ["independer.nl"], "se": ["compricer.se"]},
            look=["insurers", "comparison sites"], why="Required for every car, priced per year."),
         _I("travel", 0.2, "service", "finance-insurance.insurance.travel-insurance",
            "Travel insurance|Matkavakuutus|Reseförsäkring|Reiseversicherung|Reisverzekering", "travel insurance",
            look=["insurers"], why="Before a trip."),
         _I("health", 0.18, "service", "finance-insurance.insurance.health-insurance",
            "Health insurance|Sairausvakuutus|Sjukvårdsförsäkring|Krankenversicherung|Zorgverzekering",
            "health insurance", look=["insurers", "comparison sites"], why="Private health cover."),
     ]},
    {"key": "internet",
     "words": ["internet", "broadband", "wifi", "wi-fi", "home internet", "nettiliittyma", "laajakaista",
               "kotinetti", "valokuitu", "bredband", "internetanschluss", "glasfaser", "dsl", "internetabonnement",
               "glasvezel"],
     "nodes": ["utilities.home-internet-broadband"],
     "intents": [
         _I("broadband", 0.72, "service", "utilities.home-internet-broadband",
            "Home internet plans|Kotinetti ja laajakaista|Bredband hemma|Internet-Tarife|Internetabonnementen",
            "home broadband",
            q={"fi": ["nettiliittymä", "laajakaista hinta"], "sv": ["bredband pris"], "de": ["Internet Tarif"],
               "nl": ["internet abonnement"]},
            domains={"fi": ["puhelinliittymat.fi", "elisa.fi", "dna.fi", "telia.fi"], "de": ["check24.de", "verivox.de"],
                     "nl": ["internetten.nl"], "se": ["bredbandsval.se"]},
            look=["operators", "comparison sites"], why="A monthly connection, compared per month all in."),
         _I("mobile", 0.18, "service", "utilities.mobile-phone-plans",
            "Mobile data plans|Mobiililaajakaista|Mobilt bredband|Mobiles Internet|Mobiel internet",
            "mobile data plan", look=["operators"], why="Internet without a cable."),
         _I("router", 0.1, "product", "cpv:324131", "A router or mesh wifi|Reititin|Router|Router|Router",
            "wifi router", look=["shops"], why="Or the box that makes the wifi."),
     ]},
    {"key": "electricity",
     "words": ["electricity", "power contract", "electricity contract", "energy contract", "sahko", "sahkosopimus",
               "sahkon hinta", "el", "elavtal", "elpris", "strom", "stromtarif", "stromanbieter", "stroom",
               "energiecontract", "energie"],
     "nodes": ["utilities.electricity"],
     "intents": [
         _I("contract", 0.8, "service", "utilities.electricity",
            "Electricity contracts|Sähkösopimukset|Elavtal|Stromtarife|Energiecontracten", "electricity contract",
            q={"fi": ["sähkösopimus"], "sv": ["elavtal"], "de": ["Stromtarif"], "nl": ["energiecontract"]},
            domains={"fi": ["sahkonhinta.fi", "sahkovertailu.fi"], "se": ["elskling.se"],
                     "de": ["check24.de", "verivox.de"], "nl": ["gaslicht.com"]},
            look=["energy companies", "comparison sites"], why="A supply contract: price per kWh plus monthly fee."),
         _I("electrician", 0.2, "service", "trades.electrical-work",
            "An electrician{near}|Sähköasentaja{near}|Elektriker{near}|Elektriker{near}|Elektricien{near}",
            "electrician", look=["trades"], why="Or someone to do electrical work.", local=True),
     ]},
    {"key": "flights",
     "words": ["flight", "flights", "plane ticket", "plane tickets", "air ticket", "airfare", "lento", "lennot",
               "lentoliput", "lentolippu", "flyg", "flygbiljett", "flug", "fluge", "fluege", "vlucht", "vluchten",
               "vliegtickets"],
     "nodes": ["travel.flights"],
     "intents": [
         _I("flights", 0.75, "service", "travel.flights",
            "Flights{to}|Lennot{to}|Flyg{to}|Flüge{to}|Vluchten{to}", "flights",
            q={"fi": ["lennot {place}"], "sv": ["flyg {place}"], "de": ["Flug {place}"], "nl": ["vlucht {place}"]},
            domains={"*": ["skyscanner.net", "google.com/travel", "momondo.fi"]},
            look=["airlines", "flight comparison sites"], why="A ticket, compared all in (bags and fees).",
            travel=True),
         _I("package", 0.15, "service", "travel.package-holidays",
            "Flight + hotel packages{to}|Lento + hotelli{to}|Flyg + hotell{to}|Flug + Hotel{to}|"
            "Vlucht + hotel{to}",
            "flight and hotel", domains={"fi": ["tjareborg.fi", "aurinkomatkat.fi"]},
            look=["travel agencies"], why="Often cheaper as a package.", travel=True),
         _I("hotel", 0.1, "service", "travel.hotels",
            "Hotels{to}|Hotellit{to}|Hotell{to}|Hotels{to}|Hotels{to}", "hotel",
            domains={"*": ["booking.com"]}, look=["hotel booking sites"], why="Somewhere to stay.", travel="at"),
     ]},
    {"key": "hotel",
     "words": ["hotel", "hotels", "hotelli", "hotellit", "hotell", "accommodation", "majoitus", "boende",
               "unterkunft", "overnachting", "place to stay"],
     "nodes": ["travel.hotels"],
     "intents": [
         _I("hotels", 0.7, "service", "travel.hotels", "Hotels{to}|Hotellit{to}|Hotell{to}|Hotels{to}|Hotels{to}",
            "hotel", domains={"*": ["booking.com", "hotels.com"]}, look=["hotel booking sites", "hotels' own sites"],
            why="A room per night, compared all in (taxes and fees).", travel="at"),
         _I("rentals", 0.2, "service", "travel.holiday-rentals-cottages",
            "Apartments and cottages{to}|Lomamökit ja -asunnot{to}|Stugor och lägenheter{to}|"
            "Ferienwohnungen{to}|Vakantiehuizen{to}",
            "holiday rental", domains={"*": ["airbnb.com"], "fi": ["lomarengas.fi"]},
            look=["rental sites"], why="More space, a kitchen.", travel="at"),
         _I("hostels", 0.1, "service", "travel.hostels-camping", "Hostels{to}|Hostellit{to}|Vandrarhem{to}|"
            "Hostels{to}|Hostels{to}", "hostel", look=["hostel sites"], why="The cheap way.", travel="at"),
     ]},
    {"key": "tickets",
     "words": ["tickets", "ticket", "liput", "lippu", "biljetter", "biljett", "karten", "eintrittskarten",
               "kaartjes", "tickets kopen"],
     "nodes": [],
     "intents": [
         _I("events", 0.5, "service", "events-leisure.concert-event-tickets.concert-tickets",
            "Concert and event tickets{rest}|Konsertti- ja tapahtumaliput{rest}|Konsert- och evenemangsbiljetter{rest}|"
            "Konzert- und Eventtickets{rest}|Concert- en evenementtickets{rest}",
            "event tickets", domains={"fi": ["lippu.fi", "ticketmaster.fi", "tiketti.fi"], "de": ["eventim.de"],
                                      "*": ["ticketmaster.com"]},
            look=["ticket sellers", "resale sites"], why="A concert, a match, a show."),
         _I("travel", 0.3, "service", "travel.train-bus-tickets",
            "Train and bus tickets{to}|Juna- ja bussiliput{to}|Tåg- och bussbiljetter{to}|Bahn- und Bustickets{to}|"
            "Trein- en bustickets{to}",
            "train tickets", domains={"fi": ["vr.fi", "onnibus.com"], "de": ["bahn.de", "flixbus.de"],
                                      "se": ["sj.se"], "nl": ["ns.nl"]},
            look=["rail and bus companies"], why="Getting somewhere.", travel=True),
         _I("flights", 0.2, "service", "travel.flights", "Flight tickets{to}|Lentoliput{to}|Flygbiljetter{to}|"
            "Flugtickets{to}|Vliegtickets{to}", "flights", domains={"*": ["skyscanner.net"]},
            look=["flight comparison sites"], why="Or flying.", travel=True),
     ]},
    {"key": "repair",
     "words": ["repair", "repairs", "fix", "fixing", "korjaus", "korjaamo", "reparation", "reparatur",
               "reparatie", "maintenance", "huolto"],
     "nodes": [],
     "intents": [
         _I("electronics", 0.3, "service", "home-services.appliance-electronics-repair.phone-repair",
            "Phone or computer repair{near}|Puhelimen tai tietokoneen korjaus{near}|Mobil- eller datorreparation{near}|"
            "Handy- oder PC-Reparatur{near}|Telefoon- of computerreparatie{near}",
            "phone repair", look=["repair shops"], why="The most common repair people search for.", local=True),
         _I("appliance", 0.25, "service", "home-services.appliance-electronics-repair.home-appliance-repair",
            "Home appliance repair{near}|Kodinkoneiden korjaus{near}|Vitvarureparation{near}|"
            "Hausgeräte-Reparatur{near}|Witgoedreparatie{near}",
            "appliance repair", look=["repair services"], why="A washing machine or fridge.", local=True),
         _I("car", 0.25, "service", "auto-services.car-repair-servicing",
            "Car repair{near}|Autokorjaamo{near}|Bilverkstad{near}|Autowerkstatt{near}|Autogarage{near}",
            "car repair", domains={"fi": ["fixu.fi"], "de": ["autobutler.de"]}, look=["garages"],
            why="A car to fix or service.", local=True),
         _I("handyman", 0.2, "service", "home-services.handyman",
            "A handyman for home repairs{near}|Remonttimies kotiin{near}|Hantverkare{near}|Handwerker{near}|"
            "Klusjesman{near}",
            "handyman", domains={"de": ["my-hammer.de"], "nl": ["werkspot.nl"]}, look=["service marketplaces"],
            why="Small jobs around the home.", local=True),
     ]},
    {"key": "tv",
     "words": ["tv", "tvs", "television", "televisions", "televisio", "telkkari", "fernseher", "televisie", "teevee"],
     "nodes": ["sp:el-17-4"],
     "intents": [
         _I("set", 0.72, "product", "sp:el-17-4", "A TV|Televisio|En TV|Ein Fernseher|Een televisie", "tv",
            look=["shops", "marketplaces"], why="The TV itself."),
         _I("package", 0.18, "service", "utilities.tv-streaming-packages",
            "TV and streaming packages|TV- ja suoratoistopaketit|TV- och streamingpaket|TV- und Streaming-Pakete|"
            "Tv- en streamingpakketten",
            "tv package", look=["operators", "streaming services"], why="Or something to watch on it."),
         _I("repair", 0.1, "service", "home-services.appliance-electronics-repair.tv-audio-repair",
            "TV repair{near}|Television korjaus{near}|TV-reparation{near}|Fernseher-Reparatur{near}|"
            "Tv-reparatie{near}", "tv repair", look=["repair shops"], why="Or fixing one.", local=True),
     ]},
    {"key": "coffee",
     "words": ["coffee", "kahvi", "kahvia", "kaffe", "kaffee", "koffie"],
     "nodes": ["sp:fb-1-3"],
     "intents": [
         _I("beans", 0.5, "food", "sp:fb-1-3", "Coffee beans and ground coffee|Kahvi (pavut ja jauhettu)|"
            "Kaffe (bönor och malet)|Kaffee (Bohnen und gemahlen)|Koffie (bonen en gemalen)", "coffee",
            look=["grocery shops", "roasters"], why="Coffee to make at home."),
         _I("machine", 0.28, "product", "sp:hg-11-7-4",
            "A coffee machine|Kahvinkeitin tai espressokone|Kaffebryggare eller espressomaskin|Kaffeemaschine|"
            "Koffiemachine",
            "coffee machine", look=["shops", "marketplaces"], why="Or the machine to make it."),
         _I("cafes", 0.22, "service", "food-drink.restaurants-takeaway.cafes-bakeries",
            "Cafés{near}|Kahvilat{near}|Kaféer{near}|Cafés{near}|Koffiezaken{near}", "cafe",
            look=["cafés"], why="Or a cup somewhere near.", local=True),
     ]},
    {"key": "sofa",
     "words": ["sofa", "sofas", "couch", "sohva", "soffa", "sofa bed", "bankstel"],
     "nodes": ["sp:fr-22"],
     "intents": [
         _I("sofa", 0.85, "product", "sp:fr-22", "A sofa|Sohva|En soffa|Ein Sofa|Een bank", "sofa",
            look=["furniture shops", "marketplaces"], why="The sofa itself, new or used."),
         _I("cleaning", 0.15, "service", "home-services.cleaning",
            "Sofa cleaning{near}|Sohvan pesu{near}|Soffrengöring{near}|Sofareinigung{near}|Bank reinigen{near}",
            "sofa cleaning", look=["cleaning companies"], why="Or cleaning the one you have.", local=True),
     ]},
    {"key": "kitchen",
     "words": ["kitchen", "keittio", "kok", "kuche", "keuken"],
     "nodes": [],
     "intents": [
         _I("renovation", 0.38, "service", "trades.building-renovation.kitchen-renovation",
            "Kitchen renovation{near}|Keittiöremontti{near}|Köksrenovering{near}|Küchenrenovierung{near}|"
            "Keukenrenovatie{near}",
            "kitchen renovation", q={"fi": ["keittiöremontti {place}"], "sv": ["köksrenovering {place}"],
                                     "de": ["Küche renovieren {place}"], "nl": ["keuken renoveren {place}"]},
            domains={"fi": ["remonttipalvelu.fi"], "de": ["my-hammer.de"], "nl": ["werkspot.nl"]},
            look=["kitchen fitters", "service marketplaces"], why="A new kitchen is mostly the fitting.", local=True),
         _I("cabinets", 0.32, "product", "sp:fr-4-8", "Kitchen cabinets and units|Keittiökalusteet|Köksskåp|"
            "Küchenschränke|Keukenkasten", "kitchen cabinets", domains={"*": ["ikea.com"]},
            look=["kitchen shops", "marketplaces"], why="The cabinets themselves."),
         _I("appliances", 0.3, "product", "sp:hg-11-7", "Kitchen appliances|Keittiölaitteet|Köksmaskiner|"
            "Küchengeräte|Keukenapparatuur", "kitchen appliances", look=["shops"], why="An oven, a fridge."),
     ]},
    {"key": "bike",
     "words": ["bike", "bikes", "bicycle", "bicycles", "pyora", "polkupyora", "cykel", "cyklar", "fahrrad",
               "fahrrader", "fiets", "fietsen"],
     "nodes": [],
     "intents": [
         _I("bike", 0.7, "product", None, "A bicycle|Polkupyörä|En cykel|Ein Fahrrad|Een fiets", "bicycle",
            look=["bike shops", "marketplaces"], why="The bike itself, new or used."),
         _I("repair", 0.18, "service", "home-services.appliance-electronics-repair.bicycle-repair",
            "Bike repair and service{near}|Pyöränhuolto{near}|Cykelverkstad{near}|Fahrradwerkstatt{near}|"
            "Fietsenmaker{near}", "bike repair", look=["bike shops"], why="Or a service for the one you have.",
            local=True),
         _I("rental", 0.12, "service", "transport.bike-rental-sharing",
            "Bike rental{near}|Pyörävuokraus{near}|Cykeluthyrning{near}|Fahrradverleih{near}|Fietsverhuur{near}",
            "bike rental", look=["rental shops"], why="Or one for a day.", local=True),
     ]},
    {"key": "shoes",
     "words": ["shoes", "shoe", "kengat", "kenka", "skor", "sko", "schuhe", "schuh", "schoenen", "schoen"],
     "nodes": [],
     "intents": [
         _I("shoes", 0.85, "product", None, "Shoes{rest}|Kengät{rest}|Skor{rest}|Schuhe{rest}|Schoenen{rest}",
            "shoes", look=["shoe shops", "marketplaces"], why="Shoes to buy."),
         _I("repair", 0.15, "service", "home-services.appliance-electronics-repair.shoe-repair",
            "Shoe repair{near}|Suutari{near}|Skomakare{near}|Schuster{near}|Schoenmaker{near}", "shoe repair",
            look=["cobblers"], why="Or fixing a pair.", local=True),
     ]},
    {"key": "wedding",
     "words": ["wedding", "weddings", "haat", "haihin", "brollop", "hochzeit", "bruiloft", "trouwen"],
     "nodes": ["events-leisure.weddings"],
     "intents": [
         _I("venue", 0.3, "service", "events-leisure.weddings.wedding-venues",
            "Wedding venues{near}|Hääpaikat{near}|Bröllopslokaler{near}|Hochzeitslocations{near}|Trouwlocaties{near}",
            "wedding venue", domains={"fi": ["venuu.fi", "tilamisu.fi"]}, look=["venue listings"],
            why="The first thing most couples book.", local=True),
         _I("photographer", 0.2, "service", "events-leisure.weddings.wedding-photographer",
            "Wedding photographers{near}|Hääkuvaajat{near}|Bröllopsfotografer{near}|Hochzeitsfotografen{near}|"
            "Trouwfotografen{near}", "wedding photographer", look=["photographers' sites"],
            why="Priced per package.", local=True),
         _I("catering", 0.18, "service", "events-leisure.catering",
            "Wedding catering{near}|Hääpitopalvelu{near}|Bröllopscatering{near}|Hochzeitscatering{near}|"
            "Bruiloftcatering{near}", "wedding catering", q={"fi": ["hääpitopalvelu {place}"]},
            look=["caterers"], why="Food per guest.", local=True),
         _I("dress", 0.17, "product", "sp:aa-1-22-2", "Wedding dresses|Hääpuvut|Brudklänningar|Brautkleider|"
            "Trouwjurken", "wedding dress", look=["bridal shops", "marketplaces"], why="New or worn once."),
         _I("gift", 0.15, "product", None, "A wedding gift|Häälahja|Bröllopspresent|Hochzeitsgeschenk|"
            "Huwelijkscadeau", "wedding gift", look=["gift shops"], why="If you are a guest."),
     ]},
]

# a node the hunt started from -> the curated meanings planned for it (School catering plans providers)
BY_NODE: dict[str, str] = {}
for _c in CONCEPTS:
    for _n in _c["nodes"]:
        BY_NODE.setdefault(_n, _c["key"])
BY_KEY: dict[str, dict[str, Any]] = {c["key"]: c for c in CONCEPTS}

# folded trigger phrase -> concept key (longest phrase wins at match time)
TRIGGERS: dict[str, str] = {}
for _c in CONCEPTS:
    for _w in _c["words"]:
        TRIGGERS.setdefault(fold(_w), _c["key"])
_TRIGGER_RE = re.compile(r"(?<![\w])(" + "|".join(sorted((re.escape(t) for t in TRIGGERS), key=len, reverse=True))
                         + r")(?![\w])")

# words that say the person wants a provider's work, not a thing: they push local services up
SERVICE_CUES = re.compile(r"\b(?:near me|near|nearby|lahella|lähellä|in der nahe|in der nähe|bij mij|"
                          r"service|services|palvelu\w*|company|companies|yritys|firma|firmor|bedrijf|"
                          r"provider|providers|book|booking|order|delivery|deliver|toimitus|kuljetus)\b", re.I)
PRODUCT_CUES = re.compile(r"\b(?:used|new|refurbished|käytetty|kaytetty|uusi|gebraucht|begagnad|tweedehands|"
                          r"\d+\s?(?:gb|tb|inch|tuuma|cm|mm|w)\b|€|eur|under|alle|max)\b", re.I)

# ---------------------------------------------------------------- place + language words

_NEAR = {"en": " near you", "fi": " lähelläsi", "sv": " nära dig", "de": " in deiner Nähe", "nl": " bij jou in de buurt"}
_IN = {"en": " in {p}", "fi": " – {p}", "sv": " i {p}", "de": " in {p}", "nl": " in {p}"}
_NEAR_IN = {"en": " near you in {p}", "fi": " lähelläsi – {p}", "sv": " nära dig i {p}", "de": " in {p}",
            "nl": " in {p}"}
_TO = {"en": " to {p}", "fi": " – {p}", "sv": " till {p}", "de": " nach {p}", "nl": " naar {p}"}
_LANG_OF_CC = {"fi": "fi", "se": "sv", "de": "de", "at": "de", "nl": "nl", "be": "nl"}
_PLACE_PREP = re.compile(r"\b(?:in|near|around|at|to|till|nach|naar|bei|i|kohteeseen|lähellä)\s*$", re.I)


def _cc(country: str | None) -> str:
    raw = (country or os.environ.get("AGORA_COUNTRY") or "fi").strip().lower()
    names = {"finland": "fi", "suomi": "fi", "sweden": "se", "sverige": "se", "germany": "de", "deutschland": "de",
             "netherlands": "nl", "nederland": "nl", "uk": "gb", "united kingdom": "gb"}
    return names.get(raw, raw[:2] if len(raw) >= 2 else "fi")


def _lang(lang: str | None) -> str:
    lang = (lang or "en").lower()[:2]
    return lang if lang in LANGS else "en"


def find_place(text: str) -> tuple[str | None, str | None, str]:
    """(place display name, its country code, the text without it). Uses agora.places when it loads."""
    try:
        from agora import places
        hit = places.find_place(text)
    except Exception:
        hit = None
    if not hit:
        return None, None, text
    name, cc, (a, b) = hit
    rest = (_PLACE_PREP.sub("", text[:a]) + " " + text[b:]).strip()
    return name, cc, re.sub(r"\s+", " ", rest)


def _fill(s: str, place: str | None) -> str:
    return re.sub(r"\s+", " ", s.replace("{place}", place or "")).strip()


# ---------------------------------------------------------------- taxonomy (optional, read-only)

def _tax() -> Any | None:
    try:
        from agora import taxonomy
        return taxonomy.load()
    except Exception:
        return None


def _node_brief(T: Any, nid: str | None, lang: str) -> dict[str, Any] | None:
    if T is None or not nid:
        return None
    cur = T.resolve(nid)
    if cur is None:
        return None
    i = T._i(cur)
    return {"id": cur, "label": T.label(i, lang), "path": T.path(i, lang), "kind": T.kind[i],
            "huntable": bool(T.hunt_ok[i]), "where": T.where(i)}


# ---------------------------------------------------------------- building one intent

def _render(tpl: dict[str, Any], *, concept: str, lang: str, cc: str, place: str | None, near: str | None,
            rest: str, T: Any) -> dict[str, Any]:
    nb = _node_brief(T, tpl["node"], lang)
    label = tpl["label"].get(lang) or tpl["label"]["en"]
    where_p = place or near
    if tpl["local"]:
        near_txt = (_IN[lang].format(p=place) if place else _NEAR_IN[lang].format(p=near) if near else _NEAR[lang])
    else:
        near_txt = ""
    to_txt = ((_TO if tpl["travel"] == "to" else _IN)[lang].format(p=place)) if (tpl["travel"] and place) else ""
    rest_txt = f" {rest}" if rest else ""
    label = label.replace("{near}", near_txt).replace("{to}", to_txt).replace("{rest}", rest_txt)
    label = re.sub(r"\s+", " ", label).strip()
    if tpl["travel"] and place:
        hunt_words = f"{tpl['hunt']} {'to ' if tpl['travel'] == 'to' else ''}{place}"
    else:
        hunt_words = tpl["hunt"] + rest_txt + (f" {place}" if tpl["local"] and place else "")
    queries: dict[str, list[str]] = {}
    for lg, qs in (tpl["q"] or {}).items():
        out = []
        for qq in qs:
            qq = qq.replace("{rest}", f" {rest}" if rest else "")
            if "{place}" not in qq and ((tpl["local"] and where_p) or (tpl["travel"] and place)):
                qq += " {place}"
            out.append(_fill(qq, where_p if tpl["local"] else place if tpl["travel"] else None))
        queries[lg] = out
    queries.setdefault("en", [_fill(hunt_words, None)])
    doms = list(tpl["domains"].get(cc, [])) + [d for d in tpl["domains"].get("*", []) if "." in d]
    look = list(tpl["look"])
    for d in tpl["domains"].get("*", []):
        if "." not in d and d not in look:
            look.append(d)
    if nb:
        doms += _node_domains(nb, cc, tpl["kind"])
    doms = list(dict.fromkeys(doms))
    node_id = nb["id"] if nb else None
    cat = node_id if (nb and nb["huntable"]) else None
    return {
        "id": f"c:{concept}.{tpl['key']}", "label": label, "kind": tpl["kind"], "node": node_id,
        "node_label": nb["label"] if nb else None, "node_path": nb["path"] if nb else None,
        "huntable": bool(nb["huntable"]) if nb else True,
        "hunt": {"q": re.sub(r"\s+", " ", hunt_words).strip(), "cat": cat, "intent": f"c:{concept}.{tpl['key']}"},
        "queries": queries, "lanes": list(tpl["lanes"]), "domains": doms[:10], "look": look,
        "why": tpl["why"], "local": tpl["local"], "travel": tpl["travel"] or "",
        "place": where_p if tpl["local"] else place if tpl["travel"] else None,
        "source": "curated", "w": tpl["w"],
    }


def _from_node(T: Any, nid: str, lang: str, cc: str, *, place: str | None, near: str | None, typed: str,
               w: float, source: str, why: str = "") -> dict[str, Any] | None:
    nb = _node_brief(T, nid, lang)
    if nb is None:
        return None
    kind = nb["kind"]
    local = kind == "service" and not any(x in nb["id"] for x in ("utilities", "finance", "software", "digital",
                                                                   "travel", "professional"))
    where_p = place or near
    label = nb["label"]
    if local:
        label += _IN[lang].format(p=place) if place else _NEAR_IN[lang].format(p=near) if near else _NEAR[lang]
    i = T._i(nb["id"])
    labels = T.labels[i]
    queries: dict[str, list[str]] = {}
    for lg in LANGS:
        lab = labels.get(lg)
        if lab:
            queries[lg] = [_fill(f"{lab} {{place}}" if local else lab, where_p if local else None)]
    doms = _node_domains(nb, cc, kind)[:8]
    hunt_q = typed if source == "as-typed" else (nb["label"] + (f" {place}" if (local and place) else ""))
    return {
        "id": f"n:{nb['id']}", "label": label, "kind": kind, "node": nb["id"], "node_label": nb["label"],
        "node_path": nb["path"], "huntable": nb["huntable"],
        "hunt": {"q": hunt_q, "cat": nb["id"] if nb["huntable"] and source != "as-typed" else None,
                 "intent": f"n:{nb['id']}"},
        "queries": queries, "lanes": T.lanes(i), "domains": doms,
        "look": ["providers near you"] if local else (["shops", "marketplaces"] if kind in ("product", "vehicle")
                                                      else ["providers", "comparison sites"]),
        "why": why or f"{' › '.join(nb['path'][-3:])}", "local": local,
        "place": where_p if local else None, "source": source, "w": w,
    }


# sites that only serve one country (the tree's shop-menu sources): never offered to a person elsewhere
DOMAIN_CC = {"checkatrade.com": "gb", "bark.com": "gb", "yelp.com": "us", "taskrabbit.com": "us",
             "my-hammer.de": "de", "myhammer.at": "at", "helpling.de": "de", "helpling.nl": "nl", "werkspot.nl": "nl",
             "marktplaats.nl": "nl", "kleinanzeigen.de": "de", "blocket.se": "se", "tori.fi": "fi", "emag.hu": "hu",
             "otto.de": "de", "mediamarkt.de": "de", "coolblue.nl": "nl", "offerta.se": "se", "zalando.fi": "fi"}
_CC_TLDS = ("fi", "se", "de", "nl", "hu", "dk", "no", "at", "be", "fr", "es", "it", "pl", "ee", "uk")


def dom_ok(dom: str, cc: str) -> bool:
    """False for a site that serves another country only (checkatrade.com is British, tori.fi Finnish)."""
    known = DOMAIN_CC.get(dom)
    if known:
        return known == cc
    tld = dom.rsplit(".", 1)[-1]
    return tld not in _CC_TLDS or tld == cc or (tld == "uk" and cc == "gb")


def _node_domains(nb: dict[str, Any], cc: str, kind: str) -> list[str]:
    """Where-to-look domains of a node that fit the meaning: a service only its own service-lane sites (an
    inherited ticket shop is no caterer); a thing its own shops, else the inherited shops of the country."""
    svc = kind in ("service", "digital")
    out = []
    for w in nb["where"]:
        lane, dom = w["lane"], w["domain"]
        if lane == "comparison" or (lane == "service") != svc:
            continue
        if not dom_ok(dom, cc):
            continue
        if w["from"] == nb["id"] or (not svc and dom.endswith("." + cc)):
            out.append(dom)
    return out


# tree nodes read from one country's shop or service menu (checkatrade.com is British)
NODE_CC = {"m:checkatrade:": "gb", "m:myhammer:": "de", "m:helpling:": "de", "m:tori:": "fi", "m:blocket:": "se",
           "m:marktplaats:": "nl", "m:otto:": "de", "m:mediamarkt": "de", "m:coolblue:": "nl", "m:emag:": "hu",
           "m:ipon:": "hu"}


def node_ok(nid: str, cc: str) -> bool:
    for pre, ncc in NODE_CC.items():
        if nid.startswith(pre):
            return ncc == cc
    return True


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", fold(s)) if len(w) > 2 and w not in ("and", "for", "the", "other")]


def _official(nid: str) -> bool:
    return nid.startswith(("cpv:", "nace:"))


def _taxonomy_intents(T: Any, core: str, lang: str, cc: str, *, place: str | None, near: str | None,
                      typed: str, limit: int = 4) -> list[dict[str, Any]]:
    """One meaning per distinct branch of the tree (a phone / a phone plan / phone repair), scored by search."""
    if T is None or not core.strip():
        return []
    try:
        hits = T.search(core, limit=14, lang=lang)
    except Exception:
        return []
    if not hits:
        return []
    top = hits[0]["score"]
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for h in hits:
        if h["score"] < max(0.8, top * 0.7):
            continue
        root = T.path_idx(T._i(h["id"]))[0]
        kind_group = "product" if h["kind"] in ("product", "food", "vehicle") else h["kind"]
        key = (kind_group, T.ids[root])
        s = h["score"] - (0.05 if _official(h["id"]) else 0.0)
        if key not in groups or s > groups[key]["s"]:
            groups[key] = {"s": s, "h": h}
    ranked, per_kind = [], {}
    for g in sorted(groups.values(), key=lambda g: -g["s"]):
        kg = "product" if g["h"]["kind"] in ("product", "food", "vehicle") else g["h"]["kind"]
        if per_kind.get(kg, 0) >= 2:          # a massage, not four kinds of massager
            continue
        per_kind[kg] = per_kind.get(kg, 0) + 1
        ranked.append(g)
        if len(ranked) >= limit:
            break
    out = []
    try:
        cls = T.classify(typed, lang=lang)
    except Exception:
        cls = None
    for k, g in enumerate(ranked):
        h = g["h"]
        as_typed = k == 0 and (cls is None or cls["id"] == h["id"] or (cls.get("confidence") or 0) < 0.6)
        it = _from_node(T, h["id"], lang, cc, place=place, near=near, typed=typed, w=math.exp(6 * g["s"]),
                        source="as-typed" if as_typed else "taxonomy")
        if it:
            out.append(it)
    return out


# ---------------------------------------------------------------- category context (a hunt or page from the tree)

def _category_intents(T: Any, nid: str, lang: str, cc: str, *, place: str | None, near: str | None,
                      typed: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(meanings, next steps) for a node: its curated plan when it has one, else the node itself as a provider
    search, its broader parent and two concrete siblings. Next steps never leave a dead end."""
    nb = _node_brief(T, nid, lang)
    if nb is None:
        return [], []
    intents: list[dict[str, Any]] = []
    key = BY_NODE.get(nb["id"])
    if key:
        c = BY_KEY[key]
        intents = [_render(t, concept=key, lang=lang, cc=cc, place=place, near=near, rest="", T=T)
                   for t in c["intents"]]
    else:
        me = _from_node(T, nb["id"], lang, cc, place=place, near=near, typed=typed, w=3.0, source="category",
                        why="The category you are in.")
        if me:
            intents.append(me)
    i = T._i(nb["id"])
    sib_ids: list[str] = []
    p = T.parent[i]
    stems = {t[:5] for t in _words(T.label(i, "en"))}
    if p >= 0:
        if T.hunt_ok[p] and T.depth[p] >= 2 and node_ok(T.ids[p], cc) and T.ids[p] not in {x["node"] for x in intents}:
            par = _from_node(T, T.ids[p], lang, cc, place=place, near=near, typed=typed, w=0.6 if key else 1.0,
                             source="broader", why=f"Broader: everything in {T.label(p, lang)}.")
            if par:
                intents.append(par)
        # siblings that are the same sort of thing ('School catering' -> other catering services, never 'Zoos')
        kids = [c for c in T.children_of[p] if c != i and T.hunt_ok[c] and T.kind[c] == T.kind[i]
                and node_ok(T.ids[c], cc) and len(T.label(c, lang)) <= 40
                and stems & {t[:5] for t in _words(T.label(c, "en"))}]
        kids.sort(key=lambda c: (_official(T.ids[c]), len(T.label(c, lang)), T.label(c, lang)))
        sib_ids = [T.ids[c] for c in kids[:3]]
    for sid in sib_ids:
        if key or len(intents) >= MAX_INTENTS or sid in {x["node"] for x in intents}:
            continue
        sib = _from_node(T, sid, lang, cc, place=place, near=near, typed=typed, w=0.4, source="sibling",
                         why="Next to it in the tree.")
        if sib:
            intents.append(sib)
    nxt = []
    if nb["kind"] in ("service", "digital"):
        words = (nb["label"] + (" near me" if not (place or near) else f" {place or near}")).strip()
        nxt.append({"label": {"en": "Search providers near you", "fi": "Hae palveluntarjoajia läheltäsi",
                              "sv": "Sök leverantörer nära dig", "de": "Anbieter in deiner Nähe suchen",
                              "nl": "Zoek aanbieders bij jou in de buurt"}[lang],
                    "hunt": {"q": words, "cat": nb["id"] if nb["huntable"] else None, "intent": f"n:{nb['id']}"},
                    "kind": "providers"})
    if p >= 0:
        nxt.append({"label": T.label(p, lang), "open": T.ids[p], "kind": "broader"})
    for sid in sib_ids[:2]:
        nxt.append({"label": T.label(T._i(sid), lang), "hunt": {"q": T.label(T._i(sid), lang), "cat": sid,
                                                                 "intent": f"n:{sid}"}, "kind": "sibling"})
    return intents, nxt


# ---------------------------------------------------------------- Gemini (optional)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_PROMPT = """A person typed a short request into a price comparison site for things AND services in {country}.
{request}
List the 2 to 4 most likely things they want to buy, likeliest first. Return only JSON:
{{"intents": [{{"label": "plain words, max 6 words", "kind": "product|service|digital|food",
"search": "2-4 English words a shop or provider would use", "where": ["kind of site to look at"],
"confidence": 0.0-1.0}}]}}"""


def _gemini_key() -> str | None:
    if os.environ.get("AGORA_OFFLINE", "").lower() in ("1", "true", "yes"):
        return None
    if os.environ.get("AGORA_INTENT_LLM", "1") in ("0", "off", "false"):
        return None
    try:
        from agora.relevance import _key
        return _key()
    except Exception:
        return os.environ.get("GEMINI_API_KEY") or None


def _gemini(q: str, cc: str, timeout: float = GEMINI_TIMEOUT_S) -> list[dict[str, Any]] | None:
    key = _gemini_key()
    if not key:
        return None
    try:
        import httpx
        from agora import fence
        prompt = _PROMPT.format(country=cc.upper(), request=fence.fence(q, source="search box", max_chars=200))
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        r = httpx.post(GEMINI_URL.format(model=model), json=body, headers={"x-goog-api-key": key}, timeout=timeout)
        r.raise_for_status()
        data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    except Exception:
        return None
    return parse_gemini(data)


def parse_gemini(data: Any) -> list[dict[str, Any]] | None:
    """Strict: a dict with an 'intents' list of {label, kind, search, confidence}; anything else is dropped."""
    if not isinstance(data, dict) or not isinstance(data.get("intents"), list):
        return None
    out = []
    for x in data["intents"][:4]:
        if not isinstance(x, dict):
            continue
        label, search, kind = x.get("label"), x.get("search"), x.get("kind")
        if not (isinstance(label, str) and isinstance(search, str) and 1 < len(label) <= 60 and 1 < len(search) <= 60):
            continue
        if kind not in ("product", "service", "digital", "food"):
            continue
        try:
            conf = max(0.0, min(1.0, float(x.get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        where = [w for w in (x.get("where") or []) if isinstance(w, str) and len(w) <= 40][:3]
        out.append({"label": re.sub(r"[<>\n\r]", " ", label).strip(), "search": re.sub(r"[<>\n\r]", " ", search).strip(),
                    "kind": kind, "where": where, "confidence": conf})
    return out or None


def _merge_gemini(T: Any, intents: list[dict[str, Any]], llm: list[dict[str, Any]], lang: str, cc: str, *,
                  place: str | None, near: str | None, typed: str) -> list[dict[str, Any]]:
    have_nodes = {i["node"] for i in intents if i.get("node")}
    for k, g in enumerate(llm):
        node = None
        try:
            c = T.classify(g["search"], lang=lang) if T is not None else None
            node = c["id"] if c and (c.get("confidence") or 0) >= 0.5 else None
        except Exception:
            node = None
        if node and node in have_nodes:            # the model agrees with a meaning we had: lift it
            for i in intents:
                if i.get("node") == node:
                    i["w"] *= 1.0 + g["confidence"]
            continue
        it = _from_node(T, node, lang, cc, place=place, near=near, typed=typed, w=0.0, source="gemini") if node else None
        if it is None:
            it = {"id": f"g:{fold(g['search'])}", "label": g["label"], "kind": g["kind"], "node": None,
                  "node_label": None, "node_path": None, "huntable": True,
                  "hunt": {"q": g["search"] + (f" {place}" if place else ""), "cat": None,
                           "intent": f"g:{fold(g['search'])}"},
                  "queries": {"en": [g["search"]]}, "lanes": ["service"] if g["kind"] == "service" else ["new", "used"],
                  "domains": [], "look": g["where"], "why": "Suggested by Gemini.", "local": g["kind"] == "service",
                  "place": place, "source": "gemini", "w": 0.0}
        it["label"] = g["label"] if it["source"] == "gemini" and not it.get("node_label") else it["label"]
        it["source"] = "gemini"
        it["w"] = 0.0          # set below relative to the others
        it["_g"] = g["confidence"] * (1.0 - 0.15 * k)
        intents.append(it)
    total = sum(i["w"] for i in intents if "_g" not in i) or 1.0
    for i in intents:
        if "_g" in i:
            i["w"] = total * 0.5 * i.pop("_g")
    return intents


# ---------------------------------------------------------------- interpret

def match_concept(text: str) -> tuple[str | None, str, str]:
    """(concept key, the matched phrase, the words left over) for the longest trigger in the text."""
    f = fold(text)
    best = None
    for m in _TRIGGER_RE.finditer(f):
        if best is None or len(m.group(1)) > len(best.group(1)):
            best = m
    if best is None:
        return None, "", f
    rest = (f[:best.start()] + " " + f[best.end():]).strip()
    rest = re.sub(r"^(?:a|an|the|some|my)\s+", "", rest)
    rest = re.sub(r"\s+", " ", rest).strip()
    return TRIGGERS[best.group(1)], best.group(1), rest


def interpret(q: str, country: str | None = None, lang: str | None = None, category: str | None = None, *,
              near: str | None = None, llm: bool = True) -> dict[str, Any]:
    """q -> {q, country, lang, place, concept, dominant, intents: [...2-5], next: [...]}. Intents are ranked,
    confidences sum to <= 1. `near`: a city the viewer told us before (labels say 'near you in Helsinki')."""
    q = re.sub(r"\s+", " ", (q or "").strip())[:200]
    cc, lang = _cc(country), _lang(lang)
    T = _tax()
    place, place_cc, core = find_place(q)
    if place_cc and not country:
        cc = place_cc
    near = (near or "").strip()[:60] or None
    if place:
        near = None
    out: dict[str, Any] = {"q": q, "country": cc, "lang": lang, "place": place, "near": near, "concept": None,
                           "category": None, "dominant": False, "intents": [], "next": []}
    intents: list[dict[str, Any]] = []
    nxt: list[dict[str, Any]] = []
    if category and T is not None:
        intents, nxt = _category_intents(T, category, lang, cc, place=place, near=near, typed=q)
        nb = _node_brief(T, category, lang)
        out["category"] = {"id": nb["id"], "label": nb["label"], "path": nb["path"], "kind": nb["kind"],
                           "huntable": nb["huntable"]} if nb else None
    if not intents:
        key, phrase, rest = match_concept(core)
        # a concept word buried in a longer specific request ('lunch box with 3 compartments') is not vague:
        # the curated meanings lead only when the words are mostly the concept itself
        if key and len(rest.split()) > 3:
            key = None
        if key:
            out["concept"] = key
            c = BY_KEY[key]
            intents = [_render(t, concept=key, lang=lang, cc=cc, place=place, near=near, rest=rest, T=T)
                       for t in c["intents"]]
        else:
            intents = _taxonomy_intents(T, core or q, lang, cc, place=place, near=near, typed=q)
    # context: a place, or words like 'near me' / 'company' / 'delivery', make local services likelier;
    # 'used', sizes, a budget make things for sale likelier
    svc_cue = bool(place) or bool(SERVICE_CUES.search(q))
    prod_cue = bool(PRODUCT_CUES.search(q))
    for it in intents:
        if svc_cue and it["kind"] in ("service",) and it.get("local"):
            it["w"] *= 1.6
        if svc_cue and it["kind"] in ("product", "vehicle", "food") and not prod_cue:
            it["w"] *= 0.6
        if prod_cue and it["kind"] in ("product", "vehicle", "food"):
            it["w"] *= 1.6
    if llm and not category and intents is not None:
        g = _gemini(q, cc)
        if g:
            intents = _merge_gemini(T, intents, g, lang, cc, place=place, near=near, typed=q)
    # rank, dedupe (one per node / label), cap, normalise
    intents.sort(key=lambda i: -i["w"])
    seen_nodes, seen_labels, ranked = set(), set(), []
    for it in intents:
        k_node, k_lab = it.get("node"), fold(it["label"])
        if (k_node and k_node in seen_nodes and it["source"] != "curated") or k_lab in seen_labels:
            continue
        if k_node:
            seen_nodes.add(k_node)
        seen_labels.add(k_lab)
        ranked.append(it)
        if len(ranked) >= MAX_INTENTS:
            break
    total = sum(i["w"] for i in ranked) or 1.0
    for it in ranked:
        it["confidence"] = round(it.pop("w") / total, 3)
    for it in ranked:
        # this meaning is what a plain hunt for the typed words already does: the viewer runs it unchanged
        it["as_typed"] = it["source"] == "as-typed" or (
            it["kind"] in ("product", "vehicle", "food") and fold(it["hunt"]["q"]) == fold(q))
        if it["as_typed"]:
            it["hunt"] = {"q": q, "cat": None, "intent": it["id"]}
    out["intents"] = ranked
    if len(ranked) >= 2:
        top, second = ranked[0]["confidence"], ranked[1]["confidence"]
        out["dominant"] = top >= DOMINANT_CONF and top - second >= DOMINANT_MARGIN
    else:
        out["dominant"] = bool(ranked)
    if ranked and not category:
        nxt = _next_steps(T, ranked[0], lang, place=place, near=near)
    out["next"] = nxt
    out["summary"] = summary(ranked[0], lang) if ranked else None
    # a place the viewer may want remembered as 'near you' (a destination like 'flight to berlin' is not home)
    out["remember"] = place if (place and ranked and ranked[0].get("local")) else None
    return out


def _same_branch(T: Any, a: str | None, b: str | None) -> bool:
    if T is None or not a or not b:
        return False
    try:
        pa, pb = T.path_idx(T._i(a)), T.path_idx(T._i(b))
    except KeyError:
        return False
    return pa[: len(pb)] == pb or pb[: len(pa)] == pa or (len(pa) > 1 and len(pb) > 1 and pa[:2] == pb[:2])


def _next_steps(T: Any, top: dict[str, Any], lang: str, *, place: str | None, near: str | None) -> list[dict[str, Any]]:
    """What to offer when the top meaning's hunt finds nothing: providers near you, the broader category."""
    out = []
    if top["kind"] in ("service", "digital"):
        words = re.sub(r"\s+", " ", f"{top['hunt']['q']}" + ("" if (place or near) else " near me")).strip()
        out.append({"label": {"en": "Search providers near you", "fi": "Hae palveluntarjoajia läheltäsi",
                              "sv": "Sök leverantörer nära dig", "de": "Anbieter in deiner Nähe suchen",
                              "nl": "Zoek aanbieders bij jou in de buurt"}[lang],
                    "hunt": {"q": words if near is None else f"{top['hunt']['q']} {near}",
                             "cat": top["hunt"].get("cat"), "intent": top["id"]}, "kind": "providers"})
    if T is not None and top.get("node"):
        try:
            i = T._i(top["node"])
            p = T.parent[i]
            if p >= 0:
                out.append({"label": T.label(p, lang), "open": T.ids[p], "kind": "broader"})
        except KeyError:
            pass
    return out


def summary(it: dict[str, Any], lang: str = "en") -> str:
    """The chosen meaning in plain words: 'Lunch places near you · lounaat.info, lounasaika.net, restaurant sites'."""
    where = [d for d in it.get("domains") or []][:3] or list(it.get("look") or [])[:2]
    return it["label"] + (f" · {', '.join(where)}" if where else "")


# ---------------------------------------------------------------- lookups for the hunt hook

def plan(intent_id: str, q: str = "", *, country: str | None = None, lang: str | None = "en",
         near: str | None = None) -> dict[str, Any] | None:
    """One meaning by id ('c:lunch.places', 'n:<node id>'), rendered for q's place and the country."""
    if not intent_id:
        return None
    cc, lg = _cc(country), _lang(lang)
    T = _tax()
    place, place_cc, core = find_place(q or "")
    if place_cc and not country:
        cc = place_cc
    if intent_id.startswith("c:"):
        key, _, sub = intent_id[2:].partition(".")
        c = BY_KEY.get(key)
        tpl = next((t for t in (c or {}).get("intents", []) if t["key"] == sub), None)
        if tpl is None:
            return None
        hw, fc = fold(tpl["hunt"]), fold(core)
        if fc == hw or fc.startswith(hw + " "):      # the hunt's own words came back ('lunch restaurant')
            rest = fc[len(hw):].strip()
        else:                                        # the typed words ('gift for mom')
            _k, _p, rest = match_concept(core)
            rest = rest if _k == key else ""
        it = _render(tpl, concept=key, lang=lg, cc=cc, place=place, near=near, rest=rest, T=T)
        it["confidence"] = tpl["w"]
        it.pop("w", None)
        return it
    if intent_id.startswith("n:") and T is not None:
        it = _from_node(T, intent_id[2:], lg, cc, place=place, near=near, typed=q, w=1.0, source="taxonomy")
        if it:
            it.pop("w", None)
            it["confidence"] = 1.0
        return it
    return None


def apply(need: Any, intent_id: str, *, country: str | None = None, lang: str = "en") -> dict[str, Any] | None:
    """Fit a parsed Need to one meaning, for agora.hunt (GET /hunt?...&intent=<id>). Sets need.category to the
    meaning's node (via agora.need.category_info / apply_category: kind, lanes, size), then lays the meaning's
    words over it: need.thing = its hunt words, labels[local lang] = its local query (discover.local_words reads
    it), its where-to-look domains as the node's own service domains (discover.category_sites reads them), and
    category["intent"] = {id, label, queries, look, why}. Returns the `category` event payload (+ "intent"), or
    None when the id is unknown. Never raises."""
    try:
        it = plan(intent_id, getattr(need, "raw", "") or "", country=country, lang=lang)
        if it is None:
            return None
        from agora import need as need_mod
        cat = need_mod.category_info(it["node"], source="intent", confidence=it.get("confidence") or 0.5) \
            if it.get("node") else None
        if cat is None:
            cat = {"id": None, "label": it["label"], "path": [it["label"]], "path_ids": [], "kind": it["kind"],
                   "lanes": it["lanes"], "size": None, "bulky": False, "domains": [], "labels": {}, "synonyms": [],
                   "service": None, "source": "intent", "confidence": it.get("confidence") or 0.5}
        cat = dict(cat)
        labels = dict(cat.get("labels") or {})
        for lg, qs in (it.get("queries") or {}).items():
            if qs and lg != "en":
                labels[lg] = re.sub(r"\s+", " ", qs[0].replace(it.get("place") or "\x00", "")).strip()
        cat["labels"] = labels
        own = [{"domain": d, "lane": "service" if it["kind"] in ("service", "digital") else "new",
                "from": cat.get("id")} for d in it.get("domains") or []]
        cat["domains"] = own + [d for d in cat.get("domains") or [] if d.get("domain") not in set(it["domains"])]
        cat["kind"] = it["kind"] if it["kind"] in ("service", "digital") else cat.get("kind") or it["kind"]
        cat["intent"] = {"id": it["id"], "label": it["label"], "queries": it["queries"], "look": it["look"],
                         "why": it["why"], "domains": it["domains"], "travel": bool(it.get("travel"))}
        need_mod.apply_category(need, cat)
        if it["kind"] in ("vehicle", "product", "food") and it.get("lanes"):
            need.conditions = [c for c in it["lanes"] if c in ("new", "used", "refurbished", "rental")] \
                or need.conditions
        words = it["hunt"]["q"]
        if it.get("place") and it.get("local"):       # 'haircut Helsinki': the job, in that city
            words = re.sub(rf"\s*\b{re.escape(it['place'])}\b", "", words, flags=re.I).strip()
            need.where = need.where or it["place"]
        elif it.get("travel"):                        # 'flights to Berlin': bought at home, the place is the trip
            need.where = None
        need.thing = words.lower() or need.thing
        ev = need_mod._cat_event(cat) if cat.get("id") else {
            "id": None, "label": cat["label"], "path": cat["path"], "kind": cat["kind"],
            "confidence": cat["confidence"], "source": "intent", "lanes": cat["lanes"], "size": None,
            "domains": [d["domain"] for d in cat["domains"]][:8]}
        ev["intent"] = {"id": it["id"], "label": it["label"], "look": it["look"]}
        return ev
    except Exception:
        return None


# ---------------------------------------------------------------- HTTP (mounted by agora.api)

try:
    from fastapi import APIRouter, Query, Response
except ImportError:          # fastapi missing: the module still works as a library
    APIRouter = None         # type: ignore[assignment,misc]


def _router() -> Any:
    r = APIRouter()
    import threading

    def warm() -> None:              # the tree's search index (~1 s) before the first person types
        T = _tax()
        if T is not None and getattr(T, "_post", None) is None:
            T._build_index()
    threading.Thread(target=warm, name="intent-warm", daemon=True).start()

    @r.get("/api/intent")
    def intent_endpoint(response: Response, q: str = Query("", max_length=200), country: str | None = Query(None),
                        lang: str = Query("en"), cat: str | None = Query(None, max_length=120),
                        near: str | None = Query(None, max_length=60)) -> dict[str, Any]:
        """What a vague request most likely means: 2-5 ranked meanings, each with a search plan (hunt {q, cat,
        intent}, local-language queries, lanes, where-to-look domains, why) and a confidence; dominant = the
        top one is clearly it. cat=<node id>: meanings and next steps for a category (never a dead end)."""
        response.headers["Cache-Control"] = "public, max-age=300"
        if len(q.strip()) < 2 and not cat:
            return {"q": q, "intents": [], "dominant": False, "next": []}
        return interpret(q, country, lang, cat or None, near=near)

    return r


router = _router() if APIRouter is not None else None
