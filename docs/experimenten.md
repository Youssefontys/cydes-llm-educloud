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
