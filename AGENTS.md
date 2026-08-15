# Local AI trading desk instructions

This repository contains an upstream prompt layer plus an independent local runtime.

## Preserve upstream

Treat these paths as read-only upstream source material unless the human explicitly asks to update
the upstream snapshot:

- `README.md`, `SKILL.md`, `LICENSE`, `CONTRIBUTING.md`
- `skills/`, `prompts/`, `loop/`, `examples/`
- upstream documentation under `docs/`, except files prefixed with `LOCAL_` and `UPSTREAM.md`

Put local work in `src/local_trader/`, `runtime/`, `local-prompts/`, `research/`, and `tests/`.

## Hard safety boundary

- Research agents never place orders, start live trading, edit live credentials, or read secret
  files/environment variables.
- Binance is Spot/USDT, long-only, 1x. Futures, margin, shorts, DCA, and martingale are forbidden.
- Risk ceilings may only be lowered by an agent, never increased: 250 USDT capital, 80 USDT per
  position, 240 USDT total open exposure, and three open positions.
- `dry_run` remains true unless the human invokes the documented, Registry-authorized recovery
  launcher. That launcher remains `paused` and cannot enable real-money entries.
- CANARY and PRODUCTION promotions require explicit human approval through the deterministic CLI.
- Registry promotion never makes generated Python trusted. Live recovery additionally requires an
  independent manual source audit for the exact hash in `runtime/trusted-live-artifacts.json`.
- Candidate strategies are immutable after registration. Create a new version instead of editing a
  registered artifact.
- Never copy exchange secrets into code, config, tests, logs, reports, prompts, or chat output.

## Verbindlicher STARTBOT-Bedienvertrag

Vor größeren Umbauten am lokalen Bot sowie vor Änderungen an `STARTBOT.bat`, FreqUI, lokaler
Authentifizierung, dem Backtest-Bereich oder dem Paper-Launcher ist
`deep-research-report.md` im Repository vollständig zu prüfen.
Besonders verbindlich sind dort **„Verbindlicher Bedienvertrag für den lokalen Paper-Bot“** und
**„Verbindlicher Leitfaden für kommende Umbauten und die Backtest-UI“**. Zusätzlich ist
`TESTBOT_ANLEITUNG.md` zu lesen und zu erhalten.

- Ein Doppelklick auf `STARTBOT.bat` ist der normale und vollständige Startweg.
- Bei jedem normalen Start müssen Adresse, Botname, Benutzer und das aktuell gültige lokale
  Passwort sichtbar im Botfenster stehen. Nicht-interaktive Tests dürfen das Passwort nie zeigen.
- Nach erfolgreichem API-Ping muss sich eine frische FreqUI-Anmeldung öffnen. Abgelaufene
  Browser-Tokens dürfen nicht zu einem leeren Dashboard führen.
- Sicherheitsverbesserungen dürfen diesen Ablauf nicht stillschweigend verändern. Falls der
  Ablauf nicht bewahrt werden kann, muss vor der Umsetzung der Besitzer gefragt werden.
- Änderungen an diesem Ablauf brauchen einen echten Windows-End-to-End-Starttest bis zu
  `RUNNING`, sichtbaren 250 virtuellen USDT, mindestens einem Heartbeat und fehlerfreiem Log.

## Research discipline

- One falsifiable hypothesis and one major change per version.
- Closed-candle OHLCV data only; no lookahead or repainting.
- Include fees and realistic slippage assumptions.
- Validate across multiple symbols, nearby timeframes, unseen time windows, lookahead analysis, and
  recursive-indicator analysis before promotion.
- Persist failed trials as well as wins. A backtest is not evidence of future profit.
- Do not tune after seeing details from a quarantined holdout.

Run the narrowest relevant tests after changes and keep generated market data, databases, logs,
reports, credentials, and promoted live artifacts out of Git.
