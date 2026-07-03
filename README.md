# PolyPredict — Research + Execution Framework for Prediction Markets

Football forecasting model (Dixon-Coles/Elo) wired into live Polymarket
order books, with edge detection, Kelly sizing, and automated execution.

## Architecture

```
Gamma API (market catalog) ─┐
                              ├─> Market Data Ingestor ──> DB (snapshots)
CLOB API (live prices/books)─┘                                │
                                                                ▼
Dixon-Coles/Elo Model ──> Fair Value Generator ──> Edge Calculator ──> Kelly Sizer
                                                                │
                                                                ▼
                                              Execution Engine ──> CLOB Orders
                                                                │
                                                                ▼
                                          Dashboard: PnL, positions, model vs market
```

## Day 1 checklist

- [ ] Create/confirm Polymarket account (email login is simplest — avoids
      MetaMask allowance setup for now)
- [ ] Deposit a small amount of USDC on Polygon (start with $50–100 — this
      is a track record project, not a bankroll project)
- [ ] `pip install -r requirements.txt`
- [ ] Copy `.env.example` to `.env`, leave keys blank for now (not needed
      for read-only steps below)
- [ ] Run `python data/discover_markets.py` — confirms Gamma API access
      and produces `football_markets.json`
- [ ] Inspect `football_markets.json` — the keyword filter is crude, you'll
      likely need to tighten/loosen `FOOTBALL_KEYWORDS` once you see what's
      actually live
- [ ] Grab a `token_id` from that file, run
      `python data/check_book.py <token_id>` — confirms CLOB read access
      and that the book isn't returning ghost data
- [ ] Only once both scripts work: export your private key from the
      Polymarket UI, fill in `.env` (never commit it), and move to Day 2

## Notes

- Using `py_clob_client_v2` — the v1 client (`py-clob-client`) is archived
  and has an open bug where `get_order_book()` can return stale 0.01/0.99
  ghost prices on active markets. `check_book.py` flags this automatically.
- `signature_type=1` (email/proxy wallet) is the right default if you
  signed up with email rather than MetaMask — it's what most of the
  official examples assume and avoids manual token-allowance setup.
- Gamma API (`gamma-api.polymarket.com`) is unauthenticated and is where
  you discover markets/events. CLOB API (`clob.polymarket.com`) is where
  you get live prices and place orders. You'll use both throughout.
