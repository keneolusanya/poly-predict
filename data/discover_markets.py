"""
Day 1, Step 1: Market discovery.

Polymarket's Gamma API is the market/metadata catalog (no auth needed).
The CLOB API (py_clob_client_v2) is where you get live prices/books and place orders.
You need a market's clobTokenIds from Gamma before you can query its book on the CLOB.

Run: python data/discover_markets.py
"""
import requests
import json
from pathlib import Path

GAMMA_BASE = "https://gamma-api.polymarket.com"

# Polymarket tags markets by category. We filter client-side on title keywords
# for now since exact tag slugs drift — inspect the raw output on first run.
FOOTBALL_KEYWORDS = [
    "premier league", "champions league", "la liga", "serie a",
    "bundesliga", "ligue 1", "world cup", " fc ", "united", "city",
]


def fetch_active_events(limit: int = 500) -> list[dict]:
    """Pull active events from Gamma. Events contain nested markets."""
    resp = requests.get(
        f"{GAMMA_BASE}/events",
        params={"active": "true", "closed": "false", "limit": limit},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def filter_football(events: list[dict]) -> list[dict]:
    out = []
    for ev in events:
        title = (ev.get("title") or "").lower()
        if any(kw in title for kw in FOOTBALL_KEYWORDS):
            out.append(ev)
    return out


def extract_markets(events: list[dict]) -> list[dict]:
    """Flatten to one row per tradable market with its CLOB token IDs."""
    rows = []
    for ev in events:
        for m in ev.get("markets", []):
            token_ids_raw = m.get("clobTokenIds")
            try:
                token_ids = json.loads(token_ids_raw) if token_ids_raw else []
            except (TypeError, json.JSONDecodeError):
                token_ids = []
            rows.append({
                "event_title": ev.get("title"),
                "market_question": m.get("question"),
                "condition_id": m.get("conditionId"),
                "token_ids": token_ids,  # [YES_token_id, NO_token_id] typically
                "outcomes": m.get("outcomes"),
                "end_date": m.get("endDate"),
                "active": m.get("active"),
                "closed": m.get("closed"),
            })
    return rows


if __name__ == "__main__":
    events = fetch_active_events()
    print(f"Fetched {len(events)} active events")

    football = filter_football(events)
    print(f"Matched {len(football)} events on football keywords")

    markets = extract_markets(football)
    print(f"Extracted {len(markets)} tradable markets")

    out_path = Path(__file__).parent / "football_markets.json"
    out_path.write_text(json.dumps(markets, indent=2))
    print(f"Wrote {out_path}")

    if markets:
        print("\nSample market:")
        print(json.dumps(markets[0], indent=2))