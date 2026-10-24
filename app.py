import os
import sqlite3
import math
import json
import urllib.request
import urllib.error
import re
import time
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

# 21 LIGAS OFICIALES CONSOLIDADAS SIN DUPLICADOS
LIGAS_INICIALES = [
    ("ecu.1", "LigaPro Ecuador", "Ecuador"),
    ("esp.1", "LaLiga España", "España"),
    ("eng.1", "Premier League", "Inglaterra"),
    ("ita.1", "Serie A Italia", "Italia"),
    ("ger.1", "Bundesliga", "Alemania"),
    ("fra.1", "Ligue 1", "Francia"),
    ("col.1", "Liga BetPlay", "Colombia"),
    ("arg.1", "Liga Profesional", "Argentina"),
    ("conmebol.libertadores", "Copa Libertadores", "Sudamérica"),
    ("conmebol.sudamericana", "Copa Sudamericana", "Sudamérica"),
    ("uefa.champions", "UEFA Champions League", "Europa"),
    ("uefa.europa", "UEFA Europa League", "Europa"),
    ("uefa.europa.conf", "UEFA Conference League", "Europa"),
    ("mex.1", "Liga MX México", "México"),
    ("usa.1", "Major League Soccer (MLS)", "Estados Unidos"),
    ("ned.1", "Eredivisie Países Bajos", "Países Bajos"),
    ("por.1", "Primeira Liga Portugal", "Portugal"),
    ("bol.1", "División Profesional Bolivia", "Bolivia"),
    ("per.1", "Liga 1 Perú", "Perú"),
    ("aus.1", "A-League Australia", "Australia"),
    ("bra.1", "Brasileirao Serie A", "Brasil")
]

# ==============================================================================
# CONEXIÓN A BASE DE DATOS (SUPABASE DIRECTO / FALLBACK SQLITE)
# ==============================================================================
def get_db_connection():
    env_url = os.environ.get("DATABASE_URL")
    if env_url and PG_DISPONIBLE:
        try:
            url = env_url.replace("postgres://", "postgresql://", 1)
            return psycopg2.connect(url, sslmode='require', connect_timeout=8)
        except Exception as e:
            print(f"Fallo conectando por DATABASE_URL: {e}")

    if PG_DISPONIBLE:
        for port in [5432, 6543]:
            try:
                return psycopg2.connect(
                    host="aws-0-us-west-1.pooler.supabase.com",
                    port=port,
                    dbname="postgres",
                    user="postgres.waldnnzetbbmbsyokzxp",
                    password="CHIqui18..%",
                    sslmode="require",
                    connect_timeout=6
                )
            except Exception:
                pass

    return sqlite3.connect(DB_NAME)

def ejecutar_sql(query, params=(), fetch=None):
    conn = get_db_connection()
    is_pg = PG_DISPONIBLE and not isinstance(conn, sqlite3.Connection)
    
    if is_pg:
        query = query.replace("?", "%s")
        cur = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
    try:
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
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"Error SQL: {ex}")
        return [] if fetch == "all" else None
    finally:
        try:
            conn.close()
        except Exception:
            pass

def inicializar_bd():
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

        # Inserción asegurada sin duplicados
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
        try:
            cur.execute("ALTER TABLE competiciones ADD COLUMN pais TEXT")
            conn.commit()
        except Exception:
            pass

        for lid, lnom, lpais in LIGAS_INICIALES:
            try:
                cur.execute("INSERT OR REPLACE INTO competiciones (id, nombre, pais, activa) VALUES (?, ?, ?, 1)", (lid, lnom, lpais))
            except Exception:
                pass
        conn.commit()

    conn.close()

try:
    inicializar_bd()
except Exception as e:
    print(f"Aviso durante inicializar_bd: {e}")

# ==============================================================================
# MANEJO HORARIO EXACTO ECUADOR (UTC-5)
# ==============================================================================
def formatear_fecha_hora_ecuador(valor_fecha):
    if not valor_fecha:
        return datetime.now().strftime("%Y-%m-%d"), "Por definir"
    try:
        dt = None
        if isinstance(valor_fecha, datetime):
            if valor_fecha.tzinfo is not None:
                dt_utc = valor_fecha.astimezone(timezone.utc)
                dt = dt_utc - timedelta(hours=5)
            else:
                dt = valor_fecha - timedelta(hours=5)
        else:
            s = str(valor_fecha).strip()
            # ESPN devuelve T00:00Z cuando la liga aún no define la hora
            if "T00:00" in s or " 00:00:00" in s:
                fecha_base = s.split("T")[0].split(" ")[0]
                return fecha_base, "Por definir"

            s_iso = s.replace("Z", "+00:00")
            if "+" in s_iso or ("-" in s_iso[10:]):
                dt_obj = datetime.fromisoformat(s_iso)
                if dt_obj.tzinfo is not None:
                    dt = dt_obj.astimezone(timezone.utc) - timedelta(hours=5)
                else:
                    dt = dt_obj - timedelta(hours=5)
            else:
                dt_obj = datetime.fromisoformat(s)
                dt = dt_obj - timedelta(hours=5)

        if dt:
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except Exception:
        pass

    s_raw = str(valor_fecha)
    return s_raw[:10], "Por definir"

# ==============================================================================
# UTILIDADES & PARSING ESPN
# ==============================================================================
def fetch_url(url):
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=12) as resp:
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
                    try:
                        val = int(s.get("displayValue", 0))
                    except (ValueError, TypeError):
                        val = 0
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
            return 0, f"No hay eventos para {codigo_liga} en {fecha_str}."
            
        total_guardados = 0
        conn = get_db_connection()
        is_pg = PG_DISPONIBLE and not isinstance(conn, sqlite3.Connection)
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
            
            st = descargar_resumen_evento(codigo_liga, fix_id)
            
            # Obtener la hora real oficial enviada por ESPN en el objeto competition
            comp_info = ev.get("competitions", [{}])[0]
            fecha_iso = comp_info.get("date") or ev.get("date") or datetime.now().isoformat()
            estado = "finalizado" if ev.get("status", {}).get("type", {}).get("completed", False) else "programado"

            if is_pg:
                ejecutar_sql("""
                    INSERT INTO partidos 
                    (fixture_id, competicion_id, fecha, local, visitante, goles_local, goles_visitante,
                     corners_local, corners_visitante, tarjetas_local, tarjetas_visitante, offsides_local, offsides_visitante, estado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (fixture_id) DO UPDATE SET 
                        fecha = EXCLUDED.fecha,
                        goles_local = EXCLUDED.goles_local,
                        goles_visitante = EXCLUDED.goles_visitante,
                        corners_local = EXCLUDED.corners_local,
                        corners_visitante = EXCLUDED.corners_visitante,
                        tarjetas_local = EXCLUDED.tarjetas_local,
                        tarjetas_visitante = EXCLUDED.tarjetas_visitante,
                        offsides_local = EXCLUDED.offsides_local,
                        offsides_visitante = EXCLUDED.offsides_visitante,
                        estado = EXCLUDED.estado,
                        updated_at = NOW()
                """, (fix_id, codigo_liga, fecha_iso, loc, vis, gl, gv,
                      st["cl"], st["cv"], st["tl"], st["tv"], st["ol"], st["ov"], estado))
            else:
                ejecutar_sql("""
                    INSERT OR REPLACE INTO partidos 
                    (fixture_id, competicion_id, fecha, local, visitante, goles_local, goles_visitante,
                     corners_local, corners_visitante, tarjetas_local, tarjetas_visitante, offsides_local, offsides_visitante, estado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (fix_id, codigo_liga, fecha_iso, loc, vis, gl, gv,
                      st["cl"], st["cv"], st["tl"], st["tv"], st["ol"], st["ov"], estado))
            total_guardados += 1
            
        return total_guardados, None
    except Exception as e:
        return 0, str(e)

# ==============================================================================
# MOTOR POISSON & AUDITORÍA
# ==============================================================================
def poisson_prob(lmbda, k):
    if lmbda <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)

def auditar_partido_flexible(competicion_id, local, visitante):
    def obtener_stats_reales(club, es_local):
        if es_local:
            filas = ejecutar_sql("""
                SELECT goles_local, corners_local, tarjetas_local, offsides_local 
                FROM partidos WHERE competicion_id = ? AND UPPER(local) = ? 
                ORDER BY fecha DESC LIMIT 5
            """, (competicion_id, club.upper()), fetch="all")
        else:
            filas = ejecutar_sql("""
                SELECT goles_visitante, corners_visitante, tarjetas_visitante, offsides_visitante 
                FROM partidos WHERE competicion_id = ? AND UPPER(visitante) = ? 
                ORDER BY fecha DESC LIMIT 5
            """, (competicion_id, club.upper()), fetch="all")

        if not filas:
            filas = ejecutar_sql("""
                SELECT CASE WHEN UPPER(local) = ? THEN goles_local ELSE goles_visitante END AS g,
                       CASE WHEN UPPER(local) = ? THEN corners_local ELSE corners_visitante END AS c,
                       CASE WHEN UPPER(local) = ? THEN tarjetas_local ELSE tarjetas_visitante END AS t,
                       CASE WHEN UPPER(local) = ? THEN offsides_local ELSE offsides_visitante END AS o
                FROM partidos WHERE competicion_id = ? AND (UPPER(local) = ? OR UPPER(visitante) = ?)
                ORDER BY fecha DESC LIMIT 5
            """, (club.upper(), club.upper(), club.upper(), club.upper(), competicion_id, club.upper(), club.upper()), fetch="all")

        n = len(filas) if filas else 0
        if n > 0:
            avg_goles = sum(f.get("goles_local" if es_local else "goles_visitante", f.get("g", 0)) for f in filas) / n
            avg_corners = sum(f.get("corners_local" if es_local else "corners_visitante", f.get("c", 0)) for f in filas) / n
            avg_tarjetas = sum(f.get("tarjetas_local" if es_local else "tarjetas_visitante", f.get("t", 0)) for f in filas) / n
            avg_offsides = sum(f.get("offsides_local" if es_local else "offsides_visitante", f.get("o", 0)) for f in filas) / n
            return n, float(avg_goles), float(avg_corners), float(avg_tarjetas), float(avg_offsides)
        return 0, 1.2, 4.5, 2.0, 1.5

    n_l, l_loc, crn_l, tar_l, off_l = obtener_stats_reales(local, True)
    n_v, l_vis, crn_v, tar_v, off_v = obtener_stats_reales(visitante, False)

    corners_total = crn_l + crn_v
    tarjetas_total = tar_l + tar_v
    offsides_total = off_l + off_v
    calc_lambda_loc = max(0.0001, l_loc)
    calc_lambda_vis = max(0.0001, l_vis)

    p_loc, p_emp, p_vis = 0.0, 0.0, 0.0
    p_o15, p_o25, p_o35, p_btts = 0.0, 0.0, 0.0, 0.0
    matriz = []

    for gl in range(8):
        for gv in range(8):
            prob = poisson_prob(calc_lambda_loc, gl) * poisson_prob(calc_lambda_vis, gv)
            matriz.append((f"{gl}-{gv}", prob * 100))
            if gl > gv: p_loc += prob
            elif gl == gv: p_emp += prob
            else: p_vis += prob
            if (gl + gv) > 1.5: p_o15 += prob
            if (gl + gv) > 2.5: p_o25 += prob
            if (gl + gv) > 3.5: p_o35 += prob
            if gl > 0 and gv > 0: p_btts += prob

    matriz.sort(key=lambda x: x[1], reverse=True)
    p_loc_2plus = (1.0 - (poisson_prob(calc_lambda_loc, 0) + poisson_prob(calc_lambda_loc, 1))) * 100 if l_loc > 0 else 0.0

    calc_crn = max(0.1, corners_total)
    p_crn_o85 = (1.0 - sum(poisson_prob(calc_crn, k) for k in range(9))) * 100

    calc_tar = max(0.1, tarjetas_total)
    p_tar_o35 = (1.0 - sum(poisson_prob(calc_tar, k) for k in range(4))) * 100

    calc_off = max(0.1, offsides_total)
    p_off_o25 = (1.0 - sum(poisson_prob(calc_off, k) for k in range(3))) * 100

    indice_confianza = 8
    alerta_riesgo = "Métricas estadísticas validadas."
    if l_loc == 0.0 or l_vis == 0.0:
        indice_confianza -= 2
        alerta_riesgo = f"Sequía ofensiva: {'Local' if l_loc == 0.0 else 'Visitante'} con 0.00 goles."
    if (n_l + n_v) < 6:
        indice_confianza -= 2
        alerta_riesgo += f" (Muestra corta en BD: {n_l + n_v} partidos)."

    p_n1 = max(p_loc_2plus, p_crn_o85)
    tipo_mercado = "goles_loc" if p_loc_2plus >= p_crn_o85 else "corners"
    nivel_1 = {
        "tipo": tipo_mercado,
        "mercado": f"Over 1.5 Goles {local}" if tipo_mercado == "goles_loc" else "Más de 8.5 Córners Totales",
        "prob": p_n1,
        "cuota_justa": (100.0 / p_n1) if p_n1 > 0 else 99.0,
        "stake": "Stake 2.5% - 3.0%"
    }

    prob_over25 = p_o25 * 100
    prob_under25 = 100.0 - prob_over25
    es_over = prob_over25 >= prob_under25
    nivel_2 = {
        "tipo": "o25" if es_over else "u25",
        "mercado": "Más de 2.5 Goles Totales" if es_over else "Menos de 2.5 Goles Totales",
        "prob": max(prob_over25, prob_under25),
        "cuota_justa": (100.0 / max(prob_over25, prob_under25)) if max(prob_over25, prob_under25) > 0 else 99.0,
        "stake": "Stake 1.5% - 2.0%"
    }

    return {
        "n_local_bd": n_l, "n_visitante_bd": n_v,
        "l_loc": l_loc, "l_vis": l_vis,
        "crn_l": crn_l, "crn_v": crn_v,
        "tar_l": tar_l, "tar_v": tar_v,
        "off_l": off_l, "off_v": off_v,
        "corners": corners_total, "tarjetas": tarjetas_total, "offsides": offsides_total,
        "prob_loc": p_loc * 100, "prob_emp": p_emp * 100, "prob_vis": p_vis * 100,
        "btts": p_btts * 100, "o15": p_o15 * 100, "o25": p_o25 * 100, "o35": p_o35 * 100,
        "crn_o85": p_crn_o85, "tar_o35": p_tar_o35, "off_o25": p_off_o25,
        "top_3": matriz[:3],
        "indice_confianza": max(1, min(10, indice_confianza)),
        "alerta_riesgo": alerta_riesgo,
        "nivel_1": nivel_1,
        "nivel_2": nivel_2
    }

# ==============================================================================
# RUTAS WEB & ENDPOINTS API
# ==============================================================================
@app.route('/')
def home():
    ligas = ejecutar_sql("SELECT id, nombre, pais FROM competiciones WHERE activa = 1 ORDER BY nombre", fetch="all") or []
    if not ligas:
        ligas = [{"id": l[0], "nombre": l[1], "pais": l[2]} for l in LIGAS_INICIALES]
        
    fecha_hoy = datetime.now().strftime("%Y%m%d")
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

@app.route('/api/partidos_guardados')
def api_partidos_guardados():
    filas = ejecutar_sql("""
        SELECT p.fixture_id, p.competicion_id, c.nombre as competicion_nombre,
               p.fecha, p.local, p.visitante, p.goles_local, p.goles_visitante,
               p.corners_local, p.corners_visitante, p.tarjetas_local, p.tarjetas_visitante,
               p.offsides_local, p.offsides_visitante, p.estado
        FROM partidos p
        LEFT JOIN competiciones c ON p.competicion_id = c.id
        ORDER BY p.fecha DESC LIMIT 100
    """, fetch="all") or []
    
    for r in filas:
        f_ecu, h_ecu = formatear_fecha_hora_ecuador(r.get("fecha"))
        r["fecha"] = f_ecu
        r["hora_ecuador"] = h_ecu
    return jsonify({"success": True, "partidos": filas})

@app.route('/api/alarmas_hoy')
def api_alarmas_hoy():
    forzar = request.args.get('forzar', 'false').lower() == 'true'

    if forzar:
        ligas_sync = ejecutar_sql("SELECT id FROM competiciones WHERE activa = 1", fetch="all") or []
        codigos_a_escanear = [l["id"] for l in ligas_sync] if ligas_sync else [l[0] for l in LIGAS_INICIALES]
        
        hoy_str = datetime.now().strftime("%Y%m%d")
        manana_str = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
        
        for cod in codigos_a_escanear:
            descargar_partidos_fecha(cod, hoy_str)
            descargar_partidos_fecha(cod, manana_str)

    partidos_hoy = ejecutar_sql("""
        SELECT p.*, c.nombre as competicion_nombre 
        FROM partidos p
        LEFT JOIN competiciones c ON p.competicion_id = c.id
        ORDER BY p.fecha DESC LIMIT 100
    """, fetch="all") or []

    alarmas = []
    for p in partidos_hoy:
        loc = p["local"]
        vis = p["visitante"]
        res = auditar_partido_flexible(p["competicion_id"], loc, vis)
        
        fecha_ecu, hora_ecu = formatear_fecha_hora_ecuador(p.get("fecha"))

        alarmas.append({
            "fixture_id": p.get("fixture_id"),
            "competicion_nombre": p.get("competicion_nombre", p.get("competicion_id")),
            "competicion_id": p.get("competicion_id"),
            "fecha": fecha_ecu,
            "hora_ecuador": hora_ecu,
            "local": loc,
            "visitante": vis,
            "estado": p.get("estado", "programado"),
            "marcador": f"{p.get('goles_local', 0)} - {p.get('goles_visitante', 0)}" if p.get("estado") == "finalizado" else None,
            "confianza": res["indice_confianza"],
            "alerta_riesgo": res["alerta_riesgo"],
            "mercado_recomendado": res["nivel_1"]["mercado"],
            "probabilidad": round(res["nivel_1"]["prob"], 1),
            "cuota_justa": round(res["nivel_1"]["cuota_justa"], 2),
            "stake": res["nivel_1"]["stake"],
            "stats": {
                "gl_l": res["l_loc"],
                "gl_v": res["l_vis"],
                "crn_l": res["crn_l"],
                "crn_v": res["crn_v"],
                "crn_tot": res["corners"],
                "tar_l": res["tar_l"],
                "tar_v": res["tar_v"],
                "tar_tot": res["tarjetas"],
                "off_l": res["off_l"],
                "off_v": res["off_v"],
                "off_tot": res["offsides"],
                "n_l": res["n_local_bd"],
                "n_v": res["n_visitante_bd"]
            }
        })
    return jsonify({"success": True, "alarmas": alarmas})

@app.route('/api/agregar_enlace', methods=['POST'])
def api_agregar_enlace():
    data = request.json or {}
    url = data.get('url', '').strip().lower()
    fecha_req = data.get('fecha') or datetime.now().strftime("%Y%m%d")

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

    conn = get_db_connection()
    is_pg = PG_DISPONIBLE and not isinstance(conn, sqlite3.Connection)
    conn.close()

    if is_pg:
        ejecutar_sql("""
            INSERT INTO competiciones (id, nombre, pais, activa) VALUES (?, ?, 'Internacional', 1)
            ON CONFLICT (id) DO UPDATE SET activa = 1
        """, (cod_detectado, cod_detectado.upper()))
    else:
        ejecutar_sql("INSERT OR REPLACE INTO competiciones (id, nombre, pais, activa) VALUES (?, ?, 'Internacional', 1)", (cod_detectado, cod_detectado.upper()))

    tot, _ = descargar_partidos_fecha(cod_detectado, fecha_req)
    for i in [1, 2]:
        fec = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        c, _ = descargar_partidos_fecha(cod_detectado, fec)
        tot += c

    return jsonify({"success": True, "msg": f"Liga '{cod_detectado}' sincronizada ({tot} partidos guardados)."})

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