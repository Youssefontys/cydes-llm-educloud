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

## Getest: lost meer CPU de qwen2.5:7b-timeout op?

**Actie (2026-11-20)**: de openllm-VM geresized van Medium Instance+ (2 CPU/12GB) naar Large Instance (4 CPU/16GB),
in-place via Terraform (geen nieuwe VM, wel een nieuwe SSH-hostkey — verwacht bij een resize). Daarna een goedkope
proef: qwen2.5:7b, 2 cases (grfics-001, -005), `direct` + `native`.

**Uitkomst: de timeout is weg.** Alle 4 runs liepen af zonder fout (`error: null`) — eerder liep één aanroep al
binnen 2 cases vast op de 900s-timeout, op 2 CPU's. Tijden nu: `direct` 133-143s, `native` 406-597s, ruim onder de
limiet.

| Case | Variant | Resultaat | invalid_calls |
|---|---|---|---|
| 001 | direct | correct (valid) | 0 |
| 005 | direct | correct (valid) | 0 |
| 001 | native | fout (`forbidden_function`, verzint dat fc 1/3/4 niet toegestaan zijn) | **0** |
| 005 | native | geen oordeel (12 stappen op, 6x registertool) | **0** |

**Opvallendste signaal (n=2, te klein voor een kwaliteitsconclusie): `invalid_calls: 0` in beide `native`-cases.**
qwen2.5:3b had daar doorgaans 2-10 ongeldige pogingen per case nodig; 7b volgde het tool-protocol hier foutloos,
ook waar het inhoudelijk mis zat of bleef doorzoeken. Dat wijst op betere instructie-opvolging bij een groter model,
los van de vraag of het antwoord zelf juist is. Bestand:
[results/proef-7b-4cpu-page2.jsonl](../results/proef-7b-4cpu-page2.jsonl) (2 cases, geen volledige meting).

## Getest: is qwen2.5:7b daadwerkelijk beter, op dezelfde 6 cases?

**Test (2026-11-20)**: `qwen2.5:7b`, `native`, dezelfde 6 cases als alle eerdere ablaties (grfics-001, 005, 012, 013,
016, 017) — nu op de Large Instance (4 CPU), zonder timeouts.

**Uitkomst: nee — 0 van de 6 goed, slechter dan qwen2.5:3b's steeds terugkerende 3/6.** In 5 van de 6 cases riep
7b de registertool **zes keer** aan (tegen 1x normaal) en liep daarmee de volle 12 stappen op zonder ooit
`submit_verdict` te bereiken — `geen oordeel`, niet fout, gewoon nooit klaar. De ene case die wél een oordeel gaf
(`grfics-001`) was fout, met een verzonnen reden. Bestand:
[results/proef-7b-6cases.jsonl](../results/proef-7b-6cases.jsonl).

**Dit bevestigt en verscherpt de `MAX_STEPS`-hypothese, over twee modellen heen.** qwen2.5:3b liep bij `PAGE=10`
vast door te veel pagineringsaanroepen; qwen2.5:7b loopt vast door herhaalde, overbodige verificatie
(6x dezelfde registertool). Verschillend gedrag, dezelfde onderliggende muur: 12 stappen is te weinig zodra een
model grondig probeert te zijn. 7b is dus niet "beter" gebleken — het faalt alleen netter (0-1 ongeldige aanroepen
tegen 2-10 bij 3b), zonder dat vaker tot een goed oordeel te komen. De eerdere winst (geen timeouts meer dankzij
4 CPU's) staat los hiervan en blijft overeind.

## Getest: helpt MAX_STEPS verhogen?

**Test (2026-11-20/21)**: `MAX_STEPS` van 12 naar 20, qwen2.5:3b, dezelfde 6 cases, `native`, op de inmiddels
geresizde VM (4 CPU).

**Uitkomst: niet beter — 0 van de 6 goed, en niet eenduidig toe te schrijven.** Twee dingen door elkaar: de snelheid
verdubbelde (6,2 tok/s tegen 3,4-3,8 eerder) puur door de VM-resize, dus dit is geen schone vergelijking met de
eerdere MAX_STEPS=12-cijfers op 2 CPU. Eén case (`grfics-001`) stopte na maar 5 van de 20 stappen met `geen
oordeel` — bij nader inzien geen stappen-uitputting, maar een verdict-string die niet exact in onze vaste lijst
paste (opgevangen als `None`, niet als een geldig maar onherkend antwoord). Dat is zelf een kleine, aparte
bevinding: onze validatie kan een bedoeld antwoord soms ten onrechte als "geen oordeel" tellen.

**Besluit**: `MAX_STEPS` teruggezet naar 12 (de staat waarin alle drie de volledige metingen zijn gedaan). Geen
verdere ablaties hierop — we schakelen nu over naar het schrijven van het onderzoeksrapport met wat er is. Dit
hele traject (PAGE, kwantisatie, confidence, llama3.2:3b, bewijs-afdwinging geïsoleerd, qwen2.5:7b, MAX_STEPS)
staat hierboven vastgelegd als het antwoord op deelvraag 5: geen van de ingrepen gaf een doorbraak, en dat is zelf
de bevinding over de betrouwbaarheid van deze aanpak op deze schaal.

## Getest: MAX_STEPS 12 tegen 20, nu op dezelfde hardware

**Test (2026-11-21)**: `MAX_STEPS=12`, qwen2.5:3b, `native`, dezelfde 6 cases, op de VM met 4 CPU's — verder exact
gelijk aan de MAX_STEPS=20-run (PAGE 30, bewijs-afdwinging aan, `num_predict` 600, seed 1, context 4096, Ollama
0.40.16, zelfde model-digest). De code in `bench/` is identiek aan commit `f41a24d` (de confidence-test). Bestand:
[results/proef-maxsteps12-4cpu.jsonl](../results/proef-maxsteps12-4cpu.jsonl).

| Case | Juist oordeel | 12 stappen | 20 stappen |
|---|---|---|---|
| grfics-001 | `valid` | geen oordeel (5 aanroepen, 1 ongeldig) | geen oordeel (5 aanroepen, 1 ongeldig) |
| grfics-005 | `valid` | geen oordeel (12, waarvan 10 ongeldig) | geen oordeel (20, waarvan 18 ongeldig) |
| grfics-012 | `unknown_client` | `valid` (7 / 3) | `valid` (7 / 3) |
| grfics-013 | `forbidden_function` | `valid` (8 / 3) | `valid` (8 / 3) |
| grfics-016 | `forbidden_function` | `valid` (5 / 1) | `valid` (5 / 1) |
| grfics-017 | `illegal_address` | geen oordeel (12, waarvan 10 ongeldig) | geen oordeel (20, waarvan 18 ongeldig) |

**Uitkomst: MAX_STEPS is geen knop voor qwen2.5:3b.** Elk oordeel is identiek. De vier cases die binnen het budget
klaar waren, deden precies dezelfde aanroepen. De twee die tegen de limiet liepen, besteedden de 8 extra stappen
volledig aan nog meer ongeldige aanroepen: het model zit dan vast in een lus, het komt geen stappen tekort. Dit
sluit de open vraag uit de vorige sectie af.

**Bijvangst, en belangrijker: hardware verandert de uitkomst bij temperatuur 0.** Dezelfde code, hetzelfde model,
dezelfde instellingen en dezelfde 6 cases als de confidence-test van 2026-11-20 — die haalde op 2 CPU's 3 van de 6
goed (grfics-001, -005, -012). Nu, op 4 CPU's: 0 van de 6, en geen enkele overtreding gemeld. Het enige verschil is
de VM (2 → 4 CPU's, 12 → 16 GB). Op dezelfde machine is het model deterministisch (17-11 en 18-11: 100 van de 100
oordelen identiek); tussen machines dus niet. Vermoedelijke oorzaak, niet bewezen: met een ander aantal threads
telt llama.cpp in een andere volgorde op, waardoor bij een twijfelgeval een ander eerste token wint. Beperking:
de ruwe data van de confidence-test zijn niet bewaard, alleen deze log.

Gevolgen:

- De eerdere 0/6 van qwen2.5:7b en van MAX_STEPS=20 zijn **niet** slechter dan qwen2.5:3b: op dezelfde 4-CPU-VM
  haalt qwen2.5:3b ook 0 van de 6. De vergelijking "7b 0/6 tegen 3b 3/6" ging over verschillende hardware.
- Vergelijk modellen en instellingen alleen op dezelfde hardware. **Basislijn voor alles wat nu volgt:**
  `results/proef-maxsteps12-4cpu.jsonl` (qwen2.5:3b, 4 CPU's: 0/6 juist, 0/4 overtredingen gemeld, 3 geen oordeel).
- Dat 6 cases zo hard kunnen omslaan door alleen hardware, bevestigt dat de uitkomsten op deze schaal fragiel zijn.

## Plan: nieuwere kleine modellen

**Aanleiding**: alle geteste modellen komen uit 2024. Een meting van No Hype Bench (YouTube, 4 okt 2026: "Local LLM
2026: 6 New Small Models vs Last Year's Champion") op vergelijkbare hardware (8 vCPU Xeon, 15 GB, geen GPU, Ollama,
temperatuur 0, beoordeeld door code) liet zien dat nieuwere kleine modellen het beter doen op gestructureerde taken
(JSON-extractie, strikte opmaak). Tool calling is daar **niet** getest. Alle modellen staan in de Ollama Library en
passen in de VM (16 GB, 31 GB vrije schijf). Gecontroleerd op 2026-11-21.

**Opzet per model**: precies de basislijn hierboven — `native`, dezelfde 6 cases, 4 CPU's, PAGE 30,
bewijs-afdwinging aan, MAX_STEPS 12, `num_predict` 600, seed 1. Eerst één losse tool-aanroep met een
integer-argument controleren (daar faalde llama3.2:3b), pas dan de 6 cases.

**Ronde 1, in deze volgorde:**

1. `phi4-mini:3.8b-q4_K_M` (2,5 GB) — "tools"-label, denkt niet. Geen codewijziging nodig.
2. `qwen3.5:4b-q4_K_M` (3,3 GB) — de directe opvolger van qwen2.5:3b, dus de eerlijkste vergelijking. Denkt: zet
   `think` expliciet in het verzoek (een codewijziging, hier vastleggen), anders is het geen eerlijke vergelijking
   en kan het denkwerk de cap van 600 tokens opeten.
3. `lfm2.5:8b` (8b-a1b, Q4_K_M, 5,2 GB) — volgens de beschrijving gebouwd voor tool calling, MoE met 1,5B actief
   (snel op CPU). Denkt altijd: let op de cap van 600 tokens.

**Ronde 2, alleen als een model uit ronde 1 de basislijn verslaat** (meer juiste oordelen of meer gemelde
overtredingen op de 6 cases):

4. `qwen3.5:9b-q4_K_M` (6,6 GB) — past, maar wordt traag op 4 CPU's (een proef kan uren duren; let op de
   timeout van 900 s per aanroep).
5. `gemma4:e2b-it-qat` (4,3 GB) — **niet** de standaardtag: die bevat een draft-model voor speculative decoding en
   was in de video juist het traagst op een CPU.
6. `qwen3.5:2b-q4_K_M` (1,9 GB) — kleiner dan het huidige model en scoorde lager in de video; lage prioriteit.
7. `granite4.2:3b` (2,2 GB) — de beschrijving noemt tool use, maar het "tools"-label ontbreekt in de Library.
   Alleen testen na een losse tool-check; anders `granite4.1:3b` (heeft het label wel).

**Beslisregel**: verslaat geen enkel model uit ronde 1 de basislijn, dan stopt het modelspoor. Dan is niet de
modelgeneratie de grens, maar de taak of de opzet — en dat is zelf de bevinding.

## Getest: Phi-4 mini (ronde 1, model 1)

**Losse tool-check (2026-11-21)**: via `native` (Ollama's eigen tool-calling) roept `phi4-mini:3.8b-q4_K_M`
**geen** tool aan, ook al staat het "tools"-label in de Library en meldt `ollama show` de capability `tools`: het
model schrijft het tool-schema terug als gewone tekst. Via `manual` (tools als tekst, antwoord als JSON) gaat het
wél goed: juiste toolnamen, `start` als getal. Daarom wijkt deze proef af van het plan: `manual` in plaats van
`native`, met qwen2.5:3b op `manual` ernaast als basislijn, op dezelfde 4-CPU-VM.

**Test**: `manual`, qwen2.5:3b en phi4-mini, dezelfde 6 cases, 4 CPU's, PAGE 30, bewijs-afdwinging aan,
MAX_STEPS 12, `num_predict` 600, seed 1. Bestand:
[results/proef-phi4mini-manual-4cpu.jsonl](../results/proef-phi4mini-manual-4cpu.jsonl).

| Model | Juist | Overtreding gemeld | Geen oordeel | Tijd (6 cases) | Tokens/s |
|---|---|---|---|---|---|
| qwen2.5:3b | 2/6 (001, 005) | 1/4 (016, verkeerde regel) | 0 | 9 min | 6,3 |
| phi4-mini | 0/6 | 0/4 | 6 (3x stappen op, 3x Ollama-fout) | 97 min | 3,6 |

**Uitkomst: Phi-4 mini verslaat de basislijn niet, integendeel.** In 001, 005 en 012 haalde het wel netjes het
beleid, alle transacties en de registers op, maar kwam het daarna niet tot een geldig `submit_verdict`: 5, 7 en 12
ongeldige aanroepen tot het budget op was. Het schreef veel meer tekst (ruim 3.000 tokens in één case, tegen 118
bij qwen2.5:3b) en was per token ook trager. Het gesprek liep in de Ollama-log op tot 3.988 van de 4.096 tokens,
maar werd niet afgekapt (`truncated = 0`): het vermoeden dat de instructies uit het contextvenster vielen, klopt
dus niet. In 013, 016 en 017 gaf Ollama een interne fout (HTTP 500). Dezelfde eerste aanroep los herhaald ging
wel goed, dus het is een fout die af en toe optreedt, geen vaste.

**Twee bijvangsten**:

- Het "tools"-label in de Library (en zelfs de capability in `ollama show`) zegt niet dat native tool calling
  werkt. Na llama3.2:3b is dit het tweede model waarbij dat label misleidt.
- **Meetgat in de benchmark**: als een run halverwege op een fout stuit, schrijft `bench/run.py` 0 aanroepen en
  0 tokens weg (de tellingen gaan verloren; zie de nieuwe `runners.Stats()` bij de fout). grfics-017 liep 30
  minuten maar staat met 0 aanroepen in het bestand. Op te lossen door de `Stats` vanuit `run.py` aan
  `run_case` mee te geven.

**Basislijn op manual (bijvangst, nieuw)**: qwen2.5:3b haalt op dezelfde 4-CPU-VM via `manual` 2/6 juist, via
`native` 0/6. Op deze 6 cases doet `manual` het dus beter dan `native`, net als manual in de eerste volledige
meting een hogere recall had dan native (67% tegen 56%).

**Volgende stap volgens het plan**: `qwen3.5:4b-q4_K_M`. Vooraf twee codewijzigingen: `think` expliciet in het
verzoek (anders geen eerlijke vergelijking), en het meetgat hierboven dichten.

## Codewijziging: `--think` en tellingen bij een fout (2026-11-21)

- `bench.run --think on|off` stuurt `think` mee naar Ollama (naast `options`, niet erin). Zonder de optie wordt
  niets meegestuurd, dus eerdere runs en qwen2.5:3b veranderen niet. De keuze staat als `think` in de metadata.
- `run.py` geeft zijn `Stats` mee aan `run_case`: een run die halverwege op een fout stuit, bewaart nu het aantal
  aanroepen en tokens tot aan de fout, in plaats van 0. Resultaatbestanden van vóór deze wijziging (o.a. de
  Phi-4 mini-proef) hebben bij foutregels dus 0 aanroepen staan, ook als er wel gerekend is.
- De bestaande tests slagen (20, waarvan 1 overgeslagen), plus een losse controle met een nep-Ollama op beide punten.

Qwen3.5 draait met `--think off`: denken is een andere werkwijze dan die van qwen2.5:3b, en het denkwerk zou de cap
van 600 tokens opeten. Denken aan is een aparte vraag voor later, niet deze vergelijking.

## Getest: Qwen3.5 4B (ronde 1, model 2)

**Losse tool-check (2026-11-21)**: `ollama show` meldt dat `qwen3.5:4b-q4_K_M` standaard denkt (`thinking`,
`default true`): zonder `--think off` was de vergelijking ongemerkt oneerlijk geweest. Met denken uit gaf het via
`native` echte tool-aanroepen met `start` als getal (0 en 30), zonder denkwerk. Anders dan Phi-4 mini werkt native
tool calling hier dus wel.

**Test**: `native` en `manual`, `--think off`, dezelfde 6 cases, 4 CPU's, PAGE 30, bewijs-afdwinging aan,
MAX_STEPS 12, `num_predict` 600, seed 1. Bestand: [results/proef-qwen3.5-4b-4cpu.jsonl](../results/proef-qwen3.5-4b-4cpu.jsonl). Vergeleken met de
basislijnen van qwen2.5:3b op dezelfde VM (`proef-maxsteps12-4cpu.jsonl` voor native,
`proef-phi4mini-manual-4cpu.jsonl` voor manual).

| Variant | Model | Juist | Overtreding gemeld | Geen oordeel | Tijd (6 cases) |
|---|---|---|---|---|---|
| native | qwen2.5:3b | 0/6 | 0/4 | 3 | 50 min |
| native | **qwen3.5:4b** | **2/6** (001, 016) | 1/4, juiste regel | 4 | 64 min |
| manual | qwen2.5:3b | 2/6 (001, 005) | 1/4, verkeerde regel | 0 | 9 min |
| manual | **qwen3.5:4b** | **4/6** (001, 005, 013, 016) | 2/4, beide juiste regel | 0 | 12 min |

**Uitkomst: Qwen3.5 4B verslaat de basislijn op beide varianten.** Het is de eerste ingreep in dit hele traject die
dat doet. Via `manual` gaf het in elke case een oordeel, zonder één ongeldige aanroep, in zo'n 2 minuten per case;
`forbidden_function` werd twee keer met de juiste regel gevonden. Gemist: `unknown_client` (012) en
`illegal_address` (017), beide als `valid`. Via `native` liep het in 4 van de 6 cases nog vast op het
stappenbudget (3 tot 8 ongeldige aanroepen), maar ook daar haalde het een overtreding met de juiste regel.

**Kanttekening**: zes cases is een signaal, geen bewijs. Twee cases verschil kan op deze schaal ook toeval of
hardware-afhankelijkheid zijn (zie de MAX_STEPS-sectie).

**Gevolgen volgens het plan**:

- De beslisregel is gehaald: ronde 2 gaat open (Qwen3.5 9B, Gemma 4 E2B, Qwen3.5 2B, Granite 4.2 3B), na het
  laatste model van ronde 1, LFM2.5.
- Volgens het principe "eerst klein, alleen wat overtuigend beter lijkt krijgt een volledige meting" verdient
  Qwen3.5 4B een meting op alle 20 cases. Die moet naast een nieuwe meting van qwen2.5:3b op dezelfde 4-CPU-VM,
  omdat de volledige metingen van 17/18/19-11 op 2 CPU's zijn gedaan.

## Plan: lokale decision models (apart spoor, toegevoegd 2026-11-23)

**Aanleiding**: decision models (ook "System One"-modellen) zoals Jev van TypeSafe AI (sept. 2026) genereren geen
tekst. Ze krijgen een toestand (tekst of JSON) en vooraf getypeerde vragen, en geven in één forward pass per
antwoordoptie een gekalibreerde kans terug. Onze taak heeft precies die vorm: één keuze uit vijf vaste labels. Het
raakt drie eerdere bevindingen direct:

- een antwoord dat niet in de vaste lijst past (MAX_STEPS-sectie), kan hier per constructie niet;
- het confidence-veld zei niets over juistheid (grfics-016 zelfverzekerd fout); decision models zijn juist op
  gekalibreerde kansen getraind;
- confabulatie: het model kan geen eigen onderbouwing verzinnen, het kiest alleen.

**Wat ertegen pleit, vooraf bekend**:

- Jev zelf is alleen een gehoste API (TypeSafe, VS). Dat botst met het uitgangspunt dat gevoelige data de eigen
  infrastructuur niet verlaat. Daarom alleen **lokale, open** decision models.
- Geen tool calling: één stap, dus al het bewijs moet in de toestand staan. Het is een tegenhanger van `direct`,
  niet van `native`/`manual`.
- "What Can't Jev Decide?" (arXiv 2610.24929) meldt dat de nauwkeurigheid zakt zodra het antwoord afhangt van het
  combineren van meerdere records, en dat het model een meegegeven toestand niet controleert. Wij vergelijken per
  case 16 tot 25 transacties met een beleid; dat is precies dat soort taak.

**Technisch haalbaar, gecontroleerd 2026-11-23**: Ollama heeft een categorie "decision" en een endpoint
`POST /v1/systemone` (Ollama ≥ 0.35.0; de VM draait 0.40.16 en kent het endpoint). Aanroep: `model`, `state` (string
of JSON) en `questions` (1 tot 64, elk `choice`, `noul` of `score`). Antwoord: per vraag de keuze, de kans per optie
en een `confidence`, plus `usage`. Geen streaming, geen tools; de invoer moet volledig in het contextvenster passen
(wordt nooit afgekapt).

**Opzet**:

- Een nieuwe variant `decide` in de benchmark: `state` = hetzelfde bewijs als `direct` (`dataset.evidence(case)`:
  beleid, registers, alle transacties), één `choice`-vraag met de vijf labels en als `criteria` de regelteksten uit
  `grfics.RULE_TEXT`. Loggen: keuze, kans per label, confidence, tokens, tijd.
- Variant van de vraag, als tweede proef: vier losse `noul`-vragen ("breekt dit verkeer regel X?"), elk in een
  eigen verzoek; Perplexity meldt voor pplx-decider-flash iets hogere scores met één vraag per verzoek (60,05 tegen
  58,88 op hun Decision Index).
- **Basislijn**: `direct` van qwen2.5:3b en van qwen3.5:4b op dezelfde 6 cases en dezelfde 4-CPU-VM. Die bestaan
  nog niet op deze VM en draaien eerst mee (snel: één aanroep per case).
- Dezelfde 6 cases, seed 1, dezelfde VM.

**Kandidaten** (lokaal, passen op de VM; grootte nog per model te controleren):

1. `pplx-decider-flash:4b` (Perplexity, 5,6 GB, Apache 2.0) — gebouwd op Qwen3.5-4B, dus de schoonste vergelijking
   met ons beste generatieve model.
2. `d1:3b` (Liquid AI, op LFM2.5-VL-3B).
3. `tev1:4b` (Together AI).
4. Daarna, alleen als een van deze drie iets laat zien: `nimble:9b` (Bespoke Labs), `autotrust-jev:9b`,
   `strands-decider:2b`.

**Beslisregel**: het spoor is geslaagd als een decision model op de 6 cases meer juiste oordelen haalt dan beide
`direct`-basislijnen, zonder meer vals alarm. Extra meetpunt: hangt de kans van het gekozen label samen met
juistheid (wat het confidence-veld van qwen2.5:3b niet deed)? Bij succes is de volgende vraag of een decision
model als **verificatie-agent** werkt: het oordeel van het LLM-agent na het ophalen van bewijs laten keuren, zoals
de "Verificatie-Agent" en de onafhankelijke verificatie in het bord-diagram.

**Volgorde, voorstel**: eerst LFM2.5 afmaken (loopt), dan dit spoor (goedkoop: één aanroep per case), dan ronde 2,
en de volledige meting van Qwen3.5 4B 's nachts.

**Gebouwd (2026-11-23)**: de variant `decide` in `bench/runners.py`, zoals hierboven opgezet (alleen de eerste opzet:
één `choice`-vraag; de vier losse `noul`-vragen nog niet). Geen `options` (temperatuur, seed, context) mee, want
`/v1/systemone` ondersteunt die niet. Het bewijs is 1.600 tot 2.000 tokens per case (geschat), ruim binnen elk
contextvenster. Nieuwe test met een nep-decision-model; alle 21 tests slagen (1 overgeslagen). Nog niet tegen een
echt decision model gedraaid: dat volgt na LFM2.5, om die proef niet te storen.

## Getest: LFM2.5-8B-A1B (ronde 1, model 3)

**Losse tool-check (2026-11-23)**: `ollama show lfm2.5:8b` meldt `thinking` met als enige stand `false`. Toch schrijft
het model zijn redenering als `<think>...`-tekst in het antwoord, ook met `--think off`: denken valt hier niet uit te
zetten. Twee losse `native`-aanroepen gaven wel nette tool-aanroepen met `start` als getal.

**Test**: `native` en `manual`, `--think off`, dezelfde 6 cases, 4 CPU's, PAGE 30, bewijs-afdwinging aan, MAX_STEPS
12, `num_predict` 600, seed 1. Bestand: [results/proef-lfm2.5-8b-4cpu.jsonl](../results/proef-lfm2.5-8b-4cpu.jsonl).

| Variant | Juist | Overtreding gemeld | Geen oordeel | Tijd (6 cases) |
|---|---|---|---|---|
| native | 0/6 | 0/4 | 6 (alle 12 stappen op, 9-10 ongeldig per case) | 78 min |
| manual | 0/6 | 0/4 | 6 (12 van de 12 aanroepen ongeldig) | 3 min |

**Uitkomst: 0 van de 12, de basislijn niet verslagen.** Twee verschillende manieren van falen, losse controle
achteraf:

- `manual` gebruikt de JSON-modus van Ollama. Daarin slaat LFM2.5 het denken over, maar geeft het telkens een verkeerd
  gevormd antwoord: `{"start": 0, "end": 30}`, zonder toolnaam. Twaalf keer dezelfde fout.
- Zonder JSON-modus denkt het hardop en raakt het al bij de eerste aanroep de cap van 600 tokens, voordat er een
  tool-aanroep komt. In `native` schreef het per case 4.000 tot 6.000 tokens (gemiddeld 450-510 per aanroep).

Een hogere cap zou het model meer ruimte geven, maar dat is een andere instelling dan bij de andere modellen, en het
maakt elke case nog trager. Niet getest; hooguit een losse vervolgvraag.

**Stand van ronde 1**: Phi-4 mini 0/6 (manual), Qwen3.5 4B 4/6 manual en 2/6 native, LFM2.5 0/12. Alleen Qwen3.5 4B
verslaat de basislijn, en daarmee is ronde 2 open. Van de drie nieuwere modellen werkte er één goed met onze
aanroepvorm; bij de andere twee lag het probleem bij het aanroepen zelf, niet bij het oordeel.

## Getest: lokale decision models (d1, tev1) tegen `direct`

**Kandidaten bijgesteld (2026-11-23)**: `pplx-decider-flash` valt af: al zijn tags zijn MLX-builds (de standaardtag
heeft dezelfde digest als `4b-mxfp8`), en Ollama weigert ze op onze Linux-VM ("requires MLX support"). Wel op CPU te
draaien: `d1:3b` (Liquid AI, q8_0, 3,7 GB) en `tev1:4b-q4_K_M` (Together AI, 2,8 GB). Om ruimte te maken zijn vier
afgeronde modellen van de VM verwijderd (lfm2.5, phi4-mini, llama3.2, qwen2.5-q8); opnieuw op te halen.

**Test**: `decide` voor d1 en tev1; `direct` voor qwen2.5:3b en voor Qwen3.5 4B (`--think off`) als basislijn.
Dezelfde 6 cases, 4 CPU's, seed 1, `num_predict` 600 voor de generatieve modellen. Bestanden:
[proef-decide-4cpu.jsonl](../results/proef-decide-4cpu.jsonl),
[proef-direct-qwen2.5-3b-4cpu.jsonl](../results/proef-direct-qwen2.5-3b-4cpu.jsonl),
[proef-direct-qwen3.5-4b-4cpu.jsonl](../results/proef-direct-qwen3.5-4b-4cpu.jsonl).

| Model | Variant | Juist | Overtreding gemeld | Vals alarm | Tijd (6 cases) |
|---|---|---|---|---|---|
| qwen2.5:3b | `direct` | 1/6 | 4/4 (1 juiste regel) | 2/2 | 7,0 min |
| **qwen3.5:4b** | `direct` | **4/6** (001, 005, 013, 016) | 2/4 (beide juiste regel) | 0/2 | 8,8 min |
| d1:3b | `decide` | 1/6 | 3/4 (1 juiste regel) | 2/2 | 7,6 min |
| tev1:4b | `decide` | 2/6 | 0/4 | 0/2 | 7,8 min |

**Uitkomst: het spoor slaagt niet.** Volgens de beslisregel moest een decision model meer juiste oordelen halen dan
beide `direct`-basislijnen; tev1 haalt 2/6 en d1 1/6, tegen 4/6 voor Qwen3.5 4B. De vervolgstappen die alleen bij
succes zouden volgen (vier losse ja/nee-vragen, de 9B-kandidaten, decision model als verificatie-agent) vervallen.

**Wat het wel liet zien**:

- **d1 weet dat het het niet weet.** Het verdeelt de kans bijna gelijk over de labels (de gekozen optie 0,29-0,38,
  confidence 0,11-0,22), maar die lage zekerheid zegt niets over goed of fout: de ene juiste case had dezelfde
  zekerheid als de foute.
- **tev1 zegt steeds `valid`, maar minder stellig bij echte overtredingen.** De kans op `valid` was 0,56-0,59 bij de
  twee echte valid-cases en 0,46-0,51 bij de vier overtredingen; de confidence 0,45-0,49 tegen 0,32-0,39. Op deze 6
  cases scheidt een drempel de twee groepen volledig. Met zes cases is dat geen bewijs, maar wel precies het
  signaal dat het confidence-veld van qwen2.5:3b niet gaf: bruikbaar als filter ("alleen een stellig `valid`
  vertrouwen, de rest naar een mens"), niet als eindoordeel.
- **Niet sneller op onze CPU.** Zo'n 75-85 seconden per case, net zo lang als `direct` met een generatief model.
  Het bewijs is ongeveer 3.400 tokens (eerder te laag geschat), en het inlezen daarvan kost op een CPU de meeste
  tijd; het genereren van een kort antwoord weinig. De claim "40 tot 200 keer sneller" gaat over gehoste hardware en
  korte invoer, niet over deze opzet.
- **Bijvangst: Qwen3.5 4B haalt via `direct` hetzelfde als via `manual`** (4/6, dezelfde cases), met één aanroep per
  case en zonder tools. Voor dit model voegen de tools op deze 6 cases dus niets toe. qwen2.5:3b via `direct`
  confabuleert nog steeds: zes keer `illegal_address`, net als in de eerste meting van 17-11.

## Plan: het beste model per variant (toegevoegd 2026-11-23)

**Aanleiding**: de proeven laten zien dat een model per variant heel anders kan uitpakken. Phi-4 mini werkte alleen
via `manual`; LFM2.5 kon via `native` tools aanroepen maar liep op het denken vast; qwen2.5:3b deed het op dezelfde
VM via `manual` beter dan via `native`. Eén model in alle varianten beantwoordt de vraag welke **architectuur** het
best is (één variabele per keer). Het beste model per variant beantwoordt een andere vraag, die voor de hoofdvraag
("in hoeverre bruikbaar") telt: hoe ver kom je **per architectuur maximaal** op deze hardware?

**Opzet, in deze volgorde**:

1. **Architectuurvergelijking**: de volledige metingen van Qwen3.5 4B en qwen2.5:3b, alle vijf varianten op alle 20
   cases, op de 4-CPU-VM (af, 24-11; zie "Gemeten: de volledige metingen" onderaan).
2. **Winnaar per variant kiezen**, op dezelfde 6 cases en dezelfde VM:
   - `native` en `manual`: uit ronde 1 en ronde 2 (alle modellen hebben die al gedraaid).
   - `direct`: nu alleen qwen2.5:3b en Qwen3.5 4B gemeten. De vier modellen van ronde 2 krijgen nog een korte
     `direct`-proef (goedkoop: één aanroep per case).
   - `mcp`: dezelfde tool-aanroepen als `native`, dus de `native`-winnaar.
   - `multi`: twee keer de `native`-lus, dus kandidaten zijn de `native`-winnaars.
   - Keuzeregel: meeste juiste oordelen; bij gelijkspel meer overtredingen met de juiste regel, dan minder vals
     alarm, dan minder tijd.
3. **Volledige meting van elke winnaar** op alle 20 cases in zijn eigen variant, alleen als die nog niet in stap 1
   zit. Geen complete matrix van alle modellen maal alle varianten: dat zou dagen rekentijd kosten.

**Uitbreiding voor `multi`, apart**: de analist en de reviewer hoeven niet hetzelfde model te zijn, bijvoorbeeld een
snel klein model dat het bewijs verzamelt en een sterker model dat beoordeelt. De benchmark kan dat nog niet; het
vraagt een kleine codewijziging (een apart model voor de reviewer). Pas oppakken na stap 2, met de winnaars als
kandidaten.

**Wat het oplevert**: per architectuur het beste haalbare resultaat op deze hardware, naast de schone vergelijking
met één model. Samen laten ze zien of een architectuur slecht is, of alleen slecht werkt met het verkeerde model.

## Naar aanleiding van externe feedback (2026-11-23)

Een review door Gemini op basis van de README leverde, naast punten die hierboven al zijn uitgezocht (de drie
wijzigingen van 19-11 uit elkaar trekken, een groter model proberen), drie bruikbare punten op. Uitgewerkt met de
bestaande data, zonder nieuwe runs:

**1. CPU-seconden per juist oordeel** als maat voor efficiëntie, in plaats van losse tijden. Uit de twee volledige
metingen van qwen2.5:3b (2 CPU's, 20 cases):

| Variant | 17-11: juist | 17-11: CPU-s per juist | 19-11: juist | 19-11: CPU-s per juist |
|---|---|---|---|---|
| direct | 3/20 | 1.674 | 3/20 | 1.693 |
| manual | 7/20 | **574** | 11/20 | **640** |
| native | 9/20 | 1.545 | 9/20 | 2.959 |
| mcp | 7/20 | 2.150 | 7/20 | 5.461 |
| multi | 9/20 | 2.205 | 9/20 | 4.603 |

`manual` is in beide metingen veruit het goedkoopst per juist oordeel; `mcp` en `multi` kosten drie tot acht keer
zoveel. Kanttekening: 'juist' telt ook terecht gegeven `valid`-oordelen mee (11 van de 20 cases zijn valid), dus
dit is een maat voor de kost van een correct oordeel in het algemeen, niet van een gevonden overtreding.

**2. De antwoordlimiet (`num_predict` 600) is nooit apart getest.** Meestal maakt dat niet uit: qwen2.5:3b schrijft
gemiddeld 132 tokens per antwoord, Qwen3.5 4B 87. Maar in de meting van 19-11 liepen in 5 van de 100 runs de
antwoorden op tot gemiddeld 300-500 tokens, en dat waren **allemaal `mcp`-runs** (grfics-003, -005, -007, -015,
-017). Drie daarvan eindigden zonder oordeel. De limiet heeft dus vermoedelijk meegespeeld in de 6 keer "geen
oordeel" van `mcp` op 19-11 (tegen 2 op 17-11). Niet geïsoleerd; een losse test (`mcp`, die vijf cases, zonder cap)
zou het kunnen bevestigen.

**3. De taak is mechanisch te controleren.** Om `unknown_client`, `forbidden_function` of `illegal_address` te
vinden, moet het model per transactie client, server, function code en register vergelijken met het beleid en de
registermap. `check()` doet dat foutloos in een paar regels code. Een taalmodel is daar op deze schaal slordiger en
veel duurder in. Dat is geen fout in de opzet (de taak is juist gekozen omdat het juiste antwoord mechanisch vast
te stellen is), maar wel een discussiepunt: een LLM voegt vooral iets toe waar regels vaag zijn of context
vragen, niet bij exacte vergelijkingen.

Niet overgenomen: `unauthorized_write` nu aan de dataset toevoegen. Dan zijn alle metingen tot nu toe, inclusief de
volledige metingen die nu lopen, niet meer vergelijkbaar. Dat hoort bij een volgende datasetversie.

## Getest: ronde 2 (Qwen3.5 2B, Granite 4.2 3B, Gemma 4 E2B, Qwen3.5 9B)

**Losse tool-check (2026-11-23)**: alle vier gaven via `native` echte tool-aanroepen met `start` als getal, zonder
denkwerk (`--think off`). Granite 4.2 meldt lokaal de capability `tools`, ook al ontbreekt het label in de Library.

**Test**: `native` en `manual`, `--think off`, dezelfde 6 cases, 4 CPU's, PAGE 30, bewijs-afdwinging aan, MAX_STEPS
12, `num_predict` 600, seed 1. Bestand: [results/proef-ronde2-4cpu.jsonl](../results/proef-ronde2-4cpu.jsonl).
Basislijn (qwen2.5:3b, zelfde VM): native 0/6, manual 2/6. Beste tot nu toe: Qwen3.5 4B, native 2/6, manual 4/6.

| Model | Variant | Juist | Overtreding gemeld | Vals alarm | Geen oordeel | Tijd (6 cases) |
|---|---|---|---|---|---|---|
| Qwen3.5 2B | native | 0/6 | 0/4 | 1/2 | 4 | 34 min |
| Qwen3.5 2B | manual | 3/6 (012, 013, 016) | 4/4, 3 juiste regel | 2/2 | 0 | 5 min |
| Granite 4.2 3B | native | 0/6 | 0/4 | 0/2 | 6 | 93 min |
| Granite 4.2 3B | manual | 2/6 (001, 005) | 0/4 | 0/2 | 0 | 43 min |
| **Gemma 4 E2B** | **native** | **4/6** (001, 005, 013, 016) | 2/4, juiste regel | 0/2 | 1 | **6 min** |
| Gemma 4 E2B | manual | 1/6 | 0/4 | 0/2 | 1 | 4 min |
| Qwen3.5 9B | native | 1/6 (012) | 1/4, juiste regel | 0/2 | 5 | 152 min |
| Qwen3.5 9B | manual | 2/6 (012, 017) | **4/4, 2 juiste regel** | 0/2 | 2 | 66 min |

**Uitkomst**:

- **Gemma 4 E2B via `native` evenaart de beste** (4/6, geen vals alarm), in ongeveer een minuut per case. Het is het
  eerste model dat via `native` beter scoort dan via `manual`, en daarmee de `native`-winnaar.
- **Qwen3.5 9B vond als enige `unknown_client` (012) én `illegal_address` (017)**, de twee overtredingen die
  Qwen3.5 4B en Gemma 4 E2B missen. Via `manual` meldde het alle vier overtredingen zonder vals alarm, maar liep het
  op beide valid-cases vast op het stappenbudget. Groter helpt hier dus wel bij het vinden, niet bij het afronden,
  en het kost veel tijd (1 tot 2,5 uur voor 6 cases).
- **Qwen3.5 2B via `manual` vond drie overtredingen met de juiste regel**, maar gaf ook op beide valid-cases vals
  alarm.
- **Granite 4.2 liep via `native` in alle zes cases vast.** Het ontbrekende tools-label in de Library was dus toch
  een waarschuwing, ook al slaagde de losse tool-check.

**Winnaars per variant op deze 6 cases** (voor het plan "beste model per variant"):

| Variant | Winnaar | Juist | Nog open |
|---|---|---|---|
| `direct` | Qwen3.5 4B | 4/6 | — (bevestigd door de `direct`-proef hieronder) |
| `manual` | Qwen3.5 4B | 4/6 | — |
| `native` | Gemma 4 E2B | 4/6 | — |
| `mcp`, `multi` | Gemma 4 E2B (volgt `native`) | — | volledige meting staat in de wachtrij |

**`direct`-proef van de ronde 2-modellen (2026-11-24)**: zelfde 6 cases en VM, `--think off`. Bestand:
[results/proef-direct-ronde2-4cpu.jsonl](../results/proef-direct-ronde2-4cpu.jsonl).

| Model | Juist | Overtreding gemeld | Vals alarm | Tijd (6 cases) | Gedrag |
|---|---|---|---|---|---|
| Qwen3.5 9B | 3/6 (001, 005, 012) | 1/4, juiste regel | 0/2 | 14 min | vindt weer als enige `unknown_client` |
| Gemma 4 E2B | 2/6 (001, 005) | 0/4 | 0/2 | 2 min | zes keer `valid` |
| Granite 4.2 3B | 2/6 (001, 005) | 0/4 | 0/2 | 7 min | zes keer `valid` |
| Qwen3.5 2B | 1/6 (012) | 4/4, 1 juiste regel | 2/2 | 4 min | wisselt `unknown_client` en `unauthorized_write` af |

Geen van de vier haalt de 4/6 van Qwen3.5 4B via `direct`; de winnaars per variant blijven zoals hierboven. Opvallend:
Gemma 4 E2B is via `native` de beste (4/6), maar zegt via `direct` en `manual` vrijwel alleen `valid`. Het model haalt
het meeste uit Ollama's eigen tool-aanroepen, niet uit alles in één prompt.

## Mislukt: de eerste volledige meting (2026-11-24, 02:24)

Direct na ronde 2 startte de volledige meting van Qwen3.5 4B. Bij de eerste aanroep liep de VM vol op geheugen: de
OOM-killer stopte een `llama-server` van 14,4 GB, Ollama crashte daarna (nil pointer in zijn scheduler) en systemd
herstartte het binnen 3 seconden. Vermoedelijk zat Qwen3.5 9B uit ronde 2 nog in het geheugen toen Qwen3.5 4B werd
geladen. In die 3 seconden liep de benchmark door alle 99 resterende runs heen en schreef ze weg als fout
("connection refused"); de meting van qwen2.5:3b startte daarna niet eens. Het bestand
(`2026-11-23-qwen3.5-4b-4cpu.jsonl`) bevat dus alleen foutregels en is opzijgezet, niet gebruikt.

**Lessen**: (1) een wegvallend Ollama moet de benchmark laten wachten in plaats van runs als fout te laten
wegschrijven; (2) tussen modellen expliciet het vorige model uit het geheugen halen (`ollama stop`).

**Opgelost in `bench/run.py`**:

- Een fout van Ollama als dienst (connection refused, verbinding verbroken) telt niet meer als mislukte run. De run
  wacht tot Ollama terug is (tot 5 minuten) en probeert dezelfde case opnieuw, tot 3 keer. Blijft Ollama weg, dan
  stopt de run zonder een regel weg te schrijven, zodat dezelfde opdracht later verdergaat. Fouten van het model
  zelf (zoals een HTTP 500) worden nog steeds als fout gelogd.
- Aan het begin van elk model haalt de run alle geladen modellen uit het geheugen (`keep_alive: 0`), zodat er nooit
  twee grote modellen tegelijk in staan.
- Nieuwe test met een Ollama dat één keer wegvalt; alle 22 tests slagen (1 overgeslagen).

## Gemeten: de volledige metingen (2026-11-24 en -25)

Na de reparatie liep de keten opnieuw en zonder fouten: Qwen3.5 4B en qwen2.5:3b in alle vijf varianten, daarna Gemma
4 E2B (de `native`-winnaar) in `native`, `mcp` en `multi`. Alle 20 cases, 4 CPU's (Large Instance), `--think off`,
PAGE 30, bewijs-afdwinging aan, MAX_STEPS 12, `num_predict` 600, seed 1. Geen enkele run met een fout. Bestanden:
[2026-11-24-qwen3.5-4b-4cpu.jsonl](../results/2026-11-24-qwen3.5-4b-4cpu.jsonl),
[2026-11-24-qwen2.5-3b-4cpu.jsonl](../results/2026-11-24-qwen2.5-3b-4cpu.jsonl),
[2026-11-24-gemma4-e2b-4cpu.jsonl](../results/2026-11-24-gemma4-e2b-4cpu.jsonl). De tabellen van `bench.report` staan
in de README onder Metingen.

Ter vergelijking: altijd `valid` zeggen haalt al 11/20 (55%), want 11 van de 20 cases zijn valid. Een variant is pas
bruikbaar als hij overtredingen vindt zonder de valid-cases kwijt te raken.

| Model | Variant | Juist | Overtreding, juiste regel | Vals alarm | Geen oordeel | CPU-s per juist | Rekentijd |
|---|---|---|---|---|---|---|---|
| Qwen3.5 4B | direct | 13/20 | **4/9** | 2/11 | 0 | 514 | 0,5 u |
| Qwen3.5 4B | manual | 14/20 | 3/9 | 0/11 | 0 | 627 | 0,6 u |
| Qwen3.5 4B | native | 3/20 | 1/9 | 0/11 | 15 | 20.381 | 4,3 u |
| Qwen3.5 4B | mcp | 10/20 | 2/9 | 1/11 | 9 | 6.005 | 4,2 u |
| Qwen3.5 4B | multi | 3/20 | 1/9 | 0/11 | 16 | 42.096 | 8,8 u |
| qwen2.5:3b | direct | 2/20 | 2/9 | 11/11 | 0 | 2.679 | 0,4 u |
| qwen2.5:3b | manual | 12/20 | 1/9 | 0/11 | 0 | 691 | 0,6 u |
| qwen2.5:3b | native | 7/20 | 1/9 | 2/11 | 5 | 4.849 | 2,4 u |
| qwen2.5:3b | mcp | 11/20 | 2/9 | 0/11 | 4 | 2.637 | 2,0 u |
| qwen2.5:3b | multi | 9/20 | 3/9 | 4/11 | 1 | 6.406 | 4,0 u |
| Gemma 4 E2B | native | 12/20 | 3/9 | 1/11 | 3 | **353** | 0,3 u |
| Gemma 4 E2B | mcp | 1/20 | 0/9 | 0/11 | 19 | 10.490 | 0,7 u |
| **Gemma 4 E2B** | **multi** | **15/20** | **4/9** | **0/11** | 1 | 860 | 0,9 u |

**Uitkomst**:

- **Gemma 4 E2B via `multi` is de beste meting tot nu toe**: 15/20, F1 71%, geen vals alarm, in minder dan een uur
  voor 20 cases. Het is ook de enige combinatie die vier overtredingen vindt zonder één valid-case kwijt te raken.
  Gemma via `native` is het goedkoopst per juist oordeel (353 CPU-seconden).
- **De schone architectuurvergelijking (één model, vijf varianten) wijst bij beide Qwen-modellen naar `manual`**:
  14/20 en 12/20, zonder vals alarm, en het goedkoopst per juist oordeel of op één na. Bij Qwen3.5 4B haalt `direct` bijna hetzelfde
  (13/20) en vindt het meer overtredingen (4/9), maar met twee keer vals alarm.
- **De tool-lussen lopen bij de Qwen-modellen vast op het stappenbudget.** Bij elke "geen oordeel" van Qwen3.5 4B in
  `native`, `mcp` en `multi` maakte een lus alle 12 aanroepen op. Het model vraagt gemiddeld bijna vijf
  registermaps op voordat het oordeelt. Daardoor kosten die varianten 10 tot 70 keer zoveel CPU per juist oordeel.
  Gemma doet in `native` vier aanroepen per case en is dan klaar.
- **Op 6 cases leek het beter dan op 20.** Qwen3.5 4B `native` haalde op de zes proefcases 2/6, nu 3/20; Gemma
  `native` 4/6, nu 12/20 (dus 8 van de 14 overige). De proefcases bevatten relatief veel overtredingen; de keuze van
  de winnaars blijft staan, de proefscores niet.
- **Wie vindt welke overtreding?** `forbidden_function` (013, 016, 019) gaat het best: Qwen3.5 4B via `direct` en
  `manual`, en Gemma via `native` en `multi`, vinden ze alle drie. `illegal_address` vond Gemma nooit. Case 020 werd
  alleen gevonden in de tool-lussen van de Qwen-modellen (`native` en `mcp`), die veel registermaps opvragen; 014 en
  017 alleen door qwen2.5:3b, dat via `direct` bijna overal `illegal_address` zegt (11/11 vals alarm), dus dat telt
  nauwelijks als vinden. Van `unknown_client` (012, 015, 018) vond alleen qwen2.5:3b via `multi` er twee; geen
  variant vond ze alle drie.
- **Gemma geeft drie keer een verdict dat niet bestaat** (`native` 010, 012, 015): een lange redenering over de
  schrijfrechten van de HMI, maar geen geldige regelnaam. Dat telt als geen oordeel.

## Gevonden: `mcp` krijgt kalere tool-beschrijvingen dan `native` (2026-11-27)

Gemma 4 E2B gaf via `mcp` 19 keer geen oordeel, tegen 3 keer via `native`, terwijl beide varianten dezelfde lus
gebruiken (`native_loop`). Met één case nagespeeld op de VM (`think` uit, zoals in de meting): Gemma roept
`get_register_map` aan met `{"server": "grfics-001"}`, het case-id in plaats van een IP-adres. Die aanroep mislukt,
dus telt er geen registeraanroep. De bewijs-afdwinging weigert daarna elk oordeel ("You have not checked a register
map..."), tot de 12 stappen op zijn. Gemiddeld haalde Gemma via `mcp` 0,15 geslaagde registeraanroepen per run, via
`native` 1,0.

De oorzaak zit in de benchmark, niet in het protocol: de MCP-server ([bench/mcp_server.py](../bench/mcp_server.py))
beschrijft zijn tools anders dan [bench/datasets.py](../bench/datasets.py) voor de andere varianten.

| | `native` (datasets.py) | `mcp` (mcp_server.py) |
|---|---|---|
| `get_transactions` | "up to 30 ... Fields: i, t, src, dst, fc, addr, count, values, exception" | "up to 10", geen velden uitgelegd |
| `start` | verplicht, met uitleg | optioneel (standaard 0), zonder uitleg |
| `server` | "IP address of the server, as in dst." | geen uitleg |

**Gevolg**: het verschil tussen `native` en `mcp` in alle metingen tot nu toe meet niet alleen het protocol, maar ook
deze beschrijvingen. Bij Gemma verklaart het de 19 keer geen oordeel. Bij de Qwen-modellen werkt het andersom: `mcp` scoort daar
juist beter dan `native` (10/20 tegen 3/20, en 11/20 tegen 7/20); waarom is niet uitgezocht, maar ook daar kan het aan
de beschrijvingen liggen in plaats van aan het protocol. Deelvraag 2 (wat voegt MCP toe?) is met deze data dus
niet te beantwoorden.

**Herstel (nog niet gedaan)**: de MCP-server dezelfde beschrijvingen laten geven als `datasets.py`, met een test die
de twee schema's vergelijkt, en daarna alleen `mcp` opnieuw meten voor de drie modellen (samen ongeveer 7 uur).

## Berekend: hoe groot is de marge met 20 cases? (2026-11-27)

Voordat we herhalingen draaien: wat zeggen de bestaande metingen al? Geen nieuwe runs; bootstrap (10.000 keer 20
cases trekken met teruglegging) en een exacte McNemar-toets op dezelfde cases.

| Variant | Juist | 95%-interval (bootstrap) |
|---|---|---|
| Gemma 4 E2B `multi` | 15/20 | 11-18 |
| Qwen3.5 4B `manual` | 14/20 | 10-18 |
| Qwen3.5 4B `direct` | 13/20 | 9-17 |
| Gemma 4 E2B `native` | 12/20 | 8-16 |
| qwen2.5:3b `manual` | 12/20 | 8-16 |

| Vergelijking (A tegen B) | Alleen A juist | Alleen B juist | p (McNemar, exact) |
|---|---|---|---|
| Gemma `multi` tegen Qwen3.5 4B `manual` | 1 | 0 | 1,0 |
| Gemma `multi` tegen Qwen3.5 4B `direct` | 3 | 1 | 0,63 |
| Gemma `multi` tegen Gemma `native` | 3 | 0 | 0,25 |
| Gemma `multi` tegen altijd `valid` | 4 | 0 | 0,13 |

**Uitkomst: met 20 cases is geen enkel verschil tussen de beste varianten significant, zelfs niet het verschil met
altijd `valid` zeggen.** Gemma `multi` en Qwen3.5 4B `manual` verschillen op precies één case. De intervallen van de
top vijf overlappen bijna helemaal. "Gemma `multi` is de beste" betekent dus: kwam het hoogst uit, niet: is beter.

**Waarom herhalen hier weinig oplost**: alle metingen draaien met `temperature` 0 en een vaste seed. Het model kiest
dan steeds het meest waarschijnlijke token; een herhaling met dezelfde instellingen geeft (vrijwel) dezelfde run, en
een andere seed verandert bij temperatuur 0 niets. Herhalen meet dan alleen of de opzet deterministisch is. Het zegt
iets over de spreiding per run pas met een temperatuur boven 0, en dan is het een andere instelling dan in de
metingen. Bovendien zit de grootste onzekerheid niet in de runs maar in het aantal cases: 9 overtredingen, waarvan 3
per regel. Een kleiner interval vraagt meer cases, dus een nieuwe opname in GRFICS met meer scenario-runs.
