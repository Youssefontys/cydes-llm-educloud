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
| 2026-11-19 | Drie dingen tegelijk: bewijs afgedwongen (geen oordeel zonder volledig bewijs), `PAGE` 10→30, `num_predict`-cap 600 | Verbetert afgedwongen bewijs de kwaliteit? | **Nee, averechts.** Volledig bewijs ging naar 100%, maar recall stortte in: `manual` miste 8 van de 9 echte overtredingen (allemaal als `valid` bestempeld), tegen 67% recall vóór de fix. `native` en `mcp` zakten ook. Omdat drie dingen tegelijk veranderden, weten we niet welke het deed. | Isoleren: `PAGE` terug naar 10, afdwinging aan laten, klein testen op `native`. |

## Hypothese die nu getest wordt

**Alle transacties in één grote brok (PAGE 30) is slechter dan ze in kleinere stukken (PAGE 10, zoals voorheen)
doornemen**, omdat een klein model een enkele afwijkende transactie makkelijker mist in één lange tekst dan in een
paar kortere stukken. Test: `native`, 4-6 cases, bewijs-afdwinging aan, `PAGE` terug naar 10 — vergelijk recall met
de PAGE-30-meting van 2026-11-19 op dezelfde cases.

## Volgende kandidaat, pas na de PAGE-test

**Kwantisatie van hetzelfde model.** We draaien steeds qwen2.5:3b in Ollama's standaardkwantisatie (Q4_K_M) zonder
dat ooit te hebben getest tegen een andere. Dat is een as die nog niemand heeft aangeraakt, en die past binnen
"beperkte middelen": geen ander aantal parameters, alleen een andere compressie ervan.

- **Q8_0** (minder lossy): meer geheugen, iets trager, mogelijk preciezer bij het vergelijken van registerranges —
  relevant omdat de taak draait om exacte getallen vergelijken, waar afrondingsruis een rol kan spelen.
- Een lagere kwantisatie (Q3/Q2) zou juist laten zien hoe weinig je kan weghalen voor het echt stukloopt.

Niet gelijktijdig met de PAGE-test: eerst PAGE isoleren, dan pas kwantisatie als los experiment, anders weten we
straks weer niet welke van de twee een verschil maakte.
