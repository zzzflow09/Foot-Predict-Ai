
import os
import json
import time
import urllib.parse
import urllib.request
import unicodedata
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

LINEUP_WINDOW_MINUTES = 75
LINEUP_RECHECK_MINUTES = 25
REFRESH_INTERVAL_HOURS = 6

FINISHED_STATUSES = {"FT", "AET", "PEN"}


def normalize(value):
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(
        c for c in value
        if unicodedata.category(c) != "Mn"
    )
    return "".join(c.lower() for c in value if c.isalnum())


def parse_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=PARIS)

        return parsed.astimezone(PARIS)
    except (ValueError, TypeError):
        return None


def read_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data
    except (json.JSONDecodeError, OSError):
        print("Attention : lecture impossible de", path)
        return default


def save_json(path, data):
    temporary_file = path + ".tmp"

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temporary_file, path)


def read_previous_data():
    data = read_json(OUTPUT_FILE, {})
    return data if isinstance(data, dict) else {}


def read_history():
    data = read_json(HISTORY_FILE, {})

    if not isinstance(data, dict):
        data = {}

    if not isinstance(data.get("matches"), dict):
        data["matches"] = {}

    return data


def api_get(endpoint, params=None):
    if not API_KEY:
        raise RuntimeError("Secret API_FOOTBALL_KEY absent.")

    query = urllib.parse.urlencode(params or {})
    url = f"{API_URL}/{endpoint}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "x-apisports-key": API_KEY,
            "User-Agent": "FootPredictAI/1.0"
        }
    )

    # Limite volontaire : environ 9 requêtes maximum par minute.
    time.sleep(6.2)

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("errors"):
        raise RuntimeError(
            f"Erreur API sur {endpoint}: {data['errors']}"
        )

    return data


def team_info(item):
    return {
        "id": item.get("id"),
        "name": item.get("name", "Inconnu")
    }


def extract_injuries(records):
    output = {}

    for item in records:
        fixture = item.get("fixture") or {}
        team = item.get("team") or {}
        player = item.get("player") or {}

        fixture_id = fixture.get("id")

        if not fixture_id:
            continue

        output.setdefault(str(fixture_id), []).append({
            "team": team.get("name", "Équipe inconnue"),
            "player": player.get("name", "Joueur inconnu"),
            "type": player.get("type") or "Indisponibilité",
            "reason": player.get("reason") or "Motif non précisé"
        })

    return output


def extract_lineups(records):
    teams = {}

    for lineup in records:
        team = lineup.get("team") or {}
        team_name = team.get("name", "Équipe inconnue")

        teams[team_name] = {
            "formation": lineup.get("formation"),
            "coach": (lineup.get("coach") or {}).get("name"),
            "starting_xi": [
                {
                    "name": (p.get("player") or {}).get("name"),
                    "number": (p.get("player") or {}).get("number"),
                    "position": (p.get("player") or {}).get("pos")
                }
                for p in lineup.get("startXI") or []
            ],
            "substitutes": [
                {
                    "name": (p.get("player") or {}).get("name"),
                    "number": (p.get("player") or {}).get("number"),
                    "position": (p.get("player") or {}).get("pos")
                }
                for p in lineup.get("substitutes") or []
            ]
        }

    return teams


def is_refresh_due(previous_time, hours):
    parsed = parse_datetime(previous_time)

    if not parsed:
        return True

    return NOW - parsed >= timedelta(hours=hours)


def update_results_history(history):
    """
    Récupère les résultats des deux derniers jours.
    Met à jour les matchs déjà connus sans supprimer l'ancien historique.
    """

    saved_matches = history.setdefault("matches", {})
    updated_count = 0

    dates_to_check = [
        TODAY - timedelta(days=2),
        TODAY - timedelta(days=1)
    ]

    print("Actualisation de l'historique des résultats...")

    for match_date in dates_to_check:
        print("Résultats recherchés pour :", match_date.isoformat())

        result_data = api_get(
            "fixtures",
            {
                "date": match_date.isoformat(),
                "timezone": "Europe/Paris"
            }
        )

        for item in result_data.get("response", []):
            fixture = item.get("fixture") or {}
            teams = item.get("teams") or {}
            goals = item.get("goals") or {}
            league = item.get("league") or {}
            status = fixture.get("status") or {}

            fixture_id = fixture.get("id")
            status_short = status.get("short")

            if not fixture_id:
                continue

            if status_short not in FINISHED_STATUSES:
                continue

            home = teams.get("home") or {}
            away = teams.get("away") or {}

            home_goals = goals.get("home")
            away_goals = goals.get("away")

            if home_goals is None or away_goals is None:
                continue

            record = {
                "fixture_id": str(fixture_id),
                "date": (fixture.get("date") or "")[:10],
                "kickoff": fixture.get("date"),
                "league": league.get("name"),
                "country": league.get("country"),
                "home": team_info(home),
                "away": team_info(away),
                "score": {
                    "home": home_goals,
                    "away": away_goals
                },
                "status": status.get("long"),
                "status_short": status_short,
                "winner": (
                    "home" if home_goals > away_goals
                    else "away" if away_goals > home_goals
                    else "draw"
                ),
                "collected_at": NOW.isoformat()
            }

            saved_matches[str(fixture_id)] = record
            updated_count += 1

    history["matches"] = saved_matches
    history["generated_at"] = NOW.isoformat()
    history["results_updated_at"] = NOW.isoformat()
    history["source"] = "API-Football"

    save_json(HISTORY_FILE, history)

    print("Résultats actualisés :", updated_count)
    print("Total de matchs archivés :", len(saved_matches))

    return history


def build_match(item, previous, injuries_by_id, refresh_injuries):
    fixture = item.get("fixture") or {}
    teams = item.get("teams") or {}

    home = teams.get("home") or {}
    away = teams.get("away") or {}
    fixture_id = str(fixture.get("id"))
    status = fixture.get("status") or {}
    kickoff = fixture.get("date", "")

    previous = previous or {}

    if refresh_injuries:
        injuries = injuries_by_id.get(fixture_id, [])
    else:
        injuries = previous.get("injuries", [])

    return {
        "fixture_id": fixture_id,
        "date": kickoff[:10],
        "kickoff": kickoff,
        "home": team_info(home),
        "away": team_info(away),
        "status": status.get("long", "Inconnu"),
        "status_short": status.get("short", ""),
        "injuries": injuries,
        "lineups": previous.get("lineups", {}),
        "lineups_checked": previous.get("lineups_checked", False),
        "lineups_available": previous.get("lineups_available", False)
    }


def make_match_key(match):
    return (
        normalize(match["home"]["name"]) + "|" +
        normalize(match["away"]["name"]) + "|" +
        match["date"]
    )


def main():
    print("FOOT PREDICT AI - Collecte intelligente")
    print("Heure locale :", NOW.isoformat())

    if not API_KEY:
        raise RuntimeError("Secret API_FOOTBALL_KEY introuvable.")

    previous_data = read_previous_data()
    history = read_history()

    # 1. Mise à jour des résultats réels.
    # Les anciennes entrées de l'historique sont conservées.
    update_results_history(history)

    previous_matches = previous_data.get("matches", {})

    previous_by_id = {
        str(match.get("fixture_id")): match
        for match in previous_matches.values()
        if match.get("fixture_id")
    }

    lineup_check_times = previous_data.get(
        "lineup_check_times", {}
    )

    # 2. Actualisation des matchs du jour.
    refresh_today = NOW.minute < 30 or not any(
        match.get("date") == TODAY.isoformat()
        for match in previous_matches.values()
    )

    fixtures_by_id = {}

    if refresh_today:
        print("Actualisation des matchs du jour...")

        today_data = api_get(
            "fixtures",
            {
                "date": TODAY.isoformat(),
                "timezone": "Europe/Paris"
            }
        )

        for item in today_data.get("response", []):
            fixture_id = (item.get("fixture") or {}).get("id")

            if fixture_id:
                fixtures_by_id[str(fixture_id)] = item
    else:
        print("Matchs du jour conservés depuis la dernière collecte.")

    # 3. Actualisation des matchs de demain.
    refresh_tomorrow = (
        is_refresh_due(
            previous_data.get("tomorrow_updated_at"),
            REFRESH_INTERVAL_HOURS
        )
        or not any(
            match.get("date") == TOMORROW.isoformat()
            for match in previous_matches.values()
        )
    )

    if refresh_tomorrow:
        print("Actualisation des matchs de demain...")

        tomorrow_data = api_get(
            "fixtures",
            {
                "date": TOMORROW.isoformat(),
                "timezone": "Europe/Paris"
            }
        )

        for item in tomorrow_data.get("response", []):
            fixture_id = (item.get("fixture") or {}).get("id")

            if fixture_id:
                fixtures_by_id[str(fixture_id)] = item

        tomorrow_updated_at = NOW.isoformat()
    else:
        tomorrow_updated_at = previous_data.get(
            "tomorrow_updated_at"
        )

    # 4. Actualisation des blessures.
    refresh_injuries = is_refresh_due(
        previous_data.get("injuries_updated_at"),
        REFRESH_INTERVAL_HOURS
    )

    injuries_by_id = {}

    if refresh_injuries:
        print("Actualisation des blessures...")

        for match_date in (TODAY, TOMORROW):
            injury_data = api_get(
                "injuries",
                {
                    "date": match_date.isoformat(),
                    "timezone": "Europe/Paris"
                }
            )

            injuries_by_id.update(
                extract_injuries(injury_data.get("response", []))
            )

        injuries_updated_at = NOW.isoformat()
    else:
        print("Blessures conservées depuis la dernière collecte.")
        injuries_updated_at = previous_data.get(
            "injuries_updated_at"
        )

    # 5. Construire les matchs en conservant les anciennes données.
    matches = {}

    for old_match in previous_matches.values():
        match_date = old_match.get("date")

        if match_date == TODAY.isoformat() and not refresh_today:
            matches[make_match_key(old_match)] = old_match

        if match_date == TOMORROW.isoformat() and not refresh_tomorrow:
            matches[make_match_key(old_match)] = old_match

    for fixture_id, item in fixtures_by_id.items():
        old_match = previous_by_id.get(fixture_id)

        match = build_match(
            item,
            old_match,
            injuries_by_id,
            refresh_injuries
        )

        matches[make_match_key(match)] = match

    # 6. Vérification des compositions proches du coup d'envoi.
    candidates = []

    for match in matches.values():
        if match.get("lineups_available"):
            continue

        kickoff = parse_datetime(match.get("kickoff"))

        if not kickoff:
            continue

        minutes_until_kickoff = (
            kickoff - NOW
        ).total_seconds() / 60

        if not (
            -5 <= minutes_until_kickoff <= LINEUP_WINDOW_MINUTES
        ):
            continue

        fixture_id = str(match["fixture_id"])

        last_check = parse_datetime(
            lineup_check_times.get(fixture_id)
        )

        if last_check and (
            NOW - last_check
        ) < timedelta(minutes=LINEUP_RECHECK_MINUTES):
            continue

        candidates.append((kickoff, fixture_id, match))

    candidates.sort(key=lambda entry: entry[0])

    lineups_checked_this_run = 0

    if candidates:
        kickoff, fixture_id, match = candidates[0]

        print(
            "Vérification des compositions :",
            match["home"]["name"],
            "contre",
            match["away"]["name"]
        )

        lineup_data = api_get(
            "fixtures/lineups",
            {"fixture": fixture_id}
        )

        lineups = extract_lineups(
            lineup_data.get("response", [])
        )

        lineup_check_times[fixture_id] = NOW.isoformat()
        match["lineups_checked"] = True
        match["lineups_available"] = bool(lineups)
        match["lineups"] = lineups

        lineups_checked_this_run = 1

        if lineups:
            print("Compositions récupérées.")
        else:
            print("Compositions pas encore publiées.")
    else:
        print("Aucun match imminent à vérifier pour les compositions.")

    # 7. Nettoyage des vérifications de compositions.
    active_ids = {
        str(match["fixture_id"])
        for match in matches.values()
    }

    lineup_check_times = {
        fixture_id: checked_at
        for fixture_id, checked_at in lineup_check_times.items()
        if fixture_id in active_ids
    }

    lineups_available_count = sum(
        1 for match in matches.values()
        if match.get("lineups_available")
    )

    lineups_checked_count = sum(
        1 for match in matches.values()
        if match.get("lineups_checked")
    )

    # 8. Enregistrement des données des matchs.
    result = {
        "generated_at": NOW.isoformat(),
        "source": "API-Football",
        "period_days": 2,
        "fixtures_count": len(matches),
        "lineups_checked_count": lineups_checked_count,
        "lineups_available_count": lineups_available_count,
        "lineups_checked_this_run": lineups_checked_this_run,
        "injuries_updated_at": injuries_updated_at,
        "tomorrow_updated_at": tomorrow_updated_at,
        "lineup_check_times": lineup_check_times,
        "matches": matches
    }

    save_json(OUTPUT_FILE, result)

    print("-----------------------------------")
    print("Matchs enregistrés :", len(matches))
    print("Compositions vérifiées :", lineups_checked_count)
    print("Compositions disponibles :", lineups_available_count)
    print(
        "Vérifications de compositions durant cette exécution :",
        lineups_checked_this_run
    )
    print("Fichier créé :", OUTPUT_FILE)
    print("Historique des résultats :", len(history["matches"]))
    print("Fichier historique :", HISTORY_FILE)
    print("-----------------------------------")


if __name__ == "__main__":
    main()
