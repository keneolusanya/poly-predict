# PolyPredict — Detailed Build Plan

Each day has: sub-steps in order, a "you know you're on track if" checkpoint,
and common failure points to watch for. Work top to bottom — don't start a
sub-step until the previous one's checkpoint passes.

## Tooling split (Cursor vs Claude Code)

You have both, so use each for what it's better at rather than picking one:

- **Cursor** — tight loop, in-editor, you want to read every line as it's
  written. Use for anything where a silent mistake would poison downstream
  work.
- **Claude Code** — multi-step, cross-file, clear success criterion you can
  check at the end. Use for scaffolding, wiring, and debugging that spans
  files, where reviewing the final diff is enough.

Each day below is tagged with the suggested tool.

## Config — venue, tournament, data source

Single source of truth read by every module (execution, data pipeline,
signal generator) instead of hardcoding assumptions inline. Create early
(Day 1), update by hand whenever what you're trading changes (World Cup
ends → back to club leagues; you relocate → Kalshi instead of Polymarket).

```python
# config.py
VENUE = "polymarket"           # or "kalshi"
TOURNAMENT = "world_cup_2026"  # or "premier_league"
DATA_SOURCE = "martj42/international_results"  # or football-data.co.uk
```

This is intentionally static/manual — you always know in advance what
you're trading, so there's no need for the system to auto-detect it.

---

## Day 1 — Plumbing
**Tool: Claude Code** — low-stakes scaffolding, well-defined success criteria (scripts run, checkpoints pass)

1. Create Polymarket account (email signup — avoids MetaMask allowance setup)
2. Deposit $50-100 USDC on Polygon
3. `pip install -r requirements.txt`
4. Run `python data/discover_markets.py`
   - This IS "knowing what football markets are currently tradeable" —
     it queries Polymarket's Gamma API for active events live right now.
     No separate market-tracking logic needed; just re-run this whenever
     you want a current read (e.g. switching from World Cup to club
     leagues later — same script, adjust the keyword filter below).
   - ✅ Checkpoint: `football_markets.json` exists and has >0 entries
   - ⚠️ If 0 entries: print the raw event titles from `fetch_active_events()`
     before filtering — the keyword list is a guess, adjust it to match
     what's actually live right now. For World Cup scope, filter on
     "world cup" / "fifa" / round names (round of 16, quarter-final, etc.)
     rather than club league keywords.
5. Pick one `token_id` from that file, run `python data/check_book.py <token_id>`
   - ✅ Checkpoint: midpoint is between 0 and 1, best bid < best ask, no
     ghost-book warning
   - ⚠️ If you get the 0.01/0.99 warning: try a different, more liquid
     market (higher volume events have real books)

**End of day:** you can list live football markets and read real prices.
No private key touched yet.

---

## Day 2 — Data pipeline
**Tool: Claude Code** for the poller loop and DB wiring (2a) — well-defined, multi-file (schema + loop + storage). **Cursor** if you're hand-tuning the schema or debugging why prices look frozen (2a checkpoint failure) — want to be reading closely there.

### 2a. Polymarket order book poller
1. Design the snapshot schema: `token_id, timestamp, best_bid, best_ask,
   bid_size, ask_size, midpoint`
2. Write a loop that calls `check_book.py`'s `snapshot()` on a fixed
   interval (start with every 60s — tighten later if needed) for a
   handful of token_ids
3. Write snapshots to SQLite (simplest — no server setup)
   - ✅ Checkpoint: let it run 10 minutes, query the table, confirm
     timestamps are evenly spaced and prices aren't frozen/repeating
     identically (a sign the poller is failing silently and returning
     cached data)

> **Discovery refresh cadence (design note — build when going continuous, not now).**
> Discovery and polling run on two different clocks: **prices** change
> second-to-second (poller, 60s), but the **market universe** changes only
> hourly/daily (new fixtures listed as the bracket fills in; markets resolve
> after each match). So `discover_markets.py` should re-run on a *slow*
> cadence, not the poll interval.
> - **For now: manual.** Re-run `discover_markets.py` before a polling
>   session. Matches the human-in-the-loop ethos; don't build a scheduler yet.
> - **When continuous (Day 7 concern):** decouple them — a scheduled
>   discovery job (every few hours) rewrites `football_markets.json`, and the
>   poller *reloads* its token list on an interval (~30–60 min) so newly-listed
>   markets enter the rotation without a restart. Discovery already filters out
>   resolved markets, and the poller's own drop-logic handles ones that resolve
>   *between* refreshes.
> - **Downstream implications:** the poller currently calls `load_tokens()`
>   once at startup, so a running poller won't see new markets until it reloads
>   or restarts. DB continuity is safe (snapshots key on stable `token_id`).
>   `football_markets.json` is a regenerated cache (gitignored), safe to
>   overwrite. Day-4 signal coverage depends on discovery freshness — a stale
>   list silently misses newly-listed fixtures.

### 2b. Historical results for model fitting — World Cup scope
1. Use the `martj42/international_results` GitHub repo (`results.csv`) —
   free, no API key, actively maintained through the current tournament.
   Filter to `tournament == "FIFA World Cup"` (add continental
   championships/competitive qualifiers if you want more team-strength
   context beyond just World Cup matches themselves)
   - ⚠️ Same rule as before: never use market-derived data (odds) as a
     model feature — this repo doesn't have any, so no risk here, but the
     rule still applies if you ever add a second source.
2. Use the `neutral` column — most World Cup matches aren't "home" for
   either team. Don't apply home-advantage the way a club-league model
   would; the model should skip/zero out home advantage when neutral=True.
3. Get at minimum: date, home team, away team, home goals, away goals,
   neutral flag, tournament, for as much history as the repo has
3. Normalize team names across seasons (they drift — "Man United" vs
   "Manchester United")
   - ✅ Checkpoint: one clean dataframe/table, no nulls in the four core

     columns, team names consistent across all rows

**End of day:** live prices are being logged continuously, and you have
clean historical match data sitting ready for Day 3.

---

## Day 3 — Build & fit the model
**Tool: Cursor** — stay in the loop here. A silently-wrong fit poisons everything downstream (Day 4-7), so this is the day to read every line rather than review a diff at the end.

1. Implement the Dixon-Coles likelihood: each team gets attack (α) and
   defense (β) strength parameters, goals modeled as Poisson with rates
   `λ_home = α_home * β_away * home_advantage`, `λ_away = α_away * β_home`
   - ⚠️ **World Cup adjustment:** apply `home_advantage` only when the
     match's `neutral` flag is False. For neutral=True matches (most WC
     games), both λ's use `home_advantage = 1` (no boost for either side)
2. Add the Dixon-Coles correlation adjustment (τ function) for low-score
   outcomes (0-0, 1-0, 0-1, 1-1) — this is the part that's actually
   "Dixon-Coles" rather than a plain independent-Poisson model
3. Fit via MLE using `scipy.optimize.minimize` on historical goals
4. Add time-decay weighting (exponential, more weight on recent matches)
   - ✅ Checkpoint: fit converges without errors, and eyeballing 2-3
     well-known strong/weak teams gives sane relative strengths (don't
     move on until this passes — a broken fit silently poisons everything downstream)
5. Convert fitted λ's to match outcome probabilities: simulate/sum the
   Poisson score grid to get P(home)/P(draw)/P(away)
6. Validate on a holdout season you didn't fit on: compute log-loss or
   Brier score, sanity check against the naive baseline (always predict
   home-team base rates)
   - ✅ Checkpoint: your model beats the naive baseline on holdout. If it
     doesn't, don't proceed to Day 4 — debug the fit first, since a model
     no better than "always guess the average" defeats the entire project

**End of day:** a function that takes a fixture and returns calibrated
win/draw/loss probabilities, with a validation number you can quote.

---

## Day 4 — Map model to markets + signal/sizing
**Tool: Cursor** — risk/sizing logic is worth writing hand-in-the-loop, same reasoning as Day 3.

1. For each football market in `football_markets.json`, identify which
   outcome each token_id corresponds to (YES on "Team A wins" etc.) —
   Polymarket typically splits 3-way outcomes into separate binary markets
2. Match your model's fixtures to live market token_ids (by team names +
   date — this matching logic is fiddly, budget real time for it)
3. Compute edge: `model_probability - market_implied_probability`
   (market-implied = midpoint or best available price)
4. **Query live account balance** before every sizing decision — use
   Polymarket's Data API (`data-api.polymarket.com`), specifically its
   positions endpoint, rather than reconstructing balance through the
   CLOB client. Likely queryable by wallet address with no auth needed
   for read access, since positions are on-chain/public. Don't size
   against a static/remembered bankroll number — your balance changes as
   trades settle; sizing must track it. (Confirm exact request/response
   shape when you get here — same approach as Gamma/CLOB, figure out
   specifics in place rather than pre-planning every field.)
5. Implement fractional Kelly: `f* = (edge / odds) * kelly_fraction`,
   applied against the live balance from step 4
   (use 0.25-0.5 fractional Kelly, never full Kelly — full Kelly assumes
   your model is perfectly calibrated, which it isn't)
6. Add hard caps: max % of *current* balance per single market, max %
   of *current* balance in total open exposure across concurrent
   positions
7. **Drawdown circuit breaker:** track running PnL against your
   starting balance. If losses exceed a threshold (start with 20%),
   auto-halt new signal generation until you manually review and
   re-enable — don't let the system keep sizing/trading through a losing
   streak unattended
8. **SMS notification:** when a signal clears the edge threshold, send
   yourself a text (Twilio) with the match, model vs. market probability,
   edge %, and suggested size — this is your primary way of knowing a
   signal exists, so it should fire at the same point the signal is
   generated, not bolted on later
   - ✅ Checkpoint: run the signal generator against live Day 2 data,
     confirm position sizes are sane relative to live balance (not
     suggesting your entire bankroll on one match), that it correctly
     skips markets with no edge, that the circuit breaker actually halts
     when you simulate a big loss, and that a test signal produces a
     real text message

**End of day:** given live market state and your live balance, you get
a ranked list of (market, side, size) recommendations, gated by a
drawdown circuit breaker, and you get texted when one fires.

---

## Day 5 — Execution engine
**Tool: Claude Code** for the CLOB auth wiring — but review the order-placement code closely by hand before flipping DRY_RUN off, regardless of which tool wrote it.

1. Export private key from Polymarket UI, fill in `.env` (never commit it)
2. Build the authenticated CLOB client (signature_type=1 for email signup)
3. Implement order placement wrapping `create_and_post_order` with your
   signal's price/size
4. Add a `DRY_RUN` flag that logs what *would* be ordered without posting
5. Add fill tracking: poll order status after placement, record actual
   fill price/size (may differ from requested)
6. Test the full loop end-to-end in dry-run mode only
   - ✅ Checkpoint: dry-run produces a clean, correctly-formatted order
     log for several signals with no exceptions. Do not flip DRY_RUN off
     until this is boring and reliable

**End of day:** signal → order flow works, tested safely with zero
capital at risk so far.

---

## Day 6 — Monitoring dashboard
**Tool: Claude Code** — lowest-stakes day, good autopilot candidate.

1. Pick Streamlit (fastest to stand up) unless you specifically want the
   FastAPI+React resume line
2. Build three views minimum: current positions, running PnL, model
   probability vs. market price per tracked fixture (this third one is
   the most important — it's your calibration story)
3. Wire positions/PnL to Polymarket's Data API (positions + activity
   endpoints) rather than only your own execution logs — it's Polymarket's
   own on-chain record, so it can't drift out of sync with reality the way
   a self-maintained log could. Wire the model-vs-market chart to your
   SQLite DB from Day 2/5 (poll/refresh every 30-60s, don't overbuild
   real-time infra here)
   - ✅ Checkpoint: dashboard reflects a position change within a minute
     of it happening

**End of day:** a live, glanceable view of the whole system.

---

## Day 7 — Validate, go live, write it up
**Tool: Cursor** for the replay validation (want eyes on any crash), **either** for the README/write-up.

1. Replay Day 2's logged order book history through the Day 4 signal
   generator — confirm no crashes on stale books, wide spreads, or
   markets that closed mid-window
2. Flip `DRY_RUN` off, place a small number of real orders
   - ✅ Checkpoint: at least one real fill confirmed, matching what the
     dashboard shows
3. Write the README: architecture diagram, validation numbers from Day 3,
   what the Kelly/risk layer does and why
4. Record a 60-90s demo (dashboard + a walk through one live trade)

**End of day:** shipped, live, with a documented track record starting.

---

## Optional stretch — C++ fair-value module
**Tool: Cursor** — same reasoning as Day 3/4; this is math logic worth reading closely, and pybind11 boundary bugs (type mismatches, memory issues) are easier to catch in a tight loop than in a reviewed diff.

Only attempt this if Day 1-7 finished with slack. Port the fair-value/edge
calculation (Day 4) into a small C++ module called from Python via
`pybind11`. Even a minimal version gives you a legitimate "Python + C++"
line item matching Xantium's stated stack — but it's explicitly optional:
per the "if you fall behind" priority order above, this comes after
everything else, including the dashboard.

---

## Future extension — convergence trading (early exit)

The base system (Day 4-5) is **value betting held to resolution**: find a
market where `model_probability` differs from `market_implied_price`, take
the +EV side, size with Kelly, and let settlement pay out. Profit is only
realized when the market resolves.

A natural extension is to also **sell before resolution** — exit a position
when the price converges toward your model's fair value, capturing the edge
early and freeing capital for the next signal instead of locking it up
until the match/tournament ends. This is trading the *price move*, not just
the settlement.

What it would take (don't build this into the base engine — it's opt-in):

1. **Exit logic in the signal generator (Day 4).** Alongside "enter when
   edge > threshold", add "exit when price has moved to within X of model
   fair value" (take-profit) and/or a stop. This means the generator must
   evaluate *open positions*, not just fresh markets.
2. **Sell orders in the execution engine (Day 5).** Currently we only
   place entry orders; this needs the symmetric sell path (sell shares
   back into the CLOB book), plus round-trip PnL accounting (entry price →
   exit price, minus spread/fees on both sides) rather than
   entry-vs-settlement.
3. **A timing view.** Buy-and-hold only needs a probability estimate;
   convergence trading also needs a view on *when* the market corrects,
   which is a harder prediction. Realistically this wants either a
   live-updating model input (in-play results, injuries, lineup news) or a
   simple heuristic (e.g. exit N days before kickoff when liquidity/pricing
   tightens), otherwise there's no principled sell trigger.

Risk-logic caveat: the fractional-Kelly and exposure caps still apply, but
round-trips change the exposure picture (positions turn over faster), so
re-check the per-market and total caps against realized turnover if this is
built. The drawdown circuit breaker stays as-is.

Sequencing: this comes *after* a working buy-and-hold loop is validated
end-to-end (Day 7). Trying to build exit/timing logic before the base
value-betting loop is proven just adds a second unvalidated layer on top of
an unvalidated one.

---

## If you fall behind schedule

Priority order to protect if time runs short: **model validation (Day 3)
> execution + risk logic (Day 4-5) > dashboard (Day 6)**. A plain SQL
query or a printed table is an acceptable dashboard fallback — a model
with no validation number, or execution with no risk caps, is not an
acceptable fallback for either of those.
