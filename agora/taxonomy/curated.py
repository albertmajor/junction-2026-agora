"""Hand-written part of the Agora taxonomy (Junction 2026): the roots, the services backbone and the
"where to look" defaults. Everything else in the tree comes from open taxonomies and shop menus
(see scripts/build_taxonomy.py). Only the build script reads this module.

Label format: "en|fi|de|nl|sv ~ synonym, synonym" (any language in the synonyms). A dict value holds
children. Labels written here win over imported ones, imported nodes with the same meaning merge in.
"""
from __future__ import annotations

# id -> (labels, kind). Order = display order. kind: product | service | digital | vehicle | property | food
ROOTS: dict[str, tuple[str, str]] = {
    "electronics": ("Electronics & Computers|Elektroniikka ja tietokoneet|Elektronik & Computer|"
                    "Elektronica & computers|Elektronik & datorer ~ tech, it, tietotekniikka, viihde-elektroniikka",
                    "product"),
    "appliances": ("Home Appliances|Kodinkoneet|Haushaltsgeräte|Huishoudelijke apparaten|Vitvaror & hushållsapparater"
                   " ~ white goods, kodin pienkoneet, elektrogeräte", "product"),
    "fashion": ("Fashion, Shoes & Accessories|Muoti, kengät ja asusteet|Mode, Schuhe & Accessoires|"
                "Mode, schoenen & accessoires|Mode, skor & accessoarer ~ clothes, clothing, vaatteet, kleidung, kleding, kläder",
                "product"),
    "home-garden": ("Home & Garden|Koti ja piha|Haus & Garten|Huis & tuin|Hem & trädgård ~ sisustus, wohnen, wonen, inredning",
                    "product"),
    "furniture": ("Furniture|Huonekalut|Möbel|Meubels|Möbler ~ kalusteet, meubilair", "product"),
    "diy": ("DIY, Tools & Building Supplies|Rakentaminen, remontti ja työkalut|Baumarkt & Werkzeug|"
            "Bouwmarkt & gereedschap|Bygg & verktyg ~ hardware, tools, työkalut, werkzeug, gereedschap, verktyg, rautakauppa",
            "product"),
    "health-beauty": ("Health & Beauty|Terveys ja kauneus|Gesundheit & Schönheit|Gezondheid & verzorging|Hälsa & skönhet"
                      " ~ drugstore, drogerie, apteekki, kosmetiikka", "product"),
    "baby-kids": ("Baby & Kids|Vauvat ja lapset|Baby & Kind|Baby & kind|Barn & baby ~ lastentarvikkeet", "product"),
    "toys-games": ("Toys & Games|Lelut ja pelit|Spielzeug & Spiele|Speelgoed & spellen|Leksaker & spel", "product"),
    "sports-outdoors": ("Sports & Outdoors|Urheilu ja ulkoilu|Sport & Outdoor|Sport & outdoor|Sport & fritid"
                        " ~ retkeily, camping, fitness", "product"),
    "hobbies": ("Hobbies, Arts, Crafts & Music|Harrastukset, taide ja musiikki|Hobby, Kunst & Musik|"
                "Hobby, kunst & muziek|Hobby, konst & musik ~ askartelu, basteln, knutselen, pyssel, collectibles",
                "product"),
    "media": ("Books, Movies & Music|Kirjat, elokuvat ja musiikki|Bücher, Filme & Musik|Boeken, films & muziek|"
              "Böcker, film & musik ~ media", "product"),
    "food-drink": ("Food, Drink & Restaurants|Ruoka, juoma ja ravintolat|Essen, Getränke & Restaurants|"
                   "Eten, drinken & restaurants|Mat, dryck & restauranger ~ groceries, ruokakauppa, lebensmittel, "
                   "boodschappen, livsmedel", "food"),
    "pets": ("Pets & Animals|Lemmikit ja eläimet|Haustiere & Tierbedarf|Huisdieren & dieren|Djur & husdjur"
             " ~ eläintarvikkeet, tierbedarf, dierbenodigdheden", "product"),
    "office": ("Office & School Supplies|Toimisto- ja koulutarvikkeet|Büro & Schreibwaren|Kantoor & school|Kontor & skola"
               " ~ paperitavarat, schreibwaren", "product"),
    "vehicles": ("Vehicles & Parts|Ajoneuvot ja varaosat|Fahrzeuge & Teile|Voertuigen & onderdelen|Fordon & delar"
                 " ~ auto, autot, autos, bilar, kfz", "vehicle"),
    "business": ("Business & Industrial|Yritys ja teollisuus|Business & Industrie|Zakelijk & industrie|Företag & industri"
                 " ~ b2b, industrial, teollisuus, gewerbe", "product"),
    "software": ("Software, Apps & Digital Goods|Ohjelmistot ja digitaaliset tuotteet|Software & digitale Produkte|"
                 "Software & digitale producten|Programvara & digitala produkter ~ apps, subscriptions, tilaukset, abos",
                 "digital"),
    "property": ("Property & Housing|Asunnot ja kiinteistöt|Immobilien & Wohnen|Vastgoed & wonen|Bostad & fastigheter"
                 " ~ real estate, asunto, wohnung, woning, lägenhet", "property"),
    "home-services": ("Home Services|Kotipalvelut|Haushaltsdienste|Huishoudelijke diensten|Hemtjänster"
                      " ~ household services, kotitalouspalvelut, haushaltsnahe dienstleistungen", "service"),
    "trades": ("Trades & Renovation|Remontti- ja rakennuspalvelut|Handwerker & Renovierung|Vakmensen & verbouwing|"
               "Hantverkare & renovering ~ tradesmen, contractors, handwerk, ammattilaiset, klussen", "service"),
    "auto-services": ("Car & Vehicle Services|Autopalvelut|Kfz-Service & Werkstatt|Autodiensten|Biltjänster"
                      " ~ autokorjaamo, werkstatt, garage, bilverkstad", "service"),
    "beauty-wellness": ("Beauty & Wellness Services|Kauneus- ja hyvinvointipalvelut|Beauty & Wellness|"
                        "Beauty & wellness|Skönhet & välmående ~ salon, spa, kampaamo, friseur, kapper, frisör", "service"),
    "health-services": ("Health & Medical Services|Terveyspalvelut|Gesundheit & Medizin|Zorg & medische diensten|"
                        "Vård & hälsa ~ doctor, lääkäri, arzt, dokter, läkare, clinic", "service"),
    "education": ("Education & Courses|Koulutus ja kurssit|Bildung & Kurse|Onderwijs & cursussen|Utbildning & kurser"
                  " ~ lessons, tunnit, unterricht, lessen, lektioner, training", "service"),
    "events-leisure": ("Events, Tickets & Leisure|Tapahtumat, liput ja vapaa-aika|Events, Tickets & Freizeit|"
                       "Evenementen, tickets & vrije tijd|Evenemang, biljetter & fritid ~ entertainment, activities, "
                       "elämykset, erlebnisse, uitjes, upplevelser", "service"),
    "travel": ("Travel & Accommodation|Matkailu ja majoitus|Reisen & Unterkunft|Reizen & accommodatie|Resor & boende"
               " ~ holidays, matkat, urlaub, vakantie, semester", "service"),
    "transport": ("Transport, Delivery & Mobility|Kuljetus, toimitus ja liikkuminen|Transport, Versand & Mobilität|"
                  "Transport, verzending & mobiliteit|Transport, frakt & mobilitet ~ logistics, logistiikka", "service"),
    "professional": ("Professional & Business Services|Asiantuntija- ja yrityspalvelut|Professionelle Dienstleistungen|"
                     "Zakelijke dienstverlening|Professionella tjänster ~ b2b services, consultancy", "service"),
    "digital-services": ("Digital & Freelance Services|Digitaaliset ja freelance-palvelut|Digitale & Freelance-Dienste|"
                         "Digitale & freelance diensten|Digitala tjänster & frilans ~ freelancers, gigs, online services",
                         "service"),
    "finance-insurance": ("Finance & Insurance|Raha-asiat ja vakuutukset|Finanzen & Versicherungen|"
                          "Financiën & verzekeringen|Ekonomi & försäkring ~ banking, pankki, bank", "service"),
    "utilities": ("Energy, Telecom & Utilities|Energia, liittymät ja asumisen palvelut|Energie, Telekom & Versorger|"
                  "Energie, telecom & nutsvoorzieningen|Energi, telekom & el ~ contracts, sopimukset, verträge", "service"),
    "personal-services": ("Personal, Family & Care Services|Henkilö-, perhe- ja hoivapalvelut|"
                          "Persönliche, Familien- & Pflegedienste|Persoonlijke, gezins- & zorgdiensten|"
                          "Personliga tjänster, familj & omsorg ~ care, hoiva, pflege, zorg, omsorg", "service"),
}

# services and digital backbone: root id -> {label: children}
S = dict  # readability

SERVICES: dict[str, dict] = {
    "home-services": S({
        "Cleaning|Siivous|Reinigung|Schoonmaak|Städning ~ cleaner, siivooja, putzfrau, putzhilfe, reinigungskraft, "
        "schoonmaker, städare, siivousfirma, cleaning service, housekeeping": S({
            "Home cleaning|Kotisiivous|Haushaltsreinigung|Huishoudelijke schoonmaak|Hemstädning ~ house cleaning, "
            "maid, kotisiivooja, haushaltshilfe, huishoudelijke hulp, hemstädare": {},
            "Move-out cleaning|Muuttosiivous|Endreinigung|Eindschoonmaak|Flyttstädning ~ end of tenancy cleaning, "
            "auszugsreinigung, opleverschoonmaak": {},
            "Window cleaning|Ikkunanpesu|Fensterreinigung|Glazenwassen|Fönsterputs ~ window cleaner, fensterputzer, "
            "glazenwasser, fönsterputsare": {},
            "Office cleaning|Toimistosiivous|Büroreinigung|Kantoorschoonmaak|Kontorsstädning ~ commercial cleaning": {},
            "Carpet & upholstery cleaning|Mattojen ja huonekalujen pesu|Teppich- & Polsterreinigung|"
            "Tapijt- & meubelreiniging|Matt- & möbeltvätt ~ rug cleaning, sofa cleaning": {},
            "Deep cleaning|Suursiivous|Grundreinigung|Dieptereiniging|Storstädning ~ spring cleaning": {},
            "Construction cleaning|Rakennussiivous|Baureinigung|Bouwschoonmaak|Byggstädning": {},
            "Gutter cleaning|Rännien puhdistus|Dachrinnenreinigung|Dakgootreiniging|Takrännerengöring": {},
            "Chimney sweeping|Nuohous|Schornsteinfeger|Schoorsteenveger|Sotning ~ chimney sweep, nuohooja": {},
            "Pressure washing|Painepesu|Hochdruckreinigung|Hogedrukreiniging|Högtryckstvätt ~ facade cleaning": {},
        }),
        "Moving & removals|Muutto ja muuttopalvelut|Umzug & Umzugsservice|Verhuizen|Flytt & flytthjälp ~ movers, "
        "removals, man with a van, muuttofirma, umzugsfirma, verhuizer, verhuisbedrijf, flyttfirma, muuttoapu": S({
            "Home moving|Kotimuutto|Privatumzug|Particuliere verhuizing|Privatflytt": {},
            "Office moving|Yritysmuutto|Firmenumzug|Bedrijfsverhuizing|Kontorsflytt": {},
            "Piano moving|Pianon kuljetus|Klaviertransport|Pianoverhuizing|Pianoflytt": {},
            "International moving|Ulkomaanmuutto|Auslandsumzug|Internationale verhuizing|Utlandsflytt": {},
            "Storage units|Varastotilat|Lagerräume & Self-Storage|Opslagruimte|Förråd & magasinering ~ self storage, "
            "varastohotelli, selfstorage, magasin": {},
            "Junk removal & disposal|Roskien poisvienti|Entrümpelung & Sperrmüll|Ontruiming & grofvuil|"
            "Bortforsling & skräphämtning ~ clearance, house clearance, kuolinpesän tyhjennys, haushaltsauflösung": {},
        }),
        "Garden & outdoor|Piha ja puutarha|Garten & Außenbereich|Tuin & buiten|Trädgård & utemiljö ~ gardener, "
        "puutarhuri, gärtner, hovenier, tuinman, trädgårdsmästare, landscaping": S({
            "Lawn mowing|Ruohonleikkuu|Rasenmähen|Gras maaien|Gräsklippning": {},
            "Tree felling & pruning|Puiden kaato ja leikkaus|Baumfällung & Baumpflege|Bomen kappen & snoeien|"
            "Trädfällning & beskärning ~ arborist, tree surgeon, puunkaato, baumfäller, boomverzorger": {},
            "Landscaping|Pihasuunnittelu ja -rakennus|Garten- & Landschaftsbau|Tuinaanleg|Trädgårdsanläggning": {},
            "Snow removal|Lumityöt|Winterdienst & Schneeräumung|Sneeuwruimen|Snöröjning ~ snow plowing, auraus": {},
            "Hedge trimming|Pensasaitojen leikkaus|Heckenschnitt|Heg snoeien|Häckklippning": {},
            "Pool maintenance|Uima-altaan huolto|Poolservice|Zwembadonderhoud|Poolservice": {},
        }),
        "Pest control|Tuholaistorjunta|Schädlingsbekämpfung|Ongediertebestrijding|Skadedjursbekämpning ~ exterminator, "
        "kammerjäger, bed bugs, luteet, mice, rats": {},
        "Handyman|Yleismies ja kotiapu|Hausmeisterservice & Handwerker|Klusjesman|Hantverkare & fixare ~ odd jobs, "
        "huoltomies, kodin pikkuremontit, klusjes, allt-i-allo": S({
            "Furniture assembly|Huonekalujen kokoaminen|Möbelmontage|Meubelmontage|Möbelmontering ~ ikea assembly, "
            "flat pack assembly": {},
            "Picture & TV mounting|Taulujen ja television kiinnitys|TV- & Bildermontage|Tv ophangen|TV-montering": {},
            "Lock & key services|Lukkoseppä|Schlüsseldienst|Slotenmaker|Låssmed ~ locksmith, lukkoseppä, "
            "schlüsseldienst, slotenmaker, låssmed, lockout": {},
        }),
        "Appliance & electronics repair|Kodinkoneiden ja elektroniikan korjaus|Geräte- & Elektronikreparatur|"
        "Reparatie van apparaten & elektronica|Reparation av vitvaror & elektronik ~ repair shop, korjaamo": S({
            "Phone repair|Puhelimen korjaus|Handyreparatur|Telefoonreparatie|Mobilreparation ~ screen repair, "
            "näytön vaihto, display reparatur, scherm reparatie": {},
            "Computer repair|Tietokoneen korjaus|Computerreparatur|Computerreparatie|Datorreparation ~ pc repair, "
            "laptop repair, it support": {},
            "Home appliance repair|Kodinkoneiden korjaus|Haushaltsgerätereparatur|Witgoedreparatie|Vitvarureparation ~ "
            "washing machine repair, fridge repair, pesukonehuolto": {},
            "TV & audio repair|Television ja äänentoiston korjaus|TV- & Audioreparatur|Tv- & audioreparatie|"
            "TV- & ljudreparation": {},
            "Watch & jewellery repair|Kellojen ja korujen korjaus|Uhren- & Schmuckreparatur|Horloge- & sieradenreparatie|"
            "Klock- & smyckesreparation ~ watchmaker, kelloseppä, goldsmith": {},
            "Bicycle repair|Polkupyörähuolto|Fahrradreparatur|Fietsenmaker|Cykelreparation ~ bike repair, "
            "pyöräkorjaamo, fahrradwerkstatt, fietsreparatie, cykelverkstad": {},
            "Shoe repair|Suutari|Schuhreparatur|Schoenmaker|Skomakare ~ cobbler": {},
            "Clothing alterations & tailoring|Vaatteiden korjaus ja ompelu|Änderungsschneiderei|Kleermaker|"
            "Skrädderi & ändringar ~ tailor, ompelimo, schneider, kleermaker, skräddare": {},
        }),
        "Laundry & dry cleaning|Pesula|Wäscherei & Reinigung|Wasserette & stomerij|Tvätteri & kemtvätt ~ laundromat, "
        "kemiallinen pesula, chemische reinigung, stomerij": {},
        "Home security & alarms|Kodin turvallisuus ja hälyttimet|Sicherheitstechnik & Alarmanlagen|"
        "Beveiliging & alarmsystemen|Hemlarm & säkerhet ~ burglar alarm, murtohälytin, alarmanlage": {},
        "House sitting & key holding|Talonvahti|Haussitting|Huisoppas|Husvakt": {},
    }),
    "trades": S({
        "Plumbing|Putkityöt|Sanitär & Installateur|Loodgieter|VVS & rörmokare ~ plumber, putkimies, klempner, "
        "installateur, loodgieter, rörmokare, vvs, leaking pipe, vuotava putki": S({
            "Emergency plumber|Päivystävä putkimies|Notdienst Sanitär|Spoedloodgieter|Akut rörmokare ~ 24 hour plumber": {},
            "Drain unblocking|Viemärin avaus|Rohrreinigung|Ontstopping|Avloppsrensning ~ blocked drain, "
            "viemärihuolto, rohrreinigung, ontstoppingsdienst, stopp i avloppet": {},
            "Bathroom renovation|Kylpyhuoneremontti|Badsanierung|Badkamerrenovatie|Badrumsrenovering ~ "
            "bathroom fitter, kylppäriremontti, badsanierung, badkamer verbouwen": {},
            "Water heater installation|Lämminvesivaraajan asennus|Warmwasserbereiter-Installation|Boiler installeren|"
            "Varmvattenberedare installation": {},
        }),
        "Electrical work|Sähkötyöt|Elektroinstallation|Elektricien|El-arbeten ~ electrician, sähkömies, sähköasentaja, "
        "elektriker, elektricien, elinstallatör": S({
            "EV charger installation|Latausaseman asennus|Wallbox-Installation|Laadpaal installeren|Laddbox installation"
            " ~ wallbox, sähköauton latauspiste, laadpaal": {},
            "Lighting installation|Valaisinasennus|Beleuchtungsinstallation|Verlichting installeren|Belysningsinstallation": {},
            "Solar panel installation|Aurinkopaneelien asennus|Photovoltaik-Installation|Zonnepanelen installeren|"
            "Solcellsinstallation ~ pv installer, aurinkosähkö, solaranlage, zonnepanelen": {},
        }),
        "Heating, ventilation & air conditioning|LVI, lämmitys ja ilmanvaihto|Heizung, Lüftung & Klima|"
        "Verwarming, ventilatie & airco|Värme, ventilation & klimat ~ hvac, heating engineer, lvi-asentaja, "
        "heizungsbauer, cv-monteur": S({
            "Heat pump installation|Lämpöpumpun asennus|Wärmepumpen-Installation|Warmtepomp installeren|"
            "Värmepumpsinstallation ~ air source heat pump, ilmalämpöpumppu, maalämpö, wärmepumpe, warmtepomp, värmepump": {},
            "Boiler service|Lämmityskattilan huolto|Heizungswartung|Cv-ketel onderhoud|Pannservice ~ furnace repair": {},
            "Air conditioning installation|Ilmastointilaitteen asennus|Klimaanlagen-Installation|Airco installeren|"
            "AC-installation": {},
            "Ventilation cleaning|Ilmanvaihdon puhdistus|Lüftungsreinigung|Ventilatie reinigen|OVK & ventilationsrengöring": {},
        }),
        "Carpentry & joinery|Puusepäntyöt|Tischler & Schreiner|Timmerman|Snickeri ~ carpenter, kirvesmies, puuseppä, "
        "schreiner, tischler, timmerman, snickare": S({
            "Kitchen fitting|Keittiöasennus|Küchenmontage|Keukenmontage|Köksmontering ~ kitchen installation": {},
            "Decking & fences|Terassit ja aidat|Terrassenbau & Zäune|Vlonders & schuttingen|Altaner & staket": {},
        }),
        "Painting & decorating|Maalaus ja tapetointi|Maler & Lackierer|Schilder & behanger|Måleri & tapetsering ~ "
        "painter, maalari, maler, schilder, målare, wallpapering": {},
        "Flooring|Lattiatyöt|Bodenleger|Vloeren leggen|Golvläggning ~ floor fitter, parquet, laminate, lattia, parkett": {},
        "Tiling|Laatoitus|Fliesenleger|Tegelzetter|Plattsättning ~ tiler, laatoittaja, fliesenleger, tegelzetter, plattsättare": {},
        "Roofing|Kattotyöt|Dachdecker|Dakdekker|Takläggning ~ roofer, kattoremontti, dachdecker, dakdekker, takläggare": {},
        "Masonry & bricklaying|Muuraus|Maurer|Metselaar|Murning ~ bricklayer, muurari, maurer, metselaar, murare": {},
        "Building & renovation|Rakentaminen ja remontointi|Bau & Renovierung|Bouw & renovatie|Bygg & renovering ~ "
        "builder, general contractor, rakennusliike, bauunternehmen, aannemer, byggfirma, remontti": S({
            "Home extensions|Laajennukset|Anbauten|Aanbouw|Tillbyggnad": {},
            "Kitchen renovation|Keittiöremontti|Küchenrenovierung|Keukenrenovatie|Köksrenovering": {},
            "Sauna construction|Saunan rakentaminen|Saunabau|Sauna bouwen|Bastubygge ~ sauna remontti": {},
            "Insulation|Eristys|Dämmung|Isolatie|Isolering ~ wärmedämmung, spouwmuurisolatie": {},
            "Demolition|Purkutyöt|Abriss|Sloop|Rivning": {},
        }),
        "Architects & design|Arkkitehdit ja suunnittelu|Architekten & Planung|Architecten & ontwerp|Arkitekter & design ~ "
        "architect, arkkitehti, interior designer, sisustussuunnittelija, innenarchitekt": {},
        "Glaziers|Lasitustyöt|Glaser|Glaszetter|Glasmästare ~ glazier, lasittaja, glaser": {},
        "Welding & metalwork|Hitsaus ja metallityöt|Schweißen & Metallbau|Lassen & metaalbewerking|Svetsning & smide": {},
        "Groundwork & excavation|Maanrakennus|Erdarbeiten|Grondwerk|Markarbeten ~ digger, kaivinkone, bagger": {},
        "Windows, doors & conservatories|Ikkunat, ovet ja viherhuoneet|Fenster, Türen & Wintergärten|"
        "Ramen, deuren & serres|Fönster, dörrar & uterum ~ window replacement, window fitter, conservatory builder, "
        "upvc windows, double glazing, ikkunaremontti, fensterbauer, kozijnen vervangen, fönsterbyte": {},
        "Plastering & drylining|Rappaus ja kipsilevytyöt|Verputz & Trockenbau|Stukadoor & droogbouw|"
        "Putsning & gipsarbeten ~ plasterer, rendering, drywall installer, rappaaja, stuckateur, trockenbauer, "
        "stukadoor, putsare": {},
        "Driveways, paving & fencing|Pihatiet, kiveykset ja aidat|Einfahrten, Pflaster & Zäune|"
        "Opritten, bestrating & schuttingen|Uppfarter, stenläggning & staket ~ block paving, tarmac driveway, "
        "fencing contractor, pihakiveys, pflasterarbeiten, stratenmaker, stenläggare": {},
        "Garden buildings & structures|Piharakennukset ja katokset|Gartenhäuser & Überdachungen|"
        "Tuinhuizen & overkappingen|Trädgårdsbyggnader & skärmtak ~ shed builder, summerhouse builder, log cabin "
        "installer, gazebo builder, pergola builder, carport builder, greenhouse installation": {},
        "Kitchens, bedrooms & fitted furniture|Keittiöt, makuuhuoneet ja kiintokalusteet|"
        "Küchen, Schlafzimmer & Einbaumöbel|Keukens, slaapkamers & inbouwmeubelen|Kök, sovrum & platsbyggda möbler ~ "
        "fitted wardrobes, kitchen fitter, worktops, bespoke furniture maker, kiintokalusteet, einbauschrank, "
        "inbouwkast": {},
        "Chimneys, fireplaces & stoves|Savupiiput, takat ja kamiinat|Schornsteine, Kamine & Öfen|"
        "Schoorstenen, haarden & kachels|Skorstenar, eldstäder & kaminer ~ chimney repair, flue installer, "
        "wood burner installation, log burner, takka-asennus, kaminbauer, kachelsmid, kaminmontering": {},
        "Damp, flood & structural repairs|Kosteus-, vesi- ja rakennevauriot|Feuchte-, Wasser- & Bauschäden|"
        "Vocht-, water- & constructieschade|Fukt-, vatten- & konstruktionsskador ~ damp proofing, subsidence repair, "
        "woodworm treatment, dry rot, underpinning, kosteusvaurio, schimmelsanierung, vochtbestrijding, fuktsanering": {},
        "Surveys, planning & inspections|Kuntotarkastukset ja suunnittelu|Gutachten, Planung & Prüfung|"
        "Keuringen & bouwadvies|Besiktning, planering & kontroll ~ building survey, chartered surveyor, "
        "planning permission, party wall, kuntotarkastus, bausachverständiger, bouwkundige keuring, "
        "överlåtelsebesiktning": {},
        "Energy & renewables|Energiaremontit ja uusiutuva energia|Energiesanierung & erneuerbare Energien|"
        "Energiebesparing & duurzame energie|Energi & förnybart ~ renewable energy installer, wind turbine, "
        "solar battery storage, energiaremontti, energieberater, verduurzaming": {},
        "TV aerials, telecom & networking|Antennit, tietoliikenne ja verkot|Antennen, Telefon & Netzwerk|"
        "Antennes, telefonie & netwerken|Antenner, tele & nätverk ~ aerial installer, satellite dish installer, "
        "network cabling, antenniasennus, sat-anlage, kabelinstallateur": {},
        "Restoration & specialist crafts|Entisöinti ja erikoiskäsityöt|Restaurierung & Kunsthandwerk|"
        "Restauratie & ambachten|Restaurering & hantverk ~ furniture restoration, french polisher, antique restoration, "
        "huonekalujen entisöinti, möbelrestaurierung, meubelrestauratie, möbelrenovering": {},
        "Accessibility & mobility adaptations|Esteettömyys ja apuvälineet|Barrierefreiheit & Mobilitätshilfen|"
        "Toegankelijkheid & hulpmiddelen|Tillgänglighet & hjälpmedel ~ stairlift installation, mobility scooters, "
        "disabled bathroom, esteetön kylpyhuone, treppenlift, traplift, trapphiss": {},
        "Scaffolding|Rakennustelineet|Gerüstbau|Steigerbouw|Byggnadsställningar ~ scaffolder, telineasennus, "
        "gerüstbauer, steigerbouwer, ställningsbyggare": {},
        "Merchants & trade suppliers|Rautakaupat ja tukkurit|Baustoffhandel & Fachhandel|Bouwmaterialen & groothandel|"
        "Bygghandel & grossister ~ builders merchant, timber merchant, trade counter": {},
        "Other trades & specialists|Muut ammattilaiset ja erikoisosaajat|Weitere Handwerker & Spezialisten|"
        "Overige vakmensen & specialisten|Övriga hantverkare & specialister ~ specialist trades": {},
        "Tool & equipment hire|Työkalu- ja konevuokraus|Werkzeug- & Maschinenverleih|Gereedschapsverhuur|"
        "Verktygs- & maskinuthyrning ~ tool rental, konevuokraamo, mietwerkzeug": {},
    }),
    "auto-services": S({
        "Car repair & servicing|Auton korjaus ja huolto|Autoreparatur & Inspektion|Autoreparatie & onderhoud|"
        "Bilreparation & service ~ mechanic, garage, autokorjaamo, kfz-werkstatt, apk, bilverkstad, määräaikaishuolto": {},
        "Tyre change & storage|Renkaanvaihto ja rengashotelli|Reifenwechsel & Einlagerung|Banden wissel & opslag|"
        "Däckbyte & däckhotell ~ tyre fitting, rengasliike, reifenservice, bandenservice": {},
        "Vehicle inspection|Katsastus|TÜV & Hauptuntersuchung|APK keuring|Bilbesiktning ~ mot, katsastus, hu, tüv": {},
        "Car wash & detailing|Autopesu ja detailing|Autowäsche & Aufbereitung|Autowasstraat & detailing|"
        "Biltvätt & rekond ~ valeting": {},
        "Bodywork & paint|Kolarikorjaus ja maalaus|Karosserie & Lackierung|Schadeherstel & spuiterij|Bilplåt & lack ~ "
        "panel beater, kolarikorjaamo, lackiererei, plåtslagare": {},
        "Windscreen repair|Tuulilasin korjaus|Scheibenreparatur|Ruitherstel|Vindrutereparation": {},
        "Towing & roadside assistance|Hinaus ja tiepalvelu|Abschleppdienst & Pannenhilfe|Sleepdienst & pechhulp|"
        "Bärgning & vägassistans ~ tow truck, hinausauto, abschleppen": {},
        "Driving schools|Autokoulut|Fahrschulen|Rijscholen|Trafikskolor ~ driving lessons, autokoulu, fahrschule, "
        "rijles, körskola": {},
        "Vehicle leasing|Autoleasing|Autoleasing & Auto-Abo|Private lease|Billeasing ~ car subscription, yksityisleasing": {},
        "Parking|Pysäköinti|Parken|Parkeren|Parkering ~ parking space, parkkipaikka, stellplatz, parkeerplaats": {},
    }),
    "beauty-wellness": S({
        "Hair salons & barbers|Kampaamot ja parturit|Friseure & Barbershops|Kappers & barbiers|Frisörer & barberare ~ "
        "haircut, hairdresser, barber, kampaaja, parturi, friseur, kapper, frisör, hiustenleikkuu": S({
            "Haircut|Hiustenleikkuu|Haarschnitt|Knippen|Klippning": {},
            "Hair colouring|Hiusten värjäys|Haarfärben|Haar verven|Hårfärgning ~ balayage, highlights, raidat": {},
            "Barber & beard trim|Parturi ja parranajo|Barbier & Bartpflege|Barbier|Barberare & skäggtrimning": {},
            "Hair extensions|Hiustenpidennykset|Haarverlängerung|Hairextensions|Hårförlängning": {},
        }),
        "Nails|Kynnet|Nagelstudio|Nagelstudio|Naglar ~ manicure, pedicure, gel nails, kynsistudio, maniküre": {},
        "Massage|Hieronta|Massage|Massage|Massage ~ masseur, hieroja, thai massage, sports massage, urheiluhieronta": {},
        "Spa & day spa|Kylpylä ja day spa|Spa & Wellness|Spa & sauna|Spa ~ wellness, kylpylä, therme, saunadag": {},
        "Facials & skincare|Kasvohoidot|Gesichtsbehandlungen & Kosmetik|Gezichtsbehandelingen|Ansiktsbehandlingar ~ "
        "beautician, kosmetologi, kosmetikerin, schoonheidsspecialiste": {},
        "Hair removal & waxing|Karvanpoisto ja vahaus|Haarentfernung & Waxing|Ontharing & waxen|Hårborttagning & vaxning ~ "
        "laser hair removal, sokerointi": {},
        "Brows & lashes|Kulmat ja ripset|Augenbrauen & Wimpern|Wenkbrauwen & wimpers|Bryn & fransar ~ lash extensions": {},
        "Makeup artists|Meikkaajat|Visagisten|Visagisten|Makeupartister ~ make-up artist, maskeeraaja": {},
        "Tattoo & piercing|Tatuointi ja lävistykset|Tattoo & Piercing|Tattoo & piercing|Tatuering & piercing ~ "
        "tattoo artist, tatuoija, tätowierer": {},
        "Tanning|Solarium|Solarium & Bräunung|Zonnestudio|Solarium & spraytan ~ spray tan": {},
        "Fitness & personal training|Kuntosalit ja personal training|Fitness & Personal Training|Fitness & personal training|"
        "Gym & personlig träning ~ gym, kuntosali, fitnessstudio, sportschool, personal trainer, pt": {},
        "Yoga & pilates|Jooga ja pilates|Yoga & Pilates|Yoga & pilates|Yoga & pilates": {},
    }),
    "health-services": S({
        "General practitioners|Yleislääkärit|Hausärzte|Huisartsen|Allmänläkare ~ doctor, gp, lääkäri, lääkäriasema, "
        "arzt, hausarzt, huisarts, läkare, vårdcentral": {},
        "Dentists|Hammaslääkärit|Zahnärzte|Tandartsen|Tandläkare ~ dentist, hammaslääkäri, zahnarzt, tandarts, "
        "tandläkare, dental hygienist, suuhygienisti": {},
        "Physiotherapy|Fysioterapia|Physiotherapie|Fysiotherapie|Fysioterapi ~ physio, physiotherapist, "
        "fysioterapeutti, physiotherapeut, fysiotherapeut, sjukgymnast": {},
        "Mental health & therapy|Mielenterveys ja terapia|Psychotherapie & Beratung|Psycholoog & therapie|"
        "Psykoterapi & samtalsterapi ~ psychologist, psykologi, therapist, terapeutti, counselling": {},
        "Opticians & eye care|Optikot ja silmälääkärit|Optiker & Augenärzte|Opticiens & oogartsen|Optiker & ögonläkare ~ "
        "eye test, näöntutkimus, sehtest, oogmeting, synundersökning": {},
        "Specialist doctors|Erikoislääkärit|Fachärzte|Medisch specialisten|Specialistläkare ~ dermatologist, "
        "gynecologist, ihotautilääkäri, gynekologi": {},
        "Chiropractic & osteopathy|Kiropraktiikka ja osteopatia|Chiropraktik & Osteopathie|Chiropractie & osteopathie|"
        "Kiropraktik & osteopati ~ chiropractor, naprapath, naprapaatti, osteopaatti": {},
        "Pharmacies|Apteekit|Apotheken|Apotheken|Apotek ~ pharmacy, apteekki, apotheke, apotheek, online pharmacy": {},
        "Lab tests & health checks|Laboratoriotutkimukset|Labortests & Check-ups|Bloedonderzoek & check-ups|"
        "Provtagning & hälsokontroller ~ blood test, verikoe, health check": {},
        "Cosmetic & aesthetic treatments|Esteettiset hoidot|Ästhetische Medizin|Cosmetische behandelingen|Estetiska behandlingar"
        " ~ botox, fillers, cosmetic surgery, plastiikkakirurgia": {},
        "Hearing care|Kuulonhuolto|Hörakustik|Audicien|Hörselvård ~ hearing aids, kuulolaite, hörgeräte": {},
        "Online doctor|Etälääkäri|Online-Arzt|Online huisarts|Digital vårdcentral ~ telemedicine, video doctor": {},
    }),
    "education": S({
        "Tutoring & homework help|Yksityisopetus ja läksyapu|Nachhilfe|Bijles & huiswerkbegeleiding|Läxhjälp & privatlektioner"
        " ~ tutor, kotiopettaja, nachhilfelehrer, bijlesdocent": {},
        "Language courses|Kielikurssit|Sprachkurse|Taalcursussen|Språkkurser ~ language school, kielikoulu, "
        "sprachschule, taalschool, english course, suomen kielen kurssi, deutschkurs": {},
        "Music lessons|Musiikkitunnit|Musikunterricht|Muziekles|Musiklektioner ~ piano lessons, guitar lessons, "
        "pianotunnit, kitaratunnit, gitarrenunterricht": {},
        "Online courses|Verkkokurssit|Online-Kurse|Online cursussen|Onlinekurser ~ e-learning, mooc, udemy, coursera": {},
        "Professional training & certification|Ammatillinen koulutus|Weiterbildung & Zertifikate|Bijscholing & certificering|"
        "Vidareutbildning & certifiering": {},
        "Coding bootcamps|Ohjelmointikoulutus|Programmierkurse|Programmeercursussen|Programmeringskurser": {},
        "Art, craft & cooking classes|Taide-, käsityö- ja kokkikurssit|Kunst-, Bastel- & Kochkurse|"
        "Kunst-, knutsel- & kookcursussen|Konst-, hantverks- & matlagningskurser ~ workshop, kokkauskurssi, kochkurs": {},
        "Sports & swimming lessons|Urheilu- ja uimakoulut|Sport- & Schwimmkurse|Sport- & zwemles|Sport- & simskola": {},
        "Driving lessons|Ajotunnit|Fahrstunden|Rijlessen|Körlektioner": {},
        "Universities & schools|Yliopistot ja oppilaitokset|Universitäten & Schulen|Universiteiten & scholen|"
        "Universitet & skolor ~ degree, tutkinto, studium, opleiding": {},
        "Childcare & preschool|Päivähoito ja esikoulu|Kita & Kindergarten|Kinderopvang|Förskola ~ daycare, päiväkoti, "
        "kita, kinderdagverblijf, dagis": {},
    }),
    "events-leisure": S({
        "Concert & event tickets|Konsertti- ja tapahtumaliput|Konzert- & Eventtickets|Concert- & evenementtickets|"
        "Konsert- & evenemangsbiljetter ~ tickets, liput, karten, kaartjes, biljetter, ticketmaster, lippu.fi": S({
            "Concert tickets|Konserttiliput|Konzertkarten|Concertkaartjes|Konsertbiljetter": {},
            "Sports tickets|Urheilutapahtumien liput|Sporttickets|Sporttickets|Sportbiljetter ~ football tickets": {},
            "Theatre & musical tickets|Teatteri- ja musikaaliliput|Theater- & Musicalkarten|Theater- & musicaltickets|"
            "Teater- & musikalbiljetter": {},
            "Festival tickets|Festivaaliliput|Festivaltickets|Festivaltickets|Festivalbiljetter": {},
            "Cinema tickets|Elokuvaliput|Kinokarten|Bioscoopkaartjes|Biobiljetter ~ movie tickets, leffaliput": {},
            "Museum & attraction tickets|Museo- ja nähtävyysliput|Museums- & Attraktionstickets|Museum- & attractietickets|"
            "Museum- & attraktionsbiljetter ~ theme park, huvipuisto, freizeitpark, pretpark, nöjespark": {},
        }),
        "Weddings|Häät|Hochzeit|Bruiloft|Bröllop ~ wedding services, hääpalvelut, hochzeitsplanung": S({
            "Wedding photographer|Hääkuvaaja|Hochzeitsfotograf|Trouwfotograaf|Bröllopsfotograf ~ wedding photography, "
            "hääkuvaus, hochzeitsfotografie, bruidsfotograaf": {},
            "Wedding planner|Hääsuunnittelija|Hochzeitsplaner|Weddingplanner|Bröllopsplanerare": {},
            "Wedding venues|Hääpaikat|Hochzeitslocations|Trouwlocaties|Bröllopslokaler": {},
            "Wedding dresses & suits|Hääpuvut|Brautmode|Trouwjurken|Brudklänningar": {},
        }),
        "Photography & video|Valokuvaus ja video|Fotografie & Video|Fotografie & video|Fotografering & video ~ "
        "photographer, valokuvaaja, fotograf, fotograaf, videographer": S({
            "Event photographer|Tapahtumakuvaaja|Eventfotograf|Evenementfotograaf|Eventfotograf": {},
            "Portrait & family photography|Muotokuvaus ja perhekuvaus|Porträt- & Familienfotografie|Portretfotografie|"
            "Porträtt- & familjefotografering ~ passport photos, passikuvat": {},
            "Videography|Videokuvaus|Videografie|Videografie|Videofilmning": {},
            "Drone photography|Drone-kuvaus|Drohnenaufnahmen|Dronefotografie|Drönarfotografering": {},
        }),
        "Catering|Pitopalvelu|Catering|Catering|Catering ~ caterer, pitopalvelu, partyservice": {},
        "Event venues|Juhlatilat|Eventlocations|Feestlocaties|Festlokaler ~ venue hire, juhlatila, location mieten, zaalverhuur": {},
        "DJs & entertainers|DJ:t ja esiintyjät|DJs & Entertainer|DJ's & artiesten|DJ:s & underhållare ~ band, live music, "
        "magician, taikuri, clown": {},
        "Party supplies & rentals|Juhlatarvikkeet ja vuokraus|Partyzubehör & Verleih|Feestartikelen & verhuur|"
        "Festartiklar & uthyrning ~ tent hire, bouncy castle, pomppulinna": {},
        "Event planning|Tapahtumasuunnittelu|Eventplanung|Evenementenplanning|Eventplanering ~ event planner, "
        "corporate events, yritystapahtumat": {},
        "Activities & experiences|Elämykset ja aktiviteetit|Erlebnisse & Aktivitäten|Uitjes & activiteiten|"
        "Upplevelser & aktiviteter ~ escape room, karting, gift experiences, elämyslahja": {},
        "Sports clubs & venues|Urheiluseurat ja -paikat|Sportvereine & Sportstätten|Sportclubs & sportlocaties|"
        "Idrottsföreningar & anläggningar ~ padel, golf, bowling, swimming pool, uimahalli": {},
        "Nightlife & bars|Yöelämä ja baarit|Nachtleben & Bars|Uitgaan & bars|Nattliv & barer ~ pub, club, cocktail bar": {},
        "Streaming & entertainment subscriptions|Suoratoisto ja viihdetilaukset|Streaming & Unterhaltungs-Abos|"
        "Streaming & entertainment-abonnementen|Streaming & underhållningsabonnemang ~ netflix, spotify, disney+, hbo, "
        "viaplay, music streaming": {},
    }),
    "travel": S({
        "Flights|Lennot|Flüge|Vluchten|Flyg ~ airline tickets, lentoliput, flugtickets, vliegtickets, flygbiljetter, "
        "cheap flights, halvat lennot": {},
        "Hotels|Hotellit|Hotels|Hotels|Hotell ~ hotel room, booking, hotellihuone, hotelzimmer, hotelkamer": {},
        "Holiday rentals & cottages|Lomamökit ja loma-asunnot|Ferienwohnungen & Ferienhäuser|Vakantiehuizen|"
        "Stugor & semesterboenden ~ airbnb, mökki, cottage, ferienhaus, vakantiewoning, stuga": {},
        "Hostels & camping|Hostellit ja leirintäalueet|Hostels & Campingplätze|Hostels & campings|Vandrarhem & camping": {},
        "Package holidays|Valmismatkat|Pauschalreisen|Pakketreizen|Paketresor ~ all inclusive, matkatoimisto, reisebüro": {},
        "Cruises & ferries|Risteilyt ja laivat|Kreuzfahrten & Fähren|Cruises & veerboten|Kryssningar & färjor ~ "
        "viking line, tallink, ferry tickets, laivaliput": {},
        "Car rental|Autonvuokraus|Autovermietung|Autoverhuur|Biluthyrning ~ rental car, vuokra-auto, mietwagen, "
        "huurauto, hyrbil": {},
        "Tours & excursions|Retket ja kierrokset|Touren & Ausflüge|Rondleidingen & excursies|Turer & utflykter ~ "
        "guided tour, opastettu kierros, sightseeing": {},
        "Travel insurance & visas|Matkavakuutus ja viisumit|Reiseversicherung & Visa|Reisverzekering & visa|"
        "Reseförsäkring & visum": {},
        "Train & bus tickets|Juna- ja bussiliput|Zug- & Busfahrkarten|Trein- & buskaartjes|Tåg- & bussbiljetter ~ vr, "
        "deutsche bahn, flixbus, onnibus, sj": {},
        "Airport transfers & parking|Lentokenttäkuljetukset ja pysäköinti|Flughafentransfer & Parken|"
        "Luchthavenvervoer & parkeren|Flygtransfer & parkering": {},
    }),
    "transport": S({
        "Taxi & ride hailing|Taksi|Taxi & Fahrdienste|Taxi|Taxi ~ cab, uber, bolt, taksi": {},
        "Public transport|Julkinen liikenne|Öffentlicher Nahverkehr|Openbaar vervoer|Kollektivtrafik ~ hsl, bus pass, "
        "monthly ticket, kuukausilippu, deutschlandticket, ov-chipkaart": {},
        "Parcel & courier delivery|Paketti- ja kuriiripalvelut|Paket- & Kurierdienste|Pakket- & koeriersdiensten|"
        "Paket- & budtjänster ~ shipping, posti, dhl, ups, postnl, postnord, courier": {},
        "Freight & haulage|Rahti ja kuljetukset|Fracht & Spedition|Vracht & transport|Frakt & åkeri ~ trucking, "
        "rahtipalvelu, spedition": {},
        "Van & truck hire|Pakettiauton vuokraus|Transporter- & LKW-Vermietung|Busje huren|Hyra skåpbil ~ van rental, "
        "peräkärryn vuokraus, trailer hire": {},
        "Car sharing & scooters|Yhteiskäyttöautot ja sähköpotkulaudat|Carsharing & E-Scooter|Autodelen & deelscooters|"
        "Bilpool & elsparkcyklar ~ e-scooter rental, sähköpotkulauta, share now, voi, tier": {},
        "Bike rental & sharing|Pyörävuokraus ja kaupunkipyörät|Fahrradverleih|Fietsverhuur|Cykeluthyrning ~ city bikes "
        "rental, kaupunkipyörä": {},
        "Vehicle transport & shipping|Ajoneuvokuljetukset|Fahrzeugtransport|Autotransport|Fordonstransport": {},
    }),
    "professional": S({
        "Legal services|Lakipalvelut|Rechtsberatung|Juridische diensten|Juridiska tjänster ~ lawyer, solicitor, "
        "asianajaja, lakimies, anwalt, rechtsanwalt, advocaat, advokat, jurist, notary, notaari, notar": {},
        "Accounting & tax|Kirjanpito ja verot|Buchhaltung & Steuerberatung|Boekhouding & belastingadvies|"
        "Redovisning & skatt ~ accountant, tilitoimisto, steuerberater, boekhouder, revisor, bookkeeping, tax return": {},
        "Translation & interpreting|Käännös- ja tulkkauspalvelut|Übersetzung & Dolmetschen|Vertaling & tolken|"
        "Översättning & tolkning ~ translator, kääntäjä, übersetzer, vertaler, översättare": {},
        "Consulting|Konsultointi|Unternehmensberatung|Advies & consultancy|Konsulttjänster ~ consultant, konsultti, "
        "berater, adviseur, management consulting": {},
        "Marketing & advertising|Markkinointi ja mainonta|Marketing & Werbung|Marketing & reclame|Marknadsföring & reklam"
        " ~ advertising agency, mainostoimisto, werbeagentur, reclamebureau": {},
        "Recruitment & HR|Rekrytointi ja henkilöstöpalvelut|Personalvermittlung & HR|Werving & selectie|"
        "Rekrytering & bemanning ~ staffing agency, henkilöstövuokraus, zeitarbeit, uitzendbureau": {},
        "Printing & copying|Painatus ja kopiointi|Druck & Kopien|Drukwerk & kopiëren|Tryck & kopiering ~ print shop, "
        "kirjapaino, druckerei, drukkerij, business cards, käyntikortit": {},
        "Real estate agents|Kiinteistönvälittäjät|Immobilienmakler|Makelaars|Fastighetsmäklare ~ estate agent, realtor, "
        "kiinteistönvälitys, makler, makelaar, mäklare": {},
        "Security services|Vartiointi ja turvallisuuspalvelut|Sicherheitsdienste|Beveiligingsdiensten|Säkerhetstjänster ~ "
        "security guard, vartija, wachdienst": {},
        "Coworking & office space|Coworking ja toimitilat|Coworking & Büroräume|Coworking & kantoorruimte|"
        "Coworking & kontorslokaler ~ office rental, toimitila, büro mieten": {},
        "Business registration & admin|Yrityksen perustaminen ja hallinto|Firmengründung & Verwaltung|"
        "Bedrijf oprichten & administratie|Företagsregistrering & administration ~ virtual office": {},
        "Engineering & surveying|Insinööri- ja mittauspalvelut|Ingenieur- & Vermessungsdienste|Ingenieurs- & landmeetdiensten|"
        "Ingenjörs- & mättjänster ~ surveyor, energy certificate, kuntotarkastus, energieausweis": {},
    }),
    "digital-services": S({
        "Web & app development|Verkkosivut ja sovelluskehitys|Web- & App-Entwicklung|Web- & app-ontwikkeling|"
        "Webb- & apputveckling ~ web developer, programmer, koodari, website, kotisivut, webdesign": {},
        "Graphic & logo design|Graafinen suunnittelu ja logot|Grafik- & Logodesign|Grafisch ontwerp & logo's|"
        "Grafisk design & logotyper ~ graphic designer, logo, graafikko": {},
        "Digital marketing & SEO|Digimarkkinointi ja hakukoneoptimointi|Online-Marketing & SEO|Online marketing & SEO|"
        "Digital marknadsföring & SEO ~ social media marketing, google ads, some-markkinointi": {},
        "Writing & copywriting|Tekstisisällöt ja copywriting|Texten & Copywriting|Copywriting & teksten|Copywriting & texter"
        " ~ content writing, ghostwriter": {},
        "Video & animation|Video ja animaatio|Video & Animation|Video & animatie|Video & animation ~ video editing, editointi": {},
        "Music & audio production|Musiikki- ja äänituotanto|Musik- & Audioproduktion|Muziek- & audioproductie|"
        "Musik- & ljudproduktion ~ voice over, mixing, podcast editing": {},
        "Data & AI services|Data- ja tekoälypalvelut|Daten- & KI-Dienste|Data- & AI-diensten|Data- & AI-tjänster ~ "
        "data analysis, machine learning, chatbot": {},
        "IT support & cloud|IT-tuki ja pilvipalvelut|IT-Support & Cloud|IT-support & cloud|IT-support & moln ~ "
        "web hosting, domains, verkkotunnus, webhosting, managed it": {},
        "Virtual assistants|Virtuaaliassistentit|Virtuelle Assistenz|Virtuele assistenten|Virtuella assistenter ~ "
        "data entry, admin support": {},
        "Online tutoring & coaching|Verkkovalmennus|Online-Coaching|Online coaching|Onlinecoaching ~ life coach, "
        "career coaching, uravalmennus": {},
    }),
    "finance-insurance": S({
        "Insurance|Vakuutukset|Versicherungen|Verzekeringen|Försäkringar ~ insurance quote, vakuutus, versicherung, "
        "verzekering, försäkring": S({
            "Car insurance|Autovakuutus|Kfz-Versicherung|Autoverzekering|Bilförsäkring ~ motor insurance, liikennevakuutus, "
            "kasko, autoversicherung, bilförsäkring, vehicle insurance": {},
            "Home & contents insurance|Kotivakuutus|Hausrat- & Wohngebäudeversicherung|Inboedel- & opstalverzekering|"
            "Hemförsäkring ~ home insurance, house insurance, kotivakuutus, hausratversicherung": {},
            "Health insurance|Sairausvakuutus|Krankenversicherung|Zorgverzekering|Sjukförsäkring ~ medical insurance, "
            "private health insurance": {},
            "Life insurance|Henkivakuutus|Lebensversicherung|Levensverzekering|Livförsäkring": {},
            "Travel insurance|Matkavakuutus|Reiseversicherung|Reisverzekering|Reseförsäkring": {},
            "Pet insurance|Lemmikkivakuutus|Tierversicherung|Huisdierenverzekering|Djurförsäkring ~ dog insurance, "
            "koiravakuutus, hundeversicherung": {},
            "Liability insurance|Vastuuvakuutus|Haftpflichtversicherung|Aansprakelijkheidsverzekering|Ansvarsförsäkring": {},
            "Business insurance|Yritysvakuutus|Betriebsversicherung|Zakelijke verzekering|Företagsförsäkring": {},
            "Device & gadget insurance|Laitevakuutus|Geräteversicherung|Apparatenverzekering|Mobilförsäkring ~ "
            "phone insurance, extended warranty": {},
        }),
        "Loans & credit|Lainat ja luotot|Kredite & Darlehen|Leningen & krediet|Lån & krediter ~ loan, laina, kredit, "
        "lening, lån": S({
            "Mortgages|Asuntolainat|Baufinanzierung & Hypotheken|Hypotheken|Bolån ~ home loan, asuntolaina, hypothek, "
            "hypotheek, bolån": {},
            "Personal loans|Kulutusluotot|Privatkredite|Persoonlijke leningen|Privatlån ~ consumer loan, kulutusluotto": {},
            "Car loans|Autolainat|Autokredite|Autofinanciering|Billån ~ car finance": {},
            "Business loans|Yrityslainat|Unternehmenskredite|Zakelijke leningen|Företagslån": {},
        }),
        "Bank accounts|Pankkitilit|Girokonten|Bankrekeningen|Bankkonton ~ current account, käyttötili, girokonto, "
        "betaalrekening, lönekonto": {},
        "Credit cards|Luottokortit|Kreditkarten|Creditcards|Kreditkort": {},
        "Investing & savings|Sijoittaminen ja säästäminen|Geldanlage & Sparen|Beleggen & sparen|Investeringar & sparande ~ "
        "broker, stocks, funds, osakkeet, rahastot, etf, depot, savings account, säästötili": {},
        "Pensions|Eläkkeet|Altersvorsorge|Pensioen|Pension ~ retirement savings": {},
        "Payments & money transfer|Maksut ja rahansiirrot|Zahlungen & Geldtransfer|Betalingen & geld overmaken|"
        "Betalningar & överföringar ~ wise, paypal, currency exchange, valuutanvaihto": {},
        "Crypto|Kryptovaluutat|Kryptowährungen|Crypto|Kryptovalutor ~ bitcoin, ethereum, crypto exchange": {},
        "Financial advice|Talousneuvonta|Finanzberatung|Financieel advies|Ekonomisk rådgivning ~ financial advisor, "
        "debt counselling, velkaneuvonta, schuldnerberatung": {},
    }),
    "utilities": S({
        "Electricity|Sähkö|Strom|Elektriciteit|El ~ electricity contract, sähkösopimus, stromtarif, stromanbieter, "
        "energiecontract, elavtal, spot price, pörssisähkö": {},
        "Gas|Kaasu|Gas|Gas|Gas ~ gasanbieter, gascontract": {},
        "District heating|Kaukolämpö|Fernwärme|Stadsverwarming|Fjärrvärme": {},
        "Water & sewerage|Vesi ja viemäri|Wasser & Abwasser|Water & riolering|Vatten & avlopp": {},
        "Waste collection & recycling|Jätehuolto ja kierrätys|Müllabfuhr & Recycling|Afvalinzameling & recycling|"
        "Sophämtning & återvinning ~ skip hire, jäteastia, container mieten, afvalcontainer": {},
        "Home internet & broadband|Kotinetti ja laajakaista|Internet & DSL/Glasfaser|Internet & glasvezel|"
        "Bredband & internet ~ fibre, valokuitu, glasfaser, glasvezel, fiber, 5g home internet, mobiilinetti": {},
        "Mobile phone plans|Puhelinliittymät|Handyverträge & Tarife|Mobiele abonnementen|Mobilabonnemang ~ sim card, "
        "prepaid, liittymä, handyvertrag, sim only, mobilabonnemang, esim": {},
        "TV & streaming packages|TV-paketit|TV-Pakete|Tv-pakketten|TV-paket ~ cable tv, iptv": {},
        "Home energy upgrades|Energiaremontit|Energetische Sanierung|Verduurzaming woning|Energieffektivisering ~ "
        "energy audit, energiakatselmus": {},
    }),
    "personal-services": S({
        "Childcare & babysitting|Lastenhoito|Kinderbetreuung & Babysitter|Kinderopvang & oppas|Barnpassning ~ babysitter, "
        "nanny, au pair, lastenhoitaja, kinderbetreuung, oppas, barnvakt": {},
        "Elderly care & home care|Vanhusten hoiva ja kotihoito|Seniorenbetreuung & Pflege|Ouderenzorg & thuiszorg|"
        "Äldreomsorg & hemtjänst ~ care home, palvelutalo, pflegedienst, thuiszorg": {},
        "Pet care|Lemmikkien hoito|Tierbetreuung|Dierenoppas|Djurpassning ~ dog walker, dog sitter, koiranulkoilutus, "
        "hundesitter, hondenuitlaatservice, hundvakt": {},
        "Funeral services|Hautauspalvelut|Bestattung|Uitvaartverzorging|Begravningstjänster ~ funeral home, "
        "hautaustoimisto, bestatter, uitvaartondernemer": {},
        "Dating & matchmaking|Deittailu|Partnervermittlung & Dating|Dating & relatiebemiddeling|Dejting": {},
        "Personal assistants & errands|Asiointiapu|Persönliche Assistenz & Botendienste|Persoonlijke assistent|"
        "Ärendehjälp ~ concierge": {},
        "Personal shoppers & stylists|Henkilökohtaiset ostosavustajat ja stylistit|Personal Shopper & Stilberatung|"
        "Personal shoppers & stylisten|Personal shoppers & stylister": {},
        "Genealogy & document services|Sukututkimus ja asiakirjapalvelut|Ahnenforschung & Dokumente|"
        "Stamboomonderzoek & documenten|Släktforskning & dokument": {},
        "Religious & spiritual services|Uskonnolliset palvelut|Religiöse Dienste|Religieuze diensten|Religiösa tjänster": {},
    }),
    "food-drink": S({
        "Restaurants & takeaway|Ravintolat ja noutoruoka|Restaurants & Lieferdienste|Restaurants & bezorging|"
        "Restauranger & takeaway ~ food delivery, ruokalähetti, wolt, foodora, lieferando, thuisbezorgd, uber eats, "
        "pizza delivery": S({
            "Food delivery|Ruoan kotiinkuljetus|Essenslieferung|Maaltijdbezorging|Matleverans ~ takeaway": {},
            "Meal kits|Ateriakassit|Kochboxen|Maaltijdboxen|Matkassar ~ hellofresh, ruokaboksi": {},
            "Cafés & bakeries|Kahvilat ja leipomot|Cafés & Bäckereien|Cafés & bakkerijen|Kaféer & bagerier": {},
        }),
        "Grocery delivery|Ruokaostosten kotiinkuljetus|Lebensmittel-Lieferdienst|Boodschappen bezorgen|Matvaruleverans ~ "
        "online grocery, verkkoruokakauppa, k-ruoka, s-kaupat, flink, picnic, mathem": {},
    }),
    "property": S({
        "Apartments for rent|Vuokra-asunnot|Mietwohnungen|Huurwoningen|Hyreslägenheter ~ rent flat, vuokrata asunto, "
        "wohnung mieten, huurwoning, lägenhet att hyra, oikotie vuokra": {},
        "Homes for sale|Myytävät asunnot|Häuser & Wohnungen kaufen|Koopwoningen|Bostäder till salu ~ buy house, "
        "omakotitalo, kerrostalo, haus kaufen, huis kopen, köpa hus, funda, hemnet, etuovi": {},
        "Holiday homes & cottages for sale|Myytävät mökit|Ferienhäuser kaufen|Vakantiehuizen te koop|Fritidshus till salu": {},
        "Rooms & shared housing|Huoneet ja kimppakämpät|WG-Zimmer|Kamers|Rum & inneboende ~ flatshare, wg-gesucht, kamernet": {},
        "Commercial property|Liiketilat|Gewerbeimmobilien|Bedrijfsruimtes|Kommersiella lokaler ~ office space, retail space": {},
        "Plots & land|Tontit|Grundstücke|Bouwgrond & kavels|Tomter ~ land for sale": {},
        "Garages & parking spaces|Autotallit ja parkkipaikat|Garagen & Stellplätze|Garageboxen & parkeerplaatsen|"
        "Garage & parkeringsplatser": {},
        "Property management|Isännöinti|Hausverwaltung|Vastgoedbeheer|Fastighetsförvaltning ~ isännöitsijä": {},
    }),
    "software": S({
        "Streaming subscriptions|Suoratoistopalvelut|Streaming-Abos|Streamingdiensten|Streamingtjänster ~ netflix, "
        "spotify, disney plus, hbo max, youtube premium, apple music": {},
        "Cloud storage|Pilvitallennus|Cloud-Speicher|Cloudopslag|Molnlagring ~ dropbox, google one, icloud": {},
        "VPN & security subscriptions|VPN ja tietoturva|VPN & Sicherheit|VPN & beveiliging|VPN & säkerhet": {},
        "Domains & web hosting|Verkkotunnukset ja webhotellit|Domains & Webhosting|Domeinnamen & webhosting|"
        "Domäner & webbhotell": {},
        "Mobile apps|Mobiilisovellukset|Apps|Apps|Appar": {},
        "Online newspapers & magazines|Digilehdet|Digitale Zeitungen & Zeitschriften|Digitale kranten & tijdschriften|"
        "Digitala tidningar ~ news subscription, hs digi": {},
        "Audiobooks & e-books|Äänikirjat ja e-kirjat|Hörbücher & E-Books|Luisterboeken & e-books|Ljudböcker & e-böcker ~ "
        "storytel, bookbeat, audible, kindle": {},
        "AI tools & assistants|Tekoälytyökalut|KI-Tools|AI-tools|AI-verktyg ~ chatgpt, claude, copilot": {},
        "Game subscriptions & in-game currency|Pelitilaukset ja pelivaluutta|Spiele-Abos & Ingame-Währung|"
        "Game-abonnementen & in-game valuta|Spelabonnemang & spelvaluta ~ game pass, playstation plus, v-bucks": {},
    }),
    "pets": S({
        "Pet services|Lemmikkipalvelut|Tierdienstleistungen|Dierendiensten|Djurtjänster": S({
            "Veterinarians|Eläinlääkärit|Tierärzte|Dierenartsen|Veterinärer ~ vet, eläinlääkäri, tierarzt, dierenarts, "
            "veterinär, djursjukhus": {},
            "Pet grooming|Lemmikkien trimmaus|Hundefriseur|Trimsalon|Hundfrisör ~ dog grooming, koiran trimmaus": {},
            "Pet boarding|Lemmikkihoitola|Tierpension|Dierenpension|Djurpensionat ~ kennel, koirahoitola": {},
            "Dog training|Koirankoulutus|Hundeschule|Hondentraining|Hundträning ~ puppy class, hundeschule": {},
        }),
    }),
}

# Extra synonyms for imported nodes, matched by English label (case-insensitive) anywhere in the tree;
# the first node (shallowest) with that label gets them. Mostly shopper words and model names.
SYNONYMS: dict[str, str] = {
    "Bicycles": "bike, bikes, polkupyörä, pyörä, fahrrad, fiets, cykel, velo",
    "City Bikes": "city bike, citybike, kaupunkipyörä, stadsfiets, stadscykel, cityrad, hollandrad, commuter bike",
    "Mountain Bikes": "mtb, maastopyörä, mountainbike",
    "Electric Bikes": "e-bike, ebike, sähköpyörä, pedelec, elcykel, elektrische fiets",
    "Video Game Consoles": "console, pelikonsoli, spielkonsole, spelkonsol, ps5, ps4, playstation, xbox, nintendo switch, "
                           "switch 2, steam deck",
    "Game Controllers": "controller, gamepad, ohjain, peliohjain, dualsense, dualshock, joy-con, ps5 controller, "
                        "xbox controller",
    "Mobile & Smart Phones": "phone, smartphone, puhelin, älypuhelin, handy, telefoon, mobiltelefon, iphone, samsung galaxy, pixel",
    "Laptops": "notebook, kannettava, läppäri, macbook, chromebook, bärbar dator",
    "Tablet Computers": "tablet, ipad, tabletti, surfplatta",
    "Televisions": "tv, telkkari, televisio, fernseher, televisie, oled, qled",
    "Headphones": "headset, kuulokkeet, kopfhörer, koptelefoon, hörlurar, airpods",
    "Sofas": "couch, sohva, sofa, bank, soffa",
    "Washing Machines": "pesukone, waschmaschine, wasmachine, tvättmaskin",
    "Refrigerators": "fridge, jääkaappi, kühlschrank, koelkast, kylskåp",
    "Baby Strollers": "pram, buggy, rattaat, lastenrattaat, kinderwagen, barnvagn, kinderwagen",
    "Cars, Trucks & Vans": "car, auto, cars, used car, käytetty auto, gebrauchtwagen, occasion, begagnad bil",
    "Motorcycles & Scooters": "motorbike, moottoripyörä, motorrad, motor, motorcykel, moped, mopo",
    "Bookcases & Standing Shelves": "bookshelf, kirjahylly, bücherregal, boekenkast, bokhylla, kallax, billy",
}

# Where to look, per root or per curated path (" > " joined en labels below the root). lane: new | used |
# refurbished | rental | service | comparison. Domains are hints for discovery, not an exhaustive list.
WHERE: dict[str, list[tuple[str, str]]] = {
    "electronics": [("verkkokauppa.com", "new"), ("power.fi", "new"), ("gigantti.fi", "new"), ("jimms.fi", "new"),
                    ("amazon.de", "new"), ("mediamarkt.de", "new"), ("coolblue.nl", "new"), ("ipon.hu", "new"),
                    ("backmarket.de", "refurbished"), ("rebuy.de", "refurbished"), ("tori.fi", "used"),
                    ("kleinanzeigen.de", "used"), ("marktplaats.nl", "used"), ("blocket.se", "used"), ("ebay.de", "used")],
    "appliances": [("power.fi", "new"), ("gigantti.fi", "new"), ("verkkokauppa.com", "new"), ("coolblue.nl", "new"),
                   ("mediamarkt.de", "new"), ("otto.de", "new"), ("tori.fi", "used"), ("kleinanzeigen.de", "used"),
                   ("marktplaats.nl", "used")],
    "fashion": [("zalando.de", "new"), ("zalando.fi", "new"), ("otto.de", "new"), ("amazon.de", "new"),
                ("vinted.fi", "used"), ("vinted.de", "used"), ("tori.fi", "used"), ("kleinanzeigen.de", "used")],
    "home-garden": [("ikea.com", "new"), ("prisma.fi", "new"), ("tokmanni.fi", "new"), ("otto.de", "new"),
                    ("bol.com", "new"), ("amazon.de", "new"), ("tori.fi", "used"), ("kleinanzeigen.de", "used"),
                    ("marktplaats.nl", "used"), ("blocket.se", "used")],
    "furniture": [("ikea.com", "new"), ("otto.de", "new"), ("home24.de", "new"), ("tori.fi", "used"),
                  ("kleinanzeigen.de", "used"), ("marktplaats.nl", "used"), ("blocket.se", "used")],
    "diy": [("bauhaus.fi", "new"), ("k-rauta.fi", "new"), ("obi.de", "new"), ("hornbach.de", "new"),
            ("gamma.nl", "new"), ("tori.fi", "used"), ("kleinanzeigen.de", "used")],
    "health-beauty": [("yliopistonapteekki.fi", "new"), ("dm.de", "new"), ("douglas.de", "new"), ("lookfantastic.com", "new"),
                      ("amazon.de", "new")],
    "baby-kids": [("lastentarvike.fi", "new"), ("babyshop.com", "new"), ("tori.fi", "used"), ("vinted.fi", "used"),
                  ("kleinanzeigen.de", "used")],
    "toys-games": [("lekmer.fi", "new"), ("bol.com", "new"), ("amazon.de", "new"), ("tori.fi", "used"),
                   ("kleinanzeigen.de", "used")],
    "sports-outdoors": [("xxl.fi", "new"), ("intersport.fi", "new"), ("decathlon.de", "new"), ("bike-discount.de", "new"),
                        ("tori.fi", "used"), ("kleinanzeigen.de", "used"), ("marktplaats.nl", "used")],
    "hobbies": [("thomann.de", "new"), ("musamaailma.fi", "new"), ("tori.fi", "used"), ("kleinanzeigen.de", "used")],
    "media": [("adlibris.com", "new"), ("bol.com", "new"), ("amazon.de", "new"), ("tori.fi", "used"),
              ("momox.de", "used")],
    "food-drink": [("k-ruoka.fi", "new"), ("s-kaupat.fi", "new"), ("rewe.de", "new"), ("ah.nl", "new"),
                   ("wolt.com", "service"), ("foodora.fi", "service"), ("lieferando.de", "service"),
                   ("thuisbezorgd.nl", "service")],
    "pets": [("musti.fi", "new"), ("zooplus.de", "new"), ("zooplus.fi", "new"), ("tori.fi", "used")],
    "office": [("verkkokauppa.com", "new"), ("lyreco.com", "new"), ("amazon.de", "new")],
    "vehicles": [("nettiauto.com", "used"), ("autotalli.com", "used"), ("mobile.de", "used"), ("autoscout24.de", "used"),
                 ("marktplaats.nl", "used"), ("blocket.se", "used"), ("tori.fi", "used"), ("kleinanzeigen.de", "used")],
    "business": [("tori.fi", "used"), ("machineryline.com", "used"), ("kleinanzeigen.de", "used"), ("amazon.de", "new")],
    "software": [("verkkokauppa.com", "new"), ("amazon.de", "new"), ("g2.com", "comparison")],
    "property": [("oikotie.fi", "rental"), ("etuovi.com", "new"), ("vuokraovi.com", "rental"), ("immobilienscout24.de", "rental"),
                 ("immowelt.de", "rental"), ("funda.nl", "new"), ("pararius.nl", "rental"), ("hemnet.se", "new"),
                 ("blocket.se", "rental")],
    "home-services": [("helpling.de", "service"), ("helpling.nl", "service"), ("tori.fi", "service"),
                      ("kleinanzeigen.de", "service"), ("yelp.com", "service"), ("taskrabbit.com", "service"),
                      ("werkspot.nl", "service"), ("my-hammer.de", "service")],
    "trades": [("my-hammer.de", "service"), ("werkspot.nl", "service"), ("checkatrade.com", "service"),
               ("myhammer.at", "service"), ("tori.fi", "service"), ("remonttipalvelu.fi", "service"),
               ("offerta.se", "service"), ("yelp.com", "service")],
    "auto-services": [("fixu.fi", "service"), ("autobutler.de", "service"), ("yelp.com", "service")],
    "beauty-wellness": [("treatwell.de", "service"), ("treatwell.nl", "service"), ("timma.fi", "service"),
                        ("bokadirekt.se", "service"), ("planity.com", "service"), ("yelp.com", "service")],
    "health-services": [("terveystalo.com", "service"), ("mehilainen.fi", "service"), ("doctolib.de", "service"),
                        ("jameda.de", "service"), ("zorgkaartnederland.nl", "service"), ("1177.se", "service")],
    "education": [("superprof.de", "service"), ("superprof.fi", "service"), ("udemy.com", "service"),
                  ("coursera.org", "service"), ("preply.com", "service")],
    "events-leisure": [("lippu.fi", "service"), ("ticketmaster.fi", "service"), ("ticketmaster.de", "service"),
                       ("eventim.de", "service"), ("getyourguide.com", "service"), ("yelp.com", "service")],
    "travel": [("booking.com", "service"), ("skyscanner.net", "comparison"), ("google.com/travel", "comparison"),
               ("airbnb.com", "service"), ("momondo.fi", "comparison"), ("tjareborg.fi", "service"),
               ("check24.de", "comparison"), ("getyourguide.com", "service")],
    "transport": [("posti.fi", "service"), ("dhl.de", "service"), ("sendcloud.com", "service"), ("uber.com", "service"),
                  ("bolt.eu", "service"), ("hsl.fi", "service")],
    "professional": [("fiverr.com", "service"), ("upwork.com", "service"), ("yelp.com", "service"),
                     ("anwalt.de", "service")],
    "digital-services": [("fiverr.com", "service"), ("upwork.com", "service"), ("freelancer.com", "service"),
                         ("malt.de", "service")],
    "finance-insurance": [("vertaa.fi", "comparison"), ("check24.de", "comparison"), ("verivox.de", "comparison"),
                          ("independer.nl", "comparison"), ("compricer.se", "comparison"), ("lainaa.fi", "comparison")],
    "utilities": [("sahkonhinta.fi", "comparison"), ("sahkovertailu.fi", "comparison"), ("check24.de", "comparison"),
                  ("verivox.de", "comparison"), ("gaslicht.com", "comparison"), ("elskling.se", "comparison"),
                  ("puhelinliittymat.fi", "comparison")],
    "events-leisure.weddings": [("bark.com", "service"), ("yelp.com", "service")],
    "events-leisure.photography-video": [("bark.com", "service"), ("yelp.com", "service"), ("fiverr.com", "service")],
    "pets.pet-services": [("rover.com", "service"), ("yelp.com", "service")],
    "food-drink.restaurants-takeaway": [("wolt.com", "service"), ("foodora.fi", "service"), ("lieferando.de", "service"),
                                        ("thuisbezorgd.nl", "service"), ("ubereats.com", "service"), ("yelp.com", "service")],
    "personal-services": [("care.com", "service"), ("yoopies.de", "service"), ("rover.com", "service"),
                          ("tori.fi", "service")],
}


# Curated ids that moved: old id -> new id (written into tree.json "aliases", so old ids keep resolving).
ID_ALIASES: dict[str, str] = {
    "trades.carpentry-joinery.doors-windows": "trades.windows-doors-conservatories",
}

# The A-Z list a trades platform publishes (Checkatrade, ~1,000 entries) lands in "Other trades & specialists";
# these rules spread it over the curated groups. First match wins (lower-case English label, regex search).
TRADE_BUCKET_RULES: list[tuple[str, str]] = [
    (r"^(emergency )?miscellaneous|^hire services$|^restoration$|^refurbishments$|^glass$|^fault finding$", "-fold"),
    # not trades at all: other roots
    (r"chauffeur|minibus taxi|\btaxi", "transport.taxi-ride-hailing"),
    (r"commercial deliveries", "transport.parcel-courier-delivery"),
    (r"corporate filming|filming", "events-leisure.photography-video"),
    (r"mobile disco|\bdj", "events-leisure.djs-entertainers"),
    (r"events setting|marquee", "events-leisure.party-supplies-rentals"),
    (r"landlord|commercial agents|letting", "property.property-management"),
    (r"hot tub|spas?$|swimming pool", "home-services.garden-outdoor.pool-maintenance"),
    (r"auto glass", "auto-services.windscreen-repair"),
    (r"diagnostic", "auto-services.car-repair-servicing"),
    (r"moving transport|umzug", "home-services.moving-removals"),
    (r"shot blasting|sand blasting", "home-services.cleaning.pressure-washing"),
    # vehicles
    (r"accident repair|dent repair|smart repairs|vehicle paint|alloy wheel|wheel refurb|vehicle wrapping|"
     r"vehicle signwriting|vehicle window tinting", "auto-services.bodywork-paint"),
    (r"motorcycle tyres|scooter tyres", "auto-services.tyre-change-storage"),
    (r"\bmots?\b", "auto-services.vehicle-inspection"),
    (r"vehicle recovery|towing", "auto-services.towing-roadside-assistance"),
    (r"windscreen", "auto-services.windscreen-repair"),
    (r"valeting", "auto-services.car-wash-detailing"),
    (r"cambelt|clutch|gearbox|engine rebuild|garage vehicle|motorcycle services|motor home|vehicle air con|"
     r"battery exhaust|locking wheel nut|car alarm|car audio|classic car|van conversion", "auto-services.car-repair-servicing"),
    (r"scrap car|scrap metal|salvage|rubbish|waste clearance|garden clearance|warehouse clearance|decluttering|"
     r"skip bag|oil tank emptying", "home-services.moving-removals.junk-removal-disposal"),
    (r"international removals", "home-services.moving-removals.international-moving"),
    (r"removals|storage service|loft storage room", "home-services.moving-removals"),
    # security, locks, mobility
    (r"car key|vehicle locksmith|\block|key cutting|doors opened|\bsafes?\b", "home-services.handyman.lock-key-services"),
    (r"alarm|cctv|intercom|door entry|fire extinguisher", "home-services.home-security-alarms"),
    (r"stairlift|mobility|wheelchair|rise and recline|adjustable beds|disabled|accessible", "trades.accessibility-mobility-adaptations"),
    # structure, roofs, damp
    (r"conservator|orangeri|\bporch|lean to", "trades.windows-doors-conservatories"),
    (r"chimney|\bflues?\b|stove|wood burner|log burn|fireplace|rayburn|solid fuel|smokeless fuel|\blogs\b",
     "trades.chimneys-fireplaces-stoves"),
    (r"asbestos (survey|testing)|survey|planning|party wall|inventor|legionella|risk assessment|pat testing|"
     r"portable appliance|investigation|structural designer|architect|technician$", "trades.surveys-planning-inspections"),
    (r"asbestos|knock through|chimney breast removal", "trades.building-renovation.demolition"),
    (r"damp|condensation|mould|dry rot|woodworm|timber treatment|timber resin|subsidence|under ?pinning|wall tie|"
     r"lintel|\brsj\b|rolled steel joist|structural|spalling|crack|water ?proofing|foundation|piling|sagging|"
     r"flood|fire damage|water damage", "trades.damp-flood-structural-repairs"),
    (r"insulation|draught proofing|sound proofing|thermal dynamics|cavity", "trades.building-renovation.insulation"),
    (r"scaffold", "trades.scaffolding"),
    # heating, electrics, plumbing
    (r"heat pump|gshp", "trades.heating-ventilation-air-conditioning.heat-pump-installation"),
    (r"boiler", "trades.heating-ventilation-air-conditioning.boiler-service"),
    (r"air conditioning|refrigeration", "trades.heating-ventilation-air-conditioning.air-conditioning-installation"),
    (r"radiator|central heating|smart heating|underfloor|\bufh\b|thermostat|\btrv\b|hive heating|tado|lpg|oil tank|oil central|"
     r"storage heating|electric heating|heater repair|power flush|extractor fan|fume extraction|ventilation",
     "trades.heating-ventilation-air-conditioning"),
    (r"electric vehicle|ev charg", "trades.electrical-work.ev-charger-installation"),
    (r"solar|photovoltaic", "trades.electrical-work.solar-panel-installation"),
    (r"lighting|\bled\b", "trades.electrical-work.lighting-installation"),
    (r"renewable|wind turbine|biomass|thermodynamic|battery storage|feed in tariff|rainwater harvesting|energy tariff",
     "trades.energy-renewables"),
    (r"rewiring|socket|fuseboard|consumer unit|electric gate|electric shower|ceiling fan|cabling$|^cabling|wiring",
     "trades.electrical-work"),
    (r"drain|sewer|soakaway|sewage|septic|macerator|soil stack|blocked loo", "trades.plumbing.drain-unblocking"),
    (r"bath|shower|wet room|toilet|basin|sink|mastic", "trades.plumbing.bathroom-renovation"),
    (r"immersion|hot water|unvented", "trades.plumbing.water-heater-installation"),
    (r"pipe|pipework|\btap\b|tap |water|leak detection|moling|plumb|dishwasher draining|purifier|well pump",
     "trades.plumbing"),
    # roofs (after conservatories), windows, doors
    (r"roof|fascia|soffit|gutter|lead ?flashing|leadwork|lead roofer|ridge|dry verge|dormer|thatch|slate|plain tiles|"
     r"skylight|velux|felt lap", "trades.roofing"),
    (r"window|door|bifold|upvc|\bsash|canop|insect screen|cat flap|dog flap|blind|curtain|shutter",
     "trades.windows-doors-conservatories"),
    (r"glass|glazing|mirror|splashback", "trades.glaziers"),
    # walls, floors, finishes
    (r"plaster|render|pebble dash|k rend|monocouche|skim|coving|dry ?lining|drywall|sheetrock|\bstud\b|partition|artex|"
     r"ceiling|screed|tape and jointing|\blath|silicone|cladding|ply boarding", "trades.plastering-drylining"),
    (r"brick|repointing|stone|flint|lime mortar|masonry|concret|core drilling|diamond drilling|memorial|gravestone",
     "trades.masonry-bricklaying"),
    (r"tile|tiling|mosaic", "trades.tiling"),
    (r"carpet|floor|laminate|skirting", "trades.flooring"),
    # furniture, joinery, outside
    (r"kitchen|worktop|wardrobe|bedroom|built in|fitted|media wall|alcove|cupboard|shelving|under stairs|bookcase|racking|"
     r"bespoke (dining|living|bedroom|pine|oak|furniture)", "trades.kitchens-bedrooms-fitted-furniture"),
    (r"restor|french polish|antique|refurbish|furniture (painting|spray|strip)|stripper|stripping|leather repair|"
     r"chair repair|wood turning|stone carving|stained glass|bed frame|surface repair", "trades.restoration-specialist-crafts"),
    (r"shed|summer ?house|log cabin|gazebo|pergola|garden room|garden studio|garden structure|outbuilding|greenhouse|"
     r"polytunnel|car ?port|aviar|stable|workshop builder|concrete garage|play area|sail shade|timber structure|"
     r"oak framing", "trades.garden-buildings-structures"),
    (r"decking|deck ", "trades.carpentry-joinery.decking-fences"),
    (r"driveway|paving|patio|tarmac|resin|gravel|imprinted|kerb|fenc|gate|railing|trellis|sleepers|road marking|"
     r"surfacing|block paving", "trades.driveways-paving-fencing"),
    (r"joiner|joinery|carpent|stair|handrail|balustrade|architrave|woodwork|roof truss|wood", "trades.carpentry-joinery"),
    (r"garage demolition", "trades.building-renovation.demolition"),
    (r"loft|attic|garage conversion|basement|barn conversion|extension|new build|renovation|eco builder|sustainable|"
     r"builders?$|agricultural build|listed building|heritage|property maintenance|dormer|rsj beam",
     "trades.building-renovation"),
    (r"grass|turf|mulch|weed|scarification|stump|crown (reduction|thinning)|grounds maintenance|garden maintenance|"
     r"knotweed|moss removal|sensory garden|roof garden|water garden|water feature|pond|gritting|garden",
     "home-services.garden-outdoor"),
    (r"graffiti|soft washing|render cleaning|stain protection|glass polishing|ironing", "home-services.cleaning"),
    (r"wasp|fumigation|bird restriction|pest", "home-services.pest-control"),
    (r"dishwasher|fridge|tumble dryer|oven|cooker|vacuum|appliance repair", "home-services.appliance-electronics-repair.home-appliance-repair"),
    (r"video audio", "home-services.appliance-electronics-repair.tv-audio-repair"),
    (r"computer maintenance|hardware consult", "home-services.appliance-electronics-repair.computer-repair"),
    (r"aerial|satellite|audio visual|freesat|freeview|television point|telephone|broadband|network|wifi|volp|voip|fixed lines|epos|"
     r"\bit\b", "trades.tv-aerials-telecom-networking"),
    (r"metal|steel|blacksmith|weld|laser cutting", "trades.welding-metalwork"),
    (r"digger|cherry picker|grab hire|hire", "trades.tool-equipment-hire"),
    (r"borehole|groundwork|excavat|agricultural contractor", "trades.groundwork-excavation"),
    (r"paint|decorat|wallpaper|mural|spray|sign (writer|maker)|lime wash|coating|door dipping", "trades.painting-decorating"),
    (r"merchant|supplier|retailer|showroom", "trades.merchants-trade-suppliers"),
    (r"handyman|odd jobs|assembly|mounting|shelves", "home-services.handyman"),
]


# ------------------------------------------------------------------ category pages (owner, 14 Nov)
# "noone would want to see something like this for 'lifestyle services' ... like wtf even is a lifestyle service".
# Broad nodes open a category page (agora/taxonomy/browse.py decides which); these make the menu read like a shop's.

# Plain names for vague or bureaucratic labels: id -> "en|fi|de|nl|sv" (empty parts keep the old label in that
# language). The old labels become search synonyms, so typing them still finds the node.
RENAMES: dict[str, str] = {
    "personal-services": "Care, Family & Everyday Help|Hoiva, perhe ja arjen apu|Pflege, Familie & Alltagshilfe|"
                         "Zorg, gezin & hulp in het dagelijks leven|Omsorg, familj & vardagshjälp",
    "beauty-wellness": "Hair, Beauty & Wellness|Kampaamot, kauneus ja hyvinvointi|Friseur, Beauty & Wellness|"
                       "Kapper, beauty & wellness|Frisör, skönhet & välmående",
    "health-services": "Doctors, Dentists & Health|Lääkärit, hammaslääkärit ja terveys|Ärzte, Zahnärzte & Gesundheit|"
                       "Artsen, tandartsen & gezondheid|Läkare, tandläkare & hälsa",
    "home-services": "Cleaning, Moving & Home Help|Siivous, muutto ja kotiapu|Reinigung, Umzug & Haushaltshilfe|"
                     "Schoonmaak, verhuizen & hulp in huis|Städning, flytt & hemhjälp",
    "auto-services": "Car Repair, Tyres & Car Care|Autokorjaamot, renkaat ja autonhoito|Kfz-Werkstatt, Reifen & Autopflege|"
                     "Garage, banden & autoverzorging|Bilverkstad, däck & bilvård",
    "professional": "Lawyers, Accountants & Business Help|Juristit, kirjanpitäjät ja yrityspalvelut|"
                    "Anwälte, Steuerberater & Business-Service|Advocaten, boekhouders & zakelijke hulp|"
                    "Jurister, redovisning & företagshjälp",
    "digital-services": "Freelancers: Web, Design & Writing|Freelancerit: verkko, suunnittelu ja kirjoitus|"
                        "Freelancer: Web, Design & Texte|Freelancers: web, design & tekst|Frilansare: webb, design & text",
    "utilities": "Electricity, Internet & Phone Plans|Sähkö, netti ja puhelinliittymät|Strom, Internet & Handyverträge|"
                 "Energie, internet & telefoonabonnementen|El, internet & mobilabonnemang",
    "transport": "Taxis, Couriers & Transport|Taksit, kuriirit ja kuljetus|Taxi, Kurier & Transport|"
                 "Taxi, koeriers & vervoer|Taxi, bud & transport",
    # second level: the umbrellas a shop would never print
    "m:fiverr:lifestyle-ce77d6": "Online coaching, wellness & hobbies|Verkkovalmennus, hyvinvointi ja harrastukset|"
                                 "Online-Coaching, Wellness & Hobbys|Online coaching, wellness & hobby's|"
                                 "Onlinecoachning, välmående & hobbyer",
    "sp:se-6-3": "Clinics & hospitals|Klinikat ja sairaalat|Kliniken & Krankenhäuser|Klinieken & ziekenhuizen|"
                 "Kliniker & sjukhus",
    "sp:se-4": "Kids' & indoor activities|Lasten ja sisäaktiviteetit|Kinder- & Indoor-Aktivitäten|"
               "Kinder- & binnenactiviteiten|Barn- & inomhusaktiviteter",
    "sp:se-5": "Home improvement|Kodin parannus|Heimwerker-Service|Woningverbetering|Hemförbättring",
    "cpv:39": "Furniture & household goods (EU list)|||",
    "pets.pet-services": "Pet care, grooming & vets|Lemmikkien hoito, trimmaus ja eläinlääkärit|"
                         "Tierbetreuung, Hundesalon & Tierarzt|Dierenoppas, trimsalon & dierenarts|"
                         "Djurpassning, trimning & veterinär",
}

# Nodes in the wrong root (an import put them where a shopper would never look): id -> new parent id.
MOVES: dict[str, str] = {
    "sp:se-6-3": "health-services",          # 'Healthcare Services' sat under Education
    "sp:se-6": "personal-services",           # 'Personal Services' sat under Recruitment & HR (then folds up)
    "yelp:airductcleaning": "home-services.cleaning",
    "yelp:bike_repair_maintenance": "home-services.appliance-electronics-repair.bicycle-repair",
    "yelp:jewelryrepair": "home-services.appliance-electronics-repair.watch-jewellery-repair",
    "yelp:sewingalterations": "home-services.appliance-electronics-repair.clothing-alterations-tailoring",
    "yelp:junkremovalandhauling": "home-services.moving-removals",
    "yelp:childcare": "personal-services.childcare-babysitting",
    "yelp:biohazardcleanup": "home-services.cleaning",
    "yelp:carpetdyeing": "home-services.cleaning",
    "yelp:wildlifecontrol": "home-services.pest-control",
    "yelp:hydrojetting": "trades.plumbing.drain-unblocking",
    "yelp:septicservices": "trades.plumbing",
    "yelp:stonemasons": "trades.masonry-bricklaying",
    "yelp:welldrilling": "trades.groundwork-excavation",
    "yelp:reupholstery": "trades.restoration-specialist-crafts",
    "yelp:craneservices": "trades.tool-equipment-hire",
    "yelp:generatorinstallrepair": "trades.electrical-work",
    "yelp:shipping_centers": "transport.parcel-courier-delivery",
    "yelp:mailboxcenters": "transport.parcel-courier-delivery",
    "yelp:busrental": "transport",
    "yelp:3dprinting": "professional",
    "yelp:screenprinting": "professional.printing-copying",
    "yelp:screen_printing_tshirt_printing": "professional.printing-copying",
}

# Empty umbrellas to merge into their parent even when the words look concrete (the rules in browse.py catch
# the rest: 'Lifestyle Services', 'Accessories', 'Other personal services' ...).
FOLD_UP: list[str] = [
    "sp:se-6-4",       # Lifestyle Services (Beauty & Wellness): nothing in it
    "sp:se-6-1",       # Beauty & Personal Care (a leaf under Beauty & Wellness): the root itself
    "sp:se-6",         # Personal Services: its two children go to the care root, its name becomes a synonym there
]

# Hand verdicts where the rules guess wrong: id -> True (huntable) | False (browse-only).
HUNTABLE: dict[str, bool] = {
    "trades.plumbing": True, "trades.electrical-work": True, "trades.roofing": True, "trades.tiling": True,
    "trades.flooring": True, "trades.painting-decorating": True, "home-services.pest-control": True,
    "home-services.handyman": True, "beauty-wellness.massage": True, "beauty-wellness.nails": True,
    "home-services.cleaning": False, "home-services.garden-outdoor": False,
}

# One plain line per root for its category page ("what's inside").
ABOUT: dict[str, str] = {
    "electronics": "Phones, laptops, TVs, cameras, headphones, gaming and everything that plugs in.",
    "appliances": "Washing machines, fridges, dishwashers, vacuums, coffee machines and kitchen gadgets.",
    "fashion": "Clothes, shoes, bags, jewellery and watches, new or second hand.",
    "home-garden": "Decor, kitchenware, bedding, lighting, plants and everything for the garden.",
    "furniture": "Sofas, beds, tables, chairs, shelves and wardrobes, for every room and the office.",
    "diy": "Power tools, hand tools, paint, building materials, plumbing and electrical parts.",
    "health-beauty": "Skin care, make-up, hair care, vitamins, medicines and personal hygiene.",
    "baby-kids": "Prams, car seats, cots, nappies, baby clothes and toys for little ones.",
    "toys-games": "Toys, board games, puzzles, LEGO, video games and outdoor play.",
    "sports-outdoors": "Bikes, fitness gear, running, camping, fishing, skiing and team sports.",
    "hobbies": "Musical instruments, art and craft supplies, collectibles and party things.",
    "media": "Books, e-books, films, music, vinyl and magazines.",
    "food-drink": "Groceries, drinks, food delivery, restaurants and catering.",
    "pets": "Pet food, beds, toys and supplies, pets for adoption and pet care.",
    "office": "Paper, pens, printer ink, desks, filing and school supplies.",
    "vehicles": "Cars, motorbikes, vans, boats, caravans, and parts and tyres for them.",
    "business": "Machinery, shop and restaurant equipment, lab and medical gear, workwear and bulk supplies.",
    "software": "Apps, software licences, streaming and cloud subscriptions, games and gift cards.",
    "property": "Flats and houses to rent or buy, holiday homes, garages and land.",
    "home-services": "Cleaners, movers, gardeners, handymen, repair shops and pest control.",
    "trades": "Plumbers, electricians, painters, roofers, builders and other tradespeople.",
    "auto-services": "Car servicing and repairs, tyre changes, inspections, car washes and towing.",
    "beauty-wellness": "Haircuts, barbers, massage, nails, facials, spas and personal trainers.",
    "health-services": "GPs, dentists, physiotherapists, psychologists, opticians and lab tests.",
    "education": "Tutors, language and music lessons, driving schools and online courses.",
    "events-leisure": "Concert tickets, weddings, photographers, DJs, venues and things to do.",
    "travel": "Flights, hotels, holiday cottages, package holidays, car rental and tours.",
    "transport": "Taxis, parcel delivery, couriers, van hire, freight and public transport.",
    "professional": "Lawyers, accountants, translators, consultants, marketing and printing.",
    "digital-services": "Freelance web developers, designers, writers, video editors and marketers.",
    "finance-insurance": "Insurance, loans, mortgages, bank accounts, credit cards and investing.",
    "utilities": "Electricity and gas contracts, home internet, mobile plans, water and waste.",
    "personal-services": "Babysitters, elderly care, pet sitters, funerals, personal assistants and other everyday help.",
}

# "Popular:" chips on a root's category page: plain words a person would type. The build finds each one's node
# inside the root (tree.json "pop": [[words, id]]); a chip hunts its words in that node.
POPULAR: dict[str, list[str]] = {
    "electronics": ["iPhone", "laptop", "TV", "headphones=>sp:el-2-2-7", "camera", "PS5", "tablet", "e-reader=>sp:el-6-4-2"],
    "appliances": ["washing machine", "fridge", "dishwasher", "vacuum cleaner", "coffee machine", "air fryer"],
    "fashion": ["winter jacket", "sneakers", "jeans", "handbag", "watch=>sp:aa-6-11", "dress=>sp:aa-1-4"],
    "home-garden": ["lamp", "rug", "bedding", "lawn mower", "garden hose", "pots and pans=>sp:hg-11-2-3"],
    "furniture": ["sofa", "bed=>sp:fr-2", "desk", "office chair", "dining table", "wardrobe", "bookcase"],
    "diy": ["drill", "ladder", "paint", "toolbox=>sp:ha-6-24-4", "pressure washer=>sp:hg-12-3-12"],
    "health-beauty": ["sunscreen", "shampoo", "electric toothbrush=>sp:hb-3-12-17-1", "perfume",
                      "vitamins=>sp:hb-1-9-6", "hair dryer"],
    "baby-kids": ["stroller", "car seat=>sp:bt-6-1", "crib=>sp:fr-1-6", "baby carrier", "high chair=>sp:fr-1-8",
                  "diapers"],
    "toys-games": ["LEGO=>sp:tg-5-7", "board games", "puzzle", "dolls", "remote control car", "trampoline"],
    "sports-outdoors": ["city bike", "running shoes=>sp:aa-8-1", "tent", "skis", "dumbbells", "kayak"],
    "hobbies": ["guitar", "digital piano", "sewing machine", "drone=>sp:tg-5-12-2", "drawing supplies"],
    "media": ["books", "vinyl records", "audiobooks", "magazines"],
    "food-drink": ["coffee beans", "wine", "food delivery", "catering", "protein powder=>sp:hb-1-9-6-8", "tea"],
    "pets": ["dog food", "cat litter", "aquarium", "cat tree", "pet sitter=>yelp:pet_sitting"],
    "office": ["printer paper", "printer ink=>sp:el-13-3-1-7", "notebooks=>sp:os-4-9-9", "pens",
               "desk lamp=>sp:hg-13-5-2", "shredder"],
    "vehicles": ["used car", "car tyres", "motorbike", "electric scooter", "car battery=>m:emag:auto-akkumulatorok-54d5f1"],
    "business": ["cash register", "forklift", "workwear=>m:marktplaats:werkkleding-b65fc7",
                 "label printer=>m:marktplaats:labelprinters-38a347"],
    "software": ["Microsoft Office=>m:marktplaats:office-software-912ca3", "antivirus", "VPN", "cloud storage",
                 "streaming subscription", "video games"],
    "property": ["apartment for rent", "house for sale", "summer cottage=>property.holiday-homes-cottages-for-sale",
                 "parking space", "room to rent"],
    "home-services": ["house cleaning", "movers", "window cleaning", "gardener", "furniture assembly", "pest control"],
    "trades": ["plumber", "electrician", "painter", "roofer", "bathroom renovation", "heat pump installation"],
    "auto-services": ["car service=>auto-services.car-repair-servicing", "tyre change", "car wash", "MOT inspection",
                      "windscreen repair", "towing"],
    "beauty-wellness": ["haircut", "massage", "manicure", "personal trainer", "barber", "facial", "eyelash extensions"],
    "health-services": ["dentist", "GP appointment", "physiotherapist", "psychologist", "eye test", "blood test"],
    "education": ["English lessons", "maths tutor", "piano lessons", "driving lessons", "swimming lessons", "coding course"],
    "events-leisure": ["concert tickets", "wedding photographer", "DJ", "party venue=>events-leisure.event-venues",
                       "escape room=>yelp:escapegames", "catering"],
    "travel": ["flights", "hotel", "holiday cottage", "car rental", "package holiday", "ferry"],
    "transport": ["taxi", "parcel delivery", "van hire", "courier", "airport transfer=>travel.airport-transfers-parking",
                  "city bike rental"],
    "professional": ["lawyer", "accountant", "translator", "tax return help", "business cards", "private investigator"],
    "digital-services": ["website", "logo design", "SEO", "video editing", "copywriting", "app development"],
    "finance-insurance": ["car insurance", "home insurance", "mortgage", "personal loan", "credit card", "travel insurance"],
    "utilities": ["electricity contract", "home broadband", "mobile plan", "solar panels", "district heating", "waste collection"],
    "personal-services": ["babysitter", "elderly care", "dog walker", "pet sitter", "funeral", "personal assistant"],
}
