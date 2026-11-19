import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import create_engine, inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

import promiedos
import torneo

ART = timezone(timedelta(hours=-3))  # Argentina no tiene horario de verano

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=120),
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
)
limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")

# En tu PC (sin la variable RENDER) la clave de admin por defecto es "admin"
ADMIN_KEY = os.environ.get("ADMIN_KEY") or ("" if os.environ.get("RENDER") else "admin")
SYNC_TOKEN = os.environ.get("SYNC_TOKEN", "")

# ---------------------------------------------------------------- base de datos
db_url = os.environ.get("DATABASE_URL") or "sqlite:///prode_local.db"
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
engine = create_engine(db_url, pool_pre_ping=True)
IS_PG = engine.dialect.name == "postgresql"


def init_db():
    pk = "SERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as c:
        c.execute(text(f"""CREATE TABLE IF NOT EXISTS groups (
            id {pk}, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            clave TEXT, created_at TEXT NOT NULL)"""))
        c.execute(text(f"""CREATE TABLE IF NOT EXISTS users (
            id {pk}, group_id INTEGER, name TEXT NOT NULL, name_key TEXT NOT NULL,
            icon TEXT NOT NULL, pin_hash TEXT NOT NULL, created_at TEXT NOT NULL)"""))
        c.execute(text("""CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY, kickoff TEXT, kickoff_manual INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pendiente', goals_a INTEGER, goals_b INTEGER,
            pens_a INTEGER, pens_b INTEGER, advance TEXT, minute TEXT,
            result_manual INTEGER DEFAULT 0, review TEXT, updated_at TEXT)"""))
        c.execute(text("""CREATE TABLE IF NOT EXISTS predictions (
            user_id INTEGER NOT NULL, match_id INTEGER NOT NULL,
            team_a TEXT, team_b TEXT, goals_a INTEGER NOT NULL, goals_b INTEGER NOT NULL,
            advance TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, match_id))"""))
        c.execute(text("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)"))
        c.execute(text("""CREATE TABLE IF NOT EXISTS login_fails (
            name_key TEXT PRIMARY KEY, fails INTEGER NOT NULL DEFAULT 0, locked_until TEXT)"""))
        for m in torneo.MATCHES:
            c.execute(text("""INSERT INTO matches (id, kickoff) VALUES (:id, :k)
                              ON CONFLICT (id) DO NOTHING"""), {"id": m["id"], "k": m["kickoff"]})


def q(sql, **p):
    with engine.begin() as c:
        res = c.execute(text(sql), p)
        return [dict(r._mapping) for r in res] if res.returns_rows else []


def now_art():
    return datetime.now(ART).replace(tzinfo=None)


def stamp():
    return now_art().strftime("%Y-%m-%d %H:%M:%S")


def set_meta(k, v):
    q("INSERT INTO meta (k, v) VALUES (:k, :v) ON CONFLICT (k) DO UPDATE SET v = :v", k=k, v=v)


def get_meta(k):
    r = q("SELECT v FROM meta WHERE k = :k", k=k)
    return r[0]["v"] if r else None


def migrate_groups():
    """Antes había un solo prode: los que ya estaban anotados pasan al grupo "Amigos"."""
    if not q("SELECT 1 FROM groups"):
        q("INSERT INTO groups (slug, name, clave, created_at) VALUES ('amigos', 'Amigos', NULL, :c)", c=stamp())
    cols = [c["name"] for c in inspect(engine).get_columns("users")]
    if "group_id" not in cols:
        if IS_PG:
            q("ALTER TABLE users ADD COLUMN group_id INTEGER")
            q("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_name_key_key")
        else:  # SQLite no puede borrar un UNIQUE: se rearma la tabla
            with engine.begin() as c:
                c.execute(text("ALTER TABLE users RENAME TO users_old"))
                c.execute(text("""CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, name TEXT NOT NULL,
                    name_key TEXT NOT NULL, icon TEXT NOT NULL, pin_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL)"""))
                c.execute(text("""INSERT INTO users (id, name, name_key, icon, pin_hash, created_at)
                                  SELECT id, name, name_key, icon, pin_hash, created_at FROM users_old"""))
                c.execute(text("DROP TABLE users_old"))
    first = q("SELECT MIN(id) AS id FROM groups")[0]["id"]
    q("UPDATE users SET group_id = :g WHERE group_id IS NULL", g=first)
    q("CREATE UNIQUE INDEX IF NOT EXISTS users_group_name ON users (group_id, name_key)")


init_db()
migrate_groups()


# ---------------------------------------------------------------- cuadro
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
ROUND_NAME = {r[0]: r[1] for r in torneo.ROUNDS}


def fmt_kickoff(k):
    if not k:
        return "Fecha a confirmar"
    d = datetime.strptime(k, "%Y-%m-%d %H:%M")
    return f"{DIAS[d.weekday()]} {d:%d/%m} · {d:%H:%M}"


def build_matches():
    """Arma los 15 partidos con equipos resueltos según los resultados."""
    rows = {r["id"]: r for r in q("SELECT * FROM matches")}
    now = now_art()
    out = {}
    for m in torneo.MATCHES:
        r = rows[m["id"]]
        mm = {"id": m["id"], "round": m["round"], "round_name": ROUND_NAME[m["round"]], **r}
        for side in ("a", "b"):
            src = m[side]
            if isinstance(src, tuple):
                prev = out[src[1]]
                key = prev["winner_key"]
                mm[f"label_{side}"] = f"Ganador P{src[1]}"
            else:
                key = src
                mm[f"label_{side}"] = None
            mm[f"key_{side}"] = key
            mm[f"team_{side}"] = ({"key": key, **torneo.TEAMS[key]} if key else None)
        mm["ready"] = bool(mm["key_a"] and mm["key_b"])
        mm["final"] = r["status"] == "final" and r["advance"] in ("a", "b")
        mm["winner_key"] = mm[f"key_{r['advance']}"] if mm["final"] else None
        ko = datetime.strptime(r["kickoff"], "%Y-%m-%d %H:%M") if r["kickoff"] else None
        mm["kickoff_iso"] = ko.strftime("%Y-%m-%dT%H:%M:00-03:00") if ko else None
        mm["kickoff_txt"] = fmt_kickoff(r["kickoff"])
        mm["locked"] = r["status"] != "pendiente" or (ko is not None and now >= ko)
        mm["open"] = mm["ready"] and not mm["locked"]
        out[m["id"]] = mm
    return out


def score_pred(p, m):
    if not m["final"] or p["team_a"] != m["key_a"] or p["team_b"] != m["key_b"]:
        return None
    pts, exacto, pasa = torneo.puntos(p["goals_a"], p["goals_b"], p["advance"],
                                      m["goals_a"], m["goals_b"], m["advance"])
    return {"pts": pts, "exacto": exacto, "pasa": pasa}


def standings(matches, users, preds):
    tabla = {u["id"]: {**u, "pts": 0, "exactos": 0, "pasa": 0, "jugados": 0} for u in users}
    for p in preds:
        s = score_pred(p, matches[p["match_id"]])
        if s and p["user_id"] in tabla:
            t = tabla[p["user_id"]]
            t["pts"] += s["pts"]
            t["exactos"] += s["exacto"]
            t["pasa"] += s["pasa"]
            t["jugados"] += 1
    rows = sorted(tabla.values(), key=lambda t: (-t["pts"], -t["exactos"], -t["pasa"], t["name"].lower()))
    pos, prev = 0, None
    for i, t in enumerate(rows, 1):
        k = (t["pts"], t["exactos"], t["pasa"])
        if k != prev:
            pos, prev = i, k
        t["pos"] = pos
    return rows


# ---------------------------------------------------------------- seguridad
def name_key(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def weak_pin(pin):
    """PIN fáciles de adivinar: 0000, 1212, 1122, 1234, 4321, años, etc."""
    d = [int(c) for c in pin]
    steps = {d[i + 1] - d[i] for i in range(3)}
    if steps in ({0}, {1}, {-1}):           # 1111, 1234, 4321
        return True
    if d[0] == d[2] and d[1] == d[3]:        # 1212
        return True
    if d[0] == d[1] and d[2] == d[3]:        # 1122
        return True
    if 1940 <= int(pin) <= 2030:             # años
        return True
    return pin in {"0007", "1004", "2580", "0852", "6969", "1357", "2468", "9999"}


MAX_FAILS = 5
LOCK_MINUTES = 15


def lock_remaining(key):
    """Minutos que le quedan de bloqueo a un nombre (0 si no está bloqueado)."""
    r = q("SELECT locked_until FROM login_fails WHERE name_key = :k", k=key)
    if not r or not r[0]["locked_until"]:
        return 0
    until = datetime.strptime(r[0]["locked_until"], "%Y-%m-%d %H:%M:%S")
    secs = (until - now_art()).total_seconds()
    return max(0, int(secs // 60) + 1) if secs > 0 else 0


def register_fail(key):
    r = q("SELECT fails FROM login_fails WHERE name_key = :k", k=key)
    fails = (r[0]["fails"] if r else 0) + 1
    until = None
    if fails >= MAX_FAILS:
        fails = 0
        until = (now_art() + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    q("""INSERT INTO login_fails (name_key, fails, locked_until) VALUES (:k, :f, :u)
         ON CONFLICT (name_key) DO UPDATE SET fails = :f, locked_until = :u""", k=key, f=fails, u=until)
    return until is not None


# ---------------------------------------------------------------- grupos
def slugify(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:30] or "grupo"


def get_group(slug):
    r = q("SELECT * FROM groups WHERE slug = :s", s=slug)
    return r[0] if r else None


def all_groups():
    return q("""SELECT g.id, g.slug, g.name, g.clave, COUNT(u.id) AS n
                FROM groups g LEFT JOIN users u ON u.group_id = g.id
                GROUP BY g.id, g.slug, g.name, g.clave ORDER BY g.name""")


def clave_ok(g, clave):
    want = (g["clave"] or "").strip().lower()
    return not want or secrets.compare_digest(str(clave or "").strip().lower(), want)


def my_uids():
    """Un mismo celular puede estar anotado en varios grupos: {id_grupo: id_usuario}."""
    uids = dict(session.get("uids") or {})
    old = session.pop("uid", None)  # sesiones de antes de que existieran los grupos
    if old:
        r = q("SELECT group_id FROM users WHERE id = :id", id=old)
        if r:
            uids[str(r[0]["group_id"])] = old
        session["uids"] = uids
    return uids


def login_user(gid, uid):
    uids = my_uids()
    uids[str(gid)] = uid
    session["uids"] = uids
    session.permanent = True


def logout_user(gid):
    uids = my_uids()
    uids.pop(str(gid), None)
    session["uids"] = uids


def current_user(g):
    uid = my_uids().get(str(g["id"]))
    if not uid:
        return None
    r = q("SELECT id, name, icon FROM users WHERE id = :id AND group_id = :g", id=uid, g=g["id"])
    if not r:
        logout_user(g["id"])
        return None
    return r[0]


def body_group():
    g = get_group(str(body().get("group", "")))
    if not g:
        abort(404)
    return g


def is_admin():
    return bool(ADMIN_KEY) and session.get("admin") is True


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST" and request.path.startswith("/api/") and request.path != "/api/sync":
        tok = request.headers.get("X-CSRF", "")
        if not tok or not secrets.compare_digest(tok, session.get("csrf", "")):
            abort(403)


def body():
    return request.get_json(silent=True) or {}


def err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


# ---------------------------------------------------------------- páginas
@app.route("/")
def index():
    groups = all_groups()
    mine = [g for g in groups if str(g["id"]) in my_uids()]
    if len(groups) == 1:
        return redirect(url_for("grupo", slug=groups[0]["slug"]))
    if len(mine) == 1 and not request.args.get("todos"):
        return redirect(url_for("grupo", slug=mine[0]["slug"]))
    mine_ids = {g["id"] for g in mine}
    return render_template("grupos.html", t=torneo, groups=groups, mine_ids=mine_ids,
                           admin=is_admin(), csrf=csrf_token())


@app.route("/g/<slug>")
def grupo(slug):
    g = get_group(slug)
    if not g:
        return redirect(url_for("index", todos=1))
    me = current_user(g)
    admin = is_admin()
    can_view = bool(me or admin or not g["clave"])
    matches = build_matches()
    users = q("SELECT id, name, icon FROM users WHERE group_id = :g", g=g["id"])
    preds = q("""SELECT p.* FROM predictions p JOIN users u ON u.id = p.user_id
                 WHERE u.group_id = :g""", g=g["id"])
    tabla = standings(matches, users, preds) if can_view else []
    user_by_id = {u["id"]: u for u in users}

    by_match = {}
    for p in preds:
        by_match.setdefault(p["match_id"], []).append(p)
    for m in matches.values():
        lst = by_match.get(m["id"], [])
        m["n_preds"] = len(lst)
        m["mine"] = next((p for p in lst if me and p["user_id"] == me["id"]), None)
        if m["mine"]:
            m["mine_score"] = score_pred(m["mine"], m)
            m["mine_stale"] = (m["mine"]["team_a"] != m["key_a"] or m["mine"]["team_b"] != m["key_b"])
        m["others"] = []
        if m["locked"] and can_view:
            for p in lst:
                u = user_by_id.get(p["user_id"])
                if u:
                    m["others"].append({**p, "name": u["name"], "icon": u["icon"],
                                        "score": score_pred(p, m)})
            m["others"].sort(key=lambda o: (-(o["score"]["pts"] if o["score"] else 0), o["name"].lower()))

    rounds = []
    for key, name, when in torneo.ROUNDS:
        ms = [m for m in matches.values() if m["round"] == key]
        rounds.append({"key": key, "name": name, "when": when, "matches": ms})

    pending = sum(1 for m in matches.values() if m["open"] and not m.get("mine"))
    return render_template(
        "index.html", t=torneo, g=g, me=me, admin=admin, can_view=can_view, rounds=rounds,
        tabla=tabla, matches=matches, pending=pending, csrf=csrf_token(),
        n_groups=len(q("SELECT id FROM groups")),
        last_sync=get_meta("last_sync"), my_row=next((r for r in tabla if me and r["id"] == me["id"]), None),
    )


@app.route("/admin", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes", methods=["POST"])
def admin():
    error = None
    if request.method == "POST":
        key = request.form.get("key", "")
        if ADMIN_KEY and secrets.compare_digest(key, ADMIN_KEY):
            session.permanent = True
            session["admin"] = True
            return redirect(url_for("admin"))
        error = "Clave incorrecta" if ADMIN_KEY else "Falta configurar ADMIN_KEY en el servidor"
    if not is_admin():
        return render_template("admin_login.html", t=torneo, error=error)
    matches = build_matches()
    users = q("""SELECT u.id, u.name, u.icon, u.created_at, u.group_id, COUNT(p.match_id) AS n
                 FROM users u LEFT JOIN predictions p ON p.user_id = u.id
                 GROUP BY u.id, u.name, u.icon, u.created_at, u.group_id ORDER BY u.name""")
    groups = all_groups()
    for gr in groups:
        gr["users"] = [u for u in users if u["group_id"] == gr["id"]]
    return render_template("admin.html", t=torneo, matches=matches.values(), groups=groups,
                           csrf=csrf_token(), last_sync=get_meta("last_sync"),
                           last_sync_msg=get_meta("last_sync_msg"))


@app.route("/admin/salir")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- API jugadores
@app.post("/api/registro")
@limiter.limit("10 per hour")
def api_registro():
    g = body_group()
    d = body()
    name = re.sub(r"\s+", " ", str(d.get("name", ""))).strip()
    icon = str(d.get("icon", ""))
    pin = str(d.get("pin", ""))
    if not clave_ok(g, d.get("clave")):
        return err("La clave del grupo no es correcta. Pedísela a quien armó el grupo.")
    if not 2 <= len(name) <= 20:
        return err("El nombre tiene que tener entre 2 y 20 letras")
    if not name_key(name):
        return err("Usá letras o números en el nombre")
    if icon not in torneo.ICONS:
        return err("Elegí un ícono")
    if not re.fullmatch(r"\d{4}", pin):
        return err("El PIN tiene que ser de 4 números")
    if weak_pin(pin):
        return err("Ese PIN es muy fácil de adivinar (como 1234, 0000 o un año). Elegí otro.")
    if q("SELECT 1 FROM users WHERE group_id = :g AND name_key = :k", g=g["id"], k=name_key(name)):
        return err("Ese nombre ya está anotado en este grupo. Si sos vos, entrá con tu PIN.")
    r = q("""INSERT INTO users (group_id, name, name_key, icon, pin_hash, created_at)
             VALUES (:g, :n, :k, :i, :p, :c) RETURNING id""",
          g=g["id"], n=name, k=name_key(name), i=icon, p=generate_password_hash(pin), c=stamp())
    login_user(g["id"], r[0]["id"])
    return jsonify({"ok": True})


@app.post("/api/ingresar")
@limiter.limit("8 per 10 minutes")
def api_ingresar():
    g = body_group()
    d = body()
    nk = name_key(str(d.get("name", "")))
    key = f"{g['id']}:{nk}"
    mins = lock_remaining(key)
    if mins:
        return err(f"Demasiados PIN incorrectos para este nombre. Probá de nuevo en {mins} min.", 429)
    r = q("SELECT id, pin_hash FROM users WHERE group_id = :g AND name_key = :k", g=g["id"], k=nk)
    if not r:
        return err("Nombre o PIN incorrecto")
    if not check_password_hash(r[0]["pin_hash"], str(d.get("pin", ""))):
        if register_fail(key):
            return err(f"Demasiados PIN incorrectos. Este nombre queda bloqueado {LOCK_MINUTES} min.", 429)
        return err("Nombre o PIN incorrecto")
    q("DELETE FROM login_fails WHERE name_key = :k", k=key)
    login_user(g["id"], r[0]["id"])
    return jsonify({"ok": True})


@app.post("/api/salir")
def api_salir():
    logout_user(body_group()["id"])
    return jsonify({"ok": True})


@app.post("/api/perfil")
def api_perfil():
    me = current_user(body_group())
    if not me:
        return err("Tenés que entrar primero", 401)
    icon = str(body().get("icon", ""))
    if icon not in torneo.ICONS:
        return err("Ícono inválido")
    q("UPDATE users SET icon = :i WHERE id = :id", i=icon, id=me["id"])
    return jsonify({"ok": True})


@app.post("/api/pronostico")
def api_pronostico():
    me = current_user(body_group())
    if not me:
        return err("Tenés que entrar primero", 401)
    d = body()
    try:
        mid = int(d.get("match_id"))
        ga, gb = int(d.get("goals_a")), int(d.get("goals_b"))
    except (TypeError, ValueError):
        return err("Datos inválidos")
    if not (0 <= ga <= 20 and 0 <= gb <= 20):
        return err("Goles fuera de rango")
    m = build_matches().get(mid)
    if not m:
        return err("Partido inexistente", 404)
    if not m["ready"]:
        return err("Todavía no se conocen los dos equipos")
    if m["locked"]:
        return err("El partido ya empezó: no se pueden cambiar los pronósticos")
    adv = "a" if ga > gb else "b" if gb > ga else d.get("advance")
    if adv not in ("a", "b"):
        return err("Si pronosticás empate, elegí quién pasa")
    q("""INSERT INTO predictions (user_id, match_id, team_a, team_b, goals_a, goals_b, advance, updated_at)
         VALUES (:u, :m, :ta, :tb, :ga, :gb, :adv, :t)
         ON CONFLICT (user_id, match_id) DO UPDATE SET team_a = :ta, team_b = :tb,
            goals_a = :ga, goals_b = :gb, advance = :adv, updated_at = :t""",
      u=me["id"], m=mid, ta=m["key_a"], tb=m["key_b"], ga=ga, gb=gb, adv=adv, t=stamp())
    return jsonify({"ok": True, "advance": adv})


# ---------------------------------------------------------------- sincronización
def kickoff_offset(games):
    """Promiedos devuelve los horarios en la zona del país desde donde se
    consulta (Render está en EE.UU.). Se compara con los horarios de octavos
    conocidos (hora argentina) para obtener la diferencia y corregir el resto."""
    seed = {}
    for m in torneo.MATCHES:
        if m["round"] == "8vos" and m["kickoff"]:
            pa, pb = torneo.TEAMS[m["a"]]["pid"], torneo.TEAMS[m["b"]]["pid"]
            seed[(pa, pb)] = seed[(pb, pa)] = datetime.strptime(m["kickoff"], "%Y-%m-%d %H:%M")
    deltas = []
    for g in games:
        if g["kickoff"] and g["pids"] in seed:
            deltas.append(seed[g["pids"]] - datetime.strptime(g["kickoff"], "%Y-%m-%d %H:%M"))
    if not deltas:
        return None
    return max(set(deltas), key=deltas.count)  # la diferencia más repetida


def run_sync():
    games = promiedos.fetch_games()
    matches = build_matches()
    by_pids = {}
    for m in matches.values():
        if m["ready"]:
            by_pids[(m["team_a"]["pid"], m["team_b"]["pid"])] = (m, False)
            by_pids[(m["team_b"]["pid"], m["team_a"]["pid"])] = (m, True)
    changes = []
    offset = kickoff_offset(games)
    # Se procesa en orden de ronda: si termina un partido de octavos, el cruce
    # de cuartos recién se conoce en la próxima corrida (o en el mismo botón,
    # que corre dos pasadas).
    for g in games:
        hit = by_pids.get(g["pids"])
        if not hit:
            continue
        m, swapped = hit
        upd = {}
        if g["kickoff"] and offset is not None and not m["kickoff_manual"]:
            fixed = (datetime.strptime(g["kickoff"], "%Y-%m-%d %H:%M") + offset).strftime("%Y-%m-%d %H:%M")
            if fixed != m["kickoff"]:
                upd["kickoff"] = fixed
        if not m["result_manual"] and g["status"] != "pendiente":
            ga, gb = g["goals"] if not swapped else (g["goals"][1], g["goals"][0])
            pens = g["pens"]
            if pens and swapped:
                pens = (pens[1], pens[0])
            adv = None
            if g["winner"] is not None:
                adv = "a" if (g["winner"] == 0) != swapped else "b"
            new = {"status": g["status"], "goals_a": ga, "goals_b": gb,
                   "pens_a": pens[0] if pens else None, "pens_b": pens[1] if pens else None,
                   "advance": adv if g["status"] == "final" else None,
                   "minute": g["minute"] if g["status"] == "en_juego" else None,
                   "review": g["review"]}
            for k, v in new.items():
                if m[k] != v:
                    upd[k] = v
        if upd:
            upd["updated_at"] = stamp()
            sets = ", ".join(f"{k} = :{k}" for k in upd)
            q(f"UPDATE matches SET {sets} WHERE id = :id", id=m["id"], **upd)
            changes.append(f"P{m['id']}: " + ", ".join(k for k in upd if k != "updated_at"))
    return len(games), changes


def sync_and_record():
    n, changes = run_sync()
    if changes:  # segunda pasada para los cruces que se acaban de definir
        n2, ch2 = run_sync()
        changes += ch2
    msg = f"{n} partidos leídos de Promiedos, {len(changes)} cambios"
    set_meta("last_sync", stamp())
    set_meta("last_sync_msg", msg + (": " + "; ".join(changes) if changes else ""))
    return {"ok": True, "leidos": n, "cambios": changes, "msg": msg}


@app.post("/api/sync")
@limiter.limit("20 per hour")
def api_sync_cron():
    tok = request.headers.get("X-Sync-Token", "")
    if not SYNC_TOKEN or not secrets.compare_digest(tok, SYNC_TOKEN):
        abort(403)
    return jsonify(sync_and_record())


# ---------------------------------------------------------------- API admin
def require_admin():
    if not is_admin():
        abort(403)


@app.post("/api/admin/sync")
def api_admin_sync():
    require_admin()
    try:
        return jsonify(sync_and_record())
    except Exception as e:  # noqa: BLE001
        return err(f"No se pudo leer Promiedos: {e}", 502)


@app.post("/api/admin/resultado")
def api_admin_resultado():
    require_admin()
    d = body()
    mid = int(d.get("match_id", 0))
    if mid not in {m["id"] for m in torneo.MATCHES}:
        return err("Partido inexistente")
    if d.get("clear"):
        q("""UPDATE matches SET status='pendiente', goals_a=NULL, goals_b=NULL, pens_a=NULL,
             pens_b=NULL, advance=NULL, minute=NULL, result_manual=0, review=NULL, updated_at=:t
             WHERE id=:id""", id=mid, t=stamp())
        return jsonify({"ok": True})
    try:
        ga, gb = int(d["goals_a"]), int(d["goals_b"])
    except (KeyError, TypeError, ValueError):
        return err("Cargá los goles de los dos equipos")
    adv = "a" if ga > gb else "b" if gb > ga else d.get("advance")
    if adv not in ("a", "b"):
        return err("Si fue empate en los 90', elegí quién pasó")
    q("""UPDATE matches SET status='final', goals_a=:ga, goals_b=:gb, advance=:adv, minute=NULL,
         result_manual=1, review=NULL, updated_at=:t WHERE id=:id""",
      ga=ga, gb=gb, adv=adv, id=mid, t=stamp())
    return jsonify({"ok": True})


@app.post("/api/admin/horario")
def api_admin_horario():
    require_admin()
    d = body()
    mid = int(d.get("match_id", 0))
    k = str(d.get("kickoff", "")).replace("T", " ").strip()
    if not k:
        q("UPDATE matches SET kickoff=NULL, kickoff_manual=0 WHERE id=:id", id=mid)
        return jsonify({"ok": True})
    try:
        datetime.strptime(k, "%Y-%m-%d %H:%M")
    except ValueError:
        return err("Formato de fecha inválido")
    q("UPDATE matches SET kickoff=:k, kickoff_manual=1 WHERE id=:id", k=k, id=mid)
    return jsonify({"ok": True})


@app.post("/api/admin/usuario")
def api_admin_usuario():
    require_admin()
    d = body()
    uid = int(d.get("user_id", 0))
    if d.get("action") == "borrar":
        q("DELETE FROM predictions WHERE user_id=:id", id=uid)
        q("DELETE FROM users WHERE id=:id", id=uid)
        return jsonify({"ok": True})
    if d.get("action") == "pin":
        pin = str(d.get("pin", ""))
        if not re.fullmatch(r"\d{4}", pin):
            return err("El PIN tiene que ser de 4 números")
        q("UPDATE users SET pin_hash=:p WHERE id=:id", p=generate_password_hash(pin), id=uid)
        # el nuevo PIN también desbloquea el nombre
        r = q("SELECT group_id, name_key FROM users WHERE id=:id", id=uid)
        if r:
            q("DELETE FROM login_fails WHERE name_key = :k", k=f"{r[0]['group_id']}:{r[0]['name_key']}")
        return jsonify({"ok": True})
    return err("Acción inválida")


@app.post("/api/admin/grupo")
def api_admin_grupo():
    require_admin()
    d = body()
    act = d.get("action")
    name = re.sub(r"\s+", " ", str(d.get("name", ""))).strip()
    clave = str(d.get("clave", "")).strip() or None
    if clave and len(clave) > 30:
        return err("La clave puede tener hasta 30 letras")
    if act in ("crear", "editar") and not 2 <= len(name) <= 30:
        return err("El nombre del grupo tiene que tener entre 2 y 30 letras")
    if act == "crear":
        base = slugify(name)
        slug, i = base, 2
        while get_group(slug):
            slug, i = f"{base}-{i}", i + 1
        q("INSERT INTO groups (slug, name, clave, created_at) VALUES (:s, :n, :c, :t)",
          s=slug, n=name, c=clave, t=stamp())
        return jsonify({"ok": True, "slug": slug})
    gid = int(d.get("group_id", 0))
    if not q("SELECT 1 FROM groups WHERE id = :id", id=gid):
        return err("Grupo inexistente", 404)
    if act == "editar":
        q("UPDATE groups SET name = :n, clave = :c WHERE id = :id", n=name, c=clave, id=gid)
        return jsonify({"ok": True})
    if act == "borrar":
        if len(q("SELECT id FROM groups")) == 1:
            return err("Tiene que quedar al menos un grupo")
        q("DELETE FROM predictions WHERE user_id IN (SELECT id FROM users WHERE group_id = :g)", g=gid)
        q("DELETE FROM users WHERE group_id = :g", g=gid)
        q("DELETE FROM groups WHERE id = :g", g=gid)
        return jsonify({"ok": True})
    return err("Acción inválida")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
