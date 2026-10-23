import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import math
import json
import urllib.request
import urllib.error
import re
import threading
from datetime import datetime

# ==============================================================================
# 1. CONSTANTES Y CONFIGURACIÓN (15 LIGAS)
# ==============================================================================

DB_NAME = "control_futbol.db"

LIGAS_ESPN = {
    "uefa.champions": "UEFA Champions League",
    "esp.1": "LaLiga (España)",
    "eng.1": "Premier League (Inglaterra)",
    "ita.1": "Serie A (Italia)",
    "ger.1": "Bundesliga (Alemania)",
    "fra.1": "Ligue 1 (Francia)",
    "uefa.europa": "UEFA Europa League",
    "uefa.europa.conf": "UEFA Conference League",
    "arg.1": "Liga Profesional (Argentina)",
    "mex.1": "Liga MX (México)",
    "usa.1": "MLS (Estados Unidos)",
    "ned.1": "Eredivisie (Países Bajos)",
    "por.1": "Primeira Liga (Portugal)",
    "bol.1": "División Profesional (Bolivia)",
    "per.1": "Liga 1 (Perú)"
}

# ==============================================================================
# 2. BASE DE DATOS LOCAL
# ==============================================================================

def inicializar_bd():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competiciones (
            id TEXT PRIMARY KEY,
            nombre TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competicion_id TEXT NOT NULL,
            nombre TEXT NOT NULL,
            UNIQUE(competicion_id, nombre)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS partidos (
            fixture_id TEXT PRIMARY KEY,
            competicion_id TEXT NOT NULL,
            fecha TEXT,
            local TEXT NOT NULL,
            visitante TEXT NOT NULL,
            goles_local INTEGER NOT NULL,
            goles_visitante INTEGER NOT NULL,
            corners_local INTEGER DEFAULT 0,
            corners_visitante INTEGER DEFAULT 0,
            tarjetas_local INTEGER DEFAULT 0,
            tarjetas_visitante INTEGER DEFAULT 0,
            offsides_local INTEGER DEFAULT 0,
            offsides_visitante INTEGER DEFAULT 0
        )
    """)
    
    cur.execute("PRAGMA table_info(partidos)")
    cols = [c[1] for c in cur.fetchall()]
    if "competicion_id" not in cols:
        cur.execute("ALTER TABLE partidos ADD COLUMN competicion_id TEXT DEFAULT 'General'")
    if "fixture_id" not in cols:
        cur.execute("ALTER TABLE partidos ADD COLUMN fixture_id TEXT")
        
    for cod, nom in LIGAS_ESPN.items():
        cur.execute("INSERT OR REPLACE INTO competiciones (id, nombre) VALUES (?, ?)", (cod, nom))
        
    conn.commit()
    conn.close()

inicializar_bd()

# ==============================================================================
# 3. CONEXIÓN API ESPN
# ==============================================================================

def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode('utf-8'))

def parsear_codigo_liga(url_o_codigo):
    cad = url_o_codigo.strip()
    m = re.search(r'liga/([a-zA-Z0-9\._]+)', cad)
    return m.group(1).lower() if m else cad.lower()

def sincronizar_equipos_de_liga(codigo):
    url = f"https://site.api.espn.com/apis/v2/sports/soccer/{codigo}/standings"
    try:
        data = get_json(url)
        nom_torneo = data.get("name", codigo.upper()).strip()
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO competiciones (id, nombre) VALUES (?, ?)", (codigo, nom_torneo))
        
        hijos = data.get("children", [])
        entries = hijos[0]["standings"].get("entries", []) if hijos and "standings" in hijos[0] else data.get("standings", {}).get("entries", [])
        
        tot = 0
        for e in entries:
            t_name = e.get("team", {}).get("name", "").strip().upper()
            if t_name:
                cur.execute("INSERT OR IGNORE INTO equipos (competicion_id, nombre) VALUES (?, ?)", (codigo, t_name))
                tot += 1
                
        conn.commit()
        conn.close()
        return codigo, nom_torneo, tot
    except Exception:
        return codigo, "", 0

def descargar_resumen_evento(codigo_liga, event_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/summary?event={event_id}"
    res = {"cl": 0, "cv": 0, "tl": 0, "tv": 0, "ol": 0, "ov": 0}
    try:
        data = get_json(url)
        boxscore = data.get("boxscore", {})
        teams = boxscore.get("teams", [])
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

        if res["tl"] == 0 and res["tv"] == 0:
            evs = data.get("keyEvents", []) or data.get("plays", [])
            hid = teams[0].get("team", {}).get("id") if teams else None
            for ev in evs:
                txt = ev.get("text", "").lower()
                is_h = (ev.get("team", {}).get("id") == hid) if hid else (ev.get("homeAway") == "home")
                pfx = "l" if is_h else "v"
                if "yellow card" in txt or "red card" in txt or "tarjeta" in txt:
                    res[f"t{pfx}"] += 1
    except Exception:
        pass
    return res

def descargar_partidos_fecha(codigo_liga, fecha_str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/scoreboard?dates={fecha_str}"
    try:
        data = get_json(url)
        events = data.get("events", [])
        if not events:
            return 0, f"No hay eventos programados en ESPN para {codigo_liga} en la fecha {fecha_str}."

        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        total_guardados = 0

        for ev in events:
            if not ev.get("status", {}).get("type", {}).get("completed", False):
                continue

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

            cur.execute("INSERT OR IGNORE INTO equipos (competicion_id, nombre) VALUES (?, ?)", (codigo_liga, loc))
            cur.execute("INSERT OR IGNORE INTO equipos (competicion_id, nombre) VALUES (?, ?)", (codigo_liga, vis))

            cur.execute("""
                INSERT OR REPLACE INTO partidos 
                (fixture_id, competicion_id, fecha, local, visitante, goles_local, goles_visitante,
                 corners_local, corners_visitante, tarjetas_local, tarjetas_visitante, offsides_local, offsides_visitante)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (fix_id, codigo_liga, fecha_str, loc, vis, gl, gv,
                  st["cl"], st["cv"], st["tl"], st["tv"], st["ol"], st["ov"]))
            total_guardados += 1

        conn.commit()
        conn.close()

        if total_guardados == 0:
            return 0, f"En la fecha {fecha_str} no se encontraron partidos finalizados en {codigo_liga}."

        return total_guardados, None

    except urllib.error.HTTPError as he:
        if he.code in (400, 404):
            return 0, f"ESPN no tiene registros de partidos para '{codigo_liga}' en la fecha {fecha_str} (HTTP {he.code})."
        return 0, f"Error del servidor ESPN (HTTP {he.code}): {he.reason}"
    except Exception as e:
        return 0, str(e)

# ==============================================================================
# 4. MOTOR MATEMÁTICO POISSON AVANZADO
# ==============================================================================

def poisson_prob(lmbda, k):
    if lmbda <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)

def auditar_partido_flexible(competicion_id, local, visitante):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        SELECT goles_local, goles_visitante, corners_local, corners_visitante, 
               tarjetas_local, tarjetas_visitante, offsides_local, offsides_visitante 
        FROM partidos WHERE competicion_id = ?
    """, (competicion_id,))
    todos_partidos = cur.fetchall()

    if todos_partidos:
        n_tot = len(todos_partidos)
        media_gl = sum(p[0] for p in todos_partidos) / n_tot
        media_gv = sum(p[1] for p in todos_partidos) / n_tot
        media_crn = sum(p[2] + p[3] for p in todos_partidos) / n_tot
        media_tar = sum(p[4] + p[5] for p in todos_partidos) / n_tot
        media_off = sum(p[6] + p[7] for p in todos_partidos) / n_tot
    else:
        media_gl, media_gv = 1.4, 1.1
        media_crn, media_tar, media_off = 9.5, 4.0, 3.5

    def obtener_stats_club(club, es_local):
        cur.execute("""
            SELECT goles_local, goles_visitante, corners_local, tarjetas_local, offsides_local 
            FROM partidos WHERE competicion_id = ? AND UPPER(local) = ?
        """, (competicion_id, club.upper()))
        como_loc = cur.fetchall()

        cur.execute("""
            SELECT goles_visitante, goles_local, corners_visitante, tarjetas_visitante, offsides_visitante 
            FROM partidos WHERE competicion_id = ? AND UPPER(visitante) = ?
        """, (competicion_id, club.upper()))
        como_vis = cur.fetchall()

        lista_condicion = como_loc if es_local else como_vis
        lista_total = como_loc + como_vis

        base = lista_condicion if lista_condicion else lista_total
        if base:
            n = len(base)
            gf = sum(x[0] for x in base) / n
            gc = sum(x[1] for x in base) / n
            crn = sum(x[2] for x in base) / n
            tar = sum(x[3] for x in base) / n
            off = sum(x[4] for x in base) / n
            return len(lista_total), gf, gc, crn, tar, off
        else:
            def_gf = media_gl if es_local else media_gv
            def_gc = media_gv if es_local else media_gl
            return 0, def_gf, def_gc, media_crn / 2.0, media_tar / 2.0, media_off / 2.0

    n_tot_l, gf_l, gc_l, crn_l, tar_l, off_l = obtener_stats_club(local, True)
    n_tot_v, gf_v, gc_v, crn_v, tar_v, off_v = obtener_stats_club(visitante, False)
    conn.close()

    lambda_loc = max(0.2, (gf_l + gc_v) / 2.0)
    lambda_vis = max(0.2, (gf_v + gc_l) / 2.0)

    p_loc_pct, p_emp_pct, p_vis_pct = 0.0, 0.0, 0.0
    p_over_1_5, p_over_2_5, p_over_3_5, p_btts = 0.0, 0.0, 0.0, 0.0
    matriz_marcadores = []

    for gl in range(8):
        for gv in range(8):
            prob = poisson_prob(lambda_loc, gl) * poisson_prob(lambda_vis, gv)
            matriz_marcadores.append((f"{gl}-{gv}", prob * 100))
            if gl > gv:
                p_loc_pct += prob
            elif gl == gv:
                p_emp_pct += prob
            else:
                p_vis_pct += prob

            if (gl + gv) > 1.5:
                p_over_1_5 += prob
            if (gl + gv) > 2.5:
                p_over_2_5 += prob
            if (gl + gv) > 3.5:
                p_over_3_5 += prob
            if gl > 0 and gv > 0:
                p_btts += prob

    matriz_marcadores.sort(key=lambda x: x[1], reverse=True)
    top_3_marcadores = matriz_marcadores[:3]

    return {
        "n_loc_tot": n_tot_l,
        "n_vis_tot": n_tot_v,
        "lambda_loc": lambda_loc,
        "lambda_vis": lambda_vis,
        "prob_loc": p_loc_pct * 100,
        "prob_emp": p_emp_pct * 100,
        "prob_vis": p_vis_pct * 100,
        "prob_over_1_5": p_over_1_5 * 100,
        "prob_over_2_5": p_over_2_5 * 100,
        "prob_over_3_5": p_over_3_5 * 100,
        "prob_btts": p_btts * 100,
        "corners_loc": crn_l,
        "corners_vis": crn_v,
        "corners_tot": crn_l + crn_v,
        "tarjetas_loc": tar_l,
        "tarjetas_vis": tar_v,
        "tarjetas_tot": tar_l + tar_v,
        "offsides_loc": off_l,
        "offsides_vis": off_v,
        "offsides_tot": off_l + off_v,
        "top_3": top_3_marcadores
    }

# ==============================================================================
# 5. INTERFAZ GRÁFICA TKINTER CON TABLERO DE SELECCIONES / BOLETA
# ==============================================================================

class AutocompleteCombobox(ttk.Combobox):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._lista_maestra = []
        self.bind("<KeyRelease>", self._filtrar)

    def set_datos(self, opciones):
        self._lista_maestra = sorted(list(set(opciones)))
        self["values"] = self._lista_maestra

    def _filtrar(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        cad = self.get().strip().upper()
        if not cad:
            self["values"] = self._lista_maestra
            return
        self["values"] = [x for x in self._lista_maestra if cad in x]
        try:
            self.event_generate("<Down>")
        except Exception:
            pass

class AppFutbolPro:
    def __init__(self, root):
        self.root = root
        self.root.title("Control Estadístico y Pronósticos en Vivo (ESPN & SQLite)")
        self.root.geometry("1220x920")
        self.root.configure(bg="#f4f5f7")

        self.ultimo_analisis = None  # Almacena el cálculo en curso para agregarlo a la boleta

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_descargas = ttk.Frame(self.notebook)
        self.tab_analisis = ttk.Frame(self.notebook)
        self.tab_metricas = ttk.Frame(self.notebook)
        self.tab_manual = ttk.Frame(self.notebook)
        self.tab_boleta = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_descargas, text="1. Descargar Partidos & Enlaces")
        self.notebook.add(self.tab_analisis, text="2. Pronóstico y Posibilidades")
        self.notebook.add(self.tab_metricas, text="3. Base de Datos & Métricas (4 Variables)")
        self.notebook.add(self.tab_manual, text="4. Registro Manual")
        self.notebook.add(self.tab_boleta, text="5. Resumen de Selecciones & Boleta")

        self.crear_tab_descargas()
        self.crear_tab_analisis()
        self.crear_tab_metricas()
        self.crear_tab_manual()
        self.crear_tab_boleta()
        self.actualizar_combos()

        threading.Thread(target=self.precargar_todas_las_ligas, daemon=True).start()

    def precargar_todas_las_ligas(self):
        for cod in LIGAS_ESPN.keys():
            sincronizar_equipos_de_liga(cod)
        self.root.after(100, self.actualizar_combos)

    # --- PESTAÑA 1: DESCARGAS Y NUEVAS LIGAS ---
    def crear_tab_descargas(self):
        f_nueva = ttk.LabelFrame(self.tab_descargas, text=" Agregar Nueva Liga por Enlace de ESPN ", padding=12)
        f_nueva.pack(fill="x", padx=15, pady=8)

        ttk.Label(f_nueva, text="Pegar Enlace ESPN:", font=("Arial", 9, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        self.ent_nuevo_enlace = ttk.Entry(f_nueva, width=58)
        self.ent_nuevo_enlace.grid(row=0, column=1, sticky="w", pady=4, padx=5)

        btn_agregar_liga = ttk.Button(f_nueva, text="Registrar Liga y Clubes", command=self.ejecutar_agregar_liga_url)
        btn_agregar_liga.grid(row=0, column=2, padx=5, pady=4)

        f_partidos = ttk.LabelFrame(self.tab_descargas, text=" Descargar Partidos Finalizados (Goles, Córners, Tarjetas y Offsides) ", padding=12)
        f_partidos.pack(fill="x", padx=15, pady=8)

        ttk.Label(f_partidos, text="Selecciona la Liga:", font=("Arial", 9, "bold")).grid(row=0, column=0, sticky="w", pady=6)
        self.combo_sync_liga = ttk.Combobox(f_partidos, state="readonly", width=42)
        self.combo_sync_liga.grid(row=0, column=1, sticky="w", pady=6, padx=5)

        ttk.Label(f_partidos, text="Fecha (AAAAMMDD):", font=("Arial", 9, "bold")).grid(row=1, column=0, sticky="w", pady=6)
        self.ent_fecha_sync = ttk.Entry(f_partidos, width=22)
        self.ent_fecha_sync.insert(0, datetime.now().strftime("%Y%m%d"))
        self.ent_fecha_sync.grid(row=1, column=1, sticky="w", pady=6, padx=5)

        btn_box = ttk.Frame(f_partidos)
        btn_box.grid(row=2, column=0, columnspan=3, pady=10)

        btn_hoy = ttk.Button(btn_box, text="Descargar Partidos de Esta Fecha", command=self.ejecutar_sync_fecha)
        btn_hoy.pack(side="left", padx=8)

        btn_todos = ttk.Button(btn_box, text="Sincronizar Clubes de Esta Liga Ahora", command=self.ejecutar_sync_clubes_manual)
        btn_todos.pack(side="left", padx=8)

        self.lbl_status = ttk.Label(self.tab_descargas, text="Estado: Base de datos lista.", font=("Arial", 9, "italic"))
        self.lbl_status.pack(padx=15, pady=6, anchor="w")

    def ejecutar_sync_clubes_manual(self):
        sel = self.combo_sync_liga.get()
        if not sel:
            return
        cod = sel.split(" - ")[0].strip()
        self.lbl_status.config(text=f"Descargando equipos de {cod}...")
        self.root.update()
        cod, nom, tot = sincronizar_equipos_de_liga(cod)
        self.lbl_status.config(text=f"Se indexaron {tot} clubes para {nom}.")
        messagebox.showinfo("Éxito", f"Se cargaron {tot} clubes oficiales para {nom}.")
        self.actualizar_combos()

    def ejecutar_agregar_liga_url(self):
        url = self.ent_nuevo_enlace.get().strip()
        if not url:
            messagebox.showwarning("Atención", "Pegue un enlace de ESPN.")
            return
        self.lbl_status.config(text="Procesando enlace...")
        self.root.update()
        try:
            codigo = parsear_codigo_liga(url)
            cod, nom, tot = sincronizar_equipos_de_liga(codigo)
            self.lbl_status.config(text=f"Liga registrada: {nom} [{cod}] con {tot} clubes.")
            messagebox.showinfo("Éxito", f"Liga agregada correctamente:\n{nom} [{cod}]\nEquipos registrados: {tot}")
            self.actualizar_combos()
        except Exception as ex:
            self.lbl_status.config(text="Fallo al procesar el enlace.")
            messagebox.showerror("Error", f"No se pudo extraer la liga del enlace:\n{str(ex)}")

    def ejecutar_sync_fecha(self):
        sel = self.combo_sync_liga.get()
        if not sel:
            messagebox.showwarning("Atención", "Seleccione una liga.")
            return
        cod = sel.split(" - ")[0].strip()
        fec = self.ent_fecha_sync.get().strip()

        self.lbl_status.config(text=f"Consultando partidos para {cod} en fecha {fec}...")
        self.root.update()

        guardados, err = descargar_partidos_fecha(cod, fec)
        if err:
            self.lbl_status.config(text="Aviso al consultar ESPN.")
            messagebox.showinfo("Información", err)
        else:
            self.lbl_status.config(text=f"Se guardaron {guardados} partidos disputados.")
            messagebox.showinfo("Éxito", f"Se registraron {guardados} encuentros con sus 4 variables completas.")
            self.actualizar_combos()

    # --- PESTAÑA 2: PRONÓSTICOS POISSON CON PANEL DERECHO Y BOTÓN A BOLETA ---
    def crear_tab_analisis(self):
        contenedor_split = ttk.Frame(self.tab_analisis)
        contenedor_split.pack(fill="x", padx=10, pady=5)

        panel_izq = ttk.Frame(contenedor_split)
        panel_izq.pack(side="left", fill="both", expand=True, padx=(0, 10))

        f1 = ttk.LabelFrame(panel_izq, text=" 1. Configurar Cruce (Buscador Predictivo) ", padding=10)
        f1.pack(fill="x", pady=4)

        ttk.Label(f1, text="Competición:", font=("Arial", 9, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        self.combo_ana_liga = ttk.Combobox(f1, state="readonly", width=36)
        self.combo_ana_liga.grid(row=0, column=1, sticky="w", pady=4)
        self.combo_ana_liga.bind("<<ComboboxSelected>>", self.al_cambiar_liga_analisis)

        ttk.Label(f1, text="Equipo Local:").grid(row=1, column=0, sticky="w", pady=4)
        self.combo_ana_loc = AutocompleteCombobox(f1, width=30)
        self.combo_ana_loc.grid(row=1, column=1, sticky="w", pady=4)
        self.combo_ana_loc.bind("<<ComboboxSelected>>", self.cargar_datos_partido)

        ttk.Label(f1, text="Equipo Visitante:").grid(row=2, column=0, sticky="w", pady=4)
        self.combo_ana_vis = AutocompleteCombobox(f1, width=30)
        self.combo_ana_vis.grid(row=2, column=1, sticky="w", pady=4)
        self.combo_ana_vis.bind("<<ComboboxSelected>>", self.cargar_datos_partido)

        f2 = ttk.LabelFrame(panel_izq, text=" 2. Medias en Base de Datos para esta Liga (Modificables) ", padding=10)
        f2.pack(fill="x", pady=4)

        ttk.Label(f2, text="Goles esperados Local:").grid(row=0, column=0, sticky="w", pady=3)
        self.ent_l_loc = ttk.Entry(f2, width=9)
        self.ent_l_loc.grid(row=0, column=1, sticky="w", pady=3)

        ttk.Label(f2, text="Goles esperados Visitante:").grid(row=0, column=2, sticky="w", padx=(15, 3), pady=3)
        self.ent_l_vis = ttk.Entry(f2, width=9)
        self.ent_l_vis.grid(row=0, column=3, sticky="w", pady=3)

        ttk.Label(f2, text="Córners proyectados:").grid(row=1, column=0, sticky="w", pady=3)
        self.ent_crn = ttk.Entry(f2, width=9)
        self.ent_crn.grid(row=1, column=1, sticky="w", pady=3)

        ttk.Label(f2, text="Tarjetas proyectadas:").grid(row=1, column=2, sticky="w", padx=(15, 3), pady=3)
        self.ent_tar = ttk.Entry(f2, width=9)
        self.ent_tar.grid(row=1, column=3, sticky="w", pady=3)

        ttk.Label(f2, text="Fueras de Juego (Offsides):").grid(row=2, column=0, sticky="w", pady=3)
        self.ent_off = ttk.Entry(f2, width=9)
        self.ent_off.grid(row=2, column=1, sticky="w", pady=3)

        btn_box = ttk.Frame(f2)
        btn_box.grid(row=3, column=0, columnspan=4, pady=8)

        btn_load = ttk.Button(btn_box, text="Cargar Promedios Guardados", command=self.cargar_datos_partido)
        btn_load.pack(side="left", padx=4)

        btn_calc = ttk.Button(btn_box, text="Calcular Posibilidades Poisson", command=self.ejecutar_calculo)
        btn_calc.pack(side="left", padx=4)

        self.btn_guardar_boleta = ttk.Button(btn_box, text="➕ Agregar a la Boleta", state="disabled", command=self.agregar_a_la_boleta)
        self.btn_guardar_boleta.pack(side="left", padx=6)

        # ====== PANEL DERECHO: LISTA DE EQUIPOS ======
        panel_der = ttk.LabelFrame(contenedor_split, text=" Equipos Oficiales de la Liga Seleccionada ", padding=10)
        panel_der.pack(side="right", fill="y", padx=(0, 5))

        f_listbox = ttk.Frame(panel_der)
        f_listbox.pack(fill="both", expand=True)

        self.listbox_equipos = tk.Listbox(f_listbox, width=32, height=13, font=("Arial", 9))
        self.listbox_equipos.pack(side="left", fill="both", expand=True)
        self.listbox_equipos.bind("<Double-Button-1>", self.al_doble_clic_equipo)

        sb_listbox = ttk.Scrollbar(f_listbox, orient="vertical", command=self.listbox_equipos.yview)
        sb_listbox.pack(side="right", fill="y")
        self.listbox_equipos.config(yscrollcommand=sb_listbox.set)

        btn_panel = ttk.Frame(panel_der)
        btn_panel.pack(fill="x", pady=6)

        btn_fijar_loc = ttk.Button(btn_panel, text="Fijar como Local", command=self.fijar_equipo_como_local)
        btn_fijar_loc.pack(side="left", expand=True, fill="x", padx=2)

        btn_fijar_vis = ttk.Button(btn_panel, text="Fijar como Visitante", command=self.fijar_equipo_como_visitante)
        btn_fijar_vis.pack(side="left", expand=True, fill="x", padx=2)

        self.txt_analisis = tk.Text(self.tab_analisis, height=14, width=115, bg="#ffffff", font=("Consolas", 10))
        self.txt_analisis.pack(fill="both", expand=True, padx=10, pady=6)

    def al_cambiar_liga_analisis(self, event=None):
        cod = self.combo_ana_liga.get().split(" - ")[0].strip()
        eqs = self.obtener_equipos(cod)

        if not eqs:
            sincronizar_equipos_de_liga(cod)
            eqs = self.obtener_equipos(cod)

        self.combo_ana_loc.set_datos(eqs)
        self.combo_ana_vis.set_datos(eqs)
        self.combo_ana_loc.set("")
        self.combo_ana_vis.set("")

        self.listbox_equipos.delete(0, tk.END)
        for eq in eqs:
            self.listbox_equipos.insert(tk.END, eq)

    def fijar_equipo_como_local(self):
        sel = self.listbox_equipos.curselection()
        if sel:
            eq = self.listbox_equipos.get(sel[0])
            self.combo_ana_loc.set(eq)
            self.cargar_datos_partido()

    def fijar_equipo_como_visitante(self):
        sel = self.listbox_equipos.curselection()
        if sel:
            eq = self.listbox_equipos.get(sel[0])
            self.combo_ana_vis.set(eq)
            self.cargar_datos_partido()

    def al_doble_clic_equipo(self, event=None):
        sel = self.listbox_equipos.curselection()
        if not sel:
            return
        eq = self.listbox_equipos.get(sel[0])
        if not self.combo_ana_loc.get().strip():
            self.combo_ana_loc.set(eq)
        else:
            self.combo_ana_vis.set(eq)
        self.cargar_datos_partido()

    def cargar_datos_partido(self, event=None):
        cod = self.combo_ana_liga.get().split(" - ")[0].strip()
        loc = self.combo_ana_loc.get().strip().upper()
        vis = self.combo_ana_vis.get().strip().upper()
        if not loc or not vis or loc == vis:
            return

        res = auditar_partido_flexible(cod, loc, vis)

        self._set_txt(self.ent_l_loc, f"{res['lambda_loc']:.2f}")
        self._set_txt(self.ent_l_vis, f"{res['lambda_vis']:.2f}")
        self._set_txt(self.ent_crn, f"{res['corners_tot']:.1f}")
        self._set_txt(self.ent_tar, f"{res['tarjetas_tot']:.1f}")
        self._set_txt(self.ent_off, f"{res['offsides_tot']:.1f}")

    def _set_txt(self, entry, val):
        entry.delete(0, tk.END)
        entry.insert(0, str(val))

    def ejecutar_calculo(self):
        cod = self.combo_ana_liga.get().split(" - ")[0].strip()
        loc = self.combo_ana_loc.get().strip().upper()
        vis = self.combo_ana_vis.get().strip().upper()

        if not loc or not vis or loc == vis:
            messagebox.showwarning("Atención", "Seleccione dos equipos distintos.")
            return

        try:
            l_loc = float(self.ent_l_loc.get().strip())
            l_vis = float(self.ent_l_vis.get().strip())
            crn = float(self.ent_crn.get().strip())
            tar = float(self.ent_tar.get().strip())
            off = float(self.ent_off.get().strip())
        except ValueError:
            messagebox.showerror("Error", "Ingrese números válidos en las métricas.")
            return

        p_loc, p_emp, p_vis = 0.0, 0.0, 0.0
        p_over_1_5, p_over_2_5, p_over_3_5, p_btts = 0.0, 0.0, 0.0, 0.0
        matriz_m = []

        for gl in range(8):
            for gv in range(8):
                prob = poisson_prob(l_loc, gl) * poisson_prob(l_vis, gv)
                matriz_m.append((f"{gl}-{gv}", prob * 100))
                if gl > gv:
                    p_loc += prob
                elif gl == gv:
                    p_emp += prob
                else:
                    p_vis += prob

                if (gl + gv) > 1.5:
                    p_over_1_5 += prob
                if (gl + gv) > 2.5:
                    p_over_2_5 += prob
                if (gl + gv) > 3.5:
                    p_over_3_5 += prob
                if gl > 0 and gv > 0:
                    p_btts += prob

        matriz_m.sort(key=lambda x: x[1], reverse=True)
        top_3 = matriz_m[:3]

        p_l_pct = p_loc * 100
        p_e_pct = p_emp * 100
        p_v_pct = p_vis * 100

        # Cuotas justas (Fair Odds: 100 / P)
        c_loc = (100.0 / p_l_pct) if p_l_pct > 0 else 99.0
        c_emp = (100.0 / p_e_pct) if p_e_pct > 0 else 99.0
        c_vis = (100.0 / p_v_pct) if p_v_pct > 0 else 99.0

        # Doble oportunidad
        p_1x = p_l_pct + p_e_pct
        p_x2 = p_e_pct + p_v_pct
        p_12 = p_l_pct + p_v_pct

        # Determinar el resultado más factible 1X2
        if p_l_pct >= p_e_pct and p_l_pct >= p_v_pct:
            pron_1x2 = f"1 ({loc})"
            pron_prob = p_l_pct
            pron_cuota = c_loc
        elif p_v_pct >= p_l_pct and p_v_pct >= p_e_pct:
            pron_1x2 = f"2 ({vis})"
            pron_prob = p_v_pct
            pron_cuota = c_vis
        else:
            pron_1x2 = "X (Empate)"
            pron_prob = p_e_pct
            pron_cuota = c_emp

        # Guardar en memoria para la boleta
        self.ultimo_analisis = {
            "liga": cod,
            "local": loc,
            "visitante": vis,
            "pron_1x2": pron_1x2,
            "prob": pron_prob,
            "cuota": pron_cuota,
            "xg_tot": l_loc + l_vis,
            "crn": crn,
            "tar": tar,
            "off": off,
            "over25": p_over_2_5 * 100
        }
        self.btn_guardar_boleta.config(state="normal")

        self.txt_analisis.delete("1.0", tk.END)
        rep = f"""========================================================================================================
ESTUDIO ESTADÍSTICO PROBABILÍSTICO AVANZADO (LIGA: {cod})
ENCUENTRO: {loc} (Local) vs {vis} (Visitante)
========================================================================================================
MÉTRICAS BASE COMPUTADAS:
 - Goles esperados {loc}: {l_loc:.2f}  |  Goles esperados {vis}: {l_vis:.2f}
 - Goles totales proyectados:  {l_loc + l_vis:.2f}

PROBABILIDADES 1X2 & CUOTAS JUSTAS (Fair Odds):
 ┌ Victoria Local ({loc}):     {p_l_pct:.1f}%  --> Cuota Justa: @{c_loc:.2f}
 ├ Empate:                     {p_e_pct:.1f}%  --> Cuota Justa: @{c_emp:.2f}
 └ Victoria Visitante ({vis}): {p_v_pct:.1f}%  --> Cuota Justa: @{c_vis:.2f}

DOBLE OPORTUNIDAD:
 ├ 1X ({loc} o Empate):        {p_1x:.1f}%  (@{100/p_1x:.2f})
 ├ X2 (Empate o {vis}):        {p_x2:.1f}%  (@{100/p_x2:.2f})
 └ 12 (Cualquiera gana):       {p_12:.1f}%  (@{100/p_12:.2f})

MERCADOS DE GOLES (Distribución Poisson):
 ├ Ambos Marcan (BTTS Sí):     {p_btts * 100:.1f}%
 ├ Más de 1.5 Goles:           {p_over_1_5 * 100:.1f}%
 ├ Más de 2.5 Goles:           {p_over_2_5 * 100:.1f}%  |  Menos de 2.5 Goles: {100 - (p_over_2_5 * 100):.1f}%
 └ Más de 3.5 Goles:           {p_over_3_5 * 100:.1f}%

TOP 3 MARCADORES EXACTOS MÁS PROBABLES:
 1. [{top_3[0][0]}] con {top_3[0][1]:.1f}%
 2. [{top_3[1][0]}] con {top_3[1][1]:.1f}%
 3. [{top_3[2][0]}] con {top_3[2][1]:.1f}%

LÍNEAS COMPLEMENTARIAS PROYECTADAS (Medias sumadas):
 ├ Tiros de Esquina (Corners) esperados: {crn:.1f}
 ├ Tarjetas totales en el partido:       {tar:.1f}
 └ Fueras de Juego (Offsides):           {off:.1f}
========================================================================================================
"""
        self.txt_analisis.insert(tk.END, rep)

    def agregar_a_la_boleta(self):
        if not self.ultimo_analisis:
            return
        d = self.ultimo_analisis
        self.tree_boleta.insert("", tk.END, values=(
            d["liga"],
            d["local"],
            d["visitante"],
            d["pron_1x2"],
            f"{d['prob']:.1f}%",
            f"@{d['cuota']:.2f}",
            f"{d['xg_tot']:.2f}",
            f"{d['over25']:.1f}%",
            f"{d['crn']:.1f}",
            f"{d['tar']:.1f}",
            f"{d['off']:.1f}"
        ))
        self.actualizar_resumen_boleta()
        messagebox.showinfo("Boleta", f"¡Partido {d['local']} vs {d['visitante']} agregado a la Boleta de Selecciones!")

    # --- PESTAÑA 3: BASE DE DATOS Y MÉTRICAS POR PARTIDO / PROMEDIOS ---
    def crear_tab_metricas(self):
        f = ttk.Frame(self.tab_metricas, padding=10)
        f.pack(fill="both", expand=True)

        top_f = ttk.Frame(f)
        top_f.pack(fill="x", pady=4)

        ttk.Label(top_f, text="Filtrar por Liga:", font=("Arial", 9, "bold")).pack(side="left", padx=5)
        self.combo_met_liga = ttk.Combobox(top_f, state="readonly", width=36)
        self.combo_met_liga.pack(side="left", padx=5)
        self.combo_met_liga.bind("<<ComboboxSelected>>", self.cargar_datos_pestana_metricas)

        btn_act = ttk.Button(top_f, text="Actualizar", command=self.cargar_datos_pestana_metricas)
        btn_act.pack(side="left", padx=10)

        sub_nb = ttk.Notebook(f)
        sub_nb.pack(fill="both", expand=True, pady=6)

        self.sub_frame_partidos = ttk.Frame(sub_nb)
        self.sub_frame_promedios = ttk.Frame(sub_nb)

        sub_nb.add(self.sub_frame_partidos, text="1. Historial Detallado por Partido (Fecha / Métricas Puras)")
        sub_nb.add(self.sub_frame_promedios, text="2. Promedios Consolidados por Club")

        # TABLA 1: Historial individual
        cols_partidos = ("fecha", "local", "visitante", "marcador", "corners", "tarjetas", "offsides")
        self.tree_partidos = ttk.Treeview(self.sub_frame_partidos, columns=cols_partidos, show="headings", height=18)

        self.tree_partidos.heading("fecha", text="Fecha")
        self.tree_partidos.heading("local", text="Local")
        self.tree_partidos.heading("visitante", text="Visitante")
        self.tree_partidos.heading("marcador", text="Goles (L - V)")
        self.tree_partidos.heading("corners", text="Córners (L - V)")
        self.tree_partidos.heading("tarjetas", text="Tarjetas (L - V)")
        self.tree_partidos.heading("offsides", text="Offsides (L - V)")

        self.tree_partidos.column("fecha", width=95, anchor="center")
        self.tree_partidos.column("local", width=180, anchor="w")
        self.tree_partidos.column("visitante", width=180, anchor="w")
        self.tree_partidos.column("marcador", width=110, anchor="center")
        self.tree_partidos.column("corners", width=110, anchor="center")
        self.tree_partidos.column("tarjetas", width=110, anchor="center")
        self.tree_partidos.column("offsides", width=110, anchor="center")

        sb1 = ttk.Scrollbar(self.sub_frame_partidos, orient="vertical", command=self.tree_partidos.yview)
        self.tree_partidos.configure(yscrollcommand=sb1.set)
        self.tree_partidos.pack(side="left", fill="both", expand=True)
        sb1.pack(side="right", fill="y")

        # TABLA 2: Promedios consolidados
        cols_prom = ("club", "pj", "gf", "gc", "prom_goles", "prom_corners", "prom_tarjetas", "prom_offsides")
        self.tree_metricas = ttk.Treeview(self.sub_frame_promedios, columns=cols_prom, show="headings", height=18)

        self.tree_metricas.heading("club", text="Club")
        self.tree_metricas.heading("pj", text="Partidos")
        self.tree_metricas.heading("gf", text="Goles Favor")
        self.tree_metricas.heading("gc", text="Goles Contra")
        self.tree_metricas.heading("prom_goles", text="Goles/P")
        self.tree_metricas.heading("prom_corners", text="Córners/P")
        self.tree_metricas.heading("prom_tarjetas", text="Tarjetas/P")
        self.tree_metricas.heading("prom_offsides", text="Offsides/P")

        self.tree_metricas.column("club", width=220, anchor="w")
        self.tree_metricas.column("pj", width=70, anchor="center")
        self.tree_metricas.column("gf", width=80, anchor="center")
        self.tree_metricas.column("gc", width=80, anchor="center")
        self.tree_metricas.column("prom_goles", width=80, anchor="center")
        self.tree_metricas.column("prom_corners", width=90, anchor="center")
        self.tree_metricas.column("prom_tarjetas", width=90, anchor="center")
        self.tree_metricas.column("prom_offsides", width=100, anchor="center")

        sb2 = ttk.Scrollbar(self.sub_frame_promedios, orient="vertical", command=self.tree_metricas.yview)
        self.tree_metricas.configure(yscrollcommand=sb2.set)
        self.tree_metricas.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

    def cargar_datos_pestana_metricas(self, event=None):
        for r in self.tree_partidos.get_children():
            self.tree_partidos.delete(r)
        for r in self.tree_metricas.get_children():
            self.tree_metricas.delete(r)

        sel = self.combo_met_liga.get()
        if not sel:
            return
        cod = sel.split(" - ")[0].strip()

        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            SELECT fecha, local, visitante, goles_local, goles_visitante,
                   corners_local, corners_visitante, tarjetas_local, tarjetas_visitante,
                   offsides_local, offsides_visitante
            FROM partidos 
            WHERE competicion_id = ?
            ORDER BY fecha DESC
        """, (cod,))
        rows = cur.fetchall()
        conn.close()

        stats = {}
        for r in rows:
            fec, loc, vis = r[0], r[1], r[2]
            gl, gv, cl, cv, tl, tv, ol, ov = r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10]

            self.tree_partidos.insert("", tk.END, values=(
                fec, loc, vis,
                f"{gl} - {gv}",
                f"{cl} - {cv}",
                f"{tl} - {tv}",
                f"{ol} - {ov}"
            ))

            for c in [loc, vis]:
                if c not in stats:
                    stats[c] = {"pj": 0, "gf": 0, "gc": 0, "corners": 0, "tarjetas": 0, "offsides": 0}

            stats[loc]["pj"] += 1
            stats[loc]["gf"] += gl
            stats[loc]["gc"] += gv
            stats[loc]["corners"] += cl
            stats[loc]["tarjetas"] += tl
            stats[loc]["offsides"] += ol

            stats[vis]["pj"] += 1
            stats[vis]["gf"] += gv
            stats[vis]["gc"] += gl
            stats[vis]["corners"] += cv
            stats[vis]["tarjetas"] += tv
            stats[vis]["offsides"] += ov

        filas_prom = []
        for club, s in stats.items():
            pj = s["pj"]
            p_g = (s["gf"] + s["gc"]) / pj if pj > 0 else 0
            p_c = s["corners"] / pj if pj > 0 else 0
            p_t = s["tarjetas"] / pj if pj > 0 else 0
            p_o = s["offsides"] / pj if pj > 0 else 0
            filas_prom.append((club, pj, s["gf"], s["gc"], f"{p_g:.2f}", f"{p_c:.1f}", f"{p_t:.1f}", f"{p_o:.1f}"))

        filas_prom.sort(key=lambda x: x[1], reverse=True)
        for f in filas_prom:
            self.tree_metricas.insert("", tk.END, values=f)

    # --- PESTAÑA 4: REGISTRO MANUAL ---
    def crear_tab_manual(self):
        f = ttk.LabelFrame(self.tab_manual, text=" Registrar Partido Manualmente ", padding=15)
        f.pack(fill="x", padx=15, pady=10)

        ttk.Label(f, text="Competición:").grid(row=0, column=0, sticky="w", pady=4)
        self.combo_man_liga = ttk.Combobox(f, state="readonly", width=38)
        self.combo_man_liga.grid(row=0, column=1, sticky="w", pady=4)
        self.combo_man_liga.bind("<<ComboboxSelected>>", self.al_cambiar_liga_manual)

        self.man_sem = self._crear_campo(f, "Jornada / Fecha:", 1, "1")
        self.man_fec = self._crear_campo(f, "Fecha (AAAA-MM-DD):", 2, datetime.now().strftime("%Y-%m-%d"))

        ttk.Label(f, text="Equipo Local (2-3 letras):").grid(row=3, column=0, sticky="w", pady=4)
        self.combo_man_loc = AutocompleteCombobox(f, width=38)
        self.combo_man_loc.grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Equipo Visitante (2-3 letras):").grid(row=4, column=0, sticky="w", pady=4)
        self.combo_man_vis = AutocompleteCombobox(f, width=38)
        self.combo_man_vis.grid(row=4, column=1, sticky="w", pady=4)

        self.man_gl = self._crear_campo(f, "Goles Local:", 5)
        self.man_gv = self._crear_campo(f, "Goles Visitante:", 6)
        self.man_cl = self._crear_campo(f, "Córners Local:", 7)
        self.man_cv = self._crear_campo(f, "Córners Visitante:", 8)
        self.man_tl = self._crear_campo(f, "Tarjetas Local:", 9)
        self.man_tv = self._crear_campo(f, "Tarjetas Visitante:", 10)
        self.man_ol = self._crear_campo(f, "Fueras de Juego Local:", 11)
        self.man_ov = self._crear_campo(f, "Fueras de Juego Visitante:", 12)

        btn = ttk.Button(f, text="Guardar Resultado Manual", command=self.guardar_manual)
        btn.grid(row=13, column=0, columnspan=2, pady=12)

    def _crear_campo(self, frame, label, row, default=""):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
        e = ttk.Entry(frame, width=40)
        e.grid(row=row, column=1, sticky="w", pady=3)
        if default:
            e.insert(0, default)
        return e

    def al_cambiar_liga_manual(self, event=None):
        cod = self.combo_man_liga.get().split(" - ")[0].strip()
        eqs = self.obtener_equipos(cod)
        self.combo_man_loc.set_datos(eqs)
        self.combo_man_vis.set_datos(eqs)

    def guardar_manual(self):
        try:
            cod = self.combo_man_liga.get().split(" - ")[0].strip()
            fec = self.man_fec.get().strip()
            loc = self.combo_man_loc.get().strip().upper()
            vis = self.combo_man_vis.get().strip().upper()
            gl = int(self.man_gl.get().strip())
            gv = int(self.man_gv.get().strip())
            cl = int(self.man_cl.get().strip())
            cv = int(self.man_cv.get().strip())
            tl = int(self.man_tl.get().strip())
            tv = int(self.man_tv.get().strip())
            ol = int(self.man_ol.get().strip())
            ov = int(self.man_ov.get().strip())

            if not loc or not vis or loc == vis:
                messagebox.showerror("Error", "Indique nombres válidos y distintos.")
                return

            conn = sqlite3.connect(DB_NAME)
            cur = conn.cursor()
            fix_id = f"MANUAL_{fec}_{loc}_{vis}"
            cur.execute("""
                INSERT OR REPLACE INTO partidos 
                (fixture_id, competicion_id, fecha, local, visitante, goles_local, goles_visitante,
                 corners_local, corners_visitante, tarjetas_local, tarjetas_visitante, offsides_local, offsides_visitante)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (fix_id, cod, fec, loc, vis, gl, gv, cl, cv, tl, tv, ol, ov))
            conn.commit()
            conn.close()

            messagebox.showinfo("Éxito", f"Partido {loc} vs {vis} guardado en {cod}.")
            for e in [self.man_gl, self.man_gv, self.man_cl, self.man_cv, self.man_tl, self.man_tv, self.man_ol, self.man_ov]:
                e.delete(0, tk.END)
            self.cargar_datos_pestana_metricas()
        except ValueError:
            messagebox.showerror("Error", "Ingrese números enteros válidos.")

    # --- PESTAÑA 5: RESUMEN DE SELECCIONES & BOLETA ---
    def crear_tab_boleta(self):
        f = ttk.Frame(self.tab_boleta, padding=12)
        f.pack(fill="both", expand=True)

        top_f = ttk.Frame(f)
        top_f.pack(fill="x", pady=6)

        ttk.Label(top_f, text="Boleta de Partidos y Pronósticos Seleccionados", font=("Arial", 11, "bold")).pack(side="left")

        btn_limpiar = ttk.Button(top_f, text="Limpiar Toda la Boleta", command=self.limpiar_boleta)
        btn_limpiar.pack(side="right", padx=5)

        btn_eliminar_fila = ttk.Button(top_f, text="Eliminar Selección Marcada", command=self.eliminar_seleccion_boleta)
        btn_eliminar_fila.pack(side="right", padx=5)

        cols_b = ("liga", "local", "vis", "pron_1x2", "prob", "cuota", "xg_tot", "over25", "crn", "tar", "off")
        self.tree_boleta = ttk.Treeview(f, columns=cols_b, show="headings", height=16)

        self.tree_boleta.heading("liga", text="Liga")
        self.tree_boleta.heading("local", text="Local")
        self.tree_boleta.heading("vis", text="Visitante")
        self.tree_boleta.heading("pron_1x2", text="Pronóstico 1X2")
        self.tree_boleta.heading("prob", text="Probabilidad")
        self.tree_boleta.heading("cuota", text="Cuota Justa")
        self.tree_boleta.heading("xg_tot", text="Goles Totales")
        self.tree_boleta.heading("over25", text="Más 2.5 Goles")
        self.tree_boleta.heading("crn", text="Córners Tot.")
        self.tree_boleta.heading("tar", text="Tarjetas Tot.")
        self.tree_boleta.heading("off", text="Offsides Tot.")

        self.tree_boleta.column("liga", width=110, anchor="center")
        self.tree_boleta.column("local", width=145, anchor="w")
        self.tree_boleta.column("vis", width=145, anchor="w")
        self.tree_boleta.column("pron_1x2", width=125, anchor="center")
        self.tree_boleta.column("prob", width=85, anchor="center")
        self.tree_boleta.column("cuota", width=85, anchor="center")
        self.tree_boleta.column("xg_tot", width=90, anchor="center")
        self.tree_boleta.column("over25", width=95, anchor="center")
        self.tree_boleta.column("crn", width=85, anchor="center")
        self.tree_boleta.column("tar", width=85, anchor="center")
        self.tree_boleta.column("off", width=85, anchor="center")

        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree_boleta.yview)
        self.tree_boleta.configure(yscrollcommand=sb.set)
        self.tree_boleta.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Panel inferior con totales acumulados (Cuota multiplicada y probabilidad combinada)
        self.lbl_resumen_boleta = ttk.Label(
            self.tab_boleta, 
            text="Partidos en boleta: 0  |  Cuota Combinada Multiplicada: @1.00  |  Probabilidad Acumulada: 100.0%", 
            font=("Arial", 10, "bold"),
            foreground="#1a5276"
        )
        self.lbl_resumen_boleta.pack(fill="x", padx=15, pady=8)

    def actualizar_resumen_boleta(self):
        items = self.tree_boleta.get_children()
        total_partidos = len(items)
        if total_partidos == 0:
            self.lbl_resumen_boleta.config(
                text="Partidos en boleta: 0  |  Cuota Combinada Multiplicada: @1.00  |  Probabilidad Acumulada: 100.0%"
            )
            return

        cuota_combinada = 1.0
        prob_acumulada = 1.0

        for it in items:
            vals = self.tree_boleta.item(it, "values")
            prob_val = float(vals[4].replace("%", "").strip()) / 100.0
            cuota_val = float(vals[5].replace("@", "").strip())
            cuota_combinada *= cuota_val
            prob_acumulada *= prob_val

        self.lbl_resumen_boleta.config(
            text=f"Partidos en boleta: {total_partidos}  |  "
                 f"Cuota Combinada Multiplicada: @{cuota_combinada:.2f}  |  "
                 f"Probabilidad Acumulada: {prob_acumulada * 100:.2f}%"
        )

    def eliminar_seleccion_boleta(self):
        sel = self.tree_boleta.selection()
        if not sel:
            messagebox.showinfo("Boleta", "Selecciona una fila de la boleta para eliminar.")
            return
        for s in sel:
            self.tree_boleta.delete(s)
        self.actualizar_resumen_boleta()

    def limpiar_boleta(self):
        if messagebox.askyesno("Confirmar", "¿Deseas limpiar todos los encuentros de la boleta?"):
            for s in self.tree_boleta.get_children():
                self.tree_boleta.delete(s)
            self.actualizar_resumen_boleta()

    # --- MÉTODOS AUXILIARES ---
    def obtener_equipos(self, competicion_id):
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT nombre FROM equipos WHERE competicion_id = ? ORDER BY nombre", (competicion_id,))
        eqs = [r[0] for r in cur.fetchall()]
        conn.close()
        return eqs

    def actualizar_combos(self):
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT id, nombre FROM competiciones ORDER BY id")
        rows = cur.fetchall()
        conn.close()

        lista = [f"{r[0]} - {r[1]}" for r in rows]
        self.combo_sync_liga["values"] = lista
        self.combo_ana_liga["values"] = lista
        self.combo_met_liga["values"] = lista
        self.combo_man_liga["values"] = lista

        if lista:
            if not self.combo_sync_liga.get():
                self.combo_sync_liga.current(0)
            if not self.combo_ana_liga.get():
                self.combo_ana_liga.current(0)
            if not self.combo_met_liga.get():
                self.combo_met_liga.current(0)
            if not self.combo_man_liga.get():
                self.combo_man_liga.current(0)

        self.al_cambiar_liga_analisis()
        self.al_cambiar_liga_manual()
        self.cargar_datos_pestana_metricas()

if __name__ == "__main__":
    root = tk.Tk()
    app = AppFutbolPro(root)
    root.mainloop()