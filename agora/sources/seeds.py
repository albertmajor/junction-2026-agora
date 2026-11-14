"""Seed list for the source registry, beyond the 193 second-hand sources (seed_secondhand.json):
big NEW-goods shops, price comparison sites, refurbishers, rental and SERVICE platforms per European
country. Hand-curated (Junction 2026); `scripts/onboard_sources.py` finds out how to search each one.

One line per source:  <home url>  <countries,>  <lanes,>  <categories,>  <kind>  [name with spaces]
lanes: new used refurb rental service.  kind: retailer marketplace comparison refurbisher rental service
housing vehicles classifieds specialist.  Categories use the vocabulary in `agora.sources.CATEGORIES`.
"""

EXTRA = r"""
# ---------------------------------------------------------------- Finland
https://www.verkkokauppa.com/fi/          fi  new        electronics,computers,phones,appliances,home,toys,general  retailer Verkkokauppa.com
https://www.gigantti.fi/                  fi  new        electronics,computers,phones,appliances                    retailer Gigantti
https://www.power.fi/                     fi  new        electronics,computers,phones,appliances                    retailer Power
https://www.jimms.fi/                     fi  new        computers,electronics,games                                retailer Jimm's
https://www.proshop.fi/                   fi  new        computers,electronics,phones                               retailer Proshop
https://www.tokmanni.fi/                  fi  new        general,home,garden,toys                                   retailer Tokmanni
https://www.prisma.fi/                    fi  new        general,home,electronics                                   retailer Prisma
https://www.k-rauta.fi/                   fi  new        diy,tools,garden,home                                      retailer K-Rauta
https://www.bauhaus.fi/                   fi  new        diy,tools,garden,home                                      retailer Bauhaus
https://www.motonet.fi/                   fi  new        auto_parts,tools,diy,bikes,outdoor                         retailer Motonet
https://www.clasohlson.com/fi/            fi  new        home,electronics,diy,tools                                 retailer Clas Ohlson
https://www.xxl.fi/                       fi  new        sports,outdoor,bikes                                       retailer XXL
https://www.intersport.fi/                fi  new        sports,outdoor,fashion                                     retailer Intersport
https://www.stockmann.com/                fi  new        fashion,beauty,home                                        retailer Stockmann
https://www.zalando.fi/                   fi  new        fashion,shoes                                              retailer Zalando
https://hinta.fi/                         fi  new        electronics,computers,appliances,general                   comparison Hinta.fi
https://www.hintaopas.fi/                 fi  new        electronics,computers,appliances,general                   comparison Hintaopas
https://www.hobbyhall.fi/                 fi  new        general,home,electronics                                   retailer Hobby Hall
https://www.karkkainen.com/               fi  new        general,home,fashion,electronics                           retailer Kärkkäinen
https://www.sotka.fi/                     fi  new        furniture,home                                             retailer Sotka
https://www.isku.fi/                      fi  new        furniture,home                                             retailer Isku
https://www.ikea.com/fi/fi/               fi  new        furniture,home                                             retailer IKEA
https://www.tori.fi/                      fi  used       general                                                    classifieds Tori
https://www.nettiauto.com/                fi  used       cars,vehicles                                              vehicles Nettiauto
https://www.oikotie.fi/                   fi  rental,service housing                                                housing Oikotie
https://www.etuovi.com/                   fi  service    housing                                                    housing Etuovi
https://www.vuokraovi.com/                fi  rental     housing                                                    housing Vuokraovi
https://www.urakkamaailma.fi/             fi  service    renovation,trades,handyman                                 service Urakkamaailma
https://www.kotisiivousvertailu.fi/       fi  service    cleaning                                                   service Kotisiivousvertailu
https://www.timma.fi/                     fi  service    beauty_services                                            service Timma
https://www.swappie.com/fi/               fi  refurb     phones                                                     refurbisher Swappie
https://www.hygglo.fi/                    fi  rental     tools,outdoor,electronics,general                          rental Hygglo
# ---------------------------------------------------------------- Sweden
https://www.elgiganten.se/                se  new        electronics,computers,phones,appliances                    retailer Elgiganten
https://www.power.se/                     se  new        electronics,computers,phones,appliances                    retailer Power
https://www.netonnet.se/                  se  new        electronics,computers,phones,appliances                    retailer NetOnNet
https://www.webhallen.com/                se  new        computers,electronics,games                                retailer Webhallen
https://www.inet.se/                      se  new        computers,electronics                                      retailer Inet
https://www.komplett.se/                  se  new        computers,electronics,phones                               retailer Komplett
https://cdon.se/                          se  new        general,electronics,home,toys                              marketplace CDON
https://www.prisjakt.nu/                  se  new        electronics,computers,appliances,general                   comparison Prisjakt
https://www.pricerunner.se/               se  new        electronics,computers,appliances,general                   comparison PriceRunner
https://www.clasohlson.com/se/            se  new        home,electronics,diy,tools                                 retailer Clas Ohlson
https://www.jula.se/                      se  new        diy,tools,garden,home                                      retailer Jula
https://www.biltema.se/                   se  new        auto_parts,tools,diy,bikes                                 retailer Biltema
https://www.bauhaus.se/                   se  new        diy,tools,garden                                           retailer Bauhaus
https://www.byggmax.se/                   se  new        diy,garden                                                 retailer Byggmax
https://www.ikea.com/se/sv/               se  new        furniture,home                                             retailer IKEA
https://www.xxl.se/                       se  new        sports,outdoor,bikes                                       retailer XXL
https://www.stadium.se/                   se  new        sports,outdoor,fashion                                     retailer Stadium
https://www.apotea.se/                    se  new        health,beauty                                              retailer Apotea
https://lyko.com/sv                       se  new        beauty                                                     retailer Lyko
https://www.boozt.com/se/sv               se  new        fashion,shoes,home                                         retailer Boozt
https://www.zalando.se/                   se  new        fashion,shoes                                              retailer Zalando
https://www.ellos.se/                     se  new        fashion,home                                               retailer Ellos
https://www.jollyroom.se/                 se  new        kids,toys                                                  retailer Jollyroom
https://www.kjell.com/se/                 se  new        electronics                                                retailer Kjell & Company
https://www.mediamarkt.se/                se  new        electronics,computers,phones,appliances                    retailer MediaMarkt
https://www.coolstuff.se/                 se  new        general,toys                                               retailer Coolstuff
https://www.ahlens.se/                    se  new        fashion,beauty,home                                        retailer Åhléns
https://www.hemnet.se/                    se  service    housing                                                    housing Hemnet
https://www.qasa.se/                      se  rental     housing                                                    housing Qasa
https://www.servicefinder.se/             se  service    trades,renovation,cleaning,moving                          service Servicefinder
https://offerta.se/                       se  service    trades,renovation,cleaning,moving                          service Offerta
https://www.hemfrid.se/                   se  service    cleaning                                                   service Hemfrid
https://www.yepstr.com/                   se  service    handyman,cleaning,childcare,gardening_services             service Yepstr
https://www.bokadirekt.se/                se  service    beauty_services,health                                     service Bokadirekt
https://www.hygglo.se/                    se  rental     tools,outdoor,electronics,general                          rental Hygglo
https://www.swappie.com/se/               se  refurb     phones                                                     refurbisher Swappie
https://www.blocket.se/                   se  used       general                                                    classifieds Blocket
# ---------------------------------------------------------------- Norway
https://www.elkjop.no/                    no  new        electronics,computers,phones,appliances                    retailer Elkjøp
https://www.power.no/                     no  new        electronics,computers,phones,appliances                    retailer Power
https://www.komplett.no/                  no  new        computers,electronics,phones                               retailer Komplett
https://www.prisjakt.no/                  no  new        electronics,computers,appliances,general                   comparison Prisjakt
https://www.kjell.com/no/                 no  new        electronics                                                retailer Kjell & Company
https://www.clasohlson.com/no/            no  new        home,electronics,diy,tools                                 retailer Clas Ohlson
https://www.xxl.no/                       no  new        sports,outdoor,bikes                                       retailer XXL
https://www.jula.no/                      no  new        diy,tools,garden                                           retailer Jula
https://www.biltema.no/                   no  new        auto_parts,tools,diy                                       retailer Biltema
https://www.ikea.com/no/no/               no  new        furniture,home                                             retailer IKEA
https://www.zalando.no/                   no  new        fashion,shoes                                              retailer Zalando
https://cdon.no/                          no  new        general,electronics,toys                                   marketplace CDON
https://www.mittanbud.no/                 no  service    trades,renovation,cleaning,moving                          service Mittanbud
# ---------------------------------------------------------------- Denmark
https://www.elgiganten.dk/                dk  new        electronics,computers,phones,appliances                    retailer Elgiganten
https://www.power.dk/                     dk  new        electronics,computers,phones,appliances                    retailer Power
https://www.proshop.dk/                   dk  new        computers,electronics,phones                               retailer Proshop
https://www.computersalg.dk/              dk  new        computers,electronics                                      retailer Computersalg
https://www.pricerunner.dk/               dk  new        electronics,computers,appliances,general                   comparison PriceRunner
https://cdon.dk/                          dk  new        general,electronics,toys                                   marketplace CDON
https://www.ikea.com/dk/da/               dk  new        furniture,home                                             retailer IKEA
https://jysk.dk/                          dk  new        furniture,home                                             retailer JYSK
https://www.bilka.dk/                     dk  new        general,home,electronics,toys                              retailer Bilka
https://www.coolshop.dk/                  dk  new        games,electronics,toys,general                             retailer Coolshop
https://www.zalando.dk/                   dk  new        fashion,shoes                                              retailer Zalando
https://www.3byggetilbud.dk/              dk  service    trades,renovation                                          service 3byggetilbud
https://happyhelper.dk/                   dk  service    cleaning                                                   service Happy Helper
https://www.helpling.dk/                  dk  service    cleaning                                                   service Helpling
https://www.boligportal.dk/               dk  rental     housing                                                    housing BoligPortal
https://www.bilbasen.dk/                  dk  used       cars,vehicles                                              vehicles Bilbasen
https://www.swappie.com/dk/               dk  refurb     phones                                                     refurbisher Swappie
# ---------------------------------------------------------------- Iceland
https://elko.is/                          is  new        electronics,computers,phones,appliances                    retailer ELKO
# ---------------------------------------------------------------- Germany
https://www.amazon.de/                    de  new,used   general,electronics,home,books,toys                        marketplace Amazon.de
https://www.otto.de/                      de  new        general,home,furniture,electronics,fashion                 marketplace OTTO
https://www.mediamarkt.de/                de  new        electronics,computers,phones,appliances                    retailer MediaMarkt
https://www.saturn.de/                    de  new        electronics,computers,phones,appliances                    retailer Saturn
https://www.cyberport.de/                 de  new        computers,electronics,phones                               retailer Cyberport
https://www.alternate.de/                 de  new        computers,electronics                                      retailer Alternate
https://www.notebooksbilliger.de/         de  new        computers,electronics,phones                               retailer notebooksbilliger
https://www.galaxus.de/                   de  new        general,electronics,home,toys                              retailer Galaxus
https://www.idealo.de/                    de  new        general,electronics,appliances,home                        comparison idealo
https://geizhals.de/                      de  new        electronics,computers,appliances                           comparison Geizhals
https://www.billiger.de/                  de  new        general,electronics                                        comparison billiger.de
https://www.guenstiger.de/                de  new        general,electronics                                        comparison guenstiger.de
https://www.check24.de/                   de  new,service general,electronics,trades                                comparison CHECK24
https://www.kaufland.de/                  de  new        general,electronics,home,garden                            marketplace Kaufland
https://www.ebay.de/                      de  new,used   general,electronics,collectibles                           marketplace eBay.de
https://www.zalando.de/                   de  new        fashion,shoes                                              retailer Zalando
https://www.aboutyou.de/                  de  new        fashion,shoes                                              retailer ABOUT YOU
https://www.bonprix.de/                   de  new        fashion,home                                               retailer bonprix
https://www.thomann.de/de/                de  new        music                                                      retailer Thomann
https://www.musicstore.de/                de  new        music                                                      retailer Music Store
https://www.conrad.de/                    de  new        electronics,tools                                          retailer Conrad
https://www.reichelt.de/                  de  new        electronics,tools                                          retailer reichelt
https://www.obi.de/                       de  new        diy,tools,garden                                           retailer OBI
https://www.hornbach.de/                  de  new        diy,tools,garden                                           retailer Hornbach
https://www.bauhaus.info/                 de  new        diy,tools,garden                                           retailer Bauhaus
https://toom.de/                          de  new        diy,tools,garden                                           retailer toom
https://www.hagebau.de/                   de  new        diy,tools,garden                                           retailer hagebau
https://www.ikea.com/de/de/               de  new        furniture,home                                             retailer IKEA
https://www.home24.de/                    de  new        furniture,home                                             retailer home24
https://www.xxxlutz.de/                   de  new        furniture,home                                             retailer XXXLutz
https://www.poco.de/                      de  new        furniture,home                                             retailer POCO
https://www.decathlon.de/                 de  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.bike-discount.de/             de  new        bikes                                                      retailer Bike-Discount
https://www.bike-components.de/           de  new        bikes                                                      retailer bike-components
https://www.fahrrad.de/                   de  new        bikes                                                      retailer fahrrad.de
https://www.rosebikes.de/                 de  new        bikes                                                      retailer ROSE Bikes
https://www.douglas.de/                   de  new        beauty                                                     retailer Douglas
https://www.dm.de/                        de  new        beauty,health                                              retailer dm
https://www.rossmann.de/                  de  new        beauty,health                                              retailer Rossmann
https://www.fressnapf.de/                 de  new        pets                                                       retailer Fressnapf
https://www.zooplus.de/                   de  new        pets                                                       retailer zooplus
https://www.lidl.de/                      de  new        general,home,garden                                        retailer Lidl
https://www.tchibo.de/                    de  new        general,home,fashion                                       retailer Tchibo
https://www.baur.de/                      de  new        general,home,fashion                                       retailer BAUR
https://www.galeria.de/                   de  new        fashion,home,beauty                                        retailer Galeria
https://www.backmarket.de/                de  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.refurbed.de/                  de  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.grover.com/de-de              de  rental     electronics,phones,computers                               rental Grover
https://www.fainin.com/                   de  rental     tools,outdoor,electronics,general                          rental fainin
https://www.helpling.de/                  de  service    cleaning                                                   service Helpling
https://www.my-hammer.de/                 de  service    trades,renovation,handyman                                 service MyHammer
https://www.betreut.de/                   de  service    childcare,eldercare,petcare,cleaning                       service Betreut
https://www.aroundhome.de/                de  service    renovation,trades                                          service Aroundhome
https://www.blauarbeit.de/                de  service    handyman,trades,moving                                     service Blauarbeit
https://www.treatwell.de/                 de  service    beauty_services                                            service Treatwell
https://www.yoopies.de/                   de  service    childcare,eldercare,petcare                                service Yoopies
https://www.immobilienscout24.de/         de  rental,service housing                                                housing ImmoScout24
https://www.immowelt.de/                  de  rental,service housing                                                housing immowelt
https://www.wg-gesucht.de/                de  rental     housing                                                    housing WG-Gesucht
https://www.mobile.de/                    de  used       cars,vehicles                                              vehicles mobile.de
https://www.autoscout24.de/               de  used       cars,vehicles                                              vehicles AutoScout24
# ---------------------------------------------------------------- Austria
https://geizhals.at/                      at  new        electronics,computers,appliances                           comparison Geizhals
https://www.mediamarkt.at/                at  new        electronics,computers,phones,appliances                    retailer MediaMarkt
https://www.cyberport.at/                 at  new        computers,electronics,phones                               retailer Cyberport
https://www.universal.at/                 at  new        general,home,fashion                                       retailer Universal
https://www.otto.at/                      at  new        general,home,fashion                                       retailer OTTO Austria
https://www.xxxlutz.at/                   at  new        furniture,home                                             retailer XXXLutz
https://www.ikea.com/at/de/               at  new        furniture,home                                             retailer IKEA
https://www.hartlauer.at/                 at  new        electronics,cameras,phones                                 retailer Hartlauer
https://www.bauhaus.at/                   at  new        diy,tools,garden                                           retailer Bauhaus
https://www.obi.at/                       at  new        diy,tools,garden                                           retailer OBI
https://www.hornbach.at/                  at  new        diy,tools,garden                                           retailer Hornbach
https://www.ebay.at/                      at  new,used   general,electronics                                        marketplace eBay.at
https://www.refurbed.at/                  at  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.backmarket.at/                at  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.myhammer.at/                  at  service    trades,renovation,handyman                                 service MyHammer
https://www.helpling.at/                  at  service    cleaning                                                   service Helpling
https://www.betreut.at/                   at  service    childcare,eldercare,petcare                                service Betreut
https://www.herold.at/                    at  service    trades,cleaning,handyman                                   service Herold
https://www.willhaben.at/                 at  used,rental general,housing,cars                                      classifieds willhaben
# ---------------------------------------------------------------- Switzerland
https://www.galaxus.ch/                   ch  new        general,electronics,home,toys                              retailer Galaxus
https://www.digitec.ch/                   ch  new        electronics,computers,phones                               retailer Digitec
https://www.brack.ch/                     ch  new        general,electronics,home                                   retailer BRACK
https://www.interdiscount.ch/             ch  new        electronics,computers,phones,appliances                    retailer Interdiscount
https://www.mediamarkt.ch/                ch  new        electronics,computers,phones,appliances                    retailer MediaMarkt
https://www.fust.ch/                      ch  new        appliances,electronics                                     retailer Fust
https://www.microspot.ch/                 ch  new        electronics,computers                                      retailer microspot
https://www.toppreise.ch/                 ch  new        electronics,computers,appliances                           comparison Toppreise
https://www.manor.ch/                     ch  new        fashion,home,beauty                                        retailer Manor
https://www.zalando.ch/                   ch  new        fashion,shoes                                              retailer Zalando
https://www.ikea.com/ch/de/               ch  new        furniture,home                                             retailer IKEA
https://www.jumbo.ch/                     ch  new        diy,tools,garden                                           retailer Jumbo
https://www.conrad.ch/                    ch  new        electronics,tools                                          retailer Conrad
https://www.pfister.ch/                   ch  new        furniture,home                                             retailer Pfister
https://www.decathlon.ch/                 ch  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.batmaid.ch/                   ch  service    cleaning                                                   service Batmaid
https://www.ofri.ch/                      ch  service    trades,renovation                                          service Ofri
https://www.renovero.ch/                  ch  service    trades,renovation                                          service Renovero
https://www.helpling.ch/                  ch  service    cleaning                                                   service Helpling
https://www.homegate.ch/                  ch  rental,service housing                                                housing Homegate
https://www.comparis.ch/                  ch  new,service general,housing,cars                                      comparison Comparis
# ---------------------------------------------------------------- Netherlands
https://www.bol.com/nl/nl/                nl,be new,used general,electronics,books,home,toys                        marketplace bol
https://www.coolblue.nl/                  nl  new        electronics,computers,phones,appliances                    retailer Coolblue
https://www.mediamarkt.nl/                nl  new        electronics,computers,phones,appliances                    retailer MediaMarkt
https://www.wehkamp.nl/                   nl  new        general,fashion,home,electronics                           retailer Wehkamp
https://www.amazon.nl/                    nl  new        general,electronics,home,books                             marketplace Amazon.nl
https://www.alternate.nl/                 nl  new        computers,electronics                                      retailer Alternate
https://www.megekko.nl/                   nl  new        computers,electronics                                      retailer Megekko
https://azerty.nl/                        nl  new        computers,electronics                                      retailer Azerty
https://tweakers.net/                     nl  new,used   electronics,computers,phones                               comparison Tweakers Pricewatch
https://www.kieskeurig.nl/                nl  new        electronics,appliances,general                             comparison Kieskeurig
https://www.beslist.nl/                   nl  new        general,electronics,home                                   comparison Beslist
https://www.blokker.nl/                   nl  new        home,appliances                                            retailer Blokker
https://www.hema.nl/                      nl  new        home,general                                               retailer HEMA
https://www.praxis.nl/                    nl  new        diy,tools,garden                                           retailer Praxis
https://www.gamma.nl/                     nl  new        diy,tools,garden                                           retailer GAMMA
https://www.karwei.nl/                    nl  new        diy,tools,garden                                           retailer Karwei
https://www.ikea.com/nl/nl/               nl  new        furniture,home                                             retailer IKEA
https://www.leenbakker.nl/                nl  new        furniture,home                                             retailer Leen Bakker
https://www.kwantum.nl/                   nl  new        furniture,home                                             retailer Kwantum
https://www.decathlon.nl/                 nl  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.debijenkorf.nl/               nl  new        fashion,beauty,home                                        retailer de Bijenkorf
https://www.zalando.nl/                   nl  new        fashion,shoes                                              retailer Zalando
https://www.forza-refurbished.nl/         nl  refurb     phones,computers                                           refurbisher Forza Refurbished
https://www.backmarket.nl/                nl  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.refurbed.nl/                  nl  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.swappie.com/nl/               nl  refurb     phones                                                     refurbisher Swappie
https://www.peerby.com/                   nl  rental     tools,outdoor,general                                      rental Peerby
https://www.werkspot.nl/                  nl  service    trades,renovation,handyman                                 service Werkspot
https://www.helpling.nl/                  nl  service    cleaning                                                   service Helpling
https://trustoo.nl/                       nl  service    trades,cleaning,moving,renovation                          service Trustoo
https://www.homedeal.nl/                  nl  service    renovation,trades                                          service Homedeal
https://www.zoofy.nl/                     nl  service    trades,handyman                                            service Zoofy
https://www.offerteadviseur.nl/           nl  service    renovation,trades,moving                                   service Offerteadviseur
https://www.treatwell.nl/                 nl  service    beauty_services                                            service Treatwell
https://www.charlycares.com/              nl  service    childcare                                                  service Charly Cares
https://www.sitly.nl/                     nl  service    childcare                                                  service Sitly
https://www.funda.nl/                     nl  service    housing                                                    housing funda
https://www.pararius.nl/                  nl  rental     housing                                                    housing Pararius
https://kamernet.nl/                      nl  rental     housing                                                    housing Kamernet
# ---------------------------------------------------------------- Belgium / Luxembourg
https://www.coolblue.be/nl/               be  new        electronics,computers,phones,appliances                    retailer Coolblue
https://www.mediamarkt.be/nl/             be  new        electronics,computers,phones,appliances                    retailer MediaMarkt
https://www.vandenborre.be/nl/            be  new        electronics,appliances                                     retailer Vanden Borre
https://www.krefel.be/nl/                 be  new        electronics,appliances                                     retailer Krëfel
https://www.fnac.be/                      be  new        electronics,books,media,games                              retailer Fnac
https://www.standaardboekhandel.be/       be  new        books                                                      retailer Standaard Boekhandel
https://www.ikea.com/be/nl/               be  new        furniture,home                                             retailer IKEA
https://www.brico.be/nl/                  be  new        diy,tools,garden                                           retailer Brico
https://www.gamma.be/nl/                  be  new        diy,tools,garden                                           retailer GAMMA
https://www.hubo.be/nl/                   be  new        diy,tools,garden                                           retailer Hubo
https://www.decathlon.be/nl/              be  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.2ememain.be/                  be  used       general                                                    classifieds 2ememain
https://www.backmarket.be/                be  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.immoweb.be/                   be  rental,service housing                                                housing Immoweb
https://www.zimmo.be/                     be  rental,service housing                                                housing Zimmo
https://trustoo.be/                       be  service    trades,cleaning,moving,renovation                          service Trustoo
https://www.starofservice.be/             be  service    trades,cleaning,handyman,tutoring                          service StarOfService
https://www.bobex.be/                     be  service    renovation,trades,moving                                   service Bobex
https://www.helpling.be/                  be  service    cleaning                                                   service Helpling
https://www.treatwell.be/                 be  service    beauty_services                                            service Treatwell
https://www.athome.lu/                    lu  rental,service housing                                                housing atHome
https://www.editus.lu/                    lu  service    trades,cleaning,handyman                                   service Editus
# ---------------------------------------------------------------- France
https://www.fnac.com/                     fr  new        electronics,books,media,games,computers                    retailer Fnac
https://www.darty.com/                    fr  new        electronics,appliances,computers                           retailer Darty
https://www.boulanger.com/                fr  new        electronics,appliances,computers                           retailer Boulanger
https://www.amazon.fr/                    fr  new,used   general,electronics,home,books                             marketplace Amazon.fr
https://www.cdiscount.com/                fr  new,used   general,electronics,home,appliances        marketplace Cdiscount
https://www.ldlc.com/                     fr  new        computers,electronics                                      retailer LDLC
https://www.rueducommerce.fr/             fr  new        computers,electronics,home                                 marketplace Rue du Commerce
https://www.materiel.net/                 fr  new        computers,electronics                                      retailer Materiel.net
https://fr.shopping.rakuten.com/          fr  new,used   general,electronics,books,media                            marketplace Rakuten France
https://www.leroymerlin.fr/               fr  new        diy,tools,garden,home                                      retailer Leroy Merlin
https://www.castorama.fr/                 fr  new        diy,tools,garden,home                                      retailer Castorama
https://www.bricodepot.fr/                fr  new        diy,tools,garden                                           retailer Brico Dépôt
https://www.ikea.com/fr/fr/               fr  new        furniture,home                                             retailer IKEA
https://www.conforama.fr/                 fr  new        furniture,home,appliances                                  retailer Conforama
https://www.but.fr/                       fr  new        furniture,home,appliances                                  retailer BUT
https://www.maisonsdumonde.com/FR/fr      fr  new        furniture,home                                             retailer Maisons du Monde
https://www.decathlon.fr/                 fr  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.intersport.fr/                fr  new        sports,outdoor,fashion                                     retailer Intersport
https://www.carrefour.fr/                 fr  new        general,home,electronics                                   retailer Carrefour
https://www.auchan.fr/                    fr  new        general,home,electronics                                   retailer Auchan
https://www.laredoute.fr/                 fr  new        fashion,home,furniture                                     retailer La Redoute
https://www.zalando.fr/                   fr  new        fashion,shoes                                              retailer Zalando
https://www.kiabi.com/                    fr  new        fashion,kids                                               retailer Kiabi
https://www.sephora.fr/                   fr  new        beauty                                                     retailer Sephora
https://www.idealo.fr/                    fr  new        general,electronics,appliances                             comparison idealo
https://ledenicheur.fr/                   fr  new        electronics,computers,appliances                           comparison LeDénicheur
https://www.ebay.fr/                      fr  new,used   general,electronics,collectibles                           marketplace eBay.fr
https://www.backmarket.fr/                fr  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.refurbed.fr/                  fr  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.largo.fr/                     fr  refurb     phones                                                     refurbisher Largo
https://www.helpling.fr/                  fr  service    cleaning                                                   service Helpling
https://yoojo.fr/                         fr  service    handyman,cleaning,moving,gardening_services                service Yoojo
https://www.starofservice.fr/             fr  service    trades,cleaning,handyman,tutoring                          service StarOfService
https://www.wecasa.fr/                    fr  service    beauty_services,cleaning                                   service Wecasa
https://www.pagesjaunes.fr/               fr  service    trades,cleaning,handyman                                   service PagesJaunes
https://yoopies.fr/                       fr  service    childcare,eldercare,petcare,cleaning                       service Yoopies
https://www.nounou-top.fr/                fr  service    childcare                                                  service Nounou Top
https://www.superprof.fr/                 fr  service    tutoring                                                   service Superprof
https://www.treatwell.fr/                 fr  service    beauty_services                                            service Treatwell
https://www.planity.com/                  fr  service    beauty_services                                            service Planity
https://www.travaux.com/                  fr  service    renovation,trades                                          service Travaux.com
https://www.habitatpresto.com/            fr  service    renovation,trades                                          service Habitatpresto
https://www.allovoisins.com/              fr  service,rental handyman,tools,general                                 service AlloVoisins
https://www.seloger.com/                  fr  rental,service housing                                                housing SeLoger
https://www.pap.fr/                       fr  rental,service housing                                                housing PAP
https://www.lacentrale.fr/                fr  used       cars,vehicles                                              vehicles La Centrale
# ---------------------------------------------------------------- Spain
https://www.amazon.es/                    es  new,used   general,electronics,home,books                             marketplace Amazon.es
https://www.elcorteingles.es/             es  new        general,fashion,electronics,home                           retailer El Corte Inglés
https://www.mediamarkt.es/                es  new        electronics,computers,phones,appliances                    retailer MediaMarkt
https://www.pccomponentes.com/            es  new        computers,electronics,phones                               retailer PcComponentes
https://www.fnac.es/                      es  new        electronics,books,media                                    retailer Fnac
https://www.carrefour.es/                 es  new        general,home,electronics                                   retailer Carrefour
https://www.worten.es/                    es  new        electronics,appliances,computers                           retailer Worten
https://www.leroymerlin.es/               es  new        diy,tools,garden,home                                      retailer Leroy Merlin
https://www.ikea.com/es/es/               es  new        furniture,home                                             retailer IKEA
https://www.decathlon.es/                 es  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.zalando.es/                   es  new        fashion,shoes                                              retailer Zalando
https://www.idealo.es/                    es  new        general,electronics,appliances                             comparison idealo
https://www.ebay.es/                      es  new,used   general,electronics                                        marketplace eBay.es
https://www.backmarket.es/                es  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.habitissimo.es/               es  service    renovation,trades                                          service Habitissimo
https://www.cronoshare.com/               es  service    trades,cleaning,handyman,moving                            service Cronoshare
https://www.starofservice.es/             es  service    trades,cleaning,handyman,tutoring                          service StarOfService
https://clintu.es/                        es  service    cleaning                                                   service Clintu
https://www.yoopies.es/                   es  service    childcare,eldercare,petcare                                service Yoopies
https://www.superprof.es/                 es  service    tutoring                                                   service Superprof
https://www.treatwell.es/                 es  service    beauty_services                                            service Treatwell
https://www.idealista.com/                es  rental,service housing                                                housing idealista
https://www.fotocasa.es/                  es  rental,service housing                                                housing Fotocasa
https://www.coches.net/                   es  used       cars,vehicles                                              vehicles coches.net
# ---------------------------------------------------------------- Italy
https://www.amazon.it/                    it  new,used   general,electronics,home,books                             marketplace Amazon.it
https://www.mediaworld.it/                it  new        electronics,computers,phones,appliances                    retailer MediaWorld
https://www.unieuro.it/                   it  new        electronics,computers,phones,appliances                    retailer Unieuro
https://www.euronics.it/                  it  new        electronics,appliances                                     retailer Euronics
https://www.eprice.it/                    it  new        electronics,appliances                                     marketplace ePRICE
https://www.trovaprezzi.it/               it  new        general,electronics,appliances                             comparison Trovaprezzi
https://www.idealo.it/                    it  new        general,electronics,appliances                             comparison idealo
https://www.ikea.com/it/it/               it  new        furniture,home                                             retailer IKEA
https://www.leroymerlin.it/               it  new        diy,tools,garden,home                                      retailer Leroy Merlin
https://www.decathlon.it/                 it  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.zalando.it/                   it  new        fashion,shoes                                              retailer Zalando
https://www.yoox.com/it                   it  new        fashion,luxury                                             retailer YOOX
https://www.ebay.it/                      it  new,used   general,electronics,collectibles                           marketplace eBay.it
https://www.backmarket.it/                it  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.refurbed.it/                  it  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.helpling.it/                  it  service    cleaning                                                   service Helpling
https://www.prontopro.it/                 it  service    trades,cleaning,handyman,tutoring                          service ProntoPro
https://www.instapro.it/                  it  service    renovation,trades                                          service Instapro
https://www.starofservice.it/             it  service    trades,cleaning,handyman                                   service StarOfService
https://www.superprof.it/                 it  service    tutoring                                                   service Superprof
https://www.treatwell.it/                 it  service    beauty_services                                            service Treatwell
https://www.immobiliare.it/               it  rental,service housing                                                housing Immobiliare.it
https://www.idealista.it/                 it  rental,service housing                                                housing idealista
https://www.autoscout24.it/               it  used       cars,vehicles                                              vehicles AutoScout24
# ---------------------------------------------------------------- Portugal
https://www.worten.pt/                    pt  new        electronics,appliances,computers                           retailer Worten
https://www.fnac.pt/                      pt  new        electronics,books,media                                    retailer Fnac
https://www.radiopopular.pt/              pt  new        electronics,appliances                                     retailer Radio Popular
https://www.kuantokusta.pt/               pt  new        general,electronics                                        comparison KuantoKusta
https://www.pcdiga.com/                   pt  new        computers,electronics                                      retailer PCDIGA
https://www.globaldata.pt/                pt  new        computers,electronics                                      retailer Globaldata
https://www.ikea.com/pt/pt/               pt  new        furniture,home                                             retailer IKEA
https://www.leroymerlin.pt/               pt  new        diy,tools,garden,home                                      retailer Leroy Merlin
https://www.decathlon.pt/                 pt  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.backmarket.pt/                pt  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.swappie.com/pt/               pt  refurb     phones                                                     refurbisher Swappie
https://www.fixando.pt/                   pt  service    trades,cleaning,handyman                                   service Fixando
https://www.zaask.pt/                     pt  service    trades,cleaning,handyman,renovation                        service Zaask
https://www.starofservice.pt/             pt  service    trades,cleaning,handyman                                   service StarOfService
https://www.idealista.pt/                 pt  rental,service housing                                                housing idealista
https://www.imovirtual.com/               pt  rental,service housing                                                housing Imovirtual
# ---------------------------------------------------------------- Ireland
https://www.harveynorman.ie/              ie  new        electronics,appliances,furniture,computers                 retailer Harvey Norman
https://www.currys.ie/                    ie  new        electronics,appliances,computers                           retailer Currys
https://www.powercity.ie/                 ie  new        electronics,appliances                                     retailer PowerCity
https://www.did.ie/                       ie  new        electronics,appliances                                     retailer DID Electrical
https://www.smythstoys.com/ie/en-ie/      ie  new        toys,kids,games                                            retailer Smyths
https://www.littlewoodsireland.ie/        ie  new        general,fashion,home                                       retailer Littlewoods
https://www.daft.ie/                      ie  rental,service housing                                                housing Daft
https://www.helpling.ie/                  ie  service    cleaning                                                   service Helpling
https://www.tradesmen.ie/                 ie  service    trades,handyman                                            service Tradesmen.ie
https://www.backmarket.ie/                ie  refurb     phones,computers,electronics                               refurbisher Back Market
# ---------------------------------------------------------------- United Kingdom
https://www.amazon.co.uk/                 gb  new,used   general,electronics,home,books                             marketplace Amazon.co.uk
https://www.argos.co.uk/                  gb  new        general,electronics,home,toys                              retailer Argos
https://www.currys.co.uk/                 gb  new        electronics,appliances,computers                           retailer Currys
https://www.johnlewis.com/                gb  new        general,home,electronics,fashion                           retailer John Lewis
https://ao.com/                           gb  new        appliances,electronics                                     retailer AO
https://www.very.co.uk/                   gb  new        general,fashion,electronics,home                           retailer Very
https://www.scan.co.uk/                   gb  new        computers,electronics                                      retailer Scan
https://www.overclockers.co.uk/           gb  new        computers,electronics                                      retailer Overclockers
https://www.ebuyer.com/                   gb  new        computers,electronics                                      retailer Ebuyer
https://www.richersounds.com/             gb  new        electronics                                                retailer Richer Sounds
https://www.screwfix.com/                 gb  new        tools,diy                                                  retailer Screwfix
https://www.toolstation.com/              gb  new        tools,diy                                                  retailer Toolstation
https://www.wickes.co.uk/                 gb  new        diy,tools,garden                                           retailer Wickes
https://www.diy.com/                      gb  new        diy,tools,garden,home                                      retailer B&Q
https://www.ikea.com/gb/en/               gb  new        furniture,home                                             retailer IKEA
https://www.dunelm.com/                   gb  new        home,furniture                                             retailer Dunelm
https://www.wayfair.co.uk/                gb  new        furniture,home                                             retailer Wayfair
https://www.decathlon.co.uk/              gb  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.sportsdirect.com/             gb  new        sports,fashion                                             retailer Sports Direct
https://www.halfords.com/                 gb  new        bikes,auto_parts                                           retailer Halfords
https://www.boots.com/                    gb  new        beauty,health                                              retailer Boots
https://www.superdrug.com/                gb  new        beauty,health                                              retailer Superdrug
https://www.asos.com/                     gb  new        fashion,shoes                                              retailer ASOS
https://www.next.co.uk/                   gb  new        fashion,home                                               retailer Next
https://www.marksandspencer.com/          gb  new        fashion,home,food                                          retailer M&S
https://www.pricerunner.com/              gb  new        electronics,appliances,general                             comparison PriceRunner
https://pricespy.co.uk/                   gb  new        electronics,computers,appliances                           comparison PriceSpy
https://www.idealo.co.uk/                 gb  new        general,electronics                                        comparison idealo
https://www.ebay.co.uk/                   gb  new,used   general,electronics,collectibles                           marketplace eBay.co.uk
https://www.backmarket.co.uk/             gb  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.raylo.com/                    gb  rental     phones,computers                                           rental Raylo
https://www.checkatrade.com/              gb  service    trades,handyman,renovation                                 service Checkatrade
https://www.mybuilder.com/                gb  service    trades,renovation                                          service MyBuilder
https://www.ratedpeople.com/              gb  service    trades,renovation                                          service Rated People
https://www.bark.com/en/gb/               gb,ie service  trades,cleaning,tutoring,handyman                          service Bark
https://www.trustatrader.com/             gb  service    trades,handyman                                            service TrustATrader
https://www.yell.com/                     gb  service    trades,cleaning,handyman                                   service Yell
https://www.treatwell.co.uk/              gb  service    beauty_services                                            service Treatwell
https://www.childcare.co.uk/              gb  service    childcare,petcare,cleaning,tutoring                        service Childcare.co.uk
https://www.taskrabbit.co.uk/             gb  service    handyman,cleaning,moving                                   service Taskrabbit
https://www.superprof.co.uk/              gb  service    tutoring                                                   service Superprof
https://www.rover.com/uk/                 gb  service    petcare                                                    service Rover
https://www.rightmove.co.uk/              gb  rental,service housing                                                housing Rightmove
https://www.zoopla.co.uk/                 gb  rental,service housing                                                housing Zoopla
https://www.spareroom.co.uk/              gb  rental     housing                                                    housing SpareRoom
https://www.autotrader.co.uk/             gb  used       cars,vehicles                                              vehicles Auto Trader
# ---------------------------------------------------------------- Poland
https://allegro.pl/                       pl  new,used   general,electronics,home,fashion                           marketplace Allegro
https://www.ceneo.pl/                     pl  new        general,electronics,appliances                             comparison Ceneo
https://www.x-kom.pl/                     pl  new        computers,electronics,phones                               retailer x-kom
https://www.mediaexpert.pl/               pl  new        electronics,appliances,computers                           retailer Media Expert
https://www.euro.com.pl/                  pl  new        electronics,appliances,computers                           retailer RTV Euro AGD
https://www.morele.net/                   pl  new        computers,electronics                                      retailer Morele
https://www.komputronik.pl/               pl  new        computers,electronics                                      retailer Komputronik
https://www.mediamarkt.pl/                pl  new        electronics,appliances,computers                           retailer MediaMarkt
https://www.empik.com/                    pl  new        books,media,electronics,toys                               retailer Empik
https://www.ikea.com/pl/pl/               pl  new        furniture,home                                             retailer IKEA
https://www.castorama.pl/                 pl  new        diy,tools,garden                                           retailer Castorama
https://www.leroymerlin.pl/               pl  new        diy,tools,garden                                           retailer Leroy Merlin
https://www.obi.pl/                       pl  new        diy,tools,garden                                           retailer OBI
https://www.decathlon.pl/                 pl  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.zalando.pl/                   pl  new        fashion,shoes                                              retailer Zalando
https://modivo.pl/                        pl  new        fashion,shoes                                              retailer Modivo
https://www.skapiec.pl/                   pl  new        general,electronics                                        comparison Skąpiec
https://www.refurbed.pl/                  pl  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.oferteo.pl/                   pl  service    trades,renovation,cleaning                                 service Oferteo
https://fixly.pl/                         pl  service    trades,handyman,cleaning                                   service Fixly
https://booksy.com/pl-pl/                 pl  service    beauty_services                                            service Booksy
https://www.otodom.pl/                    pl  rental,service housing                                                housing Otodom
https://www.otomoto.pl/                   pl  used       cars,vehicles                                              vehicles Otomoto
# ---------------------------------------------------------------- Czechia / Slovakia
https://www.alza.cz/                      cz  new        electronics,computers,phones,appliances,general            retailer Alza
https://www.czc.cz/                       cz  new        computers,electronics                                      retailer CZC
https://www.datart.cz/                    cz  new        electronics,appliances                                     retailer Datart
https://www.heureka.cz/                   cz  new        general,electronics,appliances                             comparison Heureka
https://www.zbozi.cz/                     cz  new        general,electronics                                        comparison Zboží.cz
https://www.ikea.com/cz/cs/               cz  new        furniture,home                                             retailer IKEA
https://www.hornbach.cz/                  cz  new        diy,tools,garden                                           retailer Hornbach
https://www.decathlon.cz/                 cz  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.notino.cz/                    cz  new        beauty                                                     retailer Notino
https://www.kasa.cz/                      cz  new        electronics,appliances                                     retailer Kasa
https://www.refurbed.cz/                  cz  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.nejremeslnici.cz/             cz  service    trades,renovation,handyman                                 service Nejřemeslníci
https://www.poptavej.cz/                  cz  service    trades,renovation                                          service Poptávej
https://www.sreality.cz/                  cz  rental,service housing                                                housing Sreality
https://www.alza.sk/                      sk  new        electronics,computers,phones,appliances                    retailer Alza
https://www.nay.sk/                       sk  new        electronics,appliances                                     retailer NAY
https://www.heureka.sk/                   sk  new        general,electronics                                        comparison Heureka
https://www.pricemania.sk/                sk  new        general,electronics                                        comparison Pricemania
https://www.datart.sk/                    sk  new        electronics,appliances                                     retailer Datart
https://www.nehnutelnosti.sk/             sk  rental,service housing                                                housing Nehnuteľnosti
# ---------------------------------------------------------------- Hungary
https://www.emag.hu/                      hu  new        general,electronics,appliances                             marketplace eMAG
https://www.mediamarkt.hu/                hu  new        electronics,appliances                                     retailer MediaMarkt
https://edigital.hu/                      hu  new        electronics,computers                                      retailer eDigital
https://www.alza.hu/                      hu  new        electronics,computers                                      retailer Alza
https://www.arukereso.hu/                 hu  new        general,electronics,appliances                             comparison Árukereső
https://www.argep.hu/                     hu  new        electronics                                                comparison Árgép
https://www.ikea.com/hu/hu/               hu  new        furniture,home                                             retailer IKEA
https://www.praktiker.hu/                 hu  new        diy,tools,garden                                           retailer Praktiker
https://www.obi.hu/                       hu  new        diy,tools,garden                                           retailer OBI
https://www.decathlon.hu/                 hu  new        sports,outdoor,bikes                                       retailer Decathlon
https://ingatlan.com/                     hu  rental,service housing                                                housing ingatlan.com
# ---------------------------------------------------------------- Romania / Bulgaria
https://www.emag.ro/                      ro  new        general,electronics,appliances                             marketplace eMAG
https://altex.ro/                         ro  new        electronics,appliances                                     retailer Altex
https://www.flanco.ro/                    ro  new        electronics,appliances                                     retailer Flanco
https://www.cel.ro/                       ro  new        electronics,appliances                                     retailer CEL.ro
https://www.pcgarage.ro/                  ro  new        computers,electronics                                      retailer PC Garage
https://www.evomag.ro/                    ro  new        computers,electronics                                      retailer evoMAG
https://www.compari.ro/                   ro  new        general,electronics                                        comparison Compari
https://www.dedeman.ro/                   ro  new        diy,tools,garden,home                                      retailer Dedeman
https://www.ikea.com/ro/ro/               ro  new        furniture,home                                             retailer IKEA
https://www.decathlon.ro/                 ro  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.storia.ro/                    ro  rental,service housing                                                housing Storia
https://www.imobiliare.ro/                ro  rental,service housing                                                housing Imobiliare.ro
https://www.autovit.ro/                   ro  used       cars,vehicles                                              vehicles Autovit
https://www.emag.bg/                      bg  new        general,electronics,appliances                             marketplace eMAG
https://www.technopolis.bg/               bg  new        electronics,appliances                                     retailer Technopolis
https://www.technomarket.bg/              bg  new        electronics,appliances                                     retailer Technomarket
https://www.ozone.bg/                     bg  new        games,books,electronics,toys                               retailer Ozone
https://www.pazaruvaj.com/                bg  new        general,electronics                                        comparison Pazaruvaj
https://www.imot.bg/                      bg  rental,service housing                                                housing imot.bg
https://www.mobile.bg/                    bg  used       cars,vehicles                                              vehicles mobile.bg
# ---------------------------------------------------------------- Greece / Cyprus / Malta
https://www.skroutz.gr/                   gr,cy new      general,electronics,appliances,home                        comparison Skroutz
https://www.public.gr/                    gr  new        electronics,books,games                                    retailer Public
https://www.kotsovolos.gr/                gr  new        electronics,appliances                                     retailer Kotsovolos
https://www.plaisio.gr/                   gr  new        computers,electronics                                      retailer Plaisio
https://www.bestprice.gr/                 gr  new        general,electronics                                        comparison BestPrice
https://www.e-shop.gr/                    gr  new        electronics,computers                                      retailer e-shop.gr
https://www.ikea.gr/                      gr  new        furniture,home                                             retailer IKEA
https://www.spitogatos.gr/                gr  rental,service housing                                                housing Spitogatos
https://www.car.gr/                       gr  used       cars,vehicles                                              vehicles Car.gr
https://www.stephanis.com.cy/             cy  new        electronics,appliances                                     retailer Stephanis
https://www.scanmalta.com/                mt  new        electronics,computers                                      retailer Scan Malta
# ---------------------------------------------------------------- Croatia / Slovenia
https://www.emmezeta.hr/                  hr  new        furniture,home,appliances                                  retailer Emmezeta
https://www.links.hr/                     hr  new        computers,electronics                                      retailer Links
https://www.sancta-domenica.hr/           hr  new        electronics,appliances                                     retailer Sancta Domenica
https://www.nabava.net/                   hr  new        general,electronics                                        comparison Nabava.net
https://www.mimovrste.com/                si  new        general,electronics                                        retailer Mimovrste
https://www.bigbang.si/                   si  new        electronics,appliances                                     retailer Big Bang
https://www.ceneje.si/                    si  new        general,electronics                                        comparison Ceneje
https://www.merkur.si/                    si  new        diy,tools,garden                                           retailer Merkur
https://www.nepremicnine.net/             si  rental,service housing                                                housing Nepremičnine.net
# ---------------------------------------------------------------- Baltics
https://www.hinnavaatlus.ee/              ee  new        electronics,computers                                      comparison Hinnavaatlus
https://kaup24.ee/                        ee  new        general,electronics,home                                   marketplace Kaup24
https://www.euronics.ee/                  ee  new        electronics,appliances                                     retailer Euronics
https://www.klick.ee/                     ee  new        electronics,phones                                         retailer Klick
https://arvutitark.ee/                    ee  new        computers,electronics                                      retailer Arvutitark
https://www.kv.ee/                        ee  rental,service housing                                                housing kv.ee
https://www.auto24.ee/                    ee  used       cars,vehicles                                              vehicles auto24
https://220.lv/                           lv  new        general,electronics,home                                   marketplace 220.lv
https://www.rdveikals.lv/                 lv  new        electronics,appliances                                     retailer RD Electronics
https://www.salidzini.lv/                 lv  new        general,electronics                                        comparison Salidzini
https://pigu.lt/                          lt  new        general,electronics,home                                   marketplace Pigu
https://www.varle.lt/                     lt  new        general,electronics                                        retailer Varle
https://www.kaina24.lt/                   lt  new        general,electronics                                        comparison Kaina24
https://www.topocentras.lt/               lt  new        electronics,appliances                                     retailer Topocentras
https://www.aruodas.lt/                   lt  rental,service housing                                                housing Aruodas
https://autoplius.lt/                     lt  used       cars,vehicles                                              vehicles Autoplius
# ---------------------------------------------------------------- pan-European refurb / rental / services
https://www.swappie.com/en/               eu  refurb     phones                                                     refurbisher Swappie
https://www.grover.com/nl-en              nl  rental     electronics,phones,computers                               rental Grover
https://www.grover.com/at-de              at  rental     electronics,phones,computers                               rental Grover
https://www.grover.com/es-es              es  rental     electronics,phones,computers                               rental Grover
https://www.fresha.com/                   eu  service    beauty_services                                            service Fresha
https://www.rover.com/fr/                 fr  service    petcare                                                    service Rover
https://www.rover.com/de/                 de  service    petcare                                                    service Rover
https://www.rover.com/es/                 es  service    petcare                                                    service Rover
https://www.rover.com/nl/                 nl  service    petcare                                                    service Rover
https://www.taskrabbit.fr/                fr  service    handyman,cleaning,moving                                   service Taskrabbit
https://www.taskrabbit.de/                de  service    handyman,cleaning,moving                                   service Taskrabbit
https://www.taskrabbit.es/                es  service    handyman,cleaning,moving                                   service Taskrabbit
https://www.superprof.de/                 de  service    tutoring                                                   service Superprof
https://booksy.com/en-gb/                 gb  service    beauty_services                                            service Booksy
https://www.zalando.at/                   at  new        fashion,shoes                                              retailer Zalando
https://www.zalando.be/                   be  new        fashion,shoes                                              retailer Zalando
https://www.zalando.co.uk/                gb  new        fashion,shoes                                              retailer Zalando
https://www.zalando.ie/                   ie  new        fashion,shoes                                              retailer Zalando
https://www.zalando.cz/                   cz  new        fashion,shoes                                              retailer Zalando
https://www.decathlon.at/                 at  new        sports,outdoor,bikes                                       retailer Decathlon
https://www.thomann.co.uk/                gb  new        music                                                      retailer Thomann
https://www.ikea.com/ie/en/               ie  new        furniture,home                                             retailer IKEA
https://www.ikea.com/sk/sk/               sk  new        furniture,home                                             retailer IKEA
https://www.ikea.com/hr/hr/               hr  new        furniture,home                                             retailer IKEA
https://www.ikea.com/si/sl/               si  new        furniture,home                                             retailer IKEA
https://www.ikea.lv/                      lv  new        furniture,home                                             retailer IKEA
https://www.ikea.lt/                      lt  new        furniture,home                                             retailer IKEA
https://www.ikea.ee/                      ee  new        furniture,home                                             retailer IKEA
https://www.mediamarkt.pt/                pt  new        electronics,appliances                                     retailer MediaMarkt
https://www.mediamarkt.it/                it  new        electronics,appliances                                     retailer MediaMarkt
https://www.ebay.ie/                      ie  new,used   general,electronics                                        marketplace eBay.ie
https://www.ebay.pl/                      pl  new,used   general,electronics                                        marketplace eBay.pl
https://www.ebay.nl/                      nl  new,used   general,electronics                                        marketplace eBay.nl
https://www.ebay.ch/                      ch  new,used   general,electronics                                        marketplace eBay.ch
https://www.backmarket.se/                se  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.backmarket.fi/                fi  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.backmarket.gr/                gr  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.backmarket.sk/                sk  refurb     phones,computers,electronics                               refurbisher Back Market
https://www.refurbed.ie/                  ie  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.refurbed.se/                  se  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.refurbed.fi/                  fi  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.refurbed.dk/                  dk  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.refurbed.be/                  be  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.refurbed.ch/                  ch  refurb     phones,computers,electronics                               refurbisher refurbed
https://www.vinted.fi/                    fi  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.de/                    de  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.fr/                    fr  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.nl/                    nl  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.se/                    se  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.pl/                    pl  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.es/                    es  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.it/                    it  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.co.uk/                 gb  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.cz/                    cz  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.be/                    be  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.at/                    at  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.dk/                    dk  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.lt/                    lt  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.pt/                    pt  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.ie/                    ie  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.hu/                    hu  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.ro/                    ro  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.sk/                    sk  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.gr/                    gr  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.hr/                    hr  used       fashion,kids,home                                          classifieds Vinted
https://www.vinted.lu/                    lu  used       fashion,kids,home                                          classifieds Vinted
"""
