"""
Football match prediction API.

Endpoints:
  GET /fixtures/today          -> today's fixtures with predictions
  GET /health                  -> simple health check

Data source: Football-Data.org (free tier). Get a free API token at
https://www.football-data.org/client/register and set it as the
FOOTBALL_DATA_API_KEY environment variable before running this server.

Run locally:
  pip install -r requirements.txt
  export FOOTBALL_DATA_API_KEY=your_token_here
  uvicorn main:app --reload --port 8000

Then open http://localhost:8000/fixtures/today
"""

import os
from datetime import date

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from prediction_engine import (
    MatchFactors,
    compute_probabilities,
    form_string_to_score,
    head_to_head_score,
    home_away_score,
    goals_score,
)

API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
BASE_URL = "https://api.football-data.org/v4"

app = FastAPI(title="Football Prediction API")

# Allow the mobile app to call this API from any origin during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def fd_get(path: str, params: dict | None = None) -> dict:
    if not API_KEY:
        raise HTTPException(
            status_code=500,
            detail="FOOTBALL_DATA_API_KEY haijawekwa. Weka API key yako kwanza.",
        )
    resp = requests.get(
        f"{BASE_URL}{path}",
        headers={"X-Auth-Token": API_KEY},
        params=params or {},
        timeout=10,
    )
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="Umefikia kikomo cha maombi (rate limit). Jaribu tena baadaye.")
    resp.raise_for_status()
    return resp.json()


def get_today_fixtures() -> list:
    today = date.today().isoformat()
    data = fd_get("/matches", {"dateFrom": today, "dateTo": today})
    return data.get("matches", [])


def get_team_standing(competition_id: int, team_id: int) -> dict | None:
    """Pull a team's row from the competition's standings (TOTAL table)."""
    data = fd_get(f"/competitions/{competition_id}/standings")
    for table in data.get("standings", []):
        if table.get("type") != "TOTAL":
            continue
        for row in table.get("table", []):
            if row.get("team", {}).get("id") == team_id:
                return row
    return None


def get_home_away_standing(competition_id: int, team_id: int, kind: str) -> dict | None:
    """kind is 'HOME' or 'AWAY'."""
    data = fd_get(f"/competitions/{competition_id}/standings")
    for table in data.get("standings", []):
        if table.get("type") != kind:
            continue
        for row in table.get("table", []):
            if row.get("team", {}).get("id") == team_id:
                return row
    return None


def get_head2head(match_id: int) -> dict:
    data = fd_get(f"/matches/{match_id}/head2head", {"limit": 10})
    agg = data.get("aggregates", {})
    return {
        "home_wins": agg.get("homeTeam", {}).get("wins", 0),
        "away_wins": agg.get("awayTeam", {}).get("wins", 0),
        "draws": agg.get("draws", 0),
    }


def build_prediction(match: dict) -> dict:
    competition_id = match["competition"]["id"]
    home_team = match["homeTeam"]
    away_team = match["awayTeam"]

    home_row = get_team_standing(competition_id, home_team["id"])
    away_row = get_team_standing(competition_id, away_team["id"])
    home_row_home = get_home_away_standing(competition_id, home_team["id"], "HOME")
    away_row_away = get_home_away_standing(competition_id, away_team["id"], "AWAY")
    h2h = get_head2head(match["id"])

    form_score = form_string_to_score(home_row.get("form") if home_row else None)
    h2h_score = head_to_head_score(h2h["home_wins"], h2h["draws"], h2h["away_wins"])

    home_win_rate_home = (home_row_home.get("won", 0) / home_row_home.get("playedGames", 1)) if home_row_home else 0.5
    away_win_rate_away = (away_row_away.get("won", 0) / away_row_away.get("playedGames", 1)) if away_row_away else 0.5
    ha_score = home_away_score(home_win_rate_home, away_win_rate_away)

    home_gf = home_row.get("goalsFor", 0) / max(1, home_row.get("playedGames", 1)) if home_row else 1.2
    home_ga = home_row.get("goalsAgainst", 0) / max(1, home_row.get("playedGames", 1)) if home_row else 1.2
    away_gf = away_row.get("goalsFor", 0) / max(1, away_row.get("playedGames", 1)) if away_row else 1.2
    away_ga = away_row.get("goalsAgainst", 0) / max(1, away_row.get("playedGames", 1)) if away_row else 1.2
    g_score = goals_score(home_gf, home_ga, away_gf, away_ga)

    factors = MatchFactors(form=form_score, h2h=h2h_score, home_away=ha_score, goals=g_score)
    probabilities = compute_probabilities(factors)

    return {
        "match_id": match["id"],
        "competition": match["competition"]["name"],
        "utc_date": match["utcDate"],
        "home_team": home_team["name"],
        "away_team": away_team["name"],
        "probabilities": probabilities,
        "factors": {
            "form": round(form_score, 2),
            "head_to_head": round(h2h_score, 2),
            "home_away": round(ha_score, 2),
            "goals": round(g_score, 2),
        },
    }


@app.get("/health")
def health():
    return {"status": "ok", "api_key_set": bool(API_KEY)}


@app.get("/fixtures/today")
def fixtures_today():
    fixtures = get_today_fixtures()
    predictions = []
    for match in fixtures:
        try:
            predictions.append(build_prediction(match))
        except HTTPException:
            raise
        except Exception:
            # Skip a single match if its standings/h2h data isn't available
            # (e.g. cup competitions without a league table) rather than
            # failing the whole endpoint.
            continue
    return {"date": date.today().isoformat(), "count": len(predictions), "matches": predictions}
