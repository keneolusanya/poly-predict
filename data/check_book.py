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
    # The v2 client returns plain dicts (not objects): get_midpoint ->
    # {'mid': str}, get_price -> {'price': str}. Unwrap the single value, and
    # note every price/size comes back as a STRING, so float() before math.
    print(f"Token:     {result['token_id']}")
    print(f"Midpoint:  {result['midpoint']['mid']}")
    print(f"Buy price: {result['buy_price']['price']}")
    print(f"Sell price:{result['sell_price']['price']}")

    # get_order_book -> dict with 'bids'/'asks' as lists of {'price','size'}
    # dicts. Don't assume ordering: the best bid is the highest-priced bid and
    # the best ask the lowest-priced ask, so pick them explicitly.
    book = result["book"]
    bids, asks = book["bids"], book["asks"]
    best_bid = max(bids, key=lambda o: float(o["price"])) if bids else None
    best_ask = min(asks, key=lambda o: float(o["price"])) if asks else None

    print("\nTop of book:")
    if best_bid:
        print(f"  Best bid: {(float(best_bid['price']) * 100) :.1f} cents x {best_bid['size']}")
    if best_ask:
        print(f"  Best ask: {(float(best_ask['price']) * 100) :.1f} cents x {best_ask['size']}")

    # Sanity check against the known v1-client ghost-book bug: a real market
    # has a tight inside spread. If the BEST bid/ask are pinned at the
    # 0.01/0.99 extremes, the book is empty/stale, not a real two-sided market.
    if best_bid and best_ask:
        if float(best_bid["price"]) <= 0.01 and float(best_ask["price"]) >= 0.99:
            print("\n[WARNING] Book looks like a ghost/stale snapshot "
                  "(0.01/0.99 spread). Cross-check against get_price() "
                  "before trusting this for signal generation.")