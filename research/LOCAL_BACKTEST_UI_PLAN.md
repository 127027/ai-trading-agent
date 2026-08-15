# Lokaler Plan: Video-Prinzip, aktueller Paper-Bot und Backtest-UI

Stand: 2026-08-14

## Einordnung des Videos

Das YouTube-Video ist als Inspiration zu behandeln, nicht als belastbare
technische Wahrheit. Marketingvideos koennen Ergebnisse, Auswahl der gezeigten
Tests, Auslassungen und Tool-Details so darstellen, dass ein direkter Nachbau
nicht reproduzierbar ist.

Der belastbare Kern aus `deep-research-report.md` im Repository ist:

- Es geht nicht um einen einzelnen magischen Bot, sondern um einen Research-Loop.
- Das DaviddTech-Prinzip ist: Hypothese -> Strategie -> Backtest -> Diagnose -> Fork -> Robustheitstest -> Paper/Forward-Test -> neue Version.
- Claude lernt dabei nicht seine Modellgewichte neu. Das System lernt ueber gespeicherte Strategien, Backtests, Reports, Paper-Ergebnisse und Versionen.
- Der oeffentliche Teil liefert Rollen, Prompts und Arbeitsweise. Der proprietaere Trader-Dev-Unterbau aus dem Video ist nicht vollstaendig lokal kopierbar.
- Deshalb muss unser Nachbau eigene, reproduzierbare Beweise schaffen: lokale Backtests, Paper-Trades, Risiko-Grenzen und ehrliche Reports.

## Aktueller Bot im Vergleich

Der aktuelle lokale Bot ist kein vollstaendiger DaviddTech-Research-Desk. Er ist ein sicherer Freqtrade-Paper-Bot:

- Binance Spot, long-only, kein Margin, keine Futures, kein Hebel.
- Dry-run mit 250 virtuellen USDT.
- Maximal 80 USDT je Position, maximal 240 USDT Gesamtexposure, maximal 3 Positionen.
- Paare: BTC/USDT, ETH/USDT, SOL/USDT.
- Strategie: `PaperTrendBreakout250V1`.
- Timeframe: 1h.
- Entry: Donchian-/Trend-Ausbruch ueber das verschobene 72h-Hoch, bestaetigt durch EMA50 > EMA200, steigende EMA200, ADX, ATR-Prozent, Volumen und gruene Kerze.
- Exit: ROI, Stoploss -5.5 Prozent, Schluss unter verschobenem 12h-Tief oder Trendbruch unter EMA50.

Das ist als erster Paper-Test sinnvoll, aber noch kein selbstoptimierender Agent. Der naechste sinnvolle Schritt ist nicht sofort neue Coins oder Live-Trading, sondern ein reproduzierbarer Backtest-Bereich fuer den aktuellen Bot.

## Naechste Aufgabe: Backtest-Bereich

Ziel: In der lokalen Bedienoberflaeche soll es einen Bereich `Backtest` geben. Dort kann der Nutzer fuer die aktuelle Paper-Strategie historische Tests starten.

Erster Umfang:

- Backtest fuer jeweils genau ein ausgewaehltes Paar: BTC/USDT, ETH/USDT oder SOL/USDT.
- Standardzeitraum: letzte 3 Jahre, alternativ 1 Jahr.
- Daten werden erst beim Start des Backtests heruntergeladen oder ergaenzt.
- Es werden ausschliesslich oeffentliche Binance-Spot-OHLCV-Daten geladen.
- Es werden keine Binance-Secrets gelesen und keine privaten Endpunkte verwendet.
- Der laufende Paper-Bot darf nicht doppelt gestartet und nicht gestoppt werden.
- Der Backtest muss die aktuelle Paper-Strategie `PaperTrendBreakout250V1` und das Overlay `config-paper-runtime.json` verwenden, nicht die alte `CompressionBreakout250`-Baseline.

Wichtige Korrektur zum aktuellen Bestand:

- `runtime/scripts/backtest.ps1` testet aktuell ueber `_common.ps1` noch `$script:StrategyName = "CompressionBreakout250"` und nutzt kein `config-paper-runtime.json`.
- `runtime/scripts/download-data.ps1` laedt aktuell `15m`. Fuer die laufende Paper-Strategie muss mindestens `1h` geladen werden.
- Fuer spaetere feinere Fill-/Exit-Pruefungen kann zusaetzlich `5m` oder `15m` als Detail-Timeframe sinnvoll sein, aber der erste reproduzierbare Test soll bewusst einfach bleiben.

## Vorgeschlagene technische Umsetzung

### 1. Backtest-Runner

Neues lokales Modul oder Skript, zum Beispiel:

```text
runtime/scripts/start-paper-backtest.ps1
runtime/export_backtest_report.py
```

Der Runner soll:

1. Eingaben validieren: Paar, Zeitraum, Strategie, Timeframe.
2. Daten downloaden:

```powershell
freqtrade download-data `
  --config runtime/user_data/config.json `
  --config runtime/user_data/config-paper-public.json `
  --userdir runtime/user_data `
  --timeframes 1h `
  --pairs <AUSGEWAEHLTES_PAAR> `
  --trading-mode spot `
  --days 1095
```

3. Backtest starten:

```powershell
freqtrade backtesting `
  --config runtime/user_data/config.json `
  --config runtime/user_data/config-paper-public.json `
  --config runtime/user_data/config-paper-runtime.json `
  --userdir runtime/user_data `
  --strategy PaperTrendBreakout250V1 `
  --timeframe 1h `
  --pairs <AUSGEWAEHLTES_PAAR> `
  --dry-run-wallet 250 `
  --fee 0.002 `
  --enable-protections `
  --cache none `
  --export trades `
  --backtest-directory runtime/user_data/backtest_results/paper-trend-breakout-250-v1/<run-id> `
  --breakdown month year
```

4. Ergebnisse in einen eigenen Report normalisieren:

```text
runtime/user_data/backtest_results/paper-trend-breakout-250-v1/<run-id>/
  manifest.json
  summary.json
  summary.md
  raw-freqtrade-output.txt
  freqtrade-result.json
```

### 2. UI-Integration

FreqUI ist eine installierte, gebuendelte Weboberflaeche (`FreqUI 3.1.1`). Direkte Aenderungen an den installierten Frontend-Dateien sind fragil, weil ein `freqtrade install-ui` sie ueberschreiben kann.

Robuster Plan:

- Erst einen eigenen lokalen API-/HTML-Bereich in denselben loopback-only Server einhaengen, z.B. `/testbot-backtest`.
- Dort eine Paarauswahl fuer BTC/USDT, ETH/USDT oder SOL/USDT, eine Zeitraumwahl fuer ein oder drei Jahre sowie die Befehle `Backtest starten` und `letzten Backtest-Bericht anzeigen` anbieten.
- Danach pruefen, ob ein Link/Button aus FreqUI heraus sauber und updatefest eingebunden werden kann.
- Wenn eine echte FreqUI-Navigation `Backtest` gefordert bleibt, muss das als zweiter Schritt sauber gegen die gebuendelte UI-Version 3.1.1 gepatcht und mit End-to-End-Test abgesichert werden.

### 3. Sicherheitsregeln

- Kein Start von `STARTBOT.bat` aus dem Backtest heraus.
- Kein zweiter Trade-Prozess.
- Keine Live-Keys, keine Secrets, keine echten Orders.
- Backtests duerfen den laufenden Paper-Dryrun nicht veraendern.
- Reports muessen klar sagen: Ruecktest ist kein Gewinnversprechen.
- Erst nach belastbaren Backtests und laengerem Paper-Lauf duerfen neue Coins diskutiert werden.

## Abnahmekriterien fuer die naechste Umsetzung

- Der Bot startet weiterhin per `STARTBOT.bat` wie im Bedienvertrag.
- FreqUI/Login bleibt unveraendert funktionsfaehig.
- Backtest-Bereich ist erreichbar.
- Ein Backtest fuer das einzeln ausgewaehlte Paar ueber 1h-Daten laedt fehlende Daten nach.
- Der Backtest nutzt `PaperTrendBreakout250V1` und 250 USDT Startkapital.
- Ergebnisbericht zeigt je Pair:
  - Trades
  - Gewinn/Verlust in USDT
  - Prozent
  - Profit Factor
  - Winrate
  - Max Drawdown
  - Monats-/Jahresaufschluesselung
- Wenn keine Trades entstehen, wird das klar als `NO_TRADES` berichtet und nicht als Fehler oder Erfolg verkauft.
- Der laufende Paper-Bot bleibt waehrenddessen `RUNNING`.
