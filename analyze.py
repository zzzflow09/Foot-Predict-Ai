
import os
import json
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

API_URL = "https://v3.football.api-sports.io"
API_KEY = os.environ.get("API_FOOTBALL_KEY")

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime.now(PARIS)
TODAY = NOW.date()
TOMORROW = TODAY + timedelta(days=1)

OUTPUT_FILE = "predictions.json"
HISTORY_FILE = "predictions_history.json"

# Marge de sécurité pour ne pas épuiser le quota quotidien.
MAX_API_CALLS_PER_DAY = 80
MAX_TEAM_CACHE_AGE_HOURS = 36
TEAM_LAST_MATCHES = 8

API_CALLS = 0
API_USAGE_DATE = TODAY.isoformat()


def read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        print("Lecture impossible :", path)
        return default


def save_json(path, data):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=PARIS)
        return parsed.astimezone(PARIS)
    except (ValueError, TypeError):
        return None


def api_get(endpoint, params=None):
    global API_CALLS

    if not API_KEY:
        raise RuntimeError("Le secret API_FOOTBALL_KEY est absent.")

    if API_CALLS >= MAX_API_CALLS_PER_DAY:
        raise RuntimeError("Budget quotidien de requêtes atteint.")

    query = urllib.parse.urlencode(params or {})
    url = f"{API_URL}/{endpoint}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "x-apisports-key": API_KEY,
            "User-Agent": "FootPredictAI/2.0"
        }
    )

    # Environ 9 requêtes par minute au maximum.
    time.sleep(6.2)
    API_CALLS += 1

    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Erreur HTTP API-Football {error.code}: {body[:300]}"
        )

    if data.get("errors"):
        raise RuntimeError(f"Erreur API-Football : {data['errors']}")

    return data


def team_info(team):
    return {
        "id": team.get("id"),
        "name": team.get("name") or "Équipe inconnue"
    }


def fixture_record(item):
    fixture = item.get("fixture") or {}
    teams = item.get("teams") or {}
    league = item.get("league") or {}
    status = fixture.get("status") or {}

    home = teams.get("home") or {}
    away = teams.get("away") or {}

    fixture_id = fixture.get("id")
    kickoff = fixture.get("date")

    if not fixture_id or not kickoff or not home.get("id") or not away.get("id"):
        return None

    return {
        "fixture_id": str(fixture_id),
        "date": kickoff[:10],
        "kickoff": kickoff,
        "league": {
            "id": league.get("id"),
            "name": league.get("name") or "Compétition inconnue",
            "country": league.get("country") or "",
            "season": league.get("season")
        },
        "home": team_info(home),
        "away": team_info(away),
        "status": status.get("long") or "Inconnu",
        "status_short": status.get("short") or ""
    }


def read_history():
    data = read_json(HISTORY_FILE, {})
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("matches"), dict):
        data["matches"] = {}
    return data


def update_results_history(history):
    saved = history.setdefault("matches", {})
    yesterday = TODAY - timedelta(days=1)

    print("Recherche des résultats du", yesterday.isoformat())

    try:
        response = api_get(
            "fixtures",
            {
                "date": yesterday.isoformat(),
                "timezone": "Europe/Paris"
            }
        )
    except Exception as error:
        print("Historique non actualisé :", error)
        return history

    updated = 0

    for item in response.get("response", []):
        record = fixture_record(item)
        if not record:
            continue

        goals = item.get("goals") or {}
        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        if record["status_short"] not in {"FT", "AET", "PEN"}:
            continue

        record["score"] = {
            "home": home_goals,
            "away": away_goals
        }

        record["winner"] = (
            "home" if home_goals > away_goals
            else "away" if away_goals > home_goals
            else "draw"
        )

        record["collected_at"] = NOW.isoformat()
        saved[record["fixture_id"]] = record
        updated += 1

    history["matches"] = saved
    history["generated_at"] = NOW.isoformat()
    history["source"] = "API-Football"

    print("Résultats ajoutés :", updated)
    print("Total historique :", len(saved))

    return history


def get_team_recent_matches(team_id):
    response = api_get(
        "fixtures",
        {
            "team": team_id,
            "last": TEAM_LAST_MATCHES,
            "timezone": "Europe/Paris"
        }
    )

    matches = []

    for item in response.get("response", []):
        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}
        goals = item.get("goals") or {}
        league = item.get("league") or {}
        status = fixture.get("status") or {}

        home = teams.get("home") or {}
        away = teams.get("away") or {}

        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        if status.get("short") not in {"FT", "AET", "PEN"}:
            continue

        if not home.get("id") or not away.get("id"):
            continue

        matches.append({
            "fixture_id": str(fixture.get("id") or ""),
            "date": (fixture.get("date") or "")[:10],
            "kickoff": fixture.get("date"),
            "league": league.get("name") or "",
            "league_id": league.get("id"),
            "home_id": home.get("id"),
            "home": home.get("name") or "",
            "away_id": away.get("id"),
            "away": away.get("name") or "",
            "home_goals": home_goals,
            "away_goals": away_goals
        })

    matches.sort(key=lambda match: match.get("date") or "", reverse=True)

    return matches[:TEAM_LAST_MATCHES]


def cache_is_fresh(entry):
    if not isinstance(entry, dict):
        return False

    fetched_at = parse_datetime(entry.get("fetched_at"))
    if not fetched_at:
        return False

    age = NOW - fetched_at
    return timedelta(0) <= age < timedelta(hours=MAX_TEAM_CACHE_AGE_HOURS)


def collect_team_form(fixtures, old_cache):
    cache = dict(old_cache or {})
    team_ids = {}

    for fixture in fixtures.values():
        for side in ("home", "away"):
            team = fixture.get(side) or {}
            team_id = team.get("id")
            if team_id:
                team_ids[str(team_id)] = team.get("name") or "Équipe inconnue"

    print("Équipes à vérifier :", len(team_ids))

    updated = 0
    failed = 0

    for team_id, team_name in team_ids.items():
        previous = cache.get(team_id)

        if cache_is_fresh(previous) and previous.get("matches"):
            continue

        if API_CALLS >= MAX_API_CALLS_PER_DAY:
            print("Budget API atteint : équipes restantes conservées en cache.")
            break

        print("Historique de", team_name, "(ID", team_id, ")")

        try:
            matches = get_team_recent_matches(team_id)

            cache[team_id] = {
                "team_id": team_id,
                "team_name": team_name,
                "fetched_at": NOW.isoformat(),
                "matches": matches
            }
            updated += 1

        except Exception as error:
            print("Historique indisponible pour", team_name, ":", error)
            failed += 1

            # On conserve les anciennes données si la requête échoue.
            if previous:
                cache[team_id] = previous

    print("Historiques actualisés :", updated)
    print("Échecs :", failed)

    return cache


def main():
    global API_CALLS

    print("====================================")
    print("FOOT PREDICT AI - COLLECTE V2")
    print("Heure :", NOW.isoformat())
    print("====================================")

    if not API_KEY:
        raise RuntimeError("Le secret API_FOOTBALL_KEY est introuvable.")

    previous = read_json(OUTPUT_FILE, {})
    if not isinstance(previous, dict):
        previous = {}

    history = read_history()

    old_usage = previous.get("api_usage") or {}
    if old_usage.get("date") == API_USAGE_DATE:
        API_CALLS = int(old_usage.get("calls", 0))

    print("Requêtes déjà utilisées aujourd'hui :", API_CALLS)

    history = update_results_history(history)

    # Récupération des matchs du jour et du lendemain.
    fixtures = {}

    for match_date in (TODAY, TOMORROW):
        print("Recherche des matchs :", match_date.isoformat())

        if API_CALLS >= MAX_API_CALLS_PER_DAY:
            print("Budget API atteint.")
            break

        try:
            response = api_get(
                "fixtures",
                {
                    "date": match_date.isoformat(),
                    "timezone": "Europe/Paris"
                }
            )

            for item in response.get("response", []):
                record = fixture_record(item)
                if record:
                    fixtures[record["fixture_id"]] = record

        except Exception as error:
            print("Impossible de récupérer cette date :", error)

    # Si une collecte échoue, on conserve les matchs précédemment connus
    # qui concernent encore aujourd'hui ou demain.
    for fixture_id, old_match in (previous.get("matches") or {}).items():
        if old_match.get("date") not in {
            TODAY.isoformat(),
            TOMORROW.isoformat()
        }:
            continue

        if fixture_id not in fixtures:
            fixtures[fixture_id] = old_match

    old_team_cache = previous.get("team_form") or {}
    team_form = collect_team_form(fixtures, old_team_cache)

    output = {
        "generated_at": NOW.isoformat(),
        "source": "API-Football",
        "matches": fixtures,
        "team_form": team_form,
        "api_usage": {
            "date": API_USAGE_DATE,
            "calls": API_CALLS,
            "daily_limit": MAX_API_CALLS_PER_DAY
        }
    }

    save_json(OUTPUT_FILE, output)

    history["generated_at"] = NOW.isoformat()
    save_json(HISTORY_FILE, history)

    print("------------------------------------")
    print("Matchs enregistrés :", len(fixtures))
    print("Équipes en cache :", len(team_form))
    print("Appels API aujourd'hui :", API_CALLS)
    print("Terminé.")
    print("------------------------------------")


if __name__ == "__main__":
    main()
