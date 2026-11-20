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

## Getest: hielp een confidence-veld?

**Bron**: de eigen projectdocumentatie (`GRFICS v3 DUMP.docx`, secties 18/20.2/27) had "abstention accuracy" en "het
LLM geeft onzekerheid aan" al voorzien als aandachtspunt, maar dat was nooit gebouwd. **Hypothese**: `submit_verdict`
dwingt een vast label af zonder ruimte voor onzekerheid; als het model dat kon aangeven, zou een fout `valid`-oordeel
vaker lage confidence moeten hebben dan een goed oordeel. Test (2026-11-20): optioneel `confidence`-veld
(laag/midden/hoog) toegevoegd aan `submit_verdict`, zelfde 6 cases, `native`, PAGE 30, bewijs-afdwinging aan.

**Uitkomst: weerlegd, niet bevestigd.** Opnieuw 3 van de 6 goed op recall — exact hetzelfde aantal als bij de PAGE-
en kwantisatietest, alleen weer andere cases (nu grfics-001, -005, -012 i.p.v. -005, -013, -017). Drie verschillende
ingrepen, drie keer dezelfde 3/6: dat wijst eerder op een plafond van dit model op deze cases dan op een knop die wij
kunnen omzetten.

Belangrijker: **`grfics-016` is fout (`valid` i.p.v. `forbidden_function`) mét `confidence: high`.** Dat weerlegt de
hypothese direct — als het model domweg onzeker was en daarom voor `valid` koos, zou je lage confidence verwachten
bij een fout `valid`-oordeel. Hier is het juist zelfverzekerd fout: een oprechte misinterpretatie van het bewijs, geen
aarzeling die het verborg. Op twee andere cases (012, 013) vulde het model `reason` én `confidence` niet eens in,
ondanks dat beide velden in het schema staan — dus ook onbetrouwbaar in het gebruiken van het veld zelf.

**Drie verdachten nu uitgesloten: `PAGE`, kwantisatie, ontbrekend onzekerheidssignaal.** Het `confidence`-veld blijft
wel in de code staan (goedkoop, optioneel, nu al gezien dat het soms waardevolle informatie geeft zoals bij
grfics-016) — alleen de hypothese dat het de ingestorte recall zou verklaren, klopt niet.

## Einde van dit onderzoeksspoor: conclusie

Drie onafhankelijke ingrepen (`PAGE`, kwantisatie, confidence) kwamen alle drie uit op precies 3 van de 6 goed op
recall, steeds met andere cases. Dat betekent één van twee dingen: een echt plafond van qwen2.5:3b op deze cases,
of een steekproef van 6 die te klein is om verschil te laten zien — in beide gevallen heeft nog een vierde ablatie
op dezelfde 6 cases weinig meerwaarde meer.

**Vastgestelde conclusie voor dit spoor**: bewijs afdwingen (+ `PAGE` 10→30 + `num_predict`-cap, als één pakket
ingevoerd op 2026-11-19) verbeterde `multi` (F1 43%→56%) maar verslechterde `manual`, `native` en `mcp` (F1 60%→20%,
67%→43%, 31%→20%). Drie losse, geteste verklaringen (PAGE, kwantisatie, een expliciet onzekerheidssignaal)
verklaren die verslechtering niet. De precieze oorzaak blijft open — dat melden we als een eerlijke beperking,
niet als opgelost. De bewijs-afdwinging zelf blijft aan staan: hij is de enige ingreep die ooit iets aantoonbaar
verbeterde (`multi`), en uitzetten zou dat weer ongedaan maken zonder dat we weten of het de andere vier echt
repareert.

## Getest: doet llama3.2:3b het ook zo op deze schaal?

**Test (2026-11-20)**: `llama3.2:3b`, `native`, alle 20 cases (niet een steekproef van 6 — dit is de modelvraag, geen
ablatie, dus meteen de volledige dataset om een eerlijk vergelijkbaar cijfer te krijgen met qwen2.5:3b's
20-case-resultaat). Gestopt na 12 van de 20: het patroon was al volledig consistent.

**Uitkomst: geen kwaliteitsverschil met qwen2.5:3b — een harde, structurele storing.** Alle 12 afgeronde cases
eindigden in `geen oordeel`, en in **geen enkele** daarvan werd `get_transactions` ooit succesvol aangeroepen
(`transactions_total` bleef `null` in alle 12, terwijl `get_policy` — die geen argumenten nodig heeft — wel altijd
lukte). Gemiddeld 7,9 tool-aanroepen en 11,9 ongeldige aanroepen per case, steeds tegen de stappenlimiet van 12 aan.
Dit lijkt geen subtiel kwaliteitsverschil maar een onverenigbaarheid tussen hoe `llama3.2:3b` argumenten voor een tool
met een parameter opbouwt en hoe deze harness (of Ollama's native tool-calling) dat verwacht. Bestand (12 cases, geen
volledige meting):
[results/proef-llama3.2-3b-native.jsonl](../results/proef-llama3.2-3b-native.jsonl).

## Getest: ligt het aan native tool-calling, of aan llama3.2:3b zelf?

**Test (2026-11-20)**: `llama3.2:3b` op `manual` (alle 20 cases) — geen Ollama-native tool-calling, puur JSON-in-de-
prompt dat onze eigen code ontleedt.

**Uitkomst: niet de native-tool-calling-vorm — het is breder.** Alle 20 cases eindigden ook hier in `geen oordeel`,
met `transactions_total` overal `null`. `get_policy` en de registertool (die wél een argument heeft, `server`) lukten
steeds; alleen `get_transactions` (argument `start`, een integer) lukte in **geen van de 40 pogingen over beide
varianten** (20 native + 20 manual). Vermoedelijke oorzaak, niet bevestigd: `llama3.2:3b` levert `start` mogelijk als
tekst (`"0"`) in plaats van een getal (`0`), en onze validatie (`_int()` in `bench/datasets.py`) wijst dat af. Bestand:
[results/proef-llama3.2-3b-manual.jsonl](../results/proef-llama3.2-3b-manual.jsonl).

**Conclusie van dit spoor**: `llama3.2:3b` is in deze opzet niet bruikbaar voor de tool-varianten — niet omdat het
zwakker redeneert dan qwen2.5:3b, maar omdat het een specifieke, consistente storing heeft bij één tool-argument,
over twee onafhankelijke aanroepmethodes heen. Dit is zelf een valide bevinding: niet elk model met het "tools"-label
in de Ollama Library is in de praktijk betrouwbaar, ook niet op dezelfde schaal als qwen2.5:3b. Een fix (bv. `start`
coërceren van tekst naar getal voor de validatie) is mogelijk, maar gezien hoe consistent en breed deze storing is,
is de vraag of dat de moeite waard is tegenover gewoon vaststellen dat dit model hier niet geschikt voor is.

**Nog open**: `qwen3:4b` (ook bevestigd met het "tools"-label) is nog niet geprobeerd — dat zou laten zien of dit
llama-specifiek is, of dat meer modellen op deze schaal met zo'n storing kampen.

## Terug naar qwen2.5:3b: bewijs-afdwinging alsnog geïsoleerd, op volle schaal

Na vier losse testjes (PAGE, kwantisatie, confidence, llama3.2:3b) zonder doorbraak ontstond terecht de vraag of we
aan het rondjes draaien waren. In plaats van nog een losse ablatie: één beslissende test op de **volledige** dataset
(niet 6 cases), die de laatste nog openstaande vraag uit de conclusie hierboven alsnog beantwoordt.

**Test (2026-11-20)**: `native`, qwen2.5:3b, alle 20 cases, exact de instellingen van de 18-11-meting (`PAGE=10`,
geen `num_predict`-cap) — bewijs-afdwinging is het enige verschil met 18-11.

**Uitkomst: bewijs-afdwinging is wél degelijk (mede)schuldig — maar alleen in combinatie met een krap
stappenbudget.**

| Config | F1 | Recall | Geen oordeel |
|---|---|---|---|
| `native`, geen afdwinging, PAGE 10, geen cap (18-11) | 67% | 56% | 4/20 (20%) |
| `native`, afdwinging + PAGE 30 + cap 600 (19-11) | 43% | 33% | 3/20 (15%) |
| `native`, afdwinging + PAGE 10 + geen cap (20-11, dit) | **18%** | **11%** | **12/20 (60%)** |

Dit is de slechtste van de drie. Verklaring: bij `PAGE=10` kost het ophalen van alle transacties 2-3 aanroepen in
plaats van 1; samen met de eis van bewijs-afdwinging (beleid + alle pagina's + registertool + oordeel, vaak met
herkansingen) loopt het stappenbudget van 12 in 60% van de cases vast vóór er een oordeel is — tegen 15-20% in de
andere twee configuraties. Bestand:
[results/2026-11-20-enforcement-only.jsonl](../results/2026-11-20-enforcement-only.jsonl).

**Conclusie**: bewijs-afdwinging is op zichzelf niet per se slecht — hij maakt de taak alleen duurder in stappen, en
`PAGE=30` was (onbedoeld) een gedeeltelijke compensatie daarvoor door het aantal paginering-aanroepen te verlagen.
Zonder die compensatie wordt het stappenbudget de dominante bottleneck, niet de bewijseis zelf. `PAGE` blijft op 30
en de afdwinging blijft aan — die combinatie (19-11, F1 43%) is dus beter dan afdwinging alleen (F1 18%), ook al is
geen van beide zo goed als zonder afdwinging (F1 67%). Dit maakt de eerdere conclusie preciezer, niet ongedaan: de
oorzaak lag deels wél bij de afdwinging, specifiek door zijn stappenkost, niet door iets inhoudelijks aan het eisen
van bewijs.

## Volgende kandidaat

**`MAX_STEPS` verhogen** (nu 12), met `PAGE=10` én afdwinging aan: geeft het model genoeg ruimte om het hele
protocol (beleid, alle pagina's, registertool, oordeel) af te maken zonder dat de paginering alleen al het budget
opsoupeert — zonder de granulariteit van kleinere pagina's op te geven zoals `PAGE=30` wel doet.

## Lopend: een groter model, met meer CPU

Eerder zette qwen2.5:7b vast op de 900s-timeout, niet op geheugen (piekte op maar 5,6GB van de 12GB). Nu bekend is
dat CPU, niet geheugen, de bottleneck was, en dat er ruim quota vrij is (ook al op het persoonlijke account: 32
vCPU / 6GB vrij) — wordt de VM naar Large Instance (4 CPU/16GB) geschaald en qwen2.5:7b opnieuw, goedkoop, getest
voor we er een volledige meting aan wagen.
