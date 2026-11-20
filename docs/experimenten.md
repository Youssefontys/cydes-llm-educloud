# Experimenten: hoe we onderzoeken, en wat we al weten

Dit document is het logboek van de zoektocht naar de beste manier om qwen2.5:3b de validatietaak te laten doen —
los van [methodologie.md](methodologie.md) (dat gaat over de data), en los van de eindtabellen in de README onder
["Metingen"](../README.md#metingen) (dat zijn de metingen die tellen). Hier staat waarom we iets probeerden, wat
de uitkomst was, en wat dat betekent voor de volgende stap.

## Welke maatstaf telt

**"Juist" (exact het goede oordeel) is niet de maatstaf waar het om gaat.** 11 van de 20 cases in de dataset zijn
`valid`; een model dat altijd `valid` antwoordt, zonder ook maar iets te controleren, scoort al 55% "Juist". Voor
een validatietaak in security gaat het om **recall**: mist het model geen echte overtredingen? Een lage recall
betekent dat een model dat "in goed vertrouwen" overtredingen zou moeten melden, dat in de praktijk niet doet. Vanaf
nu is **recall en F1** de maatstaf waarop we een wijziging beoordelen, niet het percentage exact juist.

## Het principe: één variabele per keer

Een volledige meting (100 runs, 5 varianten × 20 cases) kost 8-20 uur op deze VM. Dat kun je je niet vaak
permitteren, dus:

1. **Verander nooit meer dan één ding tegelijk** in een run die iets moet bewijzen. Lukt dat niet (bv. omdat een
   fix en een optimalisatie samen in dezelfde commit zaten), benoem dat expliciet als een beperking van de meting.
2. **Test eerst klein** (4-8 cases, de snelste relevante variant) voor je een volledige meting van 100 runs start.
   Alleen een configuratie die op de kleine test overtuigend beter lijkt, verdient de volledige meting.
3. **Een proefrun bevestigt geen hypothese**, die laat alleen zien dat de keten werkt. Een klein experiment dat wél
   een hypothese test, krijgt hier een eigen regel met wat het liet zien — ook met een paar cases, zolang het
   gericht is op één vraag.

## Wat we al probeerden

| Datum | Wijziging | Vraag | Uitkomst | Volgende stap |
|---|---|---|---|---|
| 2026-11-17 | (geen; eerste meting) | Hoe doet elke variant het zonder aanpassingen? | `direct` confabuleert (altijd `illegal_address`, met elke keer een andere verzonnen reden); 0-5% van de tool-varianten had volledig bewijs voor het oordeelde. | Bewijs loggen en meten voor we iets aanpassen. |
| 2026-11-18 | `reason`- en `evidence_complete`-logging toegevoegd (geen gedragswijziging) | Bevestigt de logging het vermoeden met cijfers? | Ja: 0-5% volledig bewijs, bevestigd over de hele dataset. | Bewijs afdwingen. |
| 2026-11-19 | Drie dingen tegelijk: bewijs afgedwongen (geen oordeel zonder volledig bewijs), `PAGE` 10→30, `num_predict`-cap 600 | Verbetert afgedwongen bewijs de kwaliteit? | **Gemengd, en voor drie van de vijf averechts.** Volledig bewijs ging naar 100% in alle tool-varianten. F1 ging omlaag bij `manual` (60%→20%), `native` (67%→43%) en `mcp` (31%→20%) — met volledig bewijs koos het model vaker `valid` bij een echte overtreding. **`multi` werd juist beter (43%→56%)** — de reviewer-stap lijkt baat te hebben bij afgedwongen bewijs. Kosten: 2-3x zoveel modelaanroepen en CPU-tijd. Omdat drie dingen tegelijk veranderden, weten we niet welke van de drie de verslechtering bij de andere vier veroorzaakte. | Isoleren: `PAGE` terug naar 10, afdwinging aan laten, klein testen op `native`. |

## Getest: was PAGE de boosdoener?

**Hypothese**: alle transacties in één grote brok (PAGE 30) is slechter dan ze in kleinere stukken (PAGE 10)
doornemen. Test (2026-11-19/20): `native`, 6 cases (grfics-001, 005, 012, 013, 016, 017; dezelfde cases als in de
PAGE-30-meting), bewijs-afdwinging aan, `PAGE` terug naar 10.

**Uitkomst: niet bevestigd — ongeveer gelijkspel, met een nieuwe kost erbij.** Op "detecteert het een overtreding"
(de recall-maatstaf) scoorden beide 3 van de 6 goed, alleen andere cases: PAGE 10 repareerde grfics-001 en -012,
maar liet grfics-005 en -017 juist verslechteren (van `valid`/"iets gedetecteerd" naar geen oordeel/`valid`). En
PAGE 10 gaf 2 van de 6 "geen oordeel" tegen 0 bij PAGE 30: drie pagina's opvragen in plaats van één eet in het
stappenbudget van 12, waardoor een case vaker vastloopt voor hij klaar is. `PAGE` staat terug op 30 (de gemeten,
vastgelegde staat); dit was de nulhypothese, geen fix.

## Getest: hielp een andere kwantisatie?

**Hypothese**: Q8_0 (minder lossy dan het standaard Q4_K_M) zou preciezer kunnen zijn bij het vergelijken van
registerranges. Test (2026-11-20): `qwen2.5:3b-instruct-q8_0` (3,3GB), zelfde 6 cases als de PAGE-ablatie, `native`,
PAGE op 30 (de vastgelegde staat), bewijs-afdwinging aan.

**Uitkomst: niet bevestigd, iets slechter.** Op recall: Q4_K_M 3/6, Q8_0 2/6 — `grfics-017` ging van "detecteert een
overtreding, verkeerde regel" naar "gemist" (`valid`). Exacte juistheid: beide 1/6. Kwantisatie is dus ook geen
verklaring voor de ingestorte recall.

Wel een aparte, bruikbare bijvangst: Q8_0 had voor 5 van de 6 cases veel minder modelaanroepen nodig (2-5 tegen 5-8)
en was per case 2-3x sneller — behalve bij `grfics-017`, waar het dubbel zoveel tijd kostte en het alsnog mis had.
Interessant voor een latere kosten/kwaliteit-afweging, maar geen fix voor dit probleem.

**Twee verdachten nu uitgesloten: `PAGE` en kwantisatie.** Overgebleven: de bewijs-afdwinging zelf, en de
`num_predict`-cap.

## Volgende kandidaat

**De bewijs-afdwinging zelf.** Twee andere verklaringen (`PAGE`, kwantisatie) zijn nu uitgesloten op deze zelfde 6
cases. Test: dezelfde 6 cases, `native`, bewijs-afdwinging **uit** (terug naar de code van vóór 2026-11-19) — als de
recall dan weer omhooggaat, is dat de boosdoener; blijft hij laag, dan ligt het ergens anders (bv. `num_predict`).
