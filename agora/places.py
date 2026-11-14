"""PLACES: a compact European gazetteer. Free text -> (place, ISO country code, language).

Written at Junction 2026 (round 7). Offline and instant: ~700 cities and every European country name
(English + endonyms), so "home cleaning tilburg", "plumber in eindhoven" or "kallax gebraucht köln"
get a country (search filter, local marketplaces) and a language (local-language queries).

Ambiguous names ("nice", "reading", "split", "oxford", "worms") only count after a place preposition
("in Nice"), and in an IKEA query Swedish towns are product names ("STOCKHOLM rug") unless "in"/"near"
comes first.
"""
from __future__ import annotations

import re
import unicodedata

# cc -> comma-separated city names (lower case; spelling variants allowed)
_CITIES: dict[str, str] = {
    "nl": "amsterdam, rotterdam, den haag, the hague, 's-gravenhage, utrecht, eindhoven, tilburg, groningen, "
          "almere, breda, nijmegen, apeldoorn, haarlem, arnhem, enschede, amersfoort, zaanstad, zaandam, "
          "'s-hertogenbosch, den bosch, hertogenbosch, zwolle, zoetermeer, leiden, maastricht, dordrecht, ede, "
          "alphen aan den rijn, leeuwarden, alkmaar, emmen, delft, deventer, venlo, sittard, helmond, oss, "
          "hilversum, heerlen, amstelveen, roosendaal, purmerend, schiedam, lelystad, gouda, vlaardingen, "
          "hoofddorp, assen, bergen op zoom, capelle aan den ijssel, veenendaal, katwijk, zeist, nieuwegein, "
          "hengelo, spijkenisse, hoorn, almelo, harderwijk, wageningen, waalwijk, oosterhout, goes, middelburg",
    "be": "brussels, bruxelles, brussel, antwerp, antwerpen, anvers, ghent, gent, gand, charleroi, liège, liege, "
          "luik, bruges, brugge, namur, leuven, louvain, mons, aalst, mechelen, kortrijk, hasselt, ostend, "
          "oostende, genk, sint-niklaas, tournai, roeselare, verviers, wavre, ottignies, waterloo",
    "de": "berlin, hamburg, munich, münchen, muenchen, cologne, köln, koeln, frankfurt, frankfurt am main, "
          "stuttgart, düsseldorf, duesseldorf, dusseldorf, leipzig, dortmund, essen, bremen, dresden, hanover, "
          "hannover, nuremberg, nürnberg, nuernberg, duisburg, bochum, wuppertal, bielefeld, bonn, münster, "
          "muenster, mannheim, karlsruhe, augsburg, wiesbaden, mönchengladbach, gelsenkirchen, aachen, "
          "braunschweig, kiel, chemnitz, halle, magdeburg, freiburg, krefeld, mainz, lübeck, luebeck, erfurt, "
          "oberhausen, rostock, kassel, hagen, potsdam, saarbrücken, saarbruecken, hamm, ludwigshafen, oldenburg, "
          "osnabrück, osnabrueck, leverkusen, heidelberg, darmstadt, solingen, regensburg, herne, paderborn, "
          "neuss, ingolstadt, offenbach, fürth, ulm, heilbronn, pforzheim, würzburg, wuerzburg, wolfsburg, "
          "göttingen, goettingen, bottrop, reutlingen, koblenz, bremerhaven, recklinghausen, erlangen, "
          "bergisch gladbach, trier, jena, remscheid, moers, siegen, hildesheim, salzgitter, cottbus, "
          "kaiserslautern, schwerin, gütersloh, witten, gera, iserlohn, zwickau, düren, ratingen, flensburg, "
          "konstanz, worms, marburg, lüneburg, bamberg, bayreuth, passau, rosenheim, tübingen, tuebingen, "
          "landshut, weimar, wismar, stralsund, greifswald, garmisch-partenkirchen",
    "at": "vienna, wien, graz, linz, salzburg, innsbruck, klagenfurt, villach, wels, st. pölten, sankt pölten, "
          "st pölten, dornbirn, steyr, wiener neustadt, feldkirch, bregenz, leoben, krems",
    "ch": "zurich, zürich, zuerich, geneva, genève, geneve, genf, basel, bâle, bern, berne, lausanne, winterthur, "
          "lucerne, luzern, st. gallen, sankt gallen, lugano, biel, bienne, thun, köniz, fribourg, schaffhausen, "
          "chur, neuchâtel, neuchatel, sion, zug, uster, locarno, bellinzona, montreux",
    "fr": "paris, marseille, lyon, toulouse, nice, nantes, strasbourg, montpellier, bordeaux, lille, rennes, reims, "
          "le havre, saint-étienne, saint-etienne, toulon, grenoble, dijon, angers, nîmes, nimes, villeurbanne, "
          "clermont-ferrand, le mans, aix-en-provence, brest, tours, amiens, limoges, annecy, perpignan, "
          "boulogne-billancourt, metz, besançon, besancon, orléans, orleans, rouen, mulhouse, caen, nancy, "
          "argenteuil, montreuil, roubaix, tourcoing, avignon, poitiers, versailles, pau, la rochelle, calais, "
          "cannes, antibes, ajaccio, bastia, colmar, chambéry, chambery, valence, bayonne, biarritz, lorient, "
          "vannes, quimper, saint-malo, troyes, chartres, cherbourg",
    "lu": "luxembourg city, esch-sur-alzette, differdange, dudelange",
    "es": "madrid, barcelona, valencia, seville, sevilla, zaragoza, málaga, malaga, murcia, palma, "
          "palma de mallorca, las palmas, bilbao, alicante, córdoba, cordoba, valladolid, vigo, gijón, gijon, "
          "l'hospitalet, vitoria, a coruña, la coruña, coruna, granada, elche, oviedo, badalona, cartagena, "
          "terrassa, jerez, sabadell, móstoles, alcalá de henares, pamplona, almería, almeria, fuenlabrada, "
          "leganés, san sebastián, san sebastian, donostia, santander, burgos, castellón, albacete, getafe, "
          "alcorcón, logroño, badajoz, salamanca, huelva, marbella, lleida, tarragona, león, leon, cádiz, cadiz, "
          "jaén, girona, toledo, ibiza, benidorm, santiago de compostela, segovia, torremolinos, estepona",
    "it": "rome, roma, milan, milano, naples, napoli, turin, torino, palermo, genoa, genova, bologna, florence, "
          "firenze, bari, catania, venice, venezia, verona, messina, padua, padova, trieste, taranto, brescia, "
          "parma, prato, modena, reggio calabria, reggio emilia, perugia, ravenna, livorno, cagliari, foggia, "
          "rimini, salerno, ferrara, sassari, latina, monza, siracusa, pescara, bergamo, trento, vicenza, terni, "
          "bolzano, novara, piacenza, ancona, udine, arezzo, cesena, lecce, pisa, como, siena, lucca, sorrento, "
          "varese",
    "pt": "lisbon, lisboa, porto, oporto, braga, coimbra, funchal, amadora, setúbal, setubal, aveiro, faro, évora, "
          "evora, guimarães, guimaraes, viseu, leiria, cascais, sintra, almada, matosinhos, albufeira, portimão",
    "ie": "dublin, cork, limerick, galway, waterford, drogheda, dundalk, swords, bray, navan, kilkenny, ennis, "
          "tralee, carlow, athlone, sligo, wexford, letterkenny",
    "gb": "london, birmingham, manchester, glasgow, leeds, liverpool, edinburgh, bristol, sheffield, cardiff, "
          "belfast, leicester, coventry, nottingham, newcastle, brighton, hull, plymouth, stoke-on-trent, "
          "wolverhampton, derby, southampton, portsmouth, aberdeen, swansea, oxford, cambridge, york, norwich, "
          "milton keynes, reading, luton, sunderland, bournemouth, middlesbrough, dundee, exeter, ipswich, "
          "peterborough, gloucester, bath, cheltenham, inverness, bradford, preston, blackpool, warrington, "
          "slough, watford, chester, lincoln, canterbury, salisbury, worcester, poole, crawley, stockport, bolton",
    "se": "stockholm, gothenburg, göteborg, goteborg, malmö, malmo, uppsala, västerås, vasteras, örebro, orebro, "
          "linköping, linkoping, helsingborg, jönköping, jonkoping, norrköping, norrkoping, lund, umeå, umea, "
          "gävle, gavle, borås, boras, södertälje, sodertalje, eskilstuna, halmstad, växjö, vaxjo, karlstad, "
          "sundsvall, luleå, lulea, östersund, ostersund, trollhättan, kalmar, kristianstad, falun, skövde, "
          "karlskrona, visby, kiruna",
    "no": "oslo, bergen, trondheim, stavanger, drammen, fredrikstad, kristiansand, sandnes, tromsø, tromso, "
          "sarpsborg, skien, ålesund, alesund, sandefjord, haugesund, tønsberg, tonsberg, moss, bodø, bodo, "
          "arendal, hamar, larvik, halden, lillehammer, molde, harstad, gjøvik",
    "dk": "copenhagen, københavn, kobenhavn, aarhus, århus, odense, aalborg, ålborg, esbjerg, randers, kolding, "
          "horsens, vejle, roskilde, herning, silkeborg, næstved, fredericia, viborg, køge, holstebro, slagelse, "
          "hillerød, sønderborg, svendborg, hjørring, frederikshavn, helsingør, elsinore",
    "fi": "helsinki, espoo, vantaa, tampere, turku, oulu, jyväskylä, jyvaskyla, lahti, kuopio, pori, joensuu, "
          "lappeenranta, hämeenlinna, hameenlinna, vaasa, seinäjoki, seinajoki, rovaniemi, mikkeli, kotka, salo, "
          "porvoo, kouvola, kokkola, hyvinkää, hyvinkaa, nurmijärvi, järvenpää, jarvenpaa, rauma, kajaani, "
          "kerava, savonlinna, imatra, tuusula, kirkkonummi, lohja, raisio, kaarina, kangasala, ylöjärvi",
    "ee": "tallinn, tartu, narva, pärnu, parnu, kohtla-järve, viljandi, rakvere, maardu, kuressaare, haapsalu",
    "lv": "riga, rīga, daugavpils, liepāja, liepaja, jelgava, jūrmala, jurmala, ventspils, rēzekne, valmiera",
    "lt": "vilnius, kaunas, klaipėda, klaipeda, šiauliai, siauliai, panevėžys, panevezys, alytus, palanga",
    "pl": "warsaw, warszawa, kraków, krakow, cracow, łódź, lodz, wrocław, wroclaw, poznań, poznan, gdańsk, gdansk, "
          "szczecin, bydgoszcz, lublin, białystok, bialystok, katowice, gdynia, częstochowa, czestochowa, radom, "
          "toruń, torun, sosnowiec, rzeszów, rzeszow, kielce, gliwice, olsztyn, zabrze, bielsko-biała, bytom, "
          "zielona góra, rybnik, opole, tychy, elbląg, płock, wałbrzych, sopot, zakopane",
    "cz": "prague, praha, prag, brno, ostrava, plzeň, plzen, pilsen, liberec, olomouc, české budějovice, "
          "ceske budejovice, hradec králové, ústí nad labem, pardubice, zlín, zlin, karlovy vary, jihlava, kladno",
    "sk": "bratislava, košice, kosice, prešov, presov, žilina, zilina, nitra, banská bystrica, trnava, trenčín, "
          "poprad",
    "hu": "budapest, debrecen, szeged, miskolc, pécs, pecs, győr, gyor, nyíregyháza, kecskemét, kecskemet, "
          "székesfehérvár, szombathely, sopron, eger, veszprém",
    "ro": "bucharest, bucurești, bucuresti, cluj-napoca, cluj, timișoara, timisoara, iași, iasi, constanța, "
          "constanta, craiova, brașov, brasov, galați, galati, ploiești, ploiesti, oradea, sibiu, arad, pitești, "
          "bacău, suceava",
    "bg": "sofia, plovdiv, varna, burgas, ruse, stara zagora, pleven, sliven, dobrich, shumen, bansko",
    "gr": "athens, athina, thessaloniki, salonica, patras, heraklion, larissa, volos, ioannina, chania, rhodes, "
          "kavala, kalamata, corfu, mykonos, santorini, piraeus, glyfada",
    "hr": "zagreb, split, rijeka, osijek, zadar, pula, slavonski brod, karlovac, varaždin, šibenik, sibenik, "
          "dubrovnik, makarska, rovinj, poreč",
    "si": "ljubljana, maribor, celje, kranj, koper, velenje, novo mesto, ptuj, bled",
    "mt": "valletta, sliema, birkirkara, mosta, st julian's, qormi",
    "cy": "nicosia, limassol, larnaca, paphos, famagusta, ayia napa",
    "is": "reykjavik, reykjavík, kópavogur, hafnarfjörður, akureyri",
    "rs": "belgrade, beograd, novi sad, niš",
    "ua": "kyiv, kiev, lviv, odesa, odessa, kharkiv, dnipro",
    "tr": "istanbul, ankara, izmir, antalya, bursa",
}

# country names (English + endonyms + common forms) -> cc
COUNTRY_NAMES: dict[str, str] = {
    "netherlands": "nl", "the netherlands": "nl", "holland": "nl", "nederland": "nl",
    "belgium": "be", "belgië": "be", "belgie": "be", "belgique": "be", "belgien": "be",
    "germany": "de", "deutschland": "de", "austria": "at", "österreich": "at", "oesterreich": "at",
    "switzerland": "ch", "schweiz": "ch", "suisse": "ch", "svizzera": "ch", "france": "fr",
    "luxembourg": "lu", "luxemburg": "lu", "spain": "es", "españa": "es", "espana": "es",
    "italy": "it", "italia": "it", "portugal": "pt", "ireland": "ie", "éire": "ie",
    "united kingdom": "gb", "uk": "gb", "great britain": "gb", "britain": "gb", "england": "gb",
    "scotland": "gb", "wales": "gb", "northern ireland": "gb",
    "sweden": "se", "sverige": "se", "norway": "no", "norge": "no", "denmark": "dk", "danmark": "dk",
    "finland": "fi", "suomi": "fi", "suomessa": "fi", "estonia": "ee", "eesti": "ee", "latvia": "lv",
    "latvija": "lv", "lithuania": "lt", "lietuva": "lt", "poland": "pl", "polska": "pl",
    "czechia": "cz", "czech republic": "cz", "česko": "cz", "slovakia": "sk", "slovensko": "sk",
    "hungary": "hu", "magyarország": "hu", "romania": "ro", "românia": "ro", "bulgaria": "bg",
    "greece": "gr", "hellas": "gr", "croatia": "hr", "hrvatska": "hr", "slovenia": "si", "slovenija": "si",
    "malta": "mt", "cyprus": "cy", "iceland": "is", "ísland": "is", "serbia": "rs", "ukraine": "ua",
    "turkey": "tr", "türkiye": "tr",
}
COUNTRY_DISPLAY: dict[str, str] = {
    "nl": "Netherlands", "be": "Belgium", "de": "Germany", "at": "Austria", "ch": "Switzerland", "fr": "France",
    "lu": "Luxembourg", "es": "Spain", "it": "Italy", "pt": "Portugal", "ie": "Ireland", "gb": "United Kingdom",
    "se": "Sweden", "no": "Norway", "dk": "Denmark", "fi": "Finland", "ee": "Estonia", "lv": "Latvia",
    "lt": "Lithuania", "pl": "Poland", "cz": "Czechia", "sk": "Slovakia", "hu": "Hungary", "ro": "Romania",
    "bg": "Bulgaria", "gr": "Greece", "hr": "Croatia", "si": "Slovenia", "mt": "Malta", "cy": "Cyprus",
    "is": "Iceland", "rs": "Serbia", "ua": "Ukraine", "tr": "Turkey",
}

# cc -> local language (ISO 639-1); None = English is the local language
LANGUAGE: dict[str, str | None] = {
    "nl": "nl", "be": "nl", "de": "de", "at": "de", "ch": "de", "fr": "fr", "lu": "fr", "es": "es", "it": "it",
    "pt": "pt", "ie": None, "gb": None, "mt": None, "se": "sv", "no": "no", "dk": "da", "fi": "fi", "ee": "et",
    "lv": "lv", "lt": "lt", "pl": "pl", "cz": "cs", "sk": "sk", "hu": "hu", "ro": "ro", "bg": "bg", "gr": "el",
    "cy": "el", "hr": "hr", "si": "sl", "is": "is", "rs": "sr", "ua": "uk", "tr": "tr",
}
# cities whose language differs from their country's first one
CITY_LANGUAGE: dict[str, str] = {
    **{c: "fr" for c in ("charleroi", "liège", "liege", "namur", "mons", "tournai", "verviers", "wavre",
                         "ottignies", "waterloo", "bruxelles", "geneva", "genève", "geneve", "genf", "lausanne",
                         "fribourg", "neuchâtel", "neuchatel", "sion", "montreux", "bienne")},
    **{c: "it" for c in ("lugano", "locarno", "bellinzona")},
}

# names that are ordinary words or product names too: a place only after "in / near / around ..."
AMBIGUOUS = frozenset({
    "nice", "tours", "nancy", "valence", "pau", "orleans", "orléans", "split", "reading", "bath", "derby", "oxford",
    "cambridge", "york", "lincoln", "hull", "worcester", "poole", "chester", "bolton", "preston", "worms", "essen",
    "halle", "hamm", "moss", "cork", "como", "parma", "bologna", "latina", "leon", "león", "toledo", "santander",
    "ibiza", "palma", "jerez", "faro", "porto", "sofia", "bergen", "salo", "kotka", "ede", "oss", "goes", "bray",
    "swords", "eger", "arad", "ruse", "mosta", "bled", "zug", "thun", "uster", "waterloo", "biel", "kiel",
    "lund", "falun", "hamar", "molde", "rhodes", "corfu", "varna", "nitra", "martin", "most", "luxembourg",
    "newcastle", "brighton", "sion", "trier", "jena", "gera", "witten", "siegen", "venlo", "ulm", "pisa",
    "lucca", "siena", "monza", "prato", "bari", "terni", "luton", "slough", "watford", "chur", "bonn",
    "malta", "wales", "uk", "holland", "england", "britain",
})
# IKEA names its products after Scandinavian places ('STOCKHOLM rug', 'MALMÖ'?): never a place there
_IKEA = re.compile(r"\bikea\b", re.I)
_PREP = re.compile(r"(?:\b(?:in|near|around|at|from|within|close\s+to|lähellä|bei|nahe|nabij|bij|à|en|i|nära)\s+)$",
                   re.I)


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).lower()


CITY_CC: dict[str, str] = {}
for _cc, _names in _CITIES.items():
    for _n in _names.split(","):
        _n = _n.strip()
        if _n and _n not in CITY_CC:
            CITY_CC[_n] = _cc


def _display(name: str) -> str:
    """'den haag' -> 'Den Haag', "'s-hertogenbosch" -> "'s-Hertogenbosch", 'aix-en-provence' -> 'Aix-En-Provence'."""
    out = re.sub(r"(^|[\s-])([a-zà-ÿœšžłńśźżčřěůőűăîâșțğıøåæ])",
                 lambda m: m.group(1) + m.group(2).upper(), name)
    return out.replace("'S-", "'s-")


def _hits(text: str, vocab: dict[str, str]) -> list[tuple[str, int, int]]:
    low = _fold(text)
    hits: list[tuple[str, int, int]] = []
    taken: list[tuple[int, int]] = []
    for key in sorted(vocab, key=len, reverse=True):
        if key not in low:
            continue
        for m in re.finditer(rf"(?<![\w-]){re.escape(key)}(?![\w-])", low):
            a, b = m.span()
            if any(a < y and x < b for x, y in taken):
                continue
            taken.append((a, b))
            hits.append((key, a, b))
    return hits


def place_ok(text: str, key: str, start: int, cc: str | None) -> bool:
    """Is this name at `start` a place here? Ambiguous names need a preposition before them, and so do
    Nordic towns in an IKEA query."""
    low = _fold(text)
    after_prep = bool(_PREP.search(low[:start]))
    if key in AMBIGUOUS and not after_prep:
        return False
    if cc in ("se", "no", "dk", "fi") and _IKEA.search(low) and not after_prep:
        return False
    return True


def find_place(text: str) -> tuple[str, str, tuple[int, int]] | None:
    """First European city or country in the text -> (display name, cc, span of the name).
    Cities win over countries ('tilburg netherlands' -> Tilburg). None when there is none."""
    if not text:
        return None
    for vocab in (CITY_CC, COUNTRY_NAMES):
        hits = [h for h in _hits(text, vocab) if place_ok(text, h[0], h[1], vocab[h[0]])]
        if hits:
            key, a, b = min(hits, key=lambda h: h[1])
            cc = vocab[key]
            name = COUNTRY_DISPLAY.get(cc, _display(key)) if vocab is COUNTRY_NAMES else _display(key)
            return name, cc, (a, b)
    return None


def country_for(where: str | None) -> str | None:
    """'Tilburg' / 'Netherlands' / 'Tilburg, NL' / 'nl' -> 'nl'. None when unknown."""
    if not where:
        return None
    w = _fold(where).strip()
    if len(w) == 2 and w.isalpha():
        return "gb" if w == "uk" else w
    if w in CITY_CC:
        return CITY_CC[w]
    if w in COUNTRY_NAMES:
        return COUNTRY_NAMES[w]
    # 'Tilburg, Netherlands' (an LLM's where): the country part wins, else any city in it
    for vocab in (COUNTRY_NAMES, CITY_CC):
        hits = _hits(w, vocab)
        if hits:
            return vocab[min(hits, key=lambda h: h[1])[0]]
    return None


def language_for(where: str | None, cc: str | None = None) -> str | None:
    """Local language of a place (ISO 639-1), None = English. Geneva -> fr, Lugano -> it, Tilburg -> nl."""
    w = _fold(where or "").strip()
    if w in CITY_LANGUAGE:
        return CITY_LANGUAGE[w]
    cc = cc or country_for(where)
    return LANGUAGE.get(cc or "")
