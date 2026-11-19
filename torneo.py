"""Datos fijos del torneo: equipos, cuadro y reglas de puntaje."""

TITULO = "Prode Liga Argentina"
SUBTITULO = "Fase final 2026 · Octavos a la final"

# pid = id del equipo en Promiedos (se usa para emparejar resultados)
# c1 / c2 = colores del escudo simplificado
TEAMS = {
    "instituto":     {"name": "Instituto",               "short": "Instituto",     "abbr": "INS", "pid": "hchc",  "c1": "#E30613", "c2": "#FFFFFF"},
    "huracan":       {"name": "Huracán",                 "short": "Huracán",       "abbr": "HUR", "pid": "iie",   "c1": "#FFFFFF", "c2": "#D52B1E"},
    "river":         {"name": "River Plate",             "short": "River",         "abbr": "RIV", "pid": "igi",   "c1": "#FFFFFF", "c2": "#E30613"},
    "lanus":         {"name": "Lanús",                   "short": "Lanús",         "abbr": "LAN", "pid": "igj",   "c1": "#7A1F35", "c2": "#FFFFFF"},
    "argentinos":    {"name": "Argentinos Juniors",      "short": "Argentinos",    "abbr": "AAJ", "pid": "ihb",   "c1": "#E2231A", "c2": "#FFFFFF"},
    "independiente": {"name": "Independiente",           "short": "Independiente", "abbr": "CAI", "pid": "ihe",   "c1": "#E30613", "c2": "#FFFFFF"},
    "velez":         {"name": "Vélez Sarsfield",         "short": "Vélez",         "abbr": "VEL", "pid": "ihc",   "c1": "#FFFFFF", "c2": "#1F4E9A"},
    "belgrano":      {"name": "Belgrano",                "short": "Belgrano",      "abbr": "BEL", "pid": "fhid",  "c1": "#5FB5E5", "c2": "#0B2F6B"},
    "central":       {"name": "Rosario Central",         "short": "Central",       "abbr": "CEN", "pid": "ihf",   "c1": "#003C8F", "c2": "#FFD100"},
    "gimnasia_mza":  {"name": "Gimnasia (Mendoza)",      "short": "Gimnasia MZA",  "abbr": "GIM", "pid": "bbjbf", "c1": "#FFFFFF", "c2": "#1A1A1A"},
    "defensa":       {"name": "Defensa y Justicia",      "short": "Defensa",       "abbr": "DYJ", "pid": "hcbh",  "c1": "#FFE000", "c2": "#009540"},
    "barracas":      {"name": "Barracas Central",        "short": "Barracas",      "abbr": "BAR", "pid": "jafb",  "c1": "#FFFFFF", "c2": "#E30613"},
    "boca":          {"name": "Boca Juniors",            "short": "Boca",          "abbr": "BOC", "pid": "igg",   "c1": "#0B3D91", "c2": "#FDB913"},
    "ind_rivadavia": {"name": "Independiente Rivadavia", "short": "Ind. Rivadavia", "abbr": "CSIR", "pid": "hcch", "c1": "#14163F", "c2": "#FFFFFF"},
    "gimnasia_lp":   {"name": "Gimnasia La Plata",       "short": "Gimnasia LP",   "abbr": "GEL", "pid": "iia",   "c1": "#FFFFFF", "c2": "#0B2F6B"},
    "newells":       {"name": "Newell's Old Boys",       "short": "Newell's",      "abbr": "NOB", "pid": "ihh",   "c1": "#E30613", "c2": "#1A1A1A"},
}

ROUNDS = [
    ("8vos", "Octavos de final", "20 al 25 de noviembre"),
    ("4tos", "Cuartos de final", "Fin de semana del 29 de noviembre"),
    ("semi", "Semifinales", "Fin de semana del 6 de diciembre"),
    ("final", "Final", "Sábado 12 de diciembre · Estadio Único Diego A. Maradona, La Plata"),
]

# Cuadro. "a"/"b": clave de equipo (octavos) o ("W", n) = ganador del partido n.
# kickoff: hora argentina "AAAA-MM-DD HH:MM" o None si falta confirmar.
MATCHES = [
    {"id": 1,  "round": "8vos",  "a": "instituto",  "b": "huracan",       "kickoff": "2026-11-22 22:00"},
    {"id": 2,  "round": "8vos",  "a": "river",      "b": "lanus",         "kickoff": "2026-11-22 19:00"},
    {"id": 3,  "round": "8vos",  "a": "argentinos", "b": "independiente", "kickoff": "2026-11-21 17:00"},
    {"id": 4,  "round": "8vos",  "a": "velez",      "b": "belgrano",      "kickoff": "2026-11-20 20:00"},
    {"id": 5,  "round": "8vos",  "a": "central",    "b": "gimnasia_mza",  "kickoff": "2026-11-22 16:00"},
    {"id": 6,  "round": "8vos",  "a": "defensa",    "b": "barracas",      "kickoff": "2026-11-21 15:00"},
    {"id": 7,  "round": "8vos",  "a": "boca",       "b": "ind_rivadavia", "kickoff": "2026-11-25 21:00"},
    {"id": 8,  "round": "8vos",  "a": "gimnasia_lp", "b": "newells",      "kickoff": "2026-11-23 17:00"},
    {"id": 9,  "round": "4tos",  "a": ("W", 1),  "b": ("W", 2),  "kickoff": None},
    {"id": 10, "round": "4tos",  "a": ("W", 3),  "b": ("W", 4),  "kickoff": None},
    {"id": 11, "round": "4tos",  "a": ("W", 5),  "b": ("W", 6),  "kickoff": None},
    {"id": 12, "round": "4tos",  "a": ("W", 7),  "b": ("W", 8),  "kickoff": None},
    {"id": 13, "round": "semi",  "a": ("W", 9),  "b": ("W", 10), "kickoff": None},
    {"id": 14, "round": "semi",  "a": ("W", 11), "b": ("W", 12), "kickoff": None},
    {"id": 15, "round": "final", "a": ("W", 13), "b": ("W", 14), "kickoff": None},
]

ICONS = ["⚽", "🦁", "🐯", "🦅", "🐺", "🦊", "🐻", "🐼", "🐸", "🐙", "🦈", "🐐",
         "🔥", "⚡", "🌟", "👑", "🎩", "🧉", "🥩", "🍕", "🍺", "🚀", "🎯", "💎"]

# Puntaje
PTS_EXACTO = 3      # resultado exacto de los 90'
PTS_TENDENCIA = 1   # ganador o empate correcto (sin el marcador exacto)
PTS_PASA = 1        # extra por acertar quién pasa de ronda


def puntos(pred_a, pred_b, pred_pasa, real_a, real_b, real_pasa):
    """Devuelve (puntos, exacto?, acertó_pasa?)."""
    pts = 0
    exacto = pred_a == real_a and pred_b == real_b
    if exacto:
        pts += PTS_EXACTO
    elif _signo(pred_a - pred_b) == _signo(real_a - real_b):
        pts += PTS_TENDENCIA
    pasa = pred_pasa is not None and pred_pasa == real_pasa
    if pasa:
        pts += PTS_PASA
    return pts, exacto, pasa


def _signo(x):
    return (x > 0) - (x < 0)
