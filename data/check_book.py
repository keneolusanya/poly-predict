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
from py_clob_client_v2 import ClobClient

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


def get_readonly_client() -> ClobClient:
    return ClobClient(host=HOST, chain_id=CHAIN_ID)


def snapshot(token_id: str) -> dict:
    client = get_readonly_client()
    return {
        "token_id": token_id,
        "midpoint": client.get_midpoint(token_id),
        "buy_price": client.get_price(token_id, side="BUY"),
        "sell_price": client.get_price(token_id, side="SELL"),
        "book": client.get_order_book(token_id),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python data/check_book.py <token_id>")
        sys.exit(1)

    result = snapshot(sys.argv[1])
    print(f"Token:     {result['token_id']}")
    print(f"Midpoint:  {result['midpoint']}")
    print(f"Buy price: {result['buy_price']}")
    print(f"Sell price:{result['sell_price']}")

    book = result["book"]
    print("\nTop of book:")
    if getattr(book, "bids", None):
        print(f"  Best bid: {book.bids[0].price} x {book.bids[0].size}")
    if getattr(book, "asks", None):
        print(f"  Best ask: {book.asks[0].price} x {book.asks[0].size}")

    # Sanity check against the known v1-client ghost-book bug: if midpoint
    # looks reasonable (not exactly 0.5 or NaN) but best bid/ask are 0.01/0.99,
    # something's wrong with the feed, not the market.
    if book.bids and book.asks:
        if float(book.bids[0].price) <= 0.01 and float(book.asks[0].price) >= 0.99:
            print("\n[WARNING] Book looks like a ghost/stale snapshot "
                  "(0.01/0.99 spread). Cross-check against get_price() "
                  "before trusting this for signal generation.")