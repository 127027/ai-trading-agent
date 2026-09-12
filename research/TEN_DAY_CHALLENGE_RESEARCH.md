# Deep Research: autonome Binance-10-Tage-Challenge

## Ergebnis der Architektur-Recherche

Das Ziel dieses Forschungszweigs ist bewusst enger und härter definiert als ein gewöhnlicher Jahres-Backtest: Ein identischer, eingefrorener Bot soll mit **100 virtuellen USDT** an möglichst vielen beliebigen Starttagen innerhalb eines Jahres innerhalb von zehn Tagen mindestens **200 USDT realisiertes Kapital** erreichen. Das ist ein Forschungs- und Selektionsziel, keine Renditezusage.

Ein einzelner Jahres-Backtest beantwortet diese Frage nicht sauber. Wenn der Bot früh gewinnt, handelt er später mit einem größeren Konto; spätere Perioden werden dadurch mit dem Ergebnis früherer Perioden vermischt. Deshalb startet der neue Verifier für jedes fortlaufende Zehn-Tage-Fenster einen eigenständigen Freqtrade-Backtest mit erneut exakt 100 USDT. Für den festgelegten Zeitraum 2025-09-01 bis 2026-09-01 entstehen **356 unabhängige, täglich versetzte Fenster**.

Die Verdopplung in zehn Tagen entspricht etwa 7,18 % geometrischer Tagesrendite. Zehn Prozent täglich würden aus 100 nach zehn Tagen ungefähr 259 machen. Beides ist extrem aggressiv; deshalb darf eine einzelne erfolgreiche Periode nicht als Nachweis einer robusten Strategie gelten.

## Warum die vorhandene Repository-Basis weiterverwendet wird

`127027/ai-trading-agent` enthält bereits eine lokale Freqtrade-Runtime, eine persistente Strategy Registry, Paper-Trading-Schutzmechanismen, Tests und mehrere Research-Rollen. Der bestehende lokale Research-Desk ist absichtlich fail-closed: `research/Start-ResearchDesk.ps1` stoppt autonome lokale Codex-Zyklen, weil eine Schreib-Sandbox auf demselben Windows-Benutzer keine ausreichende Lese-/Secret-Isolation garantiert.

Diese Schranke wird **nicht** entfernt. Der neue autonome Forschungsweg läuft stattdessen in frischen GitHub-hosted Runnern. Exchange-Secrets sind für historische Forschung nicht erforderlich. Der vorhandene `STARTBOT.bat`-Ablauf, die 250-USDT-Paper-Konfiguration und bestehende Live-Recovery-Schranken bleiben unverändert.

## Backtesting-Engine: Freqtrade

Freqtrade ist für die erste Version die konsistenteste Engine, weil das Repository Freqtrade bereits auf Version 2026.7 pinnt und seine Runtime-/Validierungsschicht darauf aufbaut. Die offizielle Freqtrade-Dokumentation deckt genau die benötigten Funktionen ab: historische Daten, Backtesting mit konfigurierbarem Startguthaben und Gebühren, Hyperopt, Dry-run, Lookahead-Analyse sowie Recursive-Indicator-Analyse.

Primärquellen:

1. Freqtrade Backtesting: https://www.freqtrade.io/en/stable/backtesting/
2. Freqtrade Data Download: https://www.freqtrade.io/en/stable/data-download/
3. Freqtrade Hyperopt: https://www.freqtrade.io/en/stable/hyperopt/
4. Freqtrade Lookahead Analysis: https://www.freqtrade.io/en/stable/lookahead-analysis/
5. Freqtrade Recursive Analysis: https://www.freqtrade.io/en/stable/recursive-analysis/
6. Freqtrade Strategy Customization: https://www.freqtrade.io/en/stable/strategy-customization/

Der aktuelle Freqtrade-Quellcode bestätigt außerdem, dass der eigene `FeatherDataHandler` OHLCV-Daten in das von Freqtrade erwartete Format schreibt. Deshalb erzeugt der neue Binance-Downloader keine selbst erfundene Dateistruktur, sondern verwendet Freqtrades DataHandler direkt.

## Historische Daten: Binance Public Data

Für reproduzierbare GitHub-Läufe wird das offizielle öffentliche Binance-Archiv unter `data.binance.vision` verwendet. Das dazugehörige offizielle Repository `binance/binance-public-data` dokumentiert die Spot-Kline-Archive. Für Spot-Daten ab 2025-01-01 verwendet Binance Mikrosekunden-Zeitstempel; der Downloader erkennt die Zeitstempelgröße und normalisiert sie nach UTC.

Primärquellen:

7. Binance Public Data Repository: https://github.com/binance/binance-public-data
8. Binance Public Data Archive: https://data.binance.vision/

Die erste liquide Marktmenge besteht aus BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, XRP/USDT und ADA/USDT. Der Bot handelt in dieser Phase ausschließlich Spot, long-only und ohne Hebel, Margin, Shorts, DCA oder Martingale.

## Datenquarantäne gegen Overfitting

Der Datensatz wird vor der Optimierung fest geteilt:

| Bereich | Zeitraum | Verwendung |
| --- | --- | --- |
| Training | 2025-09-01 bis 2026-05-01 | Hyperopt / Kandidatensuche |
| Validation | 2026-05-01 bis 2026-07-01 | Champion-vs-Challenger |
| Blind Holdout | 2026-07-01 bis 2026-09-01 | einmalige finale Prüfung |

Die Trennung ist nicht nur eine Konvention. Der erste Suchlauf lädt physisch nur Daten bis 2026-07-01. Damit kann der Suchalgorithmus den Blind-Holdout nicht versehentlich lesen. Erst die Finalisierungsphase erhält den Rest des Jahres; danach werden keine Parameter mehr anhand dieses Holdouts optimiert.

## Erster Bot-Kandidat

`TenDayMomentumV1` startet mit einer falsifizierbaren Hypothese: Ausbrüche über vorherige Hochs können auf liquiden Binance-Spot-Märkten kurzfristig bessere Erwartungswerte besitzen, wenn Trend, ADX, Volatilität, RSI und Volumen dasselbe Momentum-Regime bestätigen.

Verwendet werden ausschließlich abgeschlossene bzw. verschobene Referenzkerzen für Donchian-Hochs, Volumenbasis und Exit-Kanal. Optimierbar sind unter anderem Breakout-Lookback, EMA-Längen, ADX-Schwelle, RSI-Bereich, ATR-Untergrenze, Breakout-Puffer, Volumenfaktor und Exit-Länge. Die Strategie ist ausdrücklich **research-only** und verweigert sowohl Live- als auch Dry-run-Runtime-Starts.

Für einen späteren Forward-Test existiert separat `TenDayMomentumPaperV1`. Diese Klasse akzeptiert Runtime-Start nur bei Dry-run, Binance Spot, USDT, höchstens 100 konfigurierten USDT, genau einer offenen Position, ohne Shorts oder Position Adjustment und ohne Force Entry. Live-Start schlägt im Code fehl.

## Kostenmodell

Der Backtest verwendet zunächst effektiv **0,15 % Kosten pro Seite**. Das setzt sich als konservatives Forschungsmodell aus 0,10 % Exchange-Fee-Annahme plus 0,05 % Slippage-Proxy zusammen. Es ist keine Behauptung, Binance verlange stets 0,15 % Gebühren. Die Standard-Candle-Simulation modelliert reale Slippage nicht vollständig; deshalb wird die zusätzliche Reibung vorerst als Fee-Aufschlag eingebaut.

## Hyperopt-Zielfunktion

Eine Zielfunktion, die nur Jahresprofit maximiert, optimiert am eigentlichen Auftrag vorbei. `TenDayChallengeLoss` bildet aus geschlossenen Trades Tagesrenditen und daraus rollierende Zehn-Tage-Renditen. Sie belohnt besonders den Anteil der Perioden mit mindestens +100 %, berücksichtigt aber auch Median, unteres Renditequantil, Drawdown sowie zu geringe oder extreme Handelsfrequenz.

Diese Loss-Funktion ist nur der schnelle Suchfilter. Der entscheidende Test bleibt der unabhängige Prozess-Verifier mit komplett neuem Wallet je Zeitfenster.

## Exakter 10-Tage-Verifier

`rolling_windows.py` startet pro Fenster einen separaten Freqtrade-Prozess mit:

- exakt 100 USDT Startguthaben;
- exakt zehn Tagen Timerange;
- deaktiviertem Backtest-Cache;
- identischer Kostenannahme;
- aktivierten Protections;
- 5-Minuten-Detailkerzen unter der 15-Minuten-Strategie;
- exportierter Trade-Historie.

Ein Zieltreffer zählt erst, wenn **geschlossene Trades** das realisierte simulierte Kapital auf mindestens 200 USDT heben. Ein kurzzeitig hoher unrealiserter Kerzengewinn zählt nicht. Ausgegeben werden JSON, CSV und Markdown mit Trefferquote, mittlerem/medianem/schlechtestem/bestem Endkapital, Drawdown und einer explizit definierten Near-Ruin-Quote (realisierter Kontostand <= 10 USDT).

## Champion-/Challenger-Agent

`evolve.py` wiederholt bis zum Zeitbudget:

1. Hyperopt auf Trainingsdaten mit neuem Seed.
2. Exakte Rolling-Window-Validierung des neuen Kandidaten auf ungesehenen Validation-Daten.
3. Vergleich mit dem aktuellen Champion.
4. Nur bei besserem Validation-Score wird der Challenger Champion.
5. Schlechtere Parameter werden auf den letzten Champion zurückgesetzt.
6. Generation, Score, Parameter und Ergebnisse werden persistent gespeichert.

Damit kann der nächste Lauf am bestehenden Forschungsstand weiterarbeiten, statt dieselben Experimente wieder von null zu starten.

## GitHub-Orchestrierung

GitHub dokumentiert für einen GitHub-hosted Job ein maximales Laufzeitlimit von sechs Stunden. Ein ehrlicher neun Stunden langer Einzeljob ist deshalb nicht möglich. Der Workflow ist segmentiert und checkpoint-fähig; jeder Block bleibt unter dem Plattformlimit.

Primärquellen:

9. GitHub Actions Limits: https://docs.github.com/en/actions/reference/limits
10. GitHub Workflow Syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

Der Branch-Workflow führt zuerst Tests und Linting aus, lädt öffentliche Binance-Daten, führt mehrere Hyperopt-/Validation-Generationen aus und persistiert kompakte Ergebnisse. In der Finalisierungsphase wird der Champion eingefroren, der komplette Jahresdatensatz geladen, die 356-Fenster-Prüfung durchgeführt und anschließend Freqtrades Lookahead-/Recursive-Diagnostik gestartet. Rohdaten und große Logs werden nicht in Git eingecheckt.

## Was als Erfolg gilt

Nicht ausreichend sind:

- ein spektakulärer Einzel-Backtest;
- ein einziges erfolgreiches Zehn-Tage-Fenster;
- ein Hyperopt-Score;
- eine schöne Jahreskurve;
- ein Test ohne Gebühren;
- eine nachträglich ausgewählte Startperiode.

Entscheidend ist die reproduzierbare Trefferquote des eingefrorenen Kandidaten über alle 356 täglichen Startfenster samt Blind-Holdout, Kostenmodell und Qualitätsdiagnostik. Auch eine hohe historische Trefferquote garantiert keine zukünftige Rendite und rechtfertigt noch keinen Echtgeldbetrieb.

Die erste autonome Phase darf daher korrekt mit **„Ziel nicht nachgewiesen“** enden. In diesem Fall werden der beste Kandidat, alle verfügbaren Kennzahlen und der nächste Forschungsansatz gespeichert. Das ist ein valides Ergebnis; eine erfundene 10-%-Tagesrendite wäre keines.

## Ausbau nach dem ersten mechanisch erfolgreichen Lauf

Sobald Datenpipeline, Hyperopt, Verifier und Persistenz zuverlässig laufen, sollte die Suchbreite wachsen statt nur einen Breakout immer feiner zu fitten: Mean Reversion, Volatility Expansion, Cross-Sectional Momentum und Regime-spezifische Champions sind die nächsten sinnvollen Familien. Jede neue Familie muss durch denselben Beweispfad: Training -> ungesehene Validation -> eingefrorener Holdout -> Anti-Bias-Diagnostik -> Paper Forward Test.

Ein LLM/Codex-Agent kann später neue Hypothesen und Strategiedateien in einer isolierten Umgebung vorschlagen. Annahme oder Ablehnung bleibt dagegen deterministisch anhand reproduzierbarer Tests. Das hält die kreative Suche vom eigentlichen Evidenz-Gate getrennt.
