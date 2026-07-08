"""
Day 2a: order-book poller.

Polls check_book.snapshot() for a set of tokens on a fixed interval and writes
each snapshot to SQLite (the book_snapshots table in db.py). Run it for a
while, then query the table to confirm timestamps are evenly spaced and prices
aren't frozen/repeating identically (a frozen series is the tell-tale sign of a
poller failing silently and re-serving cached data).

Run:
  python data/poll_books.py                       # 10 tokens, every 60s, until Ctrl-C
  python data/poll_books.py --tokens 5 --interval 30 --minutes 10
  python data/poll_books.py <token_id> <token_id> # poll specific tokens
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import db
from check_book import snapshot

MARKETS_FILE = Path(__file__).parent / "football_markets.json"


def load_tokens(limit: int | None = None) -> list[str]:
    """Distinct token ids from the discovery output, in file order."""
    markets = json.loads(MARKETS_FILE.read_text())
    seen, out = set(), []
    for m in markets:
        for tok in m.get("token_ids", []):
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out[:limit] if limit else out


def poll_once(tokens: list[str]) -> tuple[int, list[str]]:
    """Snapshot each token and store it. Returns (written, resolved).

    - Skips storing empty snapshots (no quote on either side) — a market with
      no book contributes no price history, just null rows.
    - Collects tokens whose market has *resolved* (orderbook_missing) so the
      caller can drop them from the rotation. A merely empty/one-sided book is
      NOT treated as resolved — it may regain liquidity, so we keep polling it.
    - An error on one token is logged and skipped so the loop survives.
    """
    written = 0
    resolved = []
    for tok in tokens:
        try:
            snap = snapshot(tok)
        except Exception as e:  # network blip, unexpected API error, etc.
            print(f"  [error] {tok[:12]}...: {type(e).__name__}: {e}")
            continue
        if snap["orderbook_missing"]:
            resolved.append(tok)  # market done — stop polling it
            continue
        if snap["best_bid"] is None and snap["best_ask"] is None:
            continue  # live but empty book — nothing to store, keep polling
        db.insert_snapshot(snap)
        written += 1
    return written, resolved


def main() -> None:
    ap = argparse.ArgumentParser(description="Poll order books into SQLite.")
    ap.add_argument("tokens", nargs="*", help="specific token ids (default: from football_markets.json)")
    ap.add_argument("--tokens", dest="n", type=int, default=10,
                    help="how many tokens to track when none are given (default 10)")
    ap.add_argument("--interval", type=float, default=60, help="seconds between rounds (default 60)")
    ap.add_argument("--minutes", type=float, default=None,
                    help="stop after this many minutes (default: run until Ctrl-C)")
    args = ap.parse_args()

    db.init_db()
    tokens = args.tokens or load_tokens(args.n)
    if not tokens:
        raise SystemExit("No tokens to poll — run discover_markets.py first.")

    print(f"Polling {len(tokens)} tokens every {args.interval:g}s -> {db.DB_PATH}")
    print("Ctrl-C to stop.\n")

    deadline = None if args.minutes is None else time.monotonic() + args.minutes * 60
    round_no = 0
    try:
        while True:
            round_no += 1
            started = time.monotonic()
            polled = len(tokens)
            written, resolved = poll_once(tokens)
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            msg = f"[{stamp}] round {round_no}: wrote {written}/{polled} snapshots"
            if resolved:
                dropped = set(resolved)
                tokens = [t for t in tokens if t not in dropped]
                msg += f"  (dropped {len(resolved)} resolved; {len(tokens)} left)"
            print(msg)
            if not tokens:
                print("All tracked markets resolved — nothing left to poll.")
                break
            if deadline and time.monotonic() >= deadline:
                break
            # Sleep the *remainder* of the interval so rounds stay evenly spaced
            # regardless of how long the polling itself took.
            time.sleep(max(0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        db.close()  # close the shared connection on shutdown


if __name__ == "__main__":
    main()
