"""

Polymarket's Gamma API is the market/metadata catalog (no auth needed).
The CLOB API (py_clob_client_v2) is where you get live prices/books and place orders.
You need a market's clobTokenIds from Gamma before you can query its book on the CLOB.

Run: python data/discover_markets.py
"""
import sys
import requests
import json
from pathlib import Path

# config.py lives at the project root (one level up from data/); add it to
# the path so this script runs standalone via `python data/discover_markets.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TOURNAMENT

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"

# Per-tournament discovery profiles. The active one is selected by TOURNAMENT
# from config.py, so switching what you trade is a config change there, not an
# edit here — you just add a new profile block below for the new competition.
#
# Each profile has:
#   search_queries — terms fed to Gamma's /public-search. The search matches
#                    semantically server-side, so "world cup" alone already
#                    surfaces round-of-16 / semifinal / winner markets without
#                    enumerating every round name.
#   Tag gates (the search casts a wide net for recall, then tags give precision;
#   "world cup" also matches Esports/Cricket World Cups and novelty props like
#   halftime songs, and Gamma's search has no "football only" knob):
#     football_tags  — must have one: it's a football event (drops esports/cricket)
#     keep_type_tags — must have one: a market type the Dixon-Coles model can
#                      price (match outcomes + team progression + tournament
#                      winner); drops player props, records, awards, team props
#     novelty_tags   — must have NONE: culture/politics/off-sport (swats leaks
#                      like the halftime show that carry a Soccer tag anyway)
# Tag labels are lowercased before matching.
DISCOVERY_PROFILES = {
    "world_cup_2026": {
        "search_queries": ["world cup"],
        "football_tags": {"soccer", "fifa world cup", "2026 fifa world cup"},
        "keep_type_tags": {
            "games", "stage of elimination", "tournament futures",
            "continental futures", "group futures",
        },
        "novelty_tags": {
            "culture", "mentions", "music", "politics", "weather", "esports",
            "dota 2", "dota2", "valorant", "cricket", "international cricket",
            "tech", "big tech", "app store", "earnings calls", "youtube",
            "podcast", "trump", "trump wc", "donald trump", "truth social",
        },
    },
    # "premier_league": { "search_queries": ["premier league"], ... },
}

try:
    _PROFILE = DISCOVERY_PROFILES[TOURNAMENT]
except KeyError:
    raise SystemExit(
        f"No discovery profile for TOURNAMENT={TOURNAMENT!r} (from config.py). "
        f"Add one to DISCOVERY_PROFILES. Known: {sorted(DISCOVERY_PROFILES)}"
    )

SEARCH_QUERIES = _PROFILE["search_queries"]
FOOTBALL_TAGS = _PROFILE["football_tags"]
KEEP_TYPE_TAGS = _PROFILE["keep_type_tags"]
NOVELTY_TAGS = _PROFILE["novelty_tags"]


def _event_tags(event: dict) -> set[str]:
    """Lowercased set of an event's tag labels."""
    return {(t.get("label") or "").lower() for t in event.get("tags") or []}


def filter_tradeable(events: list[dict]) -> list[dict]:
    """Keep only football World Cup events whose market type the model prices.

    See the tag-gate comment above SEARCH_QUERIES for the rationale. An event
    passes only if it is football, is an allowed market type, and carries no
    novelty/off-sport tag.
    """
    out = []
    for ev in events:
        tags = _event_tags(ev)
        if tags & FOOTBALL_TAGS and tags & KEEP_TYPE_TAGS and not tags & NOVELTY_TAGS:
            out.append(ev)
    return out


def fetch_active_events(queries: list[str] = SEARCH_QUERIES,
                        page_size: int = 50) -> list[dict]:
    """Pull open events matching our search queries from Gamma.

    Uses /public-search rather than enumerating the full /events list. Two
    reasons: (1) the full list can't be exhausted anyway — offset is capped
    ~2000 and there are 4000+ events, with an unreachable middle band; and
    (2) searching scopes the pull to the tournament server-side, so we fold
    the football filter into the request instead of pulling everything and
    matching titles locally.

    Results are unioned across queries by event id (dedup), and we keep only
    genuinely open events: events_status=active still lets a few resolved
    (closed=True) ones through, so we drop those. Gamma caps page size at 50.
    """
    by_id = {}
    for query in queries:
        page = 1
        while True:
            resp = requests.get(
                f"{GAMMA_BASE_URL}/public-search",
                params={
                    "q": query, "events_status": "active",
                    "limit_per_type": page_size, "page": page,
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            events = payload.get("events", [])  # each event is a dictionary
            for ev in events:
                if ev.get("closed") is False:  # drop resolved leftovers
                    by_id[ev["id"]] = ev
            if not events or not payload.get("pagination", {}).get("hasMore"):
                break
            page += 1
    return list(by_id.values())


def extract_markets(events: list[dict]) -> list[dict]:
    """Flatten to one row per tradable market with its CLOB token IDs."""
    rows = []
    for ev in events:
        for m in ev.get("markets", []):
            token_ids_raw = m.get("clobTokenIds")
            outcomes_raw = m.get("outcomes")
            try:
                token_ids = json.loads(token_ids_raw) if token_ids_raw else []
            except (TypeError, json.JSONDecodeError):
                token_ids = []
            try:
                outcomes = json.loads(outcomes_raw) if outcomes_raw else []
            except (TypeError, json.JSONDecodeError):
                outcomes = []
            rows.append({
                # event_id is the stable grouping key: a match fixture is one
                # event holding its 3 outcome markets (home win / draw / away
                # win), which is exactly the Dixon-Coles model's unit. Flat
                # rows here (best for the token_id-keyed poller); regroup on
                # event_id downstream.
                "event_id": ev.get("id"),
                "event_title": ev.get("title"),
                "market_question": m.get("question"),
                "condition_id": m.get("conditionId"),
                "token_ids": token_ids,  # [YES_token_id, NO_token_id] typically
                "outcomes": outcomes, # [YES, NO] typically
                "end_date": m.get("endDate"),
                "active": m.get("active"),
                "closed": m.get("closed"),
            })
    return rows


if __name__ == "__main__":
    events = fetch_active_events()
    print(f"Fetched {len(events)} open events for {SEARCH_QUERIES}")

    tradeable = filter_tradeable(events)
    print(f"Kept {len(tradeable)} football events after tag filtering")

    if not tradeable:
        print("\nNo events matched. Check SEARCH_QUERIES / tag gates against "
              "what's live (e.g. the tournament may not be open yet, or a tag "
              "label drifted).")

    markets = extract_markets(tradeable)
    print(f"Extracted {len(markets)} tradable markets")

    out_path = Path(__file__).parent / "football_markets.json"
    out_path.write_text(json.dumps(markets, indent=2))
    print(f"Wrote {out_path}")

    if markets:
        print("\nSample market:")
        print(json.dumps(markets[0], indent=2))

    else:
        print("No markets found")
    