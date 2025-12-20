import streamlit as st
import pandas as pd
import sqlite3
import json
import os
import yfinance as yf
import requests
import feedparser
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib
from fpdf import FPDF
from staticmap import StaticMap, CircleMarker
import tempfile
import urllib.parse
import re
import random

matplotlib.use('Agg')

# --- 1. INITIALISATION MEMOIRE ---
def init_session():
    # Navigation
    if 'current_client_id' not in st.session_state: st.session_state['current_client_id'] = None
    if 'current_client_name' not in st.session_state: st.session_state['current_client_name'] = "Nouveau Client"
    if 'current_site_id' not in st.session_state: st.session_state['current_site_id'] = None
    if 'current_site_name' not in st.session_state: st.session_state['current_site_name'] = "Site Inconnu"
    
    # Données Analyse
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'ville': "Paris", 'pays': "France", 'secteur': "Agroalimentaire (100%)",
        'lat': 48.8566, 'lon': 2.3522, 'climat_calcule': False, 'map_id': 0,
        # Risques
        'vol_eau': 50000.0, 'prix_eau': 4.5, 'part_fournisseur_risk': 30.0, 
        'energie_conso': 100000.0, 'reut_invest': False,
        # Scores
        'score_global': 0.0, 'var_amount': 0.0,
        'score_physique': 0.0, 'score_reglementaire': 0.0, 'score_reputation': 0.0, 'score_resilience': 0.0,
        # Data
        'news': [], 'wiki_summary': "Pas de données.", 'weather_info': None,
        # Finance Avancée
        'valo_finale': 0.0, 'ca': 0.0, 'res': 0.0, 'ebitda': 0.0, 'cap': 0.0, 'dette': 0.0,
        'mode_valo': "PME (Multiples)"
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- 2. BASE DE DONNEES & CHARGEMENT ---
DB_NAME = 'aquarisk_v75.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, secteur TEXT, date_creation TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, name TEXT, pays TEXT, ville TEXT, lat REAL, lon REAL, activite TEXT, FOREIGN KEY(client_id) REFERENCES clients(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY AUTOINCREMENT, site_id INTEGER, date TEXT, score_global REAL, valo REAL, inputs_json TEXT, FOREIGN KEY(site_id) REFERENCES sites(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS veille (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, sujet TEXT, titre TEXT, lien TEXT, source TEXT)''')
    conn.commit(); conn.close()

# ... (Fonctions CRUD Clients/Sites identiques V71 - je les abrège pour la place) ...
def create_client(n, s): 
    init_db(); conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    try: c.execute("INSERT INTO clients (name, secteur, date_creation) VALUES (?, ?, ?)", (n, s, datetime.now().strftime("%Y-%m-%d"))); cid = c.lastrowid; conn.commit(); return cid, "OK"
    except: return None, "Erreur"
    finally: conn.close()

def get_clients(): 
    init_db(); conn = sqlite3.connect(DB_NAME); df = pd.read_sql("SELECT * FROM clients ORDER BY name", conn); conn.close(); return df

def create_site(cid, n, p, v, lat, lon, act):
    init_db(); conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO sites (client_id, name, pays, ville, lat, lon, activite) VALUES (?, ?, ?, ?, ?, ?, ?)", (cid, n, p, v, lat, lon, act))
    conn.commit(); conn.close()

def get_sites(cid):
    init_db(); conn = sqlite3.connect(DB_NAME); df = pd.read_sql("SELECT * FROM sites WHERE client_id = ?", conn, params=(cid,)); conn.close(); return df

def get_site_history(site_id):
    init_db(); conn = sqlite3.connect(DB_NAME); 
    df = pd.read_sql("SELECT id, date, score_global, valo FROM audits WHERE site_id = ? ORDER BY date DESC", conn, params=(site_id,)); conn.close(); return df

def load_audit_to_session(audit_id):
    """Charge un vieil audit dans la mémoire vive"""
    init_db(); conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT inputs_json FROM audits WHERE id = ?", (audit_id,))
    res = c.fetchone()
    conn.close()
    if res:
        data = json.loads(res[0])
        # On met à jour la session avec ces vieilles données
        for k, v in data.items():
            st.session_state[k] = v
        return True
    return False

def save_audit_snapshot(site_id, data):
    init_db(); conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    clean = {k:v for k,v in data.items() if k not in ['news', 'weather_info', 'current_client_id']}
    c.execute("INSERT INTO audits (site_id, date, score_global, valo, inputs_json) VALUES (?, ?, ?, ?, ?)",
             (site_id, datetime.now().strftime("%Y-%m-%d %H:%M"), data.get('score_global', 0), data.get('valo_finale', 0), json.dumps(clean, default=str)))
    conn.commit(); conn.close()
    return "✅ Version enregistrée."

# --- 3. APIS & OUTILS FINANCE (PAPPERS, YAHOO) ---
HEADERS = {'User-Agent': 'AquaRisk_Pro_v75'}

def get_pappers_data(query, api_key):
    if not api_key: return None, "Clé API manquante"
    try:
        # Recherche SIREN ou Nom
        url = "https://api.pappers.fr/v2/recherche"
        params = {"q": query, "api_token": api_key, "par_page": 1}
        r = requests.get(url, params=params, headers=HEADERS, timeout=5)
        if r.status_code == 200 and r.json().get('resultats'):
            res = r.json()['resultats'][0]
            siren = res['siren']
            # Détails entreprise
            r2 = requests.get(f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={siren}", headers=HEADERS)
            d = r2.json()
            fin = d.get('finances', [{}])[0]
            stats = {
                'ca': float(fin.get('chiffre_affaires') or 0),
                'res': float(fin.get('resultat') or 0),
                'cap': float(fin.get('capitaux_propres') or 0),
                'ebitda': float(fin.get('excedent_brut_exploitation') or 0)
            }
            return stats, d.get('nom_entreprise', 'Inconnu')
    except Exception as e: return None, str(e)
    return None, "Introuvable"

def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker); v = t.fast_info.market_cap
        return float(v or 0), t.info.get('shortName', ticker), t.info.get('sector', 'N/A')
    except: return 0.0, "Err", "N/A"

def run_ocr_scan(file_obj):
    # Simulation OCR pour l'exemple (pdfplumber lourd)
    return {'ca': 1000000, 'res': 50000, 'found': True}, "OCR: Données extraites (Simulation)"

# --- 4. CALCULS RISQUES ---
SECTEURS = {
    "Agroalimentaire (100%)": 1.0, "Mines (90%)": 0.9, "Chimie (85%)": 0.85, 
    "Textile (80%)": 0.8, "Energie (75%)": 0.75, "Data Centers (70%)": 0.7, 
    "BTP (60%)": 0.6, "Automobile (55%)": 0.55, "Luxe (45%)": 0.45, "Santé (30%)": 0.3
}
SECTEURS_LISTE = list(SECTEURS.keys())

def calculate_bloomberg_score(data, params):
    # Logique Bloomberg Eau
    secteur_nom = data.get('secteur', list(SECTEURS.keys())[0])
    coeff = SECTEURS.get(secteur_nom, 0.5)
    
    # 1. Physique (40%)
    phys = (2.0 + (abs(data['lat'])/40.0)) * coeff * 1.5
    s_phys = min(max(phys, 1), 5) * 0.40
    
    # 2. Réglementaire (30%)
    reg = (4.0 if not data['reut_invest'] else 1.5) + (params['pression_legale']/100.0)
    s_reg = min(reg, 5) * 0.30
    
    # 3. Réputation (10%)
    s_rep = (params['risque_image']/20.0) * 0.10
    
    # 4. Résilience (20%)
    s_res = (1 + (data['part_fournisseur_risk']/20.0)) * 0.20
    
    global_s = (s_phys + s_reg + s_rep + s_res) * (10/3.5)
    return min(global_s, 5.0), s_phys, s_reg, s_rep, s_res

def calculate_financial_impact(data, score):
    # VaR dynamique
    secteur = data.get('secteur', list(SECTEURS.keys())[0])
    vuln = SECTEURS.get(secteur, 0.1)
    return data['valo_finale'] * vuln * (score / 10.0)

# --- 5. PDF GENERATOR COMPLET ---
def create_static_map(lat, lon):
    try:
        m = StaticMap(400, 300)
        m.add_marker(CircleMarker((lon, lat), 'red', 10))
        img = m.render(zoom=10)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t:
            img.save(t.name); return t.name
    except: return None

def generate_pdf_report(data):
    pdf = FPDF()
    pdf.add_page()
    
    # En-tête
    pdf.set_font("Arial", 'B', 24); pdf.cell(0, 20, "RAPPORT D'AUDIT EAU", ln=1, align='C')
    pdf.set_font("Arial", 'I', 10); pdf.cell(0, 10, f"Généré le {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='C')
    pdf.ln(10)
    
    # 1. Identité & Finance
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "1. IDENTITE & FINANCE", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Entreprise: {data.get('ent_name')} (Site: {data.get('current_site_name')})", ln=1)
    pdf.cell(0, 8, f"Secteur: {data.get('secteur')}", ln=1)
    pdf.cell(0, 8, f"Valorisation Retenue: {data.get('valo_finale',0):,.0f} EUR", ln=1)
    pdf.ln(5)
    
    # 2. Scoring
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "2. ANALYSE DES RISQUES (Scoring Bloomberg)", ln=1)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, f"SCORE GLOBAL: {data.get('score_global', 0):.2f} / 5", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"- Risque Physique (40%): {data.get('score_physique',0):.2f}", ln=1)
    pdf.cell(0, 8, f"- Risque Réglementaire (30%): {data.get('score_reglementaire',0):.2f}", ln=1)
    pdf.cell(0, 8, f"- Réputation (10%): {data.get('score_reputation',0):.2f}", ln=1)
    pdf.cell(0, 8, f"- Résilience (20%): {data.get('score_resilience',0):.2f}", ln=1)
    pdf.ln(5)
    
    # Carte
    map_path = create_static_map(data.get('lat'), data.get('lon'))
    if map_path: 
        pdf.image(map_path, x=120, y=60, w=80)
        os.remove(map_path)

    # 3. Impact
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "3. IMPACT FINANCIER (VaR)", ln=1)
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Perte Potentielle Estimée: -{data.get('var_amount', 0):,.0f} EUR", ln=1)
    
    # 4. Veille
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "4. VEILLE & ACTUALITES", ln=1)
    pdf.set_font("Arial", '', 10)
    for n in data.get('news', [])[:5]:
        try: pdf.cell(0, 8, f"- {n['title'][:90]}...", ln=1)
        except: continue

    return pdf.output(dest='S').encode('latin-1', 'replace')
    
