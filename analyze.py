
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

# Historique des équipes
TEAM_LAST_MATCHES = 8
TEAM_CACHE_HOURS = 36
MAX_NEW_TEAM_REQUESTS_PER_RUN = 12

API_CALLS = 0

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
            return json.load(file)
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
