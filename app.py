import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import create_engine, text
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
        c.execute(text(f"""CREATE TABLE IF NOT EXISTS users (
            id {pk}, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
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
        for m in torneo.MATCHES:
            c.execute(text("""INSERT INTO matches (id, kickoff) VALUES (:id, :k)
                              ON CONFLICT (id) DO NOTHING"""), {"id": m["id"], "k": m["kickoff"]})


init_db()


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


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    r = q("SELECT id, name, icon FROM users WHERE id = :id", id=uid)
    if not r:
        session.pop("uid", None)
        return None
    return r[0]


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
    me = current_user()
    matches = build_matches()
    users = q("SELECT id, name, icon FROM users")
    preds = q("SELECT * FROM predictions")
    tabla = standings(matches, users, preds)
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
        if m["locked"]:
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
        "index.html", t=torneo, me=me, admin=is_admin(), rounds=rounds, tabla=tabla,
        matches=matches, pending=pending, csrf=csrf_token(),
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
    users = q("""SELECT u.id, u.name, u.icon, u.created_at, COUNT(p.match_id) AS n
                 FROM users u LEFT JOIN predictions p ON p.user_id = u.id
                 GROUP BY u.id, u.name, u.icon, u.created_at ORDER BY u.name""")
    return render_template("admin.html", t=torneo, matches=matches.values(), users=users,
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
    d = body()
    name = re.sub(r"\s+", " ", str(d.get("name", ""))).strip()
    icon = str(d.get("icon", ""))
    pin = str(d.get("pin", ""))
    if not 2 <= len(name) <= 20:
        return err("El nombre tiene que tener entre 2 y 20 letras")
    if not name_key(name):
        return err("Usá letras o números en el nombre")
    if icon not in torneo.ICONS:
        return err("Elegí un ícono")
    if not re.fullmatch(r"\d{4}", pin):
        return err("El PIN tiene que ser de 4 números")
    if q("SELECT 1 FROM users WHERE name_key = :k", k=name_key(name)):
        return err("Ese nombre ya está anotado. Si sos vos, entrá con tu PIN.")
    r = q("""INSERT INTO users (name, name_key, icon, pin_hash, created_at)
             VALUES (:n, :k, :i, :p, :c) RETURNING id""",
          n=name, k=name_key(name), i=icon, p=generate_password_hash(pin), c=stamp())
    session.permanent = True
    session["uid"] = r[0]["id"]
    return jsonify({"ok": True})


@app.post("/api/ingresar")
@limiter.limit("8 per 10 minutes")
def api_ingresar():
    d = body()
    r = q("SELECT id, pin_hash FROM users WHERE name_key = :k", k=name_key(str(d.get("name", ""))))
    if not r or not check_password_hash(r[0]["pin_hash"], str(d.get("pin", ""))):
        return err("Nombre o PIN incorrecto")
    session.permanent = True
    session["uid"] = r[0]["id"]
    return jsonify({"ok": True})


@app.post("/api/salir")
def api_salir():
    session.pop("uid", None)
    return jsonify({"ok": True})


@app.post("/api/perfil")
def api_perfil():
    me = current_user()
    if not me:
        return err("Tenés que entrar primero", 401)
    icon = str(body().get("icon", ""))
    if icon not in torneo.ICONS:
        return err("Ícono inválido")
    q("UPDATE users SET icon = :i WHERE id = :id", i=icon, id=me["id"])
    return jsonify({"ok": True})


@app.post("/api/pronostico")
def api_pronostico():
    me = current_user()
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
def run_sync():
    games = promiedos.fetch_games()
    matches = build_matches()
    by_pids = {}
    for m in matches.values():
        if m["ready"]:
            by_pids[(m["team_a"]["pid"], m["team_b"]["pid"])] = (m, False)
            by_pids[(m["team_b"]["pid"], m["team_a"]["pid"])] = (m, True)
    changes = []
    # Se procesa en orden de ronda: si termina un partido de octavos, el cruce
    # de cuartos recién se conoce en la próxima corrida (o en el mismo botón,
    # que corre dos pasadas).
    for g in games:
        hit = by_pids.get(g["pids"])
        if not hit:
            continue
        m, swapped = hit
        upd = {}
        if g["kickoff"] and not m["kickoff_manual"] and g["kickoff"] != m["kickoff"]:
            upd["kickoff"] = g["kickoff"]
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
        return jsonify({"ok": True})
    return err("Acción inválida")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
