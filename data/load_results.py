"""
Day 2b: historical international match results for model fitting.

Pulls results.csv from the martj42/international_results GitHub repo (free, no
API key, maintained through the current tournament), filters to senior
internationals recognized by FIFA, cleans it, and stores it as the `matches`
table in the same SQLite DB. This is the training data for the Day-3
Dixon-Coles model: date, teams, goals, and the neutral-venue flag.

Run: python data/load_results.py
"""
import sys
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATA_SOURCE
import db

# Build the raw-CSV URL from the configured source (a GitHub "owner/repo").
if "/" not in DATA_SOURCE or "." in DATA_SOURCE:
    raise SystemExit(
        f"load_results only supports a GitHub owner/repo DATA_SOURCE; got "
        f"{DATA_SOURCE!r}. (football-data.co.uk would need a different loader.)"
    )
RESULTS_URL = f"https://raw.githubusercontent.com/{DATA_SOURCE}/master/results.csv"

# Scope: senior internationals recognized by FIFA. We take a blocklist
# approach because martj42 already restricts the dataset to "strictly men's
# full internationals" — no U-23, B-teams, or league selects (see its README) —
# so the *senior* criterion is handled at the source. To get the
# *FIFA-recognized* part, we drop the NON-FIFA competitions it also includes
# (CONIFA and other non-member bodies), plus Olympic Games (modern Olympic
# football is U-23, not a FIFA "A" international).
#
# Everything else is kept: the World Cup, every continental championship and
# its qualifiers, the Nations Leagues, regional cups, AND friendlies — a
# friendly between two FIFA members is an official "A" international. Friendlies
# are lower-intensity, so the intended handling is to DOWN-WEIGHT them in the
# Day-3 fit (using the `tournament` column), not to exclude them here. That
# weighting is the main Day-3 knob.
#
# (A stricter pass would also drop matches involving non-FIFA-member teams,
# which needs the list of FIFA's ~211 members — a possible later refinement.)
EXCLUDE_TOURNAMENTS = {
    # non-FIFA (unrecognized nations / breakaway governing bodies)
    "CONIFA World Football Cup", "CONIFA World Football Cup qualification",
    "CONIFA European Football Cup", "CONIFA Asia Cup",
    "CONIFA Africa Football Cup", "CONIFA South America Football Cup",
    "ConIFA Challenger Cup",
    "Viva World Cup", "FIFI Wild Cup", "The Other Final", "World Unity Cup",
    # not a FIFA "A" international (modern Olympic football is U-23)
    "Olympic Games",
}

# Membership test: keep a match only if BOTH teams belong to FIFA or one of its
# six confederations. We derive that member set from the data — teams that have
# appeared in any top-level confederation championship or its qualifiers (every
# member enters these). This is intentionally broader than FIFA membership: it
# keeps non-FIFA confederation sides like Martinique / French Guiana (who play
# CONCACAF competitions against World-Cup-pool teams, so dropping them would
# also drop those informative matches), while still excluding CONIFA / associate
# / novelty sides (Catalonia, Zanzibar, Isle of Man) that belong to none of them.
CONFEDERATION_COMPETITIONS = [
    "FIFA World Cup", "FIFA World Cup qualification",                  # FIFA
    "UEFA Euro", "UEFA Euro qualification", "UEFA Nations League",     # UEFA
    "Copa América", "Copa América qualification",                      # CONMEBOL
    "African Cup of Nations", "African Cup of Nations qualification",  # CAF
    "AFC Asian Cup", "AFC Asian Cup qualification",                    # AFC
    "Gold Cup", "Gold Cup qualification",                              # CONCACAF
    "CONCACAF Championship", "CONCACAF Championship qualification",
    "CONCACAF Nations League", "CONCACAF Nations League qualification",
    "Oceania Nations Cup", "Oceania Nations Cup qualification",        # OFC
]

# The columns that must never be null — the model can't fit without them.
CORE_COLUMNS = ["date", "home_team", "away_team", "home_score", "away_score"]


def fetch_results() -> pd.DataFrame:
    """Download the full results.csv (every international match since 1872)."""
    df = pd.read_csv(RESULTS_URL)
    pd.set_option('display.max_rows', None)
    print(df.value_counts("tournament"))
    print()
    return df


def member_teams(df: pd.DataFrame) -> set[str]:
    """National teams that belong to FIFA or one of its six confederations,
    derived from the data: any team that has appeared in a top-level
    confederation championship or its qualifiers (see CONFEDERATION_COMPETITIONS).
    Deriving from the dataset's own names sidesteps the name-matching headache
    of an external membership list and stays current as the file updates. It
    keeps confederation members that aren't FIFA members (Martinique, French
    Guiana, Bonaire...) while excluding CONIFA / associate / novelty sides
    (Catalonia, Zanzibar, Isle of Man) that compete in none of these — which a
    tournament-name filter alone cannot distinguish.
    """
    c = df[df["tournament"].isin(CONFEDERATION_COMPETITIONS)]
    return set(c["home_team"]) | set(c["away_team"])


def clean_results(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to FIFA-recognized senior internationals; return a clean frame.

    - drop the non-FIFA / non-A competitions in EXCLUDE_TOURNAMENTS (keep
      everything else, friendlies included),
    - keep only matches where BOTH teams belong to FIFA or a confederation
      (drops CONIFA / associate / novelty sides like Catalonia / Zanzibar /
      Isle of Man that appear in regional cups and some CONCACAF matches),
    - drop rows with missing scores (unplayed/abandoned — e.g. upcoming
      fixtures the dataset lists ahead of time),
    - cast goals to int, parse the date, keep the neutral flag (Day 3 applies
      home advantage only when neutral is False) and the tournament (Day 3
      down-weights friendlies by it),
    - sort chronologically.
    Team names are left as-is: martj42 is already internally consistent, and
    the historical splits it does keep (Czechoslovakia, DR Congo) are distinct
    nations, not naming drift, so merging them would be wrong.
    """
    members = member_teams(df)  # derive before we start filtering rows out
    df = df[~df["tournament"].isin(EXCLUDE_TOURNAMENTS)].copy()
    df = df[df["home_team"].isin(members) & df["away_team"].isin(members)]
    df = df.dropna(subset=["home_score", "away_score"])
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)
    df["date"] = pd.to_datetime(df["date"])
    df = df[["date", "home_team", "away_team",
             "home_score", "away_score", "neutral", "tournament"]]
    return df.sort_values("date").reset_index(drop=True)


def save(df: pd.DataFrame, table: str = "matches") -> None:
    """Write the frame to a SQLite table, replacing any previous load."""
    df.to_sql(table, db.get_conn(), if_exists="replace", index=False)


if __name__ == "__main__":
    raw = fetch_results()
    print(f"Fetched {len(raw)} total matches")

    clean = clean_results(raw)
    span = f"{clean['date'].min().date()} .. {clean['date'].max().date()}"
    teams = set(clean["home_team"]) | set(clean["away_team"])
    print(f"Kept {len(clean)} senior internationals between FIFA/confederation "
          f"members ({span}), {len(teams)} teams")

    # Checkpoint: no nulls in the core columns.
    core_nulls = int(clean[CORE_COLUMNS].isnull().sum().sum())
    print(f"Nulls in core columns {CORE_COLUMNS}: {core_nulls}")

    save(clean)
    db.close()
    print("Wrote `matches` table to", db.DB_PATH)
    print("\nSample:")
    print(clean.head().to_string())
