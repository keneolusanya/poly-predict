"""
Single source of truth for *what* we're trading.

Hand-edited, not auto-detected — you always know in advance what you're
trading, so there's no need for the system to discover it. Every module
(discovery, data pipeline, signal generator, execution) reads from here
instead of hardcoding venue/tournament/data-source assumptions inline, so
switching what you trade is a config change, not a rewrite:

  - World Cup ends → back to club leagues:  TOURNAMENT = "premier_league"
  - you relocate (US)  → Kalshi not Polymarket:  VENUE = "kalshi"

When you change TOURNAMENT, add a matching discovery profile in
data/discover_markets.py (search terms + tag gates for that competition).
"""

VENUE = "polymarket"            # or "kalshi"
TOURNAMENT = "world_cup_2026"   # or e.g. "premier_league"
DATA_SOURCE = "martj42/international_results"  # or "football-data.co.uk"
