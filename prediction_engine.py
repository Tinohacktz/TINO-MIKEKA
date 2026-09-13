"""
Prediction engine — weighted scoring model for Win/Draw/Loss probabilities.

This mirrors the logic used in the mobile app preview, but runs on real
data pulled from the football API instead of demo values.

NOTE ON DATA AVAILABILITY:
Football-Data.org's free tier gives us: league standings (including each
team's recent "form" string, e.g. "WWDLD"), home/away records, goals
for/against, and head-to-head match history. It does NOT give player
injury/availability data on the free tier — that typically requires a
paid plan or a different provider (e.g. API-Football's injuries endpoint).
So the "availability" factor here defaults to neutral (0.5) unless you
plug in an injury data source later.
"""

from dataclasses import dataclass


@dataclass
class MatchFactors:
    form: float          # 0-1, based on recent results (W=1, D=0.5, L=0)
    h2h: float           # 0-1, home team's win rate in recent head-to-head meetings
    home_away: float     # 0-1, home team's home record vs away team's away record
    goals: float         # 0-1, goal-scoring/conceding balance
    availability: float = 0.5  # neutral unless injury data is supplied


WEIGHTS = {
    "form": 0.32,
    "h2h": 0.18,
    "home_away": 0.22,
    "goals": 0.18,
    "availability": 0.10,
}


def form_string_to_score(form_str: str | None) -> float:
    """Convert a form string like 'WWDLD' (most recent last or first,
    API-dependent) into a 0-1 score. Empty/None -> neutral 0.5."""
    if not form_str:
        return 0.5
    results = [c for c in form_str.upper() if c in "WDL"]
    if not results:
        return 0.5
    points = {"W": 1.0, "D": 0.5, "L": 0.0}
    # weight recent results slightly more than older ones
    total_weight = 0.0
    total_score = 0.0
    for i, r in enumerate(results):
        w = 1.0 + (i * 0.1)  # later entries assumed more recent
        total_weight += w
        total_score += points[r] * w
    return total_score / total_weight


def head_to_head_score(home_wins: int, draws: int, away_wins: int) -> float:
    """Home team's share of head-to-head points across recent meetings."""
    total = home_wins + draws + away_wins
    if total == 0:
        return 0.5
    points = home_wins * 1.0 + draws * 0.5
    return points / total


def home_away_score(home_win_rate_at_home: float, away_win_rate_away: float) -> float:
    """Compare home team's home win-rate against away team's away win-rate."""
    total = home_win_rate_at_home + away_win_rate_away
    if total == 0:
        return 0.5
    return home_win_rate_at_home / total


def strength_from_standing(row: dict | None) -> float:
    """Fallback signal using overall points-per-game when a competition
    doesn't provide a 'form' string or HOME/AWAY split (common on some
    leagues, e.g. Brasileirão on the free tier). Returns 0-1, where 0.5
    is an average team (roughly 1.3 pts/game)."""
    if not row:
        return 0.5
    played = row.get("playedGames", 0)
    points = row.get("points", 0)
    if played == 0:
        return 0.5
    ppg = points / played  # 0 to 3
    return max(0.0, min(1.0, ppg / 3))


def goals_score(home_gf: float, home_ga: float, away_gf: float, away_ga: float) -> float:
    """Compare goal-scoring balance (goals for minus against) between the two sides."""
    home_diff = home_gf - home_ga
    away_diff = away_gf - away_ga
    spread = home_diff - away_diff
    # squash into 0-1 range with a soft curve
    score = 0.5 + spread / (2 * (abs(spread) + 4))
    return max(0.0, min(1.0, score))


def compute_probabilities(factors: MatchFactors) -> dict:
    home_score = (
        factors.form * WEIGHTS["form"]
        + factors.h2h * WEIGHTS["h2h"]
        + factors.home_away * WEIGHTS["home_away"]
        + factors.goals * WEIGHTS["goals"]
        + factors.availability * WEIGHTS["availability"]
    )

    draw_base = max(0.10, 0.24 - abs(home_score - 0.5) * 0.18)
    home_win = max(0.05, home_score - draw_base / 2)
    away_win = max(0.05, (1 - home_score) - draw_base / 2)
    total = home_win + draw_base + away_win

    return {
        "home_win_pct": round((home_win / total) * 100),
        "draw_pct": round((draw_base / total) * 100),
        "away_win_pct": round((away_win / total) * 100),
    }
