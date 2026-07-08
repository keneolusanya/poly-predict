"""
Day 1, Step 2: CLOB client setup — read-only first.

You don't need auth/private keys to READ prices and books. Only writing
orders (Day 5) requires the signed client. Keep it read-only as long as
possible while you're still validating the data pipeline — less that can
go wrong with real funds.

Run: python data/check_book.py <token_id>
Get a token_id from data/football_markets.json (produced by discover_markets.py)
"""
import sys
from datetime import datetime, timezone
from py_clob_client_v2 import ClobClient
from py_clob_client_v2.exceptions import PolyApiException

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


_client: ClobClient | None = None


def get_readonly_client() -> ClobClient:
    """Return a shared read-only client, building it once and reusing it.

    The poller calls snapshot() repeatedly; rebuilding a client every call is
    wasteful, so we cache one at module level (lazily, on first use)."""
    global _client
    if _client is None:
        _client = ClobClient(host=HOST, chain_id=CHAIN_ID)
    return _client


def _best(levels: list[dict], extreme) -> dict | None:
    """Best order on one side of the book, or None if that side is empty.
    extreme=max for bids (highest price), min for asks (lowest price)."""
    return extreme(levels, key=lambda o: float(o["price"])) if levels else None


def snapshot(token_id: str) -> dict:
    """One order-book snapshot, flattened to storable numeric fields.

    All price fields derive from a single get_order_book call, so they share
    one instant. The client returns prices/sizes as strings; we convert to
    float here so the DB and model get numbers straight away. Any price field
    is None if that side of the book is empty.

    The dict also carries `orderbook_missing` — a transient flag (NOT a stored
    column; insert_snapshot ignores it) that is True only when the API reports
    no orderbook exists (404), i.e. the market has resolved. This lets the
    poller tell a genuinely-resolved market apart from one that just happens to
    have an empty/one-sided book right now, and drop only the former.
    """
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    orderbook_missing = False
    try:
        book = get_readonly_client().get_order_book(token_id)
    except PolyApiException as e:
        # 404 = "no orderbook exists" — the market has resolved (or never had a
        # book). Don't let one dead market crash a long poller run; flag it and
        # treat it as an empty book so all price fields come out None.
        if getattr(e, "status_code", None) == 404:
            orderbook_missing = True
            book = {"bids": [], "asks": []}
        else:
            raise
    best_bid = _best(book["bids"], max)
    best_ask = _best(book["asks"], min)
    bid = float(best_bid["price"]) if best_bid else None
    ask = float(best_ask["price"]) if best_ask else None
    return {
        "orderbook_missing": orderbook_missing,
        "token_id": token_id,
        "captured_at": captured_at,
        "best_bid": bid,
        "best_ask": ask,
        "bid_size": float(best_bid["size"]) if best_bid else None,
        "ask_size": float(best_ask["size"]) if best_ask else None,
        "midpoint": (bid + ask) / 2 if bid is not None and ask is not None else None,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python data/check_book.py <token_id>")
        sys.exit(1)

    s = snapshot(sys.argv[1])
    # snapshot() now returns flat floats (best_bid/ask, sizes, midpoint) plus a
    # capture timestamp — the same shape stored in the DB by the Day-2 poller.
    print(f"Token:     {s['token_id']}")
    print(f"Captured:  {s['captured_at']}")
    print(f"Midpoint:  {s['midpoint']}")

    print("\nTop of book:")
    if s["best_bid"] is None and s["best_ask"] is None:
        print("  (no orderbook — market resolved, or has no liquidity)")
    if s["best_bid"] is not None:
        print(f"  Best bid: {s['best_bid'] * 100:.1f} cents x {s['bid_size']}")
    if s["best_ask"] is not None:
        print(f"  Best ask: {s['best_ask'] * 100:.1f} cents x {s['ask_size']}")

    # Ghost/stale-book sanity check (the known v1 bug): a real market has a
    # tight inside spread. Best bid/ask pinned at the 0.01/0.99 extremes means
    # the book is empty/stale, not a real two-sided market.
    if s["best_bid"] is not None and s["best_ask"] is not None:
        if s["best_bid"] <= 0.01 and s["best_ask"] >= 0.99:
            print("\n[WARNING] Book looks like a ghost/stale snapshot "
                  "(0.01/0.99 spread) — don't trust it for signal generation.")