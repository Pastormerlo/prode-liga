# Prode Liga Argentina

Prode de la fase final (octavos → final) para jugar con amigos. Cada uno entra con **nombre + ícono + PIN**, sin mails ni cuentas.

- **Puntaje:** resultado exacto de los 90' = 3 · ganador/empate = 1 · acertar quién pasa = +1
- **Cierre:** cada partido se cierra a su hora de inicio; ahí se ven los pronósticos de todos.
- **Resultados:** se leen de Promiedos (botón "Traer resultados" para el admin + automático cada 30 min con GitHub Actions).
- Stack: Flask + Postgres en Render (igual que control-drenaje).

## Probar en la PC

```powershell
python -m venv .venv
.venv\Scripts\pip install flask flask-limiter requests sqlalchemy
.venv\Scripts\python app.py
```
Abrir http://localhost:5000 · admin en http://localhost:5000/admin con la clave `admin` (solo en la PC).

## Publicar

1. **GitHub:** crear el repo `prode-liga` y subir esta carpeta.
2. **Render:** New → Blueprint → elegir el repo. Crea la app y la base Postgres con `render.yaml`.
   - Te pide `ADMIN_KEY`: inventá una clave para el panel de admin.
   - `SECRET_KEY` y `SYNC_TOKEN` se generan solas.
3. **GitHub Actions** (cada 10 min mantiene despierta la app y trae resultados): en el repo → Settings → Secrets and variables → Actions, crear el secreto
   `SYNC_TOKEN` = el mismo valor que generó Render (Render → prode-liga → Environment).
4. Pasar el link al grupo.

## Admin

`/admin` con la `ADMIN_KEY`: traer resultados, cargar/corregir resultados a mano, fijar horarios de cuartos/semis/final, resetear PIN o borrar participantes. Logueado como admin, en la página principal aparece la barra con "Traer resultados".

Notas: la base gratis de Render dura 30 días (alcanza hasta la final del 12/12). La app gratis "duerme" a los 15 min sin uso; el workflow la despierta cada 10 min para evitarlo.
