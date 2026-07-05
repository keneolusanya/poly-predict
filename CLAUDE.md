# PolyPredict — Claude Code Context

Research-to-execution trading system for football prediction markets,
currently scoped to the 2026 FIFA World Cup. Dixon-Coles model → edge
detection vs. live Polymarket prices → fractional Kelly sizing →
automated order execution → monitoring dashboard.

Venue and tournament/data-source are set in `config.py` (`VENUE`,
`TOURNAMENT`, `DATA_SOURCE`) — a static, hand-edited config, not
auto-detected. Read from it rather than hardcoding assumptions, so
switching to club leagues post-tournament, or to Kalshi after a US
relocation, is a config change, not a rewrite.

**Trading strategy (default): value betting, held to resolution.** The
edge is `model_probability − market_implied_price`; we take the +EV side
of *mispriced* markets (not simply "back the likely winner" — an
efficiently-priced favorite has no edge), size with fractional Kelly, and
hold to settlement ($1 if right, $0 if wrong). There is deliberately no
sell/exit logic in the base design — profit is realized at resolution, and
the Dixon-Coles model produces one static per-fixture probability, so it
has no natural sell signal. A **convergence-trading** extension (sell back
into the book when price moves to fair value, to realize edge early and
free capital) is a considered future direction — see the "Future
extension" section in `PROJECT_PLAN.md`. Don't build exit logic into the
base execution engine unless that extension is explicitly picked up.

See `PROJECT_PLAN.md` for the full day-by-day build plan, checkpoints, and
tool guidance (this project also uses Cursor for some days — see that file
for which). See `README.md` for architecture overview and setup checklist.

## Stack
- Python throughout. Optional C++ (pybind11) stretch goal for the
  fair-value calc only — not in scope unless explicitly asked.
- `py_clob_client_v2` for Polymarket CLOB (prices, order books, orders).
  Note: v1 (`py-clob-client`) is archived and has a known ghost-order-book
  bug — never suggest switching to v1.
- Polymarket Gamma API (`gamma-api.polymarket.com`) for market/event
  discovery — unauthenticated, no client library needed, plain `requests`.
- Polymarket Data API (`data-api.polymarket.com`) for live balance/
  positions (Day 4) and trade history (Day 6 dashboard) — likely
  unauthenticated for read access since positions are on-chain/public.
  Confirm exact endpoint shapes when implementing rather than assuming.
- SQLite for all storage (order book snapshots, positions, trade log).
  Do not introduce Postgres/other DBs unless asked.
- Streamlit for the dashboard unless told otherwise.
- `python-dotenv` for secrets — see the `.env` section below.

## Critical constraints — do not violate without explicit confirmation

1. **Never write real values into `.env` yourself.** You can create or
   edit the *structure* of `.env`/`.env.example` (variable names, comments,
   host URLs), but the actual private key, funder address, and API
   credentials must be entered by the user directly, by hand. Do not
   generate placeholder-looking values that could be mistaken for real
   ones, and never print, log, or echo the contents of `.env`.

2. **Default to `DRY_RUN=true` in all execution code.** Any code that
   places real orders must check this flag and skip actual submission
   (just log what would have been sent) unless the user has explicitly
   said they want live orders placed. Never flip this default yourself.

3. **Never use market-derived data as a model feature** (e.g. bookmaker
   odds columns, if a future data source includes them) — this creates
   circularity with the "model finds edge vs. market" premise. The
   current data source (`martj42/international_results`) has no such
   columns, but this rule applies to any future source too. Only
   date/teams/goals/neutral-flag columns are valid model inputs.

4. **Kelly sizing must always be fractional (0.25–0.5×), computed against
   the LIVE account balance (query it each time, never a static/remembered
   number), with hard caps on both per-market and total exposure as a
   percentage of that live balance.** Never implement or suggest full
   Kelly, and never remove the exposure caps to "simplify" the code. A
   drawdown circuit breaker (halt new signals if losses exceed ~20% of
   starting balance) must stay in place and must require manual
   re-enabling — never have it auto-resume.

5. **Twilio credentials follow the same rule as `.env` above** — you may
   scaffold the SMS-sending code and message template, but the user
   enters their own Account SID, Auth Token, and phone numbers by hand.

5. **This project is NOT meant to run as a fully unsupervised bot.** It's
   semi-autonomous with a human checkpoint: signals are generated
   automatically, but going from DRY_RUN to live, and any change to
   position-sizing/risk logic, should prompt a check-in rather than being
   silently changed or auto-approved. Flag this if asked to "just make it
   fully automatic."

## Working style
- Follow `PROJECT_PLAN.md`'s day structure — don't jump ahead to later
  days' work unless asked.
- Each day has a ✅ checkpoint — treat these as real gates, not
  suggestions. Don't mark something done or move on if a checkpoint
  condition isn't actually met.
- If a day's checkpoint fails, debug in place rather than working around
  it by weakening the checkpoint.
