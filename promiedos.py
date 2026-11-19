"""Lee los partidos de la fase final de la Liga Profesional desde Promiedos.

Promiedos publica una API JSON (la misma que usa su web). El marcador que da
para un partido con alargue incluye los goles del suplementario; el prode se
juega con el resultado de los 90', así que en esos casos lo recalculamos con
los minutos de cada gol.
"""
import json
import re
from datetime import datetime

import requests

LEAGUE_URL = "https://www.promiedos.com.ar/league/liga-profesional/hc"
API_GAMES = "https://api.promiedos.com.ar/league/games/hc/{key}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (prode-liga)",
    "Referer": "https://www.promiedos.com.ar/",
    "Accept": "application/json, text/html",
}
STAGE_NAMES = {
    "Octavos de Final": "8vos",
    "Cuartos de Final": "4tos",
    "Semifinales": "semi",
    "Final": "final",
}
# Claves conocidas al 19/11/2026 por si falla la lectura de la página de la liga
FALLBACK_KEYS = {"8vos": "72_228_9_-1", "4tos": "72_228_10_-1",
                 "semi": "72_228_11_-1", "final": "72_228_12_-1"}
TIMEOUT = 15
FASE_DESDE = "2026-11-15"  # los octavos arrancan el 20/11


def _stage_num(key):
    try:
        return int(key.split("_")[2])
    except (IndexError, ValueError):
        return -1


def _stage_keys():
    """Busca las claves de cada ronda. La lista de Promiedos mezcla el torneo
    anterior (Apertura) con el actual: solo se aceptan rondas con número de
    etapa mayor o igual al de los octavos actuales (72_228_9_-1)."""
    keys = dict(FALLBACK_KEYS)
    min_num = _stage_num(FALLBACK_KEYS["8vos"])
    try:
        html = requests.get(LEAGUE_URL, headers=HEADERS, timeout=TIMEOUT).text
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        data = json.loads(m.group(1))["props"]["pageProps"]["data"]
        for f in data["games"]["filters"]:
            stage = STAGE_NAMES.get(f.get("name"))
            if stage and _stage_num(f["key"]) >= min_num and _stage_num(f["key"]) >= _stage_num(keys[stage]):
                keys[stage] = f["key"]
    except Exception:
        pass
    return keys


def _goals_until_90(team):
    return sum(1 for g in team.get("goals", []) if float(g.get("time", 0)) <= 90)


def _parse_game(g):
    teams = g.get("teams") or []
    if len(teams) != 2:
        return None
    status_enum = (g.get("status") or {}).get("enum")
    symbol = (g.get("status") or {}).get("symbol_name", "")
    scores = [int(s) for s in (g.get("scores") or [])]

    out = {
        "pids": (teams[0]["id"], teams[1]["id"]),
        "status": "pendiente",
        "goals": None,          # (a, b) a los 90'
        "pens": None,
        "winner": None,         # 0 o 1 (índice del que pasa)
        "minute": g.get("game_time_to_display") or g.get("game_time_status_to_display") or "",
        "kickoff": None,
        "review": None,         # texto si hay que revisar a mano
    }
    st = g.get("start_time")
    if st:
        try:
            out["kickoff"] = datetime.strptime(st, "%d-%m-%Y %H:%M").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass

    if status_enum == 2 and len(scores) == 2:
        out["status"] = "en_juego"
        out["goals"] = tuple(scores)
    elif status_enum == 3 and len(scores) == 2:
        out["status"] = "final"
        went_extra = symbol in ("TE", "Pen") or int(g.get("game_time") or 0) >= 105
        if went_extra:
            a90, b90 = _goals_until_90(teams[0]), _goals_until_90(teams[1])
            listed = len(teams[0].get("goals", [])) + len(teams[1].get("goals", []))
            if a90 != b90 or listed != sum(scores):
                out["review"] = "Hubo alargue y no se pudo calcular el resultado de los 90'"
            out["goals"] = (a90, b90)
        else:
            out["goals"] = tuple(scores)
        if g.get("penalties"):
            out["pens"] = tuple(int(p) for p in g["penalties"])
        w = g.get("winner")
        if w in (1, 2):
            out["winner"] = w - 1
        elif out["goals"][0] != out["goals"][1]:
            out["winner"] = 0 if out["goals"][0] > out["goals"][1] else 1
        else:
            out["review"] = "No se sabe quién pasó"
    return out


def fetch_games():
    """Devuelve la lista de partidos de octavos a la final que Promiedos ya tiene."""
    games = []
    for stage, key in _stage_keys().items():
        try:
            r = requests.get(API_GAMES.format(key=key), headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            for g in r.json().get("games", []):
                p = _parse_game(g)
                # Seguridad extra: ignorar partidos anteriores a esta fase final
                if p and p["kickoff"] and p["kickoff"] < FASE_DESDE:
                    continue
                if p:
                    p["stage"] = stage
                    games.append(p)
        except Exception:
            continue
    return games
