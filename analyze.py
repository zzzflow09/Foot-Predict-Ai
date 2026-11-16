
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
TODAY = datetime.now(PARIS).date()

DAYS_TO_FETCH = 2
MAX_LINEUP_FIXTURES = 20
OUTPUT_FILE = "predictions.json"


def normalize(value):
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(
        c for c in value
        if unicodedata.category(c) != "Mn"
    )
    return "".join(c.lower() for c in value if c.isalnum())


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

    # Respect de la limite de 10 requêtes par minute.
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

        entry = output.setdefault(str(fixture_id), [])

        entry.append({
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


def main():
    print("FOOT PREDICT AI - Collecte des données")
    print("Période : aujourd'hui et demain")

    if not API_KEY:
        raise RuntimeError("Secret API_FOOTBALL_KEY introuvable.")

    fixtures_by_id = {}
    injuries_by_id = {}
    lineups_by_id = {}
    lineups_checked_ids = set()

    # 1. Matchs et blessures.
    for offset in range(DAYS_TO_FETCH):
        match_date = TODAY + timedelta(days=offset)
        date_string = match_date.isoformat()

        print(f"Récupération du {date_string}...")

        fixture_data = api_get(
            "fixtures",
            {
                "date": date_string,
                "timezone": "Europe/Paris"
            }
        )

        injury_data = api_get(
            "injuries",
            {
                "date": date_string,
                "timezone": "Europe/Paris"
            }
        )

        for item in fixture_data.get("response", []):
            fixture_id = (item.get("fixture") or {}).get("id")

            if fixture_id:
                fixtures_by_id[str(fixture_id)] = item

        injuries_by_id.update(
            extract_injuries(
                injury_data.get("response", [])
            )
        )

    print(f"{len(fixtures_by_id)} matchs récupérés.")

    # 2. Compositions : une requête par match.
    upcoming = sorted(
        fixtures_by_id.values(),
        key=lambda x: (
            (x.get("fixture") or {}).get("timestamp", 0)
        )
    )

    selected = upcoming[:MAX_LINEUP_FIXTURES]

    for item in selected:
        fixture_id = (item.get("fixture") or {}).get("id")

        if not fixture_id:
            continue

        fixture_id = str(fixture_id)

        print(f"Recherche des compositions du match {fixture_id}...")

        detail_data = api_get(
            "fixtures/lineups",
            {"fixture": fixture_id}
        )

        lineups = extract_lineups(
            detail_data.get("response", [])
        )

        lineups_checked_ids.add(fixture_id)

        if lineups:
            lineups_by_id[fixture_id] = lineups

    # 3. Construction des données.
    matches = {}

    for fixture_id, item in fixtures_by_id.items():
        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}

        home = teams.get("home") or {}
        away = teams.get("away") or {}

        home_name = home.get("name", "")
        away_name = away.get("name", "")

        match_date = (fixture.get("date", "") or "")[:10]

        key = (
            normalize(home_name) + "|" +
            normalize(away_name) + "|" +
            match_date
        )

        status = fixture.get("status") or {}

        matches[key] = {
            "fixture_id": fixture_id,
            "date": match_date,
            "kickoff": fixture.get("date", ""),
            "home": team_info(home),
            "away": team_info(away),
            "status": status.get("long", "Inconnu"),
            "injuries": injuries_by_id.get(fixture_id, []),
            "lineups": lineups_by_id.get(fixture_id, {}),
            "lineups_checked": fixture_id in lineups_checked_ids,
            "lineups_available": fixture_id in lineups_by_id
        }

    result = {
        "generated_at": datetime.now(PARIS).isoformat(),
        "source": "API-Football",
        "period_days": DAYS_TO_FETCH,
        "fixtures_count": len(matches),
        "lineups_checked_count": len(lineups_checked_ids),
        "lineups_available_count": len(lineups_by_id),
        "matches": matches
    }

    # Écriture sécurisée du fichier.
    temporary_file = OUTPUT_FILE + ".tmp"

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temporary_file, OUTPUT_FILE)

    print(f"{len(matches)} matchs enregistrés.")
    print(
        f"{len(lineups_checked_ids)} matchs vérifiés pour les compositions."
    )
    print(
        f"{len(lineups_by_id)} matchs avec compositions disponibles."
    )
    print(f"Fichier créé : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
