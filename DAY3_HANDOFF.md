# Day 3 handoff — build & fit the Dixon-Coles model

**Tool: Cursor** (per `PROJECT_PLAN.md`). This is the mathematically delicate
day — a silently-wrong fit poisons every downstream day — so work it in the
tight in-editor loop and read every line, rather than reviewing a diff at the
end.

Days 1–2 are done: discovery + live price polling (2a) and a clean historical
training corpus (2b) are in place. This note is everything you need to start
Day 3 cold.

---

## Where the training data lives

The `matches` table in `data/polypredict.db` (SQLite), written by
`data/load_results.py`. Load it:

```python
import sys; sys.path.insert(0, "data")   # or run from data/
import db, pandas as pd
df = pd.read_sql("SELECT * FROM matches ORDER BY date", db.get_conn())
```

Columns:

| column | type | notes |
|---|---|---|
| `date` | text (ISO) | match date; parse with `pd.to_datetime` |
| `home_team` / `away_team` | text | canonical names (martj42 is internally consistent) |
| `home_score` / `away_score` | int | full-time goals |
| `neutral` | int 0/1 | **1 = neutral venue** (SQLite has no bool — treat as bool) |
| `tournament` | text | competition name — **used for friendly down-weighting** |

~47,700 matches, 223 teams, 1872 → present.

### What's in scope (decided in 2b — don't silently re-litigate)
- **Senior internationals between FIFA or confederation (UEFA/CONMEBOL/CAF/AFC/CONCACAF/OFC) member teams.**
- martj42 already restricts to full internationals (no U-23/B-teams); we drop
  non-FIFA/non-senior events (CONIFA, Olympics) and matches involving
  non-member sides (Catalonia, Zanzibar, Isle of Man…).
- **Friendlies are included** (they're official "A" internationals) — but must
  be **down-weighted** in the fit (see rules below). The `tournament` column is
  kept precisely so you can.

---

## Hard rules the model must obey (from CLAUDE.md / PROJECT_PLAN.md)

1. **Home advantage only when `neutral == 0`.** Most World Cup matches are
   neutral. For neutral matches, `home_advantage = 1` (no boost to either
   side). Only apply the home-advantage term when the match is non-neutral.
2. **Never use market-derived data as a feature.** Only date/teams/goals/
   neutral are valid inputs. (The corpus has no odds columns, so you're clean —
   just don't add any.)
3. **Down-weight friendlies.** Friendlies are lower-intensity and less
   predictive; weight them below competitive matches in the likelihood. This is
   *in addition to* time-decay, not instead of it.

---

## Dixon-Coles build order (each step gates the next)

1. **Likelihood.** Each team gets attack (α) and defence (β) params. Goal rates:
   `λ_home = α_home · β_away · home_adv`, `λ_away = α_away · β_home`
   (with `home_adv = 1` when neutral). Goals ~ Poisson(λ).
2. **Dixon-Coles low-score correlation (τ).** The adjustment for 0-0/1-0/0-1/1-1
   — this is the part that makes it "Dixon-Coles" rather than independent
   Poisson. Don't skip it.
3. **Fit by MLE** with `scipy.optimize.minimize` over the historical goals.
   Add an identifiability constraint (e.g. mean attack = 1) so params don't
   drift.
4. **Weighting in the objective:** exponential **time-decay** (recent matches
   weight more — pick a half-life, e.g. ~2 years, and justify it) **×** a
   **friendly down-weight** factor (keyed off `tournament`). Both multiply each
   match's log-likelihood contribution.
   - ✅ **Checkpoint:** fit converges without errors, and eyeballing 2–3
     well-known strong/weak teams gives sane relative strengths. Do **not**
     proceed until this passes — a broken fit silently poisons Days 4–7.
5. **λ → outcome probabilities.** Sum/simulate the Poisson score grid (with the
   τ adjustment) to get `P(home) / P(draw) / P(away)` for a fixture.
6. **Validate on a holdout** you didn't fit on (e.g. hold out the most recent
   season/tournament): compute log-loss or Brier score, compare to a naive
   baseline (predict home/draw/away base rates).
   - ✅ **Checkpoint:** model beats the naive baseline on holdout. If it
     doesn't, debug the fit — do **not** move to Day 4.

**End of day:** a function `fixture → (P_home, P_draw, P_away)` for two named
teams + a neutral flag, plus a validation number you can quote.

---

## Knobs (all easy to retune)

- **Corpus scope:** `EXCLUDE_TOURNAMENTS` and `CONFEDERATION_COMPETITIONS` in
  `data/load_results.py` (re-run it to rebuild the `matches` table).
- **Time-decay half-life** and **friendly weight:** in the Day-3 fit code.
- Note the model outputs must line up with **Polymarket team names** in Day 4
  (e.g. martj42 "United States" vs a market's "USA") — that name-matching is a
  Day-4 problem, not a reason to rename here.

---

## Housekeeping before you commit
- Remove the `value_counts` debug print in `load_results.fetch_results()` (it
  dumps ~180 lines every run — was exploratory scaffolding).
- Suggested location for the model code: a new `dixon_coles.py` (root) or a
  `model/` package — keep it separate from the `data/` pipeline files.

---

## Quick sanity query to start from
```python
import sys; sys.path.insert(0, "data")
import db, pandas as pd
df = pd.read_sql("SELECT * FROM matches", db.get_conn())
df["date"] = pd.to_datetime(df["date"])
print(len(df), "matches,", len(set(df.home_team) | set(df.away_team)), "teams")
print(df["tournament"].value_counts().head())      # friendlies should dominate
print(df[df.home_team.eq("Brazil")].tail())        # eyeball a strong side
```
