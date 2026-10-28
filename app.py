import os
import sqlite3
import math
import json
import urllib.request
import urllib.error
import re
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, jsonify

try:
    from bs4 import BeautifulSoup
    BS4_DISPONIBLE = True
except ImportError:
    BS4_DISPONIBLE = False

# Soporte para PostgreSQL (Supabase)
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PG_DISPONIBLE = True
except ImportError:
    PG_DISPONIBLE = False

app = Flask(__name__)
DB_NAME = "control_futbol.db"

HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8'
}

DICCIONARIO_LIGAS = {
    "ecuador": "ecu.1", "ligapro": "ecu.1", "ecu.1": "ecu.1",
    "colombia": "col.1", "betplay": "col.1", "col.1": "col.1",
    "espana": "esp.1", "españa": "esp.1", "laliga": "esp.1", "esp.1": "esp.1",
    "inglaterra": "eng.1", "premier": "eng.1", "premier league": "eng.1", "eng.1": "eng.1",
    "championship": "eng.2", "eng.2": "eng.2", "efl championship": "eng.2",
    "league one": "eng.3", "eng.3": "eng.3",
    "carabao": "eng.league_cup", "league cup": "eng.league_cup", "eng.league_cup": "eng.league_cup",
    "italia": "ita.1", "serie a": "ita.1", "calcio": "ita.1", "ita.1": "ita.1",
    "alemania": "ger.1", "bundesliga": "ger.1", "ger.1": "ger.1",
    "francia": "fra.1", "ligue 1": "fra.1", "fra.1": "fra.1",
    "argentina": "arg.1", "liga profesional": "arg.1", "arg.1": "arg.1",
    "mexico": "mex.1", "méxico": "mex.1", "liga mx": "mex.1", "mex.1": "mex.1",
    "chile": "chi.1", "campeonato nacional": "chi.1", "chi.1": "chi.1",
    "peru": "per.1", "perú": "per.1", "liga 1": "per.1", "per.1": "per.1",
    "bolivia": "bol.1", "division profesional": "bol.1", "bol.1": "bol.1",
    "brasil": "bra.1", "brasileirao": "bra.1", "bra.1": "bra.1",
    "usa": "usa.1", "mls": "usa.1", "estados unidos": "usa.1", "usa.1": "usa.1",
    "holanda": "ned.1", "paises bajos": "ned.1", "eredivisie": "ned.1", "ned.1": "ned.1",
    "portugal": "por.1", "primeira liga": "por.1", "por.1": "por.1",
    "australia": "aus.1", "a-league": "aus.1", "aus.1": "aus.1",
    "champions": "uefa.champions", "champions league": "uefa.champions", "uefa.champions": "uefa.champions",
    "europa league": "uefa.europa", "uefa.europa": "uefa.europa",
    "conference": "uefa.europa.conf", "conference league": "uefa.europa.conf", "uefa.europa.conf": "uefa.europa.conf",
    "libertadores": "conmebol.libertadores", "conmebol.libertadores": "conmebol.libertadores",
    "sudamericana": "conmebol.sudamericana", "conmebol.sudamericana": "conmebol.sudamericana"
}

LIGAS_INICIALES = [
    ("ecu.1", "LigaPro Ecuador", "Ecuador"),
    ("esp.1", "LaLiga España", "España"),
    ("eng.1", "Premier League", "Inglaterra"),
    ("eng.2", "EFL Championship", "Inglaterra"),
    ("eng.3", "League One Inglaterra", "Inglaterra"),
    ("eng.league_cup", "Carabao Cup Inglaterra", "Inglaterra"),
    ("ita.1", "Serie A Italia", "Italia"),
    ("ger.1", "Bundesliga", "Alemania"),
    ("fra.1", "Ligue 1", "Francia"),
    ("col.1", "Liga BetPlay", "Colombia"),
    ("arg.1", "Liga Profesional", "Argentina"),
    ("bra.1", "Brasileirao Serie A", "Brasil"),
    ("mex.1", "Liga MX México", "México"),
    ("usa.1", "Major League Soccer (MLS)", "Estados Unidos"),
    ("por.1", "Primeira Liga Portugal", "Portugal"),
    ("ned.1", "Eredivisie Países Bajos", "Países Bajos"),
    ("per.1", "Liga 1 Perú", "Perú"),
    ("bol.1", "División Profesional Bolivia", "Bolivia"),
    ("aus.1", "A-League Australia", "Australia"),
    ("uefa.champions", "UEFA Champions League", "Europa"),
    ("uefa.europa", "UEFA Europa League", "Europa"),
    ("uefa.europa.conf", "UEFA Conference League", "Europa"),
    ("conmebol.libertadores", "Copa Libertadores", "Sudamérica"),
    ("conmebol.sudamericana", "Copa Sudamericana", "Sudamérica")
]

# ==============================================================================
# CONEXIÓN BLINDADA CON SUPABASE Y SQLITE
# ==============================================================================
def get_db_connection():
    if PG_DISPONIBLE:
        env_url = os.environ.get("DATABASE_URL")
        if env_url:
            try:
                url_limpia = env_url.replace("postgres://", "postgresql://", 1)
                if "CHIqui18..%" in url_limpia and "CHIqui18..%25" not in url_limpia:
                    url_limpia = url_limpia.replace("CHIqui18..%", "CHIqui18..%25")
                return psycopg2.connect(url_limpia, sslmode='require', connect_timeout=3)
            except Exception as e:
                print(f"[DB] Fallo conexion DATABASE_URL: {e}")

        hosts = ["aws-1-us-west-2.pooler.supabase.com", "aws-0-us-west-1.pooler.supabase.com"]
        for host in hosts:
            for port in [5432, 6543]:
                try:
                    return psycopg2.connect(
                        host=host, port=port, dbname="postgres",
                        user="postgres.waldnnzetbbmbsyokzxp", password="CHIqui18..%",
                        sslmode="require", connect_timeout=2
                    )
                except Exception:
                    pass

    return sqlite3.connect(DB_NAME)

def ejecutar_sql(query, params=(), fetch=None):
    conn = None
    try:
        conn = get_db_connection()
        is_pg = PG_DISPONIBLE and not isinstance(conn, sqlite3.Connection)
        
        if is_pg:
            query_pg = query.replace("?", "%s")
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query_pg, params)
        else:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(query, params)
            
        if fetch == "all":
            res = [dict(r) for r in cur.fetchall()]
        elif fetch == "one":
            fila = cur.fetchone()
            res = dict(fila) if fila else None
        else:
            res = None
        conn.commit()
        return res
    except Exception as ex:
        print(f"[SQL ERROR] {ex} | Query: {query}")
        if conn:
            try: conn.rollback()
            except Exception: pass
        return [] if fetch == "all" else None
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

def inicializar_bd():
    conn = None
    try:
        conn = get_db_connection()
        is_pg = PG_DISPONIBLE and not isinstance(conn, sqlite3.Connection)
        
        if is_pg:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS competiciones (
                    id TEXT PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    pais TEXT,
                    activa INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS partidos (
                    id SERIAL PRIMARY KEY,
                    fixture_id TEXT UNIQUE,
                    competicion_id TEXT REFERENCES competiciones(id),
                    fecha TIMESTAMPTZ,
                    temporada TEXT,
                    jornada TEXT,
                    local TEXT,
                    visitante TEXT,
                    goles_local INTEGER DEFAULT 0,
                    goles_visitante INTEGER DEFAULT 0,
                    corners_local INTEGER DEFAULT 0,
                    corners_visitante INTEGER DEFAULT 0,
                    tarjetas_local INTEGER DEFAULT 0,
                    tarjetas_visitante INTEGER DEFAULT 0,
                    offsides_local INTEGER DEFAULT 0,
                    offsides_visitante INTEGER DEFAULT 0,
                    estado TEXT DEFAULT 'programado',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            conn.commit()

            for lid, lnom, lpais in LIGAS_INICIALES:
                try:
                    cur.execute("""
                        INSERT INTO competiciones (id, nombre, pais, activa)
                        VALUES (%s, %s, %s, 1)
                        ON CONFLICT (id) DO UPDATE SET nombre = EXCLUDED.nombre, pais = EXCLUDED.pais, activa = 1
                    """, (lid, lnom, lpais))
                except Exception:
                    pass
            conn.commit()
        else:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS competiciones (
                    id TEXT PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    pais TEXT,
                    activa INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS partidos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fixture_id TEXT UNIQUE,
                    competicion_id TEXT,
                    fecha TEXT,
                    temporada TEXT,
                    jornada TEXT,
                    local TEXT,
                    visitante TEXT,
                    goles_local INTEGER DEFAULT 0,
                    goles_visitante INTEGER DEFAULT 0,
                    corners_local INTEGER DEFAULT 0,
                    corners_visitante INTEGER DEFAULT 0,
                    tarjetas_local INTEGER DEFAULT 0,
                    tarjetas_visitante INTEGER DEFAULT 0,
                    offsides_local INTEGER DEFAULT 0,
                    offsides_visitante INTEGER DEFAULT 0,
                    estado TEXT DEFAULT 'programado',
                    created_at TEXT,
                    updated_at TEXT
                );
            """)
            cur = conn.cursor()
            for lid, lnom, lpais in LIGAS_INICIALES:
                try:
                    cur.execute("INSERT OR REPLACE INTO competiciones (id, nombre, pais, activa) VALUES (?, ?, ?, 1)", (lid, lnom, lpais))
                except Exception:
                    pass
            conn.commit()
    except Exception as e:
        print(f"[INIT WARNING] {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

inicializar_bd()

# ==============================================================================
# GESTIÓN EXACTA DE HORA Y FECHA ECUADOR (UTC-5)
# ==============================================================================
def obtener_tiempos_ecuador(valor_fecha):
    tz_ecu = timezone(timedelta(hours=-5))
    if not valor_fecha:
        dt_ahora = datetime.now(timezone.utc).astimezone(tz_ecu)
        return dt_ahora.strftime("%Y-%m-%d"), "Por definir", dt_ahora.isoformat()

    try:
        dt = None
        if isinstance(valor_fecha, datetime):
            dt = valor_fecha.astimezone(tz_ecu) if valor_fecha.tzinfo else valor_fecha.replace(tzinfo=timezone.utc).astimezone(tz_ecu)
        else:
            s = str(valor_fecha).strip().replace("Z", "+00:00")
            if "T00:00" in s or " 00:00:00" in s:
                return s.split("T")[0].split(" ")[0], "Por definir", s

            if "+" in s or ("-" in s[10:]):
                dt_obj = datetime.fromisoformat(s)
                dt = dt_obj.astimezone(tz_ecu) if dt_obj.tzinfo else dt_obj.replace(tzinfo=timezone.utc).astimezone(tz_ecu)
            else:
                dt_obj = datetime.fromisoformat(s)
                dt = dt_obj.replace(tzinfo=timezone.utc).astimezone(tz_ecu)

        if dt:
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"), dt.isoformat()
    except Exception:
        pass

    s_raw = str(valor_fecha)
    return s_raw[:10], "Por definir", s_raw

def formatear_fecha_hora_ecuador(valor_fecha):
    f_ecu, h_ecu, _ = obtener_tiempos_ecuador(valor_fecha)
    return f_ecu, h_ecu

# ==============================================================================
# DESCARGA Y SINCRONIZACIÓN DE DATOS REALES ESPN
# ==============================================================================
def fetch_url(url):
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode('utf-8', errors='ignore')

def get_json(url):
    contenido = fetch_url(url)
    return json.loads(contenido)

def descargar_resumen_evento(codigo_liga, event_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/summary?event={event_id}"
    res = {"cl": 0, "cv": 0, "tl": 0, "tv": 0, "ol": 0, "ov": 0}
    try:
        data = get_json(url)
        teams = data.get("boxscore", {}).get("teams", [])
        if len(teams) >= 2:
            for i, pfx in enumerate(["l", "v"]):
                for s in teams[i].get("statistics", []):
                    nm = s.get("name", "").lower()
                    lbl = s.get("label", "").lower()
                    try: val = int(s.get("displayValue", 0))
                    except (ValueError, TypeError): val = 0
                    if any(k in nm or k in lbl for k in ["corner", "corners", "woncorners"]):
                        res[f"c{pfx}"] = val
                    elif any(k in nm or k in lbl for k in ["yellowcard", "yellow_card", "redcard", "red_card", "totalcards"]):
                        res[f"t{pfx}"] += val
                    elif any(k in nm or k in lbl for k in ["offside", "offsides"]):
                        res[f"o{pfx}"] = val
    except Exception:
        pass
    return res

def descargar_partidos_fecha(codigo_liga, fecha_str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/scoreboard?dates={fecha_str}"
    try:
        data = get_json(url)
        events = data.get("events", [])
        if not events:
            return 0, "No hay eventos"
            
        total_guardados = 0
        conn = get_db_connection()
        is_pg = PG_DISPONIBLE and not isinstance(conn, sqlite3.Connection)
        if conn:
            conn.close()
        
        for ev in events:
            fix_id = str(ev.get("id"))
            comps = ev.get("competitions", [{}])[0].get("competitors", [])
            if len(comps) < 2:
                continue
            loc_c = next((c for c in comps if c.get("homeAway") == "home"), comps[0])
            vis_c = next((c for c in comps if c.get("homeAway") == "away"), comps[1])
            loc = loc_c.get("team", {}).get("name", "").strip().upper()
            vis = vis_c.get("team", {}).get("name", "").strip().upper()
            gl = int(loc_c.get("score", 0) or 0)
            gv = int(vis_c.get("score", 0) or 0)
            
            comp_info = ev.get("competitions", [{}])[0]
            fecha_cruda = comp_info.get("date") or ev.get("date")
            _, _, fecha_guardar = obtener_tiempos_ecuador(fecha_cruda)

            status_obj = ev.get("status", {})
            type_obj = status_obj.get("type", {})
            state_espn = type_obj.get("state", "").lower()
            completed = type_obj.get("completed", False)
            desc_status = type_obj.get("description", "").lower()

            if state_espn == "in" or any(k in desc_status for k in ["in progress", "live", "en curso", "1st half", "2nd half", "halftime", "ht"]):
                estado = "en_vivo"
            elif state_espn == "post" or completed or any(k in desc_status for k in ["final", "ft", "ended"]):
                estado = "finalizado"
            else:
                estado = "programado"

            st = {"cl": 0, "cv": 0, "tl": 0, "tv": 0, "ol": 0, "ov": 0}
            if estado == "finalizado":
                st = descargar_resumen_evento(codigo_liga, fix_id)

            if is_pg:
                ejecutar_sql("""
                    INSERT INTO partidos 
                    (fixture_id, competicion_id, fecha, local, visitante, goles_local, goles_visitante,
                     corners_local, corners_visitante, tarjetas_local, tarjetas_visitante, offsides_local, offsides_visitante, estado)
                    VALUES (?, ?, ?::timestamptz, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (fixture_id) DO UPDATE SET 
                        fecha = EXCLUDED.fecha,
                        goles_local = EXCLUDED.goles_local,
                        goles_visitante = EXCLUDED.goles_visitante,
                        corners_local = CASE WHEN EXCLUDED.estado = 'finalizado' THEN EXCLUDED.corners_local ELSE partidos.corners_local END,
                        corners_visitante = CASE WHEN EXCLUDED.estado = 'finalizado' THEN EXCLUDED.corners_visitante ELSE partidos.corners_visitante END,
                        tarjetas_local = CASE WHEN EXCLUDED.estado = 'finalizado' THEN EXCLUDED.tarjetas_local ELSE partidos.tarjetas_local END,
                        tarjetas_visitante = CASE WHEN EXCLUDED.estado = 'finalizado' THEN EXCLUDED.tarjetas_visitante ELSE partidos.tarjetas_visitante END,
                        offsides_local = CASE WHEN EXCLUDED.estado = 'finalizado' THEN EXCLUDED.offsides_local ELSE partidos.offsides_local END,
                        offsides_visitante = CASE WHEN EXCLUDED.estado = 'finalizado' THEN EXCLUDED.offsides_visitante ELSE partidos.offsides_visitante END,
                        estado = EXCLUDED.estado,
                        updated_at = NOW()
                """, (fix_id, codigo_liga, fecha_guardar, loc, vis, gl, gv,
                      st["cl"], st["cv"], st["tl"], st["tv"], st["ol"], st["ov"], estado))
            else:
                ejecutar_sql("""
                    INSERT INTO partidos 
                    (fixture_id, competicion_id, fecha, local, visitante, goles_local, goles_visitante,
                     corners_local, corners_visitante, tarjetas_local, tarjetas_visitante, offsides_local, offsides_visitante, estado, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT (fixture_id) DO UPDATE SET 
                        fecha = excluded.fecha,
                        goles_local = excluded.goles_local,
                        goles_visitante = excluded.goles_visitante,
                        corners_local = CASE WHEN excluded.estado = 'finalizado' THEN excluded.corners_local ELSE partidos.corners_local END,
                        corners_visitante = CASE WHEN excluded.estado = 'finalizado' THEN excluded.corners_visitante ELSE partidos.corners_visitante END,
                        tarjetas_local = CASE WHEN excluded.estado = 'finalizado' THEN excluded.tarjetas_local ELSE partidos.tarjetas_local END,
                        tarjetas_visitante = CASE WHEN excluded.estado = 'finalizado' THEN excluded.tarjetas_visitante ELSE partidos.tarjetas_visitante END,
                        offsides_local = CASE WHEN excluded.estado = 'finalizado' THEN excluded.offsides_local ELSE partidos.offsides_local END,
                        offsides_visitante = CASE WHEN excluded.estado = 'finalizado' THEN excluded.offsides_visitante ELSE partidos.offsides_visitante END,
                        estado = excluded.estado,
                        updated_at = datetime('now')
                """, (fix_id, codigo_liga, fecha_guardar, loc, vis, gl, gv,
                      st["cl"], st["cv"], st["tl"], st["tv"], st["ol"], st["ov"], estado))
            total_guardados += 1
            
        return total_guardados, None
    except Exception as e:
        return 0, str(e)

# ==============================================================================
# AUDITORÍA DE CANCHA: RADIOGRAFÍA CON HISTORIAL COMPLETO
# ==============================================================================
def auditar_partido_flexible(competicion_id, local, visitante):
    def obtener_radiografia_club(club):
        c_upper = str(club).strip().upper()
        filas = ejecutar_sql("""
            SELECT 
                fecha, local, visitante,
                goles_local, goles_visitante,
                corners_local, corners_visitante,
                tarjetas_local, tarjetas_visitante,
                offsides_local, offsides_visitante
            FROM partidos 
            WHERE (UPPER(local) = ? OR UPPER(visitante) = ?) AND estado = 'finalizado'
            ORDER BY fecha DESC LIMIT 5
        """, (c_upper, c_upper), fetch="all") or []

        if not filas:
            return None

        partidos_procesados = []
        for f in filas:
            es_local = (str(f.get("local", "")).strip().upper() == c_upper)
            gf = int(f.get("goles_local" if es_local else "goles_visitante") or 0)
            gc = int(f.get("goles_visitante" if es_local else "goles_local") or 0)
            c = int(f.get("corners_local" if es_local else "corners_visitante") or 0)
            t = int(f.get("tarjetas_local" if es_local else "tarjetas_visitante") or 0)
            o = int(f.get("offsides_local" if es_local else "offsides_visitante") or 0)
            rival = str(f.get("visitante" if es_local else "local", "Rival")).strip()
            marcador = f"{gf} - {gc}"

            partidos_procesados.append({
                "rival": rival,
                "marcador": marcador,
                "gf": gf, "gc": gc,
                "c": c, "t": t, "o": o
            })

        ult = partidos_procesados[0]
        n = len(partidos_procesados)

        promedios_5 = {
            "pj": n,
            "gf": round(sum(p["gf"] for p in partidos_procesados) / n, 1),
            "c": round(sum(p["c"] for p in partidos_procesados) / n, 1),
            "t": round(sum(p["t"] for p in partidos_procesados) / n, 1),
            "o": round(sum(p["o"] for p in partidos_procesados) / n, 1)
        }

        return {"ultimo": ult, "promedio": promedios_5}

    try:
        rad_l = obtener_radiografia_club(local)
        rad_v = obtener_radiografia_club(visitante)
    except Exception:
        rad_l, rad_v = None, None

    if not rad_l or not rad_v:
        return {
            "hay_datos": False,
            "indice_confianza": 4,
            "alerta_riesgo": "Esperando historial de partidos finalizados en la base de datos.",
            "mercado": "En recopilación",
            "probabilidad": 0,
            "cuota_justa": 1.00,
            "stake": "No operable",
            "rad_l": None, "rad_v": None
        }

    ult_l = rad_l["ultimo"]
    ult_v = rad_v["ultimo"]
    p5_l = rad_l["promedio"]
    p5_v = rad_v["promedio"]

    goles_prom_total = p5_l["gf"] + p5_v["gf"]
    corners_prom_total = p5_l["c"] + p5_v["c"]
    tarjetas_prom_total = p5_l["t"] + p5_v["t"]

    if p5_l["gf"] >= 1.4 and ult_l["gf"] >= 1:
        mercado = f"{local}: Más de 0.5 Goles"
        prob = 80.0
        cuota = 1.25
    elif goles_prom_total <= 1.2 and ult_l["gf"] == 0 and ult_v["gf"] == 0:
        mercado = "Menos de 2.5 Goles Totales"
        prob = 75.0
        cuota = 1.35
    elif corners_prom_total >= 8.5:
        linea = math.floor(corners_prom_total - 1.5) + 0.5
        mercado = f"Más de {linea} Córners Totales"
        prob = 72.0
        cuota = 1.40
    elif tarjetas_prom_total >= 4.5:
        mercado = "Más de 3.5 Tarjetas Totales"
        prob = 68.0
        cuota = 1.45
    else:
        mercado = "Más de 1.5 Goles Totales" if goles_prom_total >= 2.0 else "Menos de 3.5 Goles Totales"
        prob = 70.0
        cuota = 1.35

    n_total = p5_l["pj"] + p5_v["pj"]
    confianza = 8 if n_total >= 6 else 6

    return {
        "hay_datos": True,
        "indice_confianza": confianza,
        "alerta_riesgo": f"Historial evaluado: {p5_l['pj']} PJ de {local} y {p5_v['pj']} PJ de {visitante}.",
        "mercado": mercado,
        "probabilidad": prob,
        "cuota_justa": cuota,
        "stake": "Stake 2.5% - 3.0%",
        "rad_l": rad_l,
        "rad_v": rad_v
    }

# ==============================================================================
# RUTAS DE SERVICIO WEB & APIS
# ==============================================================================
@app.route('/')
def home():
    ligas = ejecutar_sql("SELECT id, nombre, pais FROM competiciones WHERE activa = 1 ORDER BY nombre", fetch="all") or []
    if not ligas:
        ligas = [{"id": l[0], "nombre": l[1], "pais": l[2]} for l in LIGAS_INICIALES]
        
    ahora_ecu = datetime.now(timezone.utc) - timedelta(hours=5)
    fecha_hoy = ahora_ecu.strftime("%Y%m%d")
    return render_template('index.html', ligas=ligas, fecha_hoy=fecha_hoy)

@app.route('/api/equipos/<liga>')
def api_equipos(liga):
    filas = ejecutar_sql("""
        SELECT DISTINCT local as equipo FROM partidos WHERE competicion_id = ?
        UNION
        SELECT DISTINCT visitante as equipo FROM partidos WHERE competicion_id = ?
        ORDER BY equipo
    """, (liga, liga), fetch="all") or []
    equipos = [f["equipo"] for f in filas if f.get("equipo")]
    if not equipos:
        equipos = ["EQUIPO LOCAL", "EQUIPO VISITANTE"]
    return jsonify(equipos)

@app.route('/api/alarmas_hoy')
def api_alarmas_hoy():
    try:
        forzar = request.args.get('forzar', 'false').lower() == 'true'
        ahora_ecuador = datetime.now(timezone.utc) - timedelta(hours=5)

        # Sincronización rápida: solo el día actual de ayer, hoy y mañana para no saturar Render
        if forzar:
            ligas_sync = ejecutar_sql("SELECT id FROM competiciones WHERE activa = 1", fetch="all") or []
            codigos = [l["id"] for l in ligas_sync] if ligas_sync else [l[0] for l in LIGAS_INICIALES]
            fechas_consulta = [
                (ahora_ecuador - timedelta(days=1)).strftime("%Y%m%d"),
                ahora_ecuador.strftime("%Y%m%d"),
                (ahora_ecuador + timedelta(days=1)).strftime("%Y%m%d")
            ]
            for cod in codigos:
                for f_str in fechas_consulta:
                    try:
                        descargar_partidos_fecha(cod, f_str)
                    except Exception:
                        pass

        # Lectura universal: Traemos los últimos 150 partidos y filtramos en Python para evitar errores de SQL TIMESTAMPTZ
        partidos_bd = ejecutar_sql("""
            SELECT p.*, c.nombre as competicion_nombre 
            FROM partidos p
            LEFT JOIN competiciones c ON p.competicion_id = c.id
            ORDER BY p.fecha DESC
            LIMIT 150
        """, fetch="all") or []

        fecha_limite_min = (ahora_ecuador - timedelta(days=3)).strftime("%Y-%m-%d")
        fecha_limite_max = (ahora_ecuador + timedelta(days=5)).strftime("%Y-%m-%d")

        alarmas = []
        for p in partidos_bd:
            fecha_ecu, hora_ecu = formatear_fecha_hora_ecuador(p.get("fecha"))
            
            # Filtro en memoria por ventana móvil
            if not (fecha_limite_min <= fecha_ecu <= fecha_limite_max):
                continue

            loc = p.get("local", "")
            vis = p.get("visitante", "")
            res = auditar_partido_flexible(p.get("competicion_id"), loc, vis)

            gl = p.get("goles_local", 0)
            gv = p.get("goles_visitante", 0)
            estado_real = p.get("estado", "programado")

            alarmas.append({
                "fixture_id": p.get("fixture_id"),
                "competicion_nombre": p.get("competicion_nombre", p.get("competicion_id")),
                "competicion_id": p.get("competicion_id"),
                "fecha": fecha_ecu,
                "hora_ecuador": hora_ecu,
                "local": loc,
                "visitante": vis,
                "estado": estado_real,
                "goles_local": gl,
                "goles_visitante": gv,
                "es_en_vivo": (estado_real == "en_vivo"),
                "marcador": f"{gl} - {gv}" if estado_real in ["finalizado", "en_vivo"] else None,
                "confianza": res.get("indice_confianza", 4),
                "alerta_riesgo": res.get("alerta_riesgo", ""),
                "mercado_recomendado": res.get("mercado", ""),
                "probabilidad": res.get("probabilidad", 0),
                "cuota_justa": res.get("cuota_justa", 1.0),
                "stake": res.get("stake", ""),
                "hay_datos": res.get("hay_datos", False),
                "rad_l": res.get("rad_l"),
                "rad_v": res.get("rad_v")
            })

        alarmas.sort(key=lambda x: (x["fecha"], x["hora_ecuador"]))
        return jsonify({"success": True, "alarmas": alarmas})
    except Exception as e:
        print(f"[ALARMAS ERROR RETORNO SEGURO] {e}")
        return jsonify({"success": True, "alarmas": []})

@app.route('/api/agregar_enlace', methods=['POST'])
def api_agregar_enlace():
    try:
        data = request.json or {}
        url = data.get('url', '').strip().lower()
        ahora_ecu = datetime.now(timezone.utc) - timedelta(hours=5)
        fecha_req = data.get('fecha') or ahora_ecu.strftime("%Y%m%d")

        if not url:
            return jsonify({"success": False, "msg": "Enlace o código vacío."})
        
        cod_detectado = None
        for k, v in DICCIONARIO_LIGAS.items():
            if k in url:
                cod_detectado = v
                break
                
        if not cod_detectado and "espn" in url:
            m = re.search(r'(?:liga|league)/([a-zA-Z0-9\._]+)', url)
            if m:
                cod_detectado = m.group(1).lower()

        if not cod_detectado and re.match(r'^[a-z0-9_\.]+$', url):
            cod_detectado = url

        if not cod_detectado:
            return jsonify({"success": False, "msg": "No se reconoció la liga."})

        ejecutar_sql("""
            INSERT INTO competiciones (id, nombre, pais, activa) VALUES (?, ?, 'Internacional', 1)
            ON CONFLICT (id) DO UPDATE SET activa = 1
        """, (cod_detectado, cod_detectado.upper()))

        tot, _ = descargar_partidos_fecha(cod_detectado, fecha_req)
        
        try:
            fecha_dt = datetime.strptime(fecha_req, "%Y%m%d")
            for i in range(1, 4):
                fec = (fecha_dt - timedelta(days=i)).strftime("%Y%m%d")
                c, _ = descargar_partidos_fecha(cod_detectado, fec)
                tot += c
        except Exception:
            pass

        return jsonify({
            "success": True, 
            "msg": f"Liga '{cod_detectado}' sincronizada: {tot} partidos actualizados."
        })
    except Exception as e:
        print(f"[ERROR AGREGAR ENLACE] {e}")
        return jsonify({"success": False, "msg": f"Error: {str(e)}"})

@app.route('/api/calcular', methods=['POST'])
def api_calcular():
    d = request.json or {}
    liga = d.get('liga')
    loc = d.get('local')
    vis = d.get('visitante')
    if not loc or not vis or loc == vis:
        return jsonify({"error": "Equipos inválidos o iguales."}), 400
    res = auditar_partido_flexible(liga, loc, vis)
    return jsonify(res)

if __name__ == '__main__':
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=puerto, debug=False)