# Deep Research: Der Claude-/DaviddTech-Trading-Bot aus dem Video und wie man ihn wirklich nachbaut

## Der Kernbefund

Das von dir verlinkte Video lässt sich eindeutig dem DaviddTech-Ökosystem zuordnen und wird unter dem Titel **„I Told Claude to Build the Most Profitable AI Trading Bots Possible (Insane Results)”** geführt. Entscheidend ist aber: Hinter dem gezeigten Konzept steckt **nicht ein einzelner klassischer Trading-Bot**, den man als `bot.py` herunterlädt und startet. Es ist vielmehr ein mehrstufiges **AI-Quant-Research-System**, bei dem Claude autonom Strategien entwickelt, verändert, testet, verwirft, versioniert und erneut testet. citeturn0search0

Die wichtigste Entdeckung meiner Recherche ist, dass DaviddTech tatsächlich ein passendes öffentliches GitHub-Repository veröffentlicht hat:

```text
DaviddTech/ai-trading-agent
```

Das Projekt heißt intern **AI Trader MCP** und beschreibt sich als „AI hedge fund“-Research-Desk für Claude, Codex, Cursor und andere Agenten. Es ist unter der MIT-Lizenz veröffentlicht und darf daher grundsätzlich kopiert, verändert und auch in eigenen Projekten verwendet werden. fileciteturn3file0L2-L2 fileciteturn14file0L2-L2

Der unmittelbar nutzbare Clone ist:

```bash
git clone https://github.com/DaviddTech/ai-trading-agent.git
cd ai-trading-agent
```

Aber hier kommt die entscheidende Einschränkung:

> **Das GitHub-Repository ist nicht der vollständige Bot.**

Es enthält hauptsächlich die Agenten-Prompts, Rollen, Arbeitsabläufe und Research-Logik. Die eigentliche Backtesting-/Strategie-Infrastruktur läuft über den **proprietären Trader Dev MCP Server** unter `mcp.trader.dev`. Der öffentliche Code ist also eher das „Gehirn-Handbuch“ des Systems als der vollständige Motor. fileciteturn2file0L1-L10 citeturn27search1

Meine Einschätzung nach Sichtung des Repositories, der DaviddTech-Seiten, Trader.dev, StrategyFactory, der alten DaviddTech-Ausführungssoftware sowie der öffentlich dokumentierten Claude-Mechanik lautet:

| Bestandteil | Öffentlich verfügbar? | Lokal kopierbar? |
|---|---:|---:|
| Claude-Agentenrollen | **Ja** | **Ja** |
| Strategie-Optimizer | **Ja, als Prompt/Workflow** | **Ja** |
| Risk Manager | **Ja** | **Ja** |
| Overfitting Detector | **Ja** | **Ja** |
| 24/7-Research-Loops | **Ja** | **Ja** |
| Pine-Script-Erzeugung | **Ja, durch Claude** | **Ja** |
| Trader-Dev-Backtester | Nein, SaaS | Nein |
| Strategie-Datenbank von Trader Dev | Nein | Nein |
| StrategyFactory-Bibliothek | Nein | Nein |
| Live-Signal-Monitoring | über Trader Dev | nur teilweise |
| Exchange-Ausführung | separates System | selbst nachbaubar |
| echtes ML-Training der Claude-Gewichte | **Nein** | nicht Teil des Systems |

Der wichtigste Punkt für deine Beschreibung ist deshalb:

**Ja, das System hat einen Feedback-Loop. Aber es „lernt“ nicht im klassischen Machine-Learning-Sinn. Claude wird nicht nach jedem Trade neu trainiert. Stattdessen lernt das Gesamtsystem über persistierte Strategien, Backtests, Out-of-Sample-Tests, Live-/Forward-Ergebnisse und neue Strategieversionen. Claude liest die Ergebnisse und verändert daraufhin den Code oder die Parameter.** Genau diese Unterscheidung ist für einen sauberen Nachbau entscheidend. fileciteturn5file0L2-L2 citeturn24search1turn24search5

Eine vollständige öffentlich indexierte Transkription des konkreten YouTube-Videos ließ sich während der Recherche nicht zuverlässig abrufen; YouTube selbst hat den direkten Abruf gedrosselt. Deshalb behaupte ich ausdrücklich nicht, jedes gesprochene Wort aus dem Video verifiziert zu haben. Die technische Rekonstruktion unten stützt sich stattdessen auf das **offizielle Repository des Creators, dessen aktuelle Agenten-Prompts, Trader.dev, StrategyFactory und die dazugehörige historische DaviddTech-Execution-Software**. Diese Quellen ergeben ein ziemlich eindeutiges Bild des Systems. fileciteturn3file0L2-L2 citeturn27search0turn27search1

## Was dieser „Bot“ technisch eigentlich ist

### Die Architektur

Vereinfacht besteht die Konstruktion aus sechs Schichten:

```text
                    ┌─────────────────────────────┐
                    │ Claude / AI Agent           │
                    │ Strategie + Entscheidungen  │
                    └──────────────┬──────────────┘
                                   │
                             MCP Tool Calls
                                   │
                    ┌──────────────▼──────────────┐
                    │ Trader Dev MCP              │
                    │                             │
                    │ Strategy Registry           │
                    │ Backtesting                 │
                    │ Optimization                │
                    │ Signals                     │
                    │ Performance Stats           │
                    └──────────────┬──────────────┘
                                   │
                      Pine Script / OHLCV
                                   │
                    ┌──────────────▼──────────────┐
                    │ TradingView / Markt-Daten   │
                    └──────────────┬──────────────┘
                                   │
                        Forward-/Live-Signale
                                   │
            ┌──────────────────────▼──────────────────────┐
            │ Live Monitoring / StrategyFactory /        │
            │ Trader.dev / eigener Execution Service     │
            └──────────────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │ Exchange                    │
                    │ Bybit / andere Börsen       │
                    └─────────────────────────────┘
```

Das öffentliche Repository definiert für Claude ausdrücklich einen quantitativen Research-Prozess: Strategieidee verstehen, Pine Script schreiben beziehungsweise untersuchen, Repainting und Lookahead prüfen, Strategien testen, verschiedene Symbole und Zeiteinheiten vergleichen, Schwächen berichten und nur robuste Varianten weiterverfolgen. fileciteturn4file0L2-L2

Claude bekommt über MCP unter anderem Werkzeuge für:

```text
search_strategies
create_strategy
update_strategy
fork_strategy

run_backtest
quick_backtest
optimize_strategy
compare_backtests

get_backtest_result
get_equity_curve
get_trades

get_recent_signals
get_signal_stats
list_active_alerts

promote_strategy
demote_strategy
pause_strategy
```

Die öffentliche Trader-Dev-Seite bestätigt Backtests, Parameteroptimierung und Live-Signal-Monitoring über denselben MCP-Dienst. fileciteturn3file0L2-L2 citeturn27search1

Damit wird verständlich, warum das Ganze wesentlich mächtiger ist als:

```text
strategy.py
↓
Backtest
↓
+127 %
↓
fertig
```

Stattdessen ist es näher an:

```text
Hypothese
   ↓
Strategie erzeugen
   ↓
Backtest
   ↓
Fehler diagnostizieren
   ↓
eine Änderung vornehmen
   ↓
erneut testen
   ↓
andere Coins
   ↓
andere Timeframes
   ↓
Out-of-Sample
   ↓
Parameter-Nachbarschaft
   ↓
Risk Audit
   ↓
Forward Test
   ↓
weiterentwickeln oder verwerfen
```

Genau dieser Kreislauf ist explizit im öffentlichen Strategy-Optimizer beschrieben. Pro Zyklus wird ein Kandidat genommen, eine konkrete Verbesserungshypothese formuliert, ein Fork erstellt, **eine wesentliche Variable verändert**, neu getestet und anschließend Original gegen Fork verglichen. Schlechtere Varianten werden verworfen; bessere werden persistiert. fileciteturn7file0L2-L2

### Das eigentliche „Gedächtnis“

Ein sehr wichtiger technischer Punkt: Das Gedächtnis steckt nicht ausschließlich in Claudes Conversation Context.

Das Repository schreibt sogar ausdrücklich vor, Ergebnisse **in Trader Dev zu persistieren und nicht auf Chat-Historie zu vertrauen**. Dadurch kann ein späterer Agentenlauf bestehende Strategien, Versionen, Backtests und Zustände wieder abrufen. fileciteturn5file0L2-L2

Das macht aus:

```text
LLM ohne dauerhaftes Gedächtnis
```

praktisch:

```text
LLM
  +
persistente Strategy Registry
  +
Backtest-Historie
  +
Versionsbaum
  +
Live-Signal-Statistiken
  +
Promote/Demote-Status
```

und genau dadurch entsteht der Eindruck eines sich fortlaufend verbessernden Trading-Agenten.

### Die spezialisierten Agenten

Im Repository befinden sich mittlerweile fünfzehn Rollen. Dazu gehören unter anderem ein Hedge-Fund-Manager, Quant-Mathematiker, Mean-Reversion-Entwickler, Trend-Following-Entwickler, Volatilitätsstratege, Breakout-Entwickler, Strategy Optimizer, Position Optimizer, Risk Manager, Drawdown Auditor, Overfitting Detector und Multi-Timeframe-Stratege. fileciteturn5file0L2-L2

Der Manager übernimmt beispielsweise nicht selbst die Entwicklung. Er schaut sich das vorhandene „Portfolio“ an, prüft Strategiezustände, Live-Signal-Statistiken und verfügbare Research-Ressourcen und entscheidet anschließend, welcher Spezialist als Nächstes arbeiten soll. fileciteturn9file0L2-L2

Das ist agentisch ungefähr:

```text
                  Hedge Fund Manager
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
  Quant Research     Optimizer       Risk Manager
        │                │                │
        ▼                ▼                ▼
   neue Ideen       bessere Forks      ablehnen
        │                │                │
        └────────────────┼────────────────┘
                         ▼
                  Strategy Registry
                         │
              ┌──────────┴─────────┐
              ▼                    ▼
           Backtest            Live Stats
```

Das ist viel näher an einem **automatisierten Research-Labor** als an einem einzelnen „AI-Trading-Modell“.

## Wie sein Feedback- und Lernmechanismus wirklich funktioniert

### Strategieerzeugung

Ein Research-Agent bekommt nicht einfach den Auftrag „maximiere Gewinn“, sondern soll aus einer Hypothese Regeln ableiten und daraus Pine Script erzeugen. Das Haupt-Skill-Dokument verlangt ausdrücklich mathematische Hypothesen, Backtests, mehrere Märkte und Zeiteinheiten sowie eine ehrliche Bewertung der Schwächen. fileciteturn4file0L2-L2

Beispielsweise könnte Claude auf die Hypothese kommen:

```text
Nach einer ungewöhnlich starken Volatilitätskompression
tritt häufiger als zufällig eine Volatilitätsexpansion auf.
```

Daraus könnte werden:

```text
compression =
    ATR / rolling_ATR_median < threshold

breakout =
    close > rolling_high

entry =
    compression_previous AND breakout

stop =
    entry - ATR * x

take_profit =
    entry + ATR * y
```

Anschließend beginnt aber erst der relevante Teil.

### Evaluation

Das System betrachtet nicht nur den absoluten Gewinn. Im Haupt-Skill sind unter anderem vorgesehen:

- Net Profit
- Profit Factor
- Maximum Drawdown
- Win Rate
- Average Trade
- Trade Count
- Average Win/Loss
- Long/Short-Performance
- Stabilität über Symbole
- Stabilität über Timeframes. fileciteturn4file0L2-L2

Das bedeutet:

```text
+500 % Return
```

kann schlechter bewertet werden als:

```text
+80 % Return
PF 1.6
DD 12 %
400 Trades
8/10 Märkte profitabel
mehrere Timeframes stabil
```

wenn der erste Test nur durch einen einzelnen Coin, extremen Hebel oder einen wenigen Ausreißertrades zustande gekommen ist.

### Variation und Selektion

Das ist der Teil, der fast wie evolutionäre Optimierung aussieht:

```text
Strategy v1
    │
    ├── fork → v1.1: besserer Regimefilter
    │
    ├── fork → v1.2: anderer Exit
    │
    └── fork → v1.3: ATR Stop
```

Dann:

```text
Original vs Fork
        ↓
   Testmatrix
        ↓
Risiko-adjustierter Vergleich
        ↓
 winner survives
```

Das Repository fordert dabei ausdrücklich, nur **eine wesentliche Idee pro Iteration** zu ändern, damit eine Verbesserung überhaupt einer konkreten Änderung zugerechnet werden kann. fileciteturn7file0L2-L2

Das ist aus Research-Sicht ein sehr sinnvoller Bestandteil der Konstruktion.

### Overfitting Detector

Noch interessanter ist der öffentliche `10-overfitting-detector.md`.

Dieser Agent soll Kandidaten unter anderem mit folgenden Tests angreifen:

```text
Rolling In-Sample / Out-of-Sample
Parameter Sensitivity
Cross-Pair Stability
Cross-Timeframe Stability
Random-Shuffle-Test, sofern verfügbar
Equity-Curve-Vergleich
```

Danach bekommt die Strategie einen Robustheits-/Overfitting-Score und kann zurückgestuft werden. fileciteturn6file0L2-L2

Ein beispielhafter Walk-Forward-Prozess wäre:

```text
2022 ─────── 2023 ─────── 2024 ─────── 2025 ─────── 2026

[ train ] [test]
         [ train ] [test]
                  [ train ] [test]
                           [ train ] [test]
```

also nicht:

```text
2022–2026 optimieren
2022–2026 testen
```

Das ist ein enorm wichtiger Unterschied.

### Der Risk Manager

Der Risk-Manager-Agent besitzt wiederum keinen Auftrag, Rendite zu maximieren. Er soll Strategien aktiv **demoten oder pausieren**, wenn er beispielsweise Repainting, Lookahead, stark konzentrierte Gewinne, extreme Drawdowns oder andere Warnsignale findet. Er kann auch Live-Signal-Statistiken einbeziehen. fileciteturn8file0L2-L2

Das ist konzeptionell gut:

```text
          Alpha-Agent
             │
             ▼
         "PF = 2.1!"
             │
             ▼
         Risk Agent
             │
      ┌──────┴──────┐
      │             │
   approve        reject
```

Ein System, in dem der gleiche Agent gleichzeitig maximieren und unabhängig kontrollieren soll, neigt sonst sehr schnell dazu, sich seine eigenen Resultate schönzureden.

### Forward-/Live-Feedback

Hier liegt vermutlich der Punkt, den du im Video mit „er schaut in Echtzeit, was richtig und falsch war“ meinst.

Der Manager kennt laut öffentlichem Prompt `get_signal_stats`, der Risk Manager ebenfalls; außerdem existieren Werkzeuge für aktive Alerts und aktuelle Signale. Das bedeutet, dass ein Agent nicht zwangsläufig ausschließlich historischen Backtest-P&L sehen muss, sondern auch den **nach dem Research entstandenen Signalverlauf** untersuchen kann. fileciteturn8file0L2-L2 fileciteturn9file0L2-L2

StrategyFactory beschreibt denselben größeren Produktionsprozess als regelbasierte Strategien, die zunächst backgetestet und danach unter Live-Bedingungen forward-getestet werden; die Seite zeigt außerdem eine Live-Automatisierungsinfrastruktur. Diese Performance-Zahlen und Aussagen stammen allerdings vom Anbieter selbst und sind **keine unabhängige Prüfung der Profitabilität**. citeturn27search0turn27search9

Das öffentliche AI-Trader-Repository selbst zieht hier eine klare Sicherheitsgrenze: Die Research-Loops sollen **keine Live-Orders ausführen**. Live-Ausführung ist ein separater Schritt. fileciteturn5file0L2-L2

Das halte ich für eine sehr wichtige Architekturentscheidung.

## Warum dieser Ansatz funktionieren kann – und warum die Ergebnisse trotzdem täuschen können

### Was tatsächlich gut daran ist

Der starke Teil dieses Systems ist weniger „Claude versteht den Markt besser als Menschen“, sondern die **Automatisierung des wissenschaftlichen Research-Zyklus**.

Ein Mensch schafft vielleicht:

```text
Idee
→ Pine schreiben
→ Backtest
→ Parameter ändern
→ vergleichen
```

mehrmals am Abend.

Ein Agentensystem kann denselben Prozess theoretisch hunderte oder tausende Male wiederholen und dabei automatisch Strategien versionieren, Resultate vergleichen und schlechte Varianten eliminieren. Genau hierfür sind der Strategy Optimizer und die Agentenrollen konstruiert. fileciteturn7file0L2-L2

Claude Code selbst arbeitet ebenfalls nach einem Agentic Loop aus Kontext sammeln, Aktionen durchführen, Ergebnisse prüfen und anhand der Resultate erneut handeln. Ein Tool wie Trader Dev erweitert genau diesen Loop um Backtesting- und Strategie-Werkzeuge. citeturn24search1turn25search1

Dadurch entsteht:

```text
Reason
   ↓
Act
   ↓
Measure
   ↓
Update hypothesis
   ↓
Act again
```

und nicht nur:

```text
LLM → Textantwort
```

### Warum Multi-Market-Tests sinnvoll sind

Eine Strategie, die nur auf `DOGEUSDT 37m` mit exakt einem Parametersatz funktioniert, ist wesentlich verdächtiger als eine einfache Logik, deren Charakter bei BTC, ETH, SOL und mehreren angrenzenden Timeframes erhalten bleibt.

Das Repository nutzt genau diese Idee als Robustheitskriterium. fileciteturn6file0L2-L2

Das beweist zwar keinen zukünftigen Edge, erschwert aber offensichtliches Curve Fitting.

### Warum das Overfitting-Problem trotzdem gewaltig bleibt

Hier steckt die größte Gefahr des ganzen Videos.

Die wissenschaftliche Literatur zur **Probability of Backtest Overfitting** zeigt, dass bei der Auswahl aus sehr vielen getesteten Investmentstrategien selbst klassische Holdout-Verfahren unzuverlässig werden können. Je mehr Varianten man ausprobiert, desto größer wird die Wahrscheinlichkeit, irgendwann rein zufällig eine fantastisch aussehende Strategie zu finden. citeturn20search15turn20search16

Das ist für einen autonomen Claude-Bot besonders relevant:

```text
10 Strategien testen
→ überschaubares Multiple-Testing-Problem

100 Strategien testen
→ größer

10.000 Strategien / Varianten testen
→ extrem groß
```

Das **Deflated Sharpe Ratio** wurde genau deshalb entwickelt: Es korrigiert Performance-Erwartungen unter anderem für Selection Bias und Multiple Testing. citeturn29search2

Darum würde ich beim Nachbau zusätzlich speichern:

```text
strategy_trials_total
hypothesis_family
parameter_trials
datasets_seen
oos_windows_seen
final_holdout_seen
```

Das öffentliche DaviddTech-System führt zwar Robustheitsprüfungen durch, aber die Schwellenwerte in den Prompts wie bestimmte Profit-Factor-Grenzen oder der eigene „Overfitting Index“ sind **DaviddTech-Heuristiken und keine wissenschaftlich validierten Naturgesetze**. Das muss man auseinanderhalten. fileciteturn6file0L2-L2

### Das gefährliche OOS-Paradoxon

Angenommen:

```text
Train:
2022–2024

OOS:
2025
```

Claude testet:

```text
v1 → OOS schlecht
```

Dann sieht Claude das Ergebnis und baut:

```text
v2
```

und testet wieder auf 2025.

Dann:

```text
v3
v4
v5
...
v100
```

immer wieder auf 2025.

Spätestens jetzt ist 2025 **kein echtes Out-of-Sample mehr**. Informationen aus diesem Zeitraum fließen indirekt in die Entwicklung ein.

Das ist genau die Art von Strategieauswahlproblem, vor der die Backtest-Overfitting-Literatur warnt. citeturn20search15turn29search2

Mein Nachbau würde deshalb drei Ebenen verwenden:

```text
┌─────────────────────────┐
│ Research / Train        │
│ Claude darf alles sehen │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│ Validation              │
│ begrenzte Verwendung    │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│ Quarantined Holdout     │
│ Agent sieht ihn erst    │
│ bei Promotion           │
└───────────┬─────────────┘
            ↓
┌─────────────────────────┐
│ Live Shadow / Forward   │
│ keine Optimierung       │
└─────────────────────────┘
```

Das wäre statistisch wesentlich sauberer.

### Repainting ist ein reales Problem

Bei TradingView ist besonders wichtig, dass historische und Live-Berechnung voneinander abweichen können. TradingView dokumentiert ausdrücklich, dass Repainting auftreten kann und insbesondere höhere Timeframe-Abfragen über `request.security()` sorgfältig behandelt werden müssen. citeturn29search0turn29search4

Ein Backtest kann sonst sinngemäß aussehen wie:

```text
Signal historisch:
"Oh, hier hätte ich perfekt gekauft."
```

obwohl diese Information zum realen Zeitpunkt noch gar nicht bestätigt war.

TradingView warnt insbesondere vor Future-Leak durch falsch verwendetes `lookahead`. citeturn29search5

Daher würde ich die von Claude erzeugten Pine-Skripte **nicht nur vom LLM beurteilen lassen**, sondern zusätzlich automatisch statisch auf Konstrukte wie diese untersuchen:

```text
request.security
lookahead
calc_on_every_tick
barstate
timenow
pivot logic
future offsets
```

### Gebühren und Slippage

Ein weiterer Grund, warum Backtest-Resultate live schlechter werden können, sind unrealistische Fills.

TradingView unterstützt ausdrücklich die Simulation von Slippage und weist darauf hin, dass reale Ausführungspreise vom erwarteten Preis abweichen. citeturn29search3turn29search13

Darum sollte jede Strategie mindestens mit mehreren Annahmen getestet werden:

```text
Normal:
fees + normal slippage

Stress:
fees + 2× slippage

Extreme:
fees + 3× slippage
```

und idealerweise:

```text
profit_after_costs > 0
```

auch im Stress-Szenario.

## Was auf GitHub tatsächlich vorhanden ist

### Der wichtigste Fund

Der aktuelle relevante öffentliche Code ist:

```bash
git clone https://github.com/DaviddTech/ai-trading-agent.git
```

Die Root-Struktur enthält unter anderem:

```text
README.md
SKILL.md

docs/
examples/
prompts/
skills/
loop/
```

und damit praktisch die komplette offene Agenten-/Prompt-Schicht. fileciteturn2file0L1-L10

Das Repository ist ausdrücklich MIT-lizenziert:

```text
MIT License
Copyright (c) 2026 DaviddTech
```

und erlaubt Nutzung, Kopie, Modifikation und Weiterverteilung unter den Lizenzbedingungen. fileciteturn14file0L2-L2

### Der offizielle Schnellstart

DaviddTech gibt für Claude Code folgende Verbindung vor:

```bash
claude mcp add \
  --transport sse \
  --scope user \
  trader-dev \
  https://mcp.trader.dev/sse
```

Anschließend soll der Agent die `SKILL.md` lesen und kann über Trader Dev die Research-Werkzeuge verwenden. fileciteturn13file0L2-L2

Praktisch:

```bash
git clone https://github.com/DaviddTech/ai-trading-agent.git
cd ai-trading-agent

claude mcp add \
  --transport sse \
  --scope user \
  trader-dev \
  https://mcp.trader.dev/sse

claude mcp list
claude
```

Dann beispielsweise:

```text
Read SKILL.md.

Confirm Trader Dev MCP is connected.

Do not optimize anything yet.
Inspect the available strategy registry and available MCP tools first.
```

Die Trader-Dev-Seite bestätigt dieses MCP-Setup und verwendet einen eigenen API-Key für die Verbindung. citeturn27search1

### Der 24/7-Modus aus dem Repository

DaviddTech schlägt beispielsweise vor:

```text
/loop 15m read loop/01-quant-mathematician.md and execute it
```

oder:

```text
/loop 15m read loop/06-strategy-optimizer.md and execute it
```

oder:

```text
/loop 15m read loop/08-risk-manager.md and execute it
```

Die Idee ist, unterschiedliche Research-Spezialisten parallel regelmäßig laufen zu lassen. fileciteturn5file0L2-L2

Ein sinnvoller Desk sähe etwa so aus:

```text
15m     Quant Research
15m     Strategy Optimizer
30m     Position Optimizer
1h      Risk Manager
6h      Overfitting Detector
daily   Portfolio/Manager Review
```

Das entspricht sehr eng der öffentlichen DaviddTech-Konfiguration. fileciteturn5file0L2-L2

### Eine wichtige Entdeckung zu „24/7“

Hier gibt es inzwischen einen Unterschied zwischen der Marketingformulierung im Repository und der tatsächlichen aktuellen Claude-Code-Funktion.

Anthropics offizielle Dokumentation sagt, dass ein normales `/loop` **sessiongebunden ist**, nur arbeitet, solange Claude Code läuft, und wiederkehrende Loop-Aufgaben nach **sieben Tagen automatisch auslaufen**. Für dauerhaftes Scheduling empfiehlt Anthropic stattdessen langlebige Routines, Desktop Scheduled Tasks oder eine eigene Automatisierung. citeturn25search0

Das bedeutet:

```text
/loop 15m
```

ist hervorragend zum Experimentieren, aber **nicht das, worauf ich deinen späteren 365-Tage-Produktionsbetrieb bauen würde**.

Für echten 24/7-Betrieb würde ich den Agenten über:

```text
systemd
       oder
Docker supervisor
       oder
Kubernetes/ECS scheduler
       oder
Claude Agent SDK
```

starten und jede Iteration als kontrollierten Job ausführen.

Anthropic bietet dafür inzwischen ein Agent SDK an, das denselben Agentic Loop programmatisch zugänglich macht und externe MCP-Server direkt anbinden kann. Dabei lassen sich auch erlaubte MCP-Tools explizit einschränken. citeturn24search5turn25search1turn25search3

### Der ältere DaviddTech-Trading-Bot

Ich habe außerdem ein älteres öffentliches DaviddTech-Repository gefunden:

```text
daviddme/DaviddTech-tradingview-webhook-trading-bot
```

Das ist interessant, weil es zeigt, wie DaviddTech historisch die **Execution-Seite** aufgebaut hat.

Die Architektur war:

```text
TradingView Pine Strategy
        │
        ▼
TradingView Alert
        │
        ▼
HTTP Webhook
        │
        ▼
Python / Flask
        │
        ▼
Exchange API
        │
        ▼
Order
```

Das Repository beschreibt ausdrücklich eine Flask-Anwendung, die TradingView-Webhooks empfängt und daraus Exchange-Orders erzeugt; damals wurden unter anderem FTX-/Bybit-Integrationen diskutiert. fileciteturn12file0L2-L2

**Diesen alten Bot würde ich heute nicht unverändert produktiv einsetzen.** Er ist aber sehr wertvoll, weil er bestätigt, dass Research/Signal und Execution im DaviddTech-Ökosystem schon lange getrennte Komponenten sind. fileciteturn12file0L2-L2

Hinzu kommt, dass TradingView selbst ausdrücklich darauf hinweist, dass Webhooks gelegentlich nicht zugestellt werden können, nur Ports 80/443 unterstützt werden und der Empfänger innerhalb von drei Sekunden reagieren muss. TradingView warnt außerdem davor, vertrauliche Credentials in Webhook-Payloads einzubauen. citeturn20search0turn20search1

Deshalb würde ich einen modernen Receiver so bauen:

```text
TradingView
    │
    ▼
API Gateway / nginx
    │
    ▼
Authenticate
    │
    ▼
ACK < 100 ms
    │
    ▼
Persistent Queue
    │
    ├── duplicate detection
    ├── risk checks
    ├── position reconciliation
    └── kill switch
            │
            ▼
       Exchange API
```

nicht:

```text
Webhook
   ↓
direkt Market Order
```

TradingView sagt sogar ausdrücklich, dass Pine-Strategien auf TradingView selbst weiterhin auf Backtesting beschränkt sind; direkte automatisierte Strategieausführung auf einem Brokerage-Account ist nicht die native Funktion. citeturn29search10

## Wie ich den Bot für echten 24/7-Betrieb nachbauen würde

Es gibt zwei grundsätzlich unterschiedliche Wege.

### Variante mit maximaler Ähnlichkeit zum Video

Das wäre:

```text
Claude
   +
DaviddTech/ai-trading-agent
   +
Trader Dev MCP
   +
TradingView/Pine
   +
eigener Execution Layer
```

Das ist die höchste Übereinstimmung mit dem öffentlich sichtbaren DaviddTech-System.

Die Research-Seite:

```text
┌────────────────────────────────────────────┐
│ AI RESEARCH PLANE                          │
│                                            │
│ Claude                                     │
│  ├─ Manager                                │
│  ├─ Quant Researcher                       │
│  ├─ Optimizer                              │
│  ├─ Risk Manager                           │
│  └─ Overfit Detector                       │
│                                            │
│         ↓ MCP                              │
│                                            │
│ Trader Dev                                 │
│  ├─ Strategy Registry                      │
│  ├─ Backtests                              │
│  ├─ Optimization                           │
│  └─ Signal Stats                           │
└────────────────────────────────────────────┘
                     │
               promotion gate
                     │
                     ▼
┌────────────────────────────────────────────┐
│ FORWARD TEST PLANE                         │
│                                            │
│ Paper / Shadow Signals                     │
│ PnL                                        │
│ Slippage                                   │
│ Signal statistics                          │
│ Drawdown                                   │
└────────────────────────────────────────────┘
                     │
               promotion gate
                     │
                     ▼
┌────────────────────────────────────────────┐
│ EXECUTION PLANE                            │
│                                            │
│ Position Sizer                             │
│ Portfolio Risk                             │
│ Order Manager                              │
│ Exchange Adapter                           │
│ Kill Switch                                │
└────────────────────────────────────────────┘
                     │
                     ▼
                 Exchange
```

Das entspricht auch der Philosophie des offenen Repositories, Research und reale Ausführung nicht unkontrolliert miteinander zu vermischen. fileciteturn5file0L2-L2

### Variante vollständig unter deiner Kontrolle

Hier würde ich Trader Dev komplett ersetzen.

Dann wäre mein bevorzugter Aufbau:

```text
Claude Agent SDK
       │
       ▼
Own Research MCP
       │
 ┌─────┼───────────────────────┐
 ▼     ▼                       ▼
Data  Backtester        Strategy Registry
 │      │                       │
 │      └──────────┬────────────┘
 │                 ▼
 │             Evaluator
 │                 │
 │                 ▼
 │           Promotion Engine
 │                 │
 ▼                 ▼
Realtime Feed → Shadow Trader
                   │
                   ▼
               Risk Engine
                   │
                   ▼
              Live Executor
```

Für den Trading-Kern sehe ich aktuell zwei besonders sinnvolle Open-Source-Basen.

**Freqtrade** ist eine sehr pragmatische Lösung für Crypto. Das Projekt enthält Backtesting, Dry-Run, Live-Trading, Hyperparameter-Optimierung, persistente Zustände und FreqAI. FreqAI kann Modelle im Live-Betrieb periodisch auf neuen Marktdaten retrainieren und anschließend jeweils das aktuellste Modell für eingehende Candles verwenden. Das wäre tatsächlich echtes adaptives ML und damit noch näher an deiner Formulierung „er bekommt immer wieder neue Daten und lernt daraus“ – allerdings wäre das dann technisch ein anderer Lernmechanismus als im DaviddTech-Claude-Loop. citeturn28search0turn28search4

**NautilusTrader** wäre die anspruchsvollere, professionellere Basis. Es verwendet denselben eventbasierten Kern für Research, Simulation und Live-Ausführung und besitzt aktuell unter anderem einen offiziellen Bybit-Data/Execution-Adapter. Das ist besonders interessant, wenn langfristig Tick-, Orderbook-, Multi-Venue- oder komplexe Portfolio-Systeme geplant sind. citeturn28search1turn28search2

Meine Bewertung:

| Lösung | Ähnlichkeit zum Video | Self-hosted | Echtzeit | echtes ML-Retraining | Produktionskontrolle |
|---|---:|---:|---:|---:|---:|
| DaviddTech + Trader Dev | **Sehr hoch** | teilweise | ja | nein | mittel |
| Claude + Freqtrade | hoch auf Konzeptebene | **ja** | ja | optional **ja** | hoch |
| Claude + NautilusTrader | mittel-hoch | **ja** | **sehr gut** | selbst ergänzen | **sehr hoch** |

### Was ich für deinen Fall bevorzugen würde

Ich würde **nicht sofort den gesamten DaviddTech-Stack ersetzen**.

Ich würde zuerst exakt das öffentliche System kopieren und damit feststellen:

```text
Was macht Trader Dev?
Welche MCP Tools liefert es?
Welche Strategiedaten speichert es?
Welche Resultate bekommt Claude?
Welche Forward-Daten bekommt Claude?
Wie sehen Promotion/Demotion konkret aus?
```

Danach können wir exakt jene Teile ersetzen, bei denen wir unabhängig werden wollen.

So entsteht:

```text
Phase A
DaviddTech exakt replizieren

          ↓

Phase B
Trader Dev beobachten und Schnittstelle dokumentieren

          ↓

Phase C
eigene Backtesting Engine parallel aufbauen

          ↓

Phase D
Resultate TraderDev vs eigener Engine vergleichen

          ↓

Phase E
Trader Dev optional entfernen

          ↓

Phase F
eigener 24/7 Research + Forward + Execution Stack
```

Das ist erheblich weniger riskant als zu versuchen, aus dem Video heraus sofort das gesamte System neu zu erfinden.

### Der richtige Realtime-Mechanismus

Für einen vollständig eigenen Crypto-Stack würde ich Marktdaten nicht alle paar Minuten per REST pollen.

Beispielsweise bietet Bybit einen WebSocket-Kline-Feed; das Feld `confirm=true` bedeutet, dass die entsprechende Candle abgeschlossen ist. Genau daran würde ich candle-basierte Strategien auslösen, um nicht während einer noch schwankenden Kerze andere Entscheidungen als im historischen Backtest zu treffen. citeturn21search2

Also:

```text
Bybit WebSocket
     │
     ├── candle update, confirm=false
     │        ↓
     │     nur speichern
     │
     └── candle close, confirm=true
              ↓
        feature calculation
              ↓
        strategy signal
              ↓
           risk check
              ↓
          paper/live
```

Falls später Orderbook-Strategien hinzukommen, bietet Bybit ebenfalls Snapshot-/Delta-WebSocket-Feeds mit verschiedenen Tiefen. Das wäre allerdings **nicht mehr exakt DaviddTech**, denn der öffentliche AI-Trader-Desk beschränkt seine Strategieentwicklung ausdrücklich auf TradingView-/OHLCV-kompatible Informationen. citeturn21search3 fileciteturn5file0L2-L2

Für Orders bietet Bybit V5 separate Order-Endpunkte; ein angenommener Order-Request ist dabei asynchron, und Bybit empfiehlt die anschließende Bestätigung des tatsächlichen Status über WebSocket. citeturn21search0

Darum muss der Execution-Teil immer:

```text
signal_id
order_id
client_order_id
requested_qty
filled_qty
average_fill
position_before
position_after
```

persistieren.

Sonst kann nach Netzwerkausfällen aus:

```text
"Hat die Order funktioniert?"
```

schnell:

```text
"Ich weiß es nicht, also schicke ich sie noch einmal."
```

werden.

Genau das darf ein 24/7-System niemals tun.

## Mein konkreter Blueprint für deinen Nachbau

Ich würde das fertige System nicht als einen Prozess bauen, sondern in klar getrennte Services.

### Research Controller

Der zentrale Agent.

```text
research-controller
```

Aufgaben:

```text
Strategien auswählen
Hypothesen erzeugen
Strategien forken
Backtests auslösen
Resultate bewerten
nächsten Versuch bestimmen
```

Nicht erlaubt:

```text
Live Orders
API Keys lesen
Positionsgrößen eigenmächtig erhöhen
```

Anthropics Agent SDK unterstützt genau für solche Anwendungen kontrollierte Toolfreigaben und MCP-Server. Es ist wesentlich geeigneter für einen dauerhaften Dienst als eine dauerhaft offene interaktive Claude-Code-Sitzung. citeturn25search1turn25search3

### Strategy Registry

Ich würde nicht nur Pine-Code speichern, sondern beispielsweise:

```sql
strategy
--------
id
parent_id
name
code_hash
strategy_family
hypothesis
created_at
created_by

strategy_version
----------------
id
strategy_id
version
source_code
parameters
dataset_version
fee_model
slippage_model

evaluation
----------
strategy_version_id
symbol
timeframe
period_start
period_end
sample_type
net_profit
profit_factor
max_drawdown
sharpe
trade_count
avg_trade

research_trial
--------------
id
strategy_version_id
hypothesis_tested
trial_number
dataset_seen
result
decision

forward_result
--------------
strategy_version_id
timestamp
signal
market_price
paper_fill
actual_fill
pnl

lifecycle
---------
status
reason
promoted_at
demoted_at
```

Das ist der eigentliche Schlüssel für echtes „Lernen“.

Ohne diese Historie läuft Claude Gefahr, dieselben Ideen immer wieder neu zu entdecken.

### Research Dataset Isolation

Ich würde die Daten physisch beziehungsweise logisch trennen:

```text
datasets/
├── research/
├── validation/
├── holdout/
└── live/
```

Der normale Strategy Agent erhält:

```text
research/
validation/
```

aber **niemals**:

```text
holdout/
```

Der Holdout Evaluator läuft separat.

Claude bekommt anschließend lediglich:

```json
{
  "passed": true,
  "score": 0.73,
  "promotion_allowed": true
}
```

und möglichst nicht die komplette Equity Curve.

Dadurch kann Claude nicht anfangen:

> „Hm, im Mai 2025 verliert er – ich ändere mal die Regel…“

und dadurch heimlich den Holdout optimieren.

### Trial Ledger

Zusätzlich würde ich jeden Versuch zählen:

```text
Strategy family: volatility_breakout
Trials: 473
```

und statistische Bewertung davon abhängig machen.

Eine Strategie, die nach:

```text
3 Hypothesen
```

gefunden wurde, verdient mehr Vertrauen als derselbe Sharpe-Wert, wenn zuvor:

```text
12.000 Kombinationen
```

ausprobiert wurden.

Genau hierfür ist die Literatur zu Backtest Overfitting und Deflated Sharpe Ratio relevant. citeturn20search15turn29search2

### Promotion Pipeline

Bei mir bekäme eine Strategie folgende Zustände:

```text
IDEA
 ↓
RESEARCH
 ↓
VALIDATED
 ↓
HOLDOUT_PASSED
 ↓
SHADOW
 ↓
PAPER
 ↓
CANARY
 ↓
PRODUCTION
 ↓
DEGRADED
 ↓
PAUSED
```

Claude dürfte allein bewegen:

```text
IDEA
RESEARCH
VALIDATED
```

Der statistische Evaluator:

```text
VALIDATED
→ HOLDOUT_PASSED
```

Der Forward-Test:

```text
HOLDOUT_PASSED
→ SHADOW
→ PAPER
```

und erst ein separater Risk Controller dürfte:

```text
PAPER
→ CANARY
```

freigeben.

Damit darf das LLM **niemals seine eigene Strategie erzeugen, testen, gutheißen und sofort mit echtem Kapital starten**.

### Forward-Test als echtes Lernsignal

Hier kommt genau der Teil rein, den du aus dem Video besonders interessant findest:

```text
Backtest erwartete:
PF     1.71
Win    58 %
Avg    +0.31 %
DD     11 %

Forward beobachtet:
PF     1.12
Win    49 %
Avg    +0.05 %
DD     8 %
```

Nun bekommt der Research-Agent:

```text
Backtest-to-live degradation detected.

Expected average trade: +0.31 %
Observed: +0.05 %

Investigate:
- slippage?
- entry timing?
- market regime?
- fee assumptions?
- signal repainting?
- asymmetric long/short degradation?

Do not alter the currently deployed version.
Create a new fork.
```

Das ist meiner Meinung nach die wichtigste Verbesserung gegenüber einem typischen AI-Trading-Demo.

**Die Production-Version bleibt eingefroren. Claude experimentiert ausschließlich auf einem neuen Fork.**

Also:

```text
Production v14
      │
      └────────────── stays untouched

Research:
v14
 └── v15 candidate
      └── v16 candidate
```

Erst nach erneuter vollständiger Validierung kann ein Nachfolger v14 ablösen.

### Drift Detection

Zusätzlich würde ich automatisiert vergleichen:

```text
Backtest expectancy
vs
rolling live expectancy

Backtest hit rate
vs
live hit rate

Backtest holding time
vs
live holding time

expected slippage
vs
actual slippage

expected drawdown distribution
vs
live drawdown
```

Bei deutlicher Abweichung:

```text
NORMAL
   ↓
WATCH
   ↓
DEGRADED
   ↓
PAUSED
```

und **nicht automatisch höhere Positionsgröße oder aggressivere Optimierung**.

### Execution Service

Dieser Service wäre komplett AI-frei.

```text
execution-service
```

Er bekommt nur:

```json
{
  "strategy_id": "abc",
  "signal_id": "xyz",
  "symbol": "BTCUSDT",
  "action": "BUY",
  "risk_budget": 0.0025,
  "stop": 113420,
  "take_profit": 118900
}
```

und entscheidet deterministisch:

```text
Ist Strategy aktiv?
Ist Signal neu?
Ist Markt erlaubt?
Ist Exposure erlaubt?
Ist Drawdown-Limit okay?
Gibt es bereits Position?
Ist Stop vorhanden?
Ist Daily Loss Limit erreicht?
```

Erst dann wird eine Order erzeugt.

Claude hat keinerlei Exchange-Secret.

### 24/7-Prozessmodell

Der fertige Stack sähe bei mir so aus:

```text
┌────────────────────────────────────────────┐
│ research-agent.service                     │
│ alle 15–60 Minuten                         │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ validator.service                          │
│ bei neuen Kandidaten                       │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ overfit-auditor.service                    │
│ alle paar Stunden                          │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ market-data.service                        │
│ permanent                                  │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ shadow-trader.service                      │
│ permanent                                  │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ execution.service                          │
│ permanent                                  │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ risk-watchdog.service                      │
│ permanent                                  │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ postgres                                   │
│ strategy + trials + orders + metrics       │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ redis / queue                              │
│ event transport                            │
└────────────────────────────────────────────┘
```

Das lässt sich auf einem Linux-System sauber mit Docker Compose betreiben und später praktisch unverändert auf EC2/ECS/Kubernetes übertragen.

### Sicherheitsgrenzen

Für die Live-Ausführung würde ich mindestens folgende Bedingungen hart codieren und **nicht dem LLM überlassen**:

```text
MAX_DAILY_LOSS
MAX_ACCOUNT_DRAWDOWN
MAX_POSITION_NOTIONAL
MAX_TOTAL_EXPOSURE
MAX_CORRELATED_EXPOSURE
MAX_OPEN_POSITIONS
MAX_LEVERAGE
MAX_ORDER_FREQUENCY
MAX_SLIPPAGE
STALE_MARKET_DATA_TIMEOUT
KILL_SWITCH
```

Dazu:

```text
LIVE_TRADING=false
```

als Default.

Der Weg wäre:

```text
backtest
   ↓
shadow
   ↓
dry/paper
   ↓
exchange testnet
   ↓
tiny canary allocation
   ↓
production
```

Freqtrade selbst empfiehlt ebenfalls ausdrücklich, vor echtem Kapital zunächst Dry-Run zu verwenden. citeturn28search0

## Abschließende Bewertung

**Der Bot aus dem Video ist real als technisches Konzept und ein erheblicher Teil davon ist tatsächlich öffentlich verfügbar.** Das wichtigste Repository ist `DaviddTech/ai-trading-agent`; es enthält die Claude-Rollen, den 24/7-Research-Desk, Optimizer, Risk Manager und Overfitting Detector und steht unter MIT-Lizenz. fileciteturn14file0L2-L2

**Nicht öffentlich ist jedoch der zentrale Trader-Dev-Unterbau.** Das Repository ruft einen gehosteten MCP-Dienst auf, der Backtests, Strategie-Registry, Optimierung und Live-Signal-Funktionen bereitstellt. Ein bloßes `git clone` reproduziert deshalb noch nicht das vollständige System. citeturn27search1

**Der „selbstlernende“ Charakter wird häufig missverstanden.** In der öffentlich sichtbaren Version verändert Claude nicht seine eigenen Modellgewichte anhand erfolgreicher oder erfolgloser Trades. Der Agent bildet vielmehr einen äußeren Lernzyklus: Hypothese → Code → Backtest → Diagnose → Fork → Robustheitstest → persistiertes Ergebnis → nächste Iteration. Live-/Forward-Signalstatistiken können zusätzlich in spätere Bewertungen einfließen. fileciteturn7file0L2-L2 fileciteturn8file0L2-L2

**Und genau dieser äußere Lernzyklus ist kopierbar.**

Die sinnvollste Zielarchitektur für deinen geplanten 24/7-Betrieb wäre daher nicht, Claude unkontrolliert „so lange Strategien probieren zu lassen, bis etwas profitabel aussieht“, sondern das DaviddTech-Prinzip in einer strengeren Form umzusetzen:

```text
                    CLAUDE
                       │
                Hypothesis Engine
                       │
                       ▼
                Strategy Fork
                       │
                       ▼
               Research Backtest
                       │
                       ▼
              Robustness Testing
                       │
             ┌─────────┴─────────┐
             │                   │
           reject              pass
                                 │
                                 ▼
                         Hidden Holdout
                                 │
                        ┌────────┴───────┐
                        │                │
                      reject           pass
                                         │
                                         ▼
                                  Shadow Trading
                                         │
                                         ▼
                                  Forward Test
                                         │
                              ┌──────────┴──────────┐
                              │                     │
                           degraded                pass
                              │                     │
                            learn                   ▼
                              │                  Canary
                              │                     │
                              └── new fork          ▼
                                               Production
                                                    │
                                                    ▼
                                             Live Monitoring
                                                    │
                                     ┌──────────────┴──────────────┐
                                     │                             │
                                  healthy                       drift
                                     │                             │
                                     ▼                             ▼
                                  continue                 pause + research
```

Das wäre funktional genau das, was an dem Video spannend ist: **kein einmaliger Backtest, sondern eine dauerhaft laufende Research-, Validierungs-, Forward-Test- und Feedback-Maschine.**

Der entscheidende Unterschied zu einem simplen Trading-Bot wäre damit:

```text
Normaler Bot:
Regeln → Markt → Trades

DaviddTech-Prinzip:
AI → Regeln → Tests → Bewertung → neue Regeln → Tests → Forward-Daten
                                                     │
                                                     └── Feedback

Sauberer eigener Nachbau:
AI Research
   ↓
statistisch isolierte Validierung
   ↓
Forward-/Realtime-Beobachtung
   ↓
deterministisches Risk Management
   ↓
Execution
   ↓
Live-Ergebnisse
   ↓
neuer Research-Fork
```

Und **diesen letzten Aufbau würde ich einem direkten Blind-Clone klar vorziehen**: Die offene DaviddTech-Agentenlogik kann dabei nahezu unverändert als Ausgangspunkt dienen, während wir Trader Dev schrittweise entweder weiterverwenden oder durch einen eigenen Freqtrade-/NautilusTrader-basierten Research- und Execution-Kern ersetzen. So bleibt die interessante Idee aus dem Video erhalten, ohne dass das System aufgrund endloser Backtest-Optimierung lediglich sehr effizient lernt, die Vergangenheit perfekt vorherzusagen. citeturn20search15turn29search2turn28search0turn28search1

## Verbindlicher Bedienvertrag für den lokalen Paper-Bot

> Ergänzt am 13. August 2026 auf ausdrücklichen Wunsch des Besitzers. Dieser Abschnitt ist bei jedem späteren Patch am Start-, Anmelde-, Authentifizierungs- oder FreqUI-Ablauf als verbindliche Produktanforderung zu behandeln.

Der Bot soll für einen technisch nicht spezialisierten Benutzer mit genau einem Doppelklick auf `STARTBOT.bat` benutzbar sein. Der gewünschte Ablauf ist bewusst einfach und darf nicht stillschweigend durch einen abstrakteren oder vermeintlich eleganteren Ablauf ersetzt werden:

1. `STARTBOT.bat` wird per Doppelklick gestartet.
2. Ein sichtbares Bot-/Konsolenfenster zeigt **bei jedem Start**, nicht nur beim ersten Start:
   - Adresse: `http://127.0.0.1:8080`
   - Botname: `Testbot`
   - Benutzer: `testbot`
   - das aktuell gültige lokale Passwort
   - den deutlichen Hinweis `KEIN ECHTGELD / DRY-RUN`.
3. Sobald die lokale API wirklich bereit ist und `/api/v1/ping` mit `pong` antwortet, öffnet sich automatisch die FreqUI-Anmeldung.
4. Ein alter oder abgelaufener Browser-Login darf nicht zu einem leeren Dashboard führen. Beim neuen Botstart muss gezielt nur die gespeicherte Anmeldung dieses lokalen Bots verworfen und eine frische Anmeldung angeboten werden. Andere in FreqUI hinterlegte Bots dürfen dabei nicht gelöscht werden.
5. Der Benutzer gibt Botname, Adresse, Benutzer und Passwort ein und gelangt anschließend zum vollständigen Dashboard.
6. Das Botfenster bleibt geöffnet, solange der Paper-Bot läuft. Beendet wird kontrolliert mit `Strg+C`; danach wird der Abschlussbericht erzeugt.

Die Bedienbarkeit ist Teil der Funktion und keine unverbindliche Komfortfunktion. Sicherheitsverbesserungen müssen diesen Ablauf erhalten. Konkret bedeutet das:

- Das Passwort darf zufällig erzeugt, mit Windows-DPAPI geschützt und ausschließlich lokal gespeichert werden.
- Es darf nicht in Git, Quellcode, Konfigurationsdateien, HTML, URLs, Sitzungsmanifeste oder Logs geschrieben werden.
- Weil der Besitzer es zur Anmeldung benötigt, darf und soll das bereits sicher entschlüsselte Passwort beim normalen `STARTBOT`-Start einmal sichtbar im lokalen Konsolenfenster ausgegeben werden.
- `InitializeOnly`, automatisierte Tests und nicht interaktive Diagnosebefehle dürfen das Passwort niemals ausgeben.
- JWT- und WebSocket-Schlüssel dürfen pro Start erneuert werden. Wenn dadurch alte Browser-Tokens ungültig werden, muss der Startablauf automatisch zu einer frischen Anmeldung führen und darf nicht einfach das scheinbar leere Dashboard öffnen.
- Ein festes, öffentliches Standardpasswort im Repository ist keine zulässige Abkürzung.

Die unveränderten Paper-Risikogrenzen lauten:

```text
Kapital:             250 virtuelle USDT
Je Position:         maximal 80 USDT
Gesamtexposure:      maximal 240 USDT
Offene Positionen:   maximal 3
Märkte:              BTC/USDT, ETH/USDT, SOL/USDT
Modus:               Binance Spot, long-only, 1x, ausschließlich Dry-Run
```

Jeder Patch, der `STARTBOT.bat`, den Auth-Helfer, den Paper-Launcher, den gesperrten Freqtrade-Wrapper oder die FreqUI-Anbindung verändert, ist vor der Übergabe mit einem echten Windows-End-to-End-Durchlauf zu prüfen. Die Mindestabnahme lautet:

```text
Doppelklick STARTBOT.bat
  -> Zugangsdaten sichtbar
  -> frische Loginansicht öffnet sich
  -> angezeigte Zugangsdaten funktionieren
  -> Dashboard zeigt Testbot und 250 USDT (dry)
  -> Strategie PaperTrendBreakout250V1 läuft im Zustand RUNNING
  -> BTC/ETH/SOL sind geladen
  -> mindestens ein regulärer Heartbeat
  -> keine ERROR-/Traceback-Einträge
  -> Strg+C erzeugt einen Abschlussbericht
```

Wenn eine Änderung diesen Ablauf nicht sicher bewahren kann, muss sie vor der Umsetzung mit dem Besitzer besprochen werden. Sie darf nicht eigenmächtig als neue Standardbedienung eingeführt werden.

## Verbindlicher Leitfaden für kommende Umbauten und die Backtest-UI

> Ergänzt am 15. August 2026 auf ausdrücklichen Wunsch des Besitzers. Dieser Bericht ist nicht nur eine einmalige Videoanalyse, sondern zugleich ein fortlaufender Leitfaden und ein Ort für dauerhafte Projektnotizen. Vor jedem größeren Umbau am lokalen Bot oder seiner Bedienoberfläche ist der aktuelle Stand dieses Berichts zuerst zu lesen und mit dem tatsächlichen System abzugleichen. Falls neue Erkenntnisse, Korrekturen oder ausdrücklich geänderte Wünsche des Besitzers vorliegen, ist der Leitfaden nachvollziehbar zu aktualisieren, bevor widersprechende Umbauten vorgenommen werden.

### Bestehende UI bewahren

Die aktuelle FreqUI gefällt dem Besitzer sehr gut und ist als bestehende Produktanforderung zu erhalten. Ihr Erscheinungsbild, ihre vorhandenen Bereiche und der gewohnte Bedienablauf sollen bei kommenden Arbeiten nicht unnötig ersetzt, neu gestaltet oder vereinfacht werden. Insbesondere bleiben die vorhandenen Navigationsbereiche wie Trades, Dashboard, Chart und Log in ihrer vertrauten Optik und Funktion erhalten.

Die derzeit gewünschte sichtbare Erweiterung ist genau ein zusätzlicher Navigationsbereich mit dem Namen `Backtest`. Er soll sich optisch in die bestehende UI einfügen und wie ein normaler Bestandteil derselben Oberfläche wirken. Eine separate, gestalterisch fremde Ersatzoberfläche ist nicht das gewünschte Endergebnis. Technische Zwischenschritte dürfen die laufende UI nicht beschädigen und müssen so geplant werden, dass die gebündelte FreqUI weiterhin start-, login- und updatefähig bleibt.

### Gewünschter Backtest-Ablauf

Der Bereich `Backtest` dient dazu, die aktuell im Paper-Bot verwendete Strategie rückwirkend zu simulieren. Der Benutzer wählt **eine Kryptowährung einzeln** aus:

- `BTC/USDT`
- `ETH/USDT`
- `SOL/USDT`

Anschließend wählt er einen unterstützten Zeitraum, zunächst beispielsweise ein oder drei Jahre, und startet den Backtest über eine klare Schaltfläche. Erst in diesem Moment werden die benötigten öffentlichen Binance-Spot-Marktdaten heruntergeladen oder fehlende Daten ergänzt. Ein bloßes Öffnen der UI darf keinen großen Datendownload auslösen.

Der Backtest muss sich so verhalten, als wäre die aktuelle Botstrategie im gewählten historischen Zeitraum für genau das ausgewählte Paar gelaufen. Er verwendet die zu diesem Test gehörende dokumentierte Strategieversion, ihren tatsächlichen Timeframe, 250 virtuelle USDT Startkapital sowie realistische Gebühren und Slippage. Er darf weder `STARTBOT.bat` aufrufen noch einen zweiten Trading-Bot starten, den laufenden Paper-Bot stoppen oder verändern, private Binance-Endpunkte verwenden, Zugangsdaten lesen oder echte Orders ermöglichen.

### Ergebnisdarstellung und Aussagekraft

Die Ergebnisse sollen verständlich innerhalb des Backtest-Bereichs erscheinen und mindestens Folgendes zeigen:

- getestetes Paar, Strategieversion, Zeitraum und verwendete Daten
- Anzahl der Trades sowie durchschnittliche Haltedauer und Kapitalbindung
- Gewinn oder Verlust in USDT und Prozent
- Gebühren und angenommene Slippage
- Winrate, Profit Factor und maximaler Drawdown
- Monats- und Jahresaufschlüsselung sowie Zeiten ohne Position
- klare Kennzeichnung `NO_TRADES`, falls kein Handel zustande kam

Ein Backtest ist kein Gewinnversprechen. Gute Ergebnisse dürfen nicht allein durch immer neue Anpassungen an denselben historischen Zeitraum erzeugt werden. Spätere Strategieänderungen werden versioniert und müssen zusätzlich auf ungesehenen Zeiträumen, mehreren Marktphasen und im Paper-/Forward-Betrieb geprüft werden. Ziel ist nicht bloß Sicherheit oder möglichst seltenes Handeln, sondern ein belastbares Verhältnis aus Rendite, Risiko und tatsächlicher Kapitalnutzung. Wenn Kapital über lange Zeit nahezu ungenutzt bleibt oder die Rendite im Verhältnis zur Bindungsdauer zu gering ist, gilt das als überprüfbares Strategieproblem und nicht automatisch als Erfolg.

### Abnahmebedingung für den Umbau

Der kommende Backtest-Umbau ist erst abgeschlossen, wenn die bestehende UI und der vollständige `STARTBOT.bat`-Bedienvertrag unverändert funktionieren, der zusätzliche Bereich in derselben Optik erreichbar ist und BTC, ETH sowie SOL jeweils separat getestet werden können. Nach jeder Änderung an FreqUI, Authentifizierung oder Launcher bleibt der bereits festgelegte echte Windows-End-to-End-Test bis `RUNNING` verpflichtend. Zusätzlich muss ein vollständiger Backtestlauf ohne Einfluss auf den parallel laufenden Paper-Bot geprüft werden.
