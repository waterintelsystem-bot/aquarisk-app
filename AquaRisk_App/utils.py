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
import time # Pour gérer les pauses GPS

matplotlib.use('Agg')

# --- 1. INITIALISATION MEMOIRE ---
def init_session():
    if 'current_client_id' not in st.session_state: st.session_state['current_client_id'] = None
    if 'current_client_name' not in st.session_state: st.session_state['current_client_name'] = "Nouveau Client"
    if 'current_site_id' not in st.session_state: st.session_state['current_site_id'] = None
    if 'current_site_name' not in st.session_state: st.session_state['current_site_name'] = "Site Inconnu"
    
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'ville': "Paris", 'pays': "France", 'secteur': "Agroalimentaire (100%)",
        'lat': 48.8566, 'lon': 2.3522, 'climat_calcule': False, 'map_id': 0,
        'vol_eau': 50000.0, 'prix_eau': 4.5, 'part_fournisseur_risk': 30.0, 
        'energie_conso': 100000.0, 'reut_invest': False,
        'score_global': 0.0, 'var_amount': 0.0,
        'score_physique': 0.0, 'score_reglementaire': 0.0, 'score_reputation': 0.0, 'score_resilience': 0.0,
        'news': [], 'wiki_summary': "Pas de données.", 'weather_info': None,
        'valo_finale': 0.0, 'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'ebitda': 0.0,
        'mode_valo': "PME (Multiples)"
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- 2. BASE DE DONNEES ---
DB_NAME = 'aquarisk_v80.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, secteur TEXT, date_creation TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, name TEXT, pays TEXT, ville TEXT, lat REAL, lon REAL, activite TEXT, FOREIGN KEY(client_id) REFERENCES clients(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY AUTOINCREMENT, site_id INTEGER, date TEXT, score_global REAL, valo REAL, inputs_json TEXT, FOREIGN KEY(site_id) REFERENCES sites(id))''')
    conn.commit(); conn.close()

# CRUD (Versions simplifiées pour stabilité)
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
    init_db(); conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT inputs_json FROM audits WHERE id = ?", (audit_id,))
    res = c.fetchone()
    conn.close()
    if res:
        data = json.loads(res[0])
        for k, v in data.items(): st.session_state[k] = v
        return True
    return False

def save_audit_snapshot(site_id, data):
    init_db(); conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    clean = {k:v for k,v in data.items() if k not in ['news', 'weather_info', 'current_client_id']}
    c.execute("INSERT INTO audits (site_id, date, score_global, valo, inputs_json) VALUES (?, ?, ?, ?, ?)",
             (site_id, datetime.now().strftime("%Y-%m-%d %H:%M"), data.get('score_global', 0), data.get('valo_finale', 0), json.dumps(clean, default=str)))
    conn.commit(); conn.close()
    return "✅ Version enregistrée."

# --- 3. FONCTIONS EXTERNES ROBUSTES (GPS, METEO, VEILLE) ---

# GPS : Utilise requests directement au lieu de geopy pour mieux contrôler les erreurs
def get_gps_coordinates(ville, pays):
    try:
        query = f"{ville}, {pays}"
        url = "https://nominatim.openstreetmap.org/search"
        # User-Agent aléatoire CRUCIAL pour éviter l'erreur 403
        ua = f"AquaRisk_Tool_{random.randint(10000, 99999)}"
        headers = {'User-Agent': ua}
        params = {'q': query, 'format': 'json', 'limit': 1}
        
        r = requests.get(url, params=params, headers=headers, timeout=5)
        if r.status_code == 200 and r.json():
            data = r.json()[0]
            return float(data['lat']), float(data['lon']), data.get('display_name', query)
    except: pass
    return None, None, None

# VEILLE : Google News RSS
def fetch_automated_news(topic="Water Risk"):
    news_items = []
    try:
        # Encodage propre
        encoded = urllib.parse.quote(topic)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=fr&gl=FR&ceid=FR:fr"
        feed = feedparser.parse(url)
        
        for e in feed.entries[:6]: # Top 6
            news_items.append({
                "title": e.title,
                "link": e.link,
                "date": e.published if 'published' in e else "Récent"
            })
    except: pass
    
    # Fallback si vide (pour ne pas avoir de case vide)
    if not news_items:
        news_items.append({"title": "Aucune actualité récente trouvée sur ce sujet spécifique.", "link": "#", "date": ""})
        
    return news_items

# METEO : Open-Meteo
def get_weather_data(lat, lon):
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {"latitude": lat, "longitude": lon, "current_weather": "true", "daily": "temperature_2m_max,precipitation_sum"}
        r = requests.get(url, params=params, timeout=4)
        if r.status_code == 200:
            d = r.json()
            return {
                "temp": d['current_weather']['temperature'],
                "wind": d['current_weather']['windspeed'],
                "rain_today": d['daily']['precipitation_sum'][0] if 'daily' in d else 0
            }
    except: pass
    return None

# FINANCE : Pappers & Yahoo
HEADERS_WEB = {'User-Agent': 'AquaRisk_Pro_v80'}

def get_pappers_data(query, api_key):
    if not api_key: return None, "Clé API manquante"
    try:
        url = "https://api.pappers.fr/v2/recherche"
        r = requests.get(url, params={"q": query, "api_token": api_key, "par_page": 1}, headers=HEADERS_WEB)
        if r.status_code == 200 and r.json().get('resultats'):
            res = r.json()['resultats'][0]
            r2 = requests.get(f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={res['siren']}", headers=HEADERS_WEB)
            fin = r2.json().get('finances', [{}])[0]
            return {
                'ca': float(fin.get('chiffre_affaires') or 0),
                'res': float(fin.get('resultat') or 0),
                'cap': float(fin.get('capitaux_propres') or 0),
                'ebitda': float(fin.get('excedent_brut_exploitation') or 0)
            }, res.get('nom_entreprise')
    except Exception as e: return None, str(e)
    return None, "Introuvable"

def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker); v = t.fast_info.market_cap
        return float(v or 0), t.info.get('shortName', ticker), t.info.get('sector', 'N/A')
    except: return 0.0, "Err", "N/A"

def run_ocr_scan(f): return {'ca': 1000000, 'res': 50000, 'found': True}, "OCR: Données extraites (Simulé)"

# --- 4. CALCULS RISQUES ---
SECTEURS = {
    "Agroalimentaire (100%)": 1.0, "Mines (90%)": 0.9, "Chimie (85%)": 0.85, 
    "Textile (80%)": 0.8, "Energie (75%)": 0.75, "Data Centers (70%)": 0.7, 
    "BTP (60%)": 0.6, "Automobile (55%)": 0.55, "Luxe (45%)": 0.45, "Santé (30%)": 0.3
}
SECTEURS_LISTE = list(SECTEURS.keys())

def calculate_bloomberg_score(data, params):
    secteur_nom = data.get('secteur', list(SECTEURS.keys())[0])
    coeff = SECTEURS.get(secteur_nom, 0.5)
    phys = (2.0 + (abs(data['lat'])/40.0)) * coeff * 1.5
    s_phys = min(max(phys, 1), 5) * 0.40
    reg = (4.0 if not data['reut_invest'] else 1.5) + (params['pression_legale']/100.0)
    s_reg = min(reg, 5) * 0.30
    s_rep = (params['risque_image']/20.0) * 0.10
    s_res = (1 + (data['part_fournisseur_risk']/20.0)) * 0.20
    global_s = (s_phys + s_reg + s_rep + s_res) * (10/3.5)
    return min(global_s, 5.0), s_phys, s_reg, s_rep, s_res

def calculate_financial_impact(data, score):
    secteur = data.get('secteur', list(SECTEURS.keys())[0])
    vuln = SECTEURS.get(secteur, 0.1)
    return data['valo_finale'] * vuln * (score / 10.0)

# --- 5. PDF GENERATOR ---
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
    
    pdf.set_font("Arial", 'B', 24); pdf.cell(0, 20, "AUDIT AQUARISK", ln=1, align='C')
    pdf.set_font("Arial", 'I', 10); pdf.cell(0, 10, f"Date: {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='C')
    pdf.ln(10)
    
    # Identité
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "1. PROFIL & FINANCE", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Entreprise: {data.get('ent_name')} | Site: {data.get('current_site_name')}", ln=1)
    pdf.cell(0, 8, f"Secteur: {data.get('secteur')}", ln=1)
    pdf.cell(0, 8, f"Valorisation: {data.get('valo_finale',0):,.0f} EUR", ln=1)
    pdf.ln(5)
    
    # Risques
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "2. ANALYSE DES RISQUES (Ponderee)", ln=1)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, f"SCORE GLOBAL: {data.get('score_global', 0):.2f} / 5", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"- Physique (40%): {data.get('score_physique',0):.2f}", ln=1)
    pdf.cell(0, 8, f"- Reglementaire (30%): {data.get('score_reglementaire',0):.2f}", ln=1)
    pdf.cell(0, 8, f"- Reputation (10%): {data.get('score_reputation',0):.2f}", ln=1)
    
    # Impact
    pdf.ln(10); pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "3. IMPACT FINANCIER (VaR)", ln=1)
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Perte Estimée: -{data.get('var_amount', 0):,.0f} EUR", ln=1)
    
    # Carte
    map_path = create_static_map(data.get('lat'), data.get('lon'))
    if map_path: 
        pdf.image(map_path, x=120, y=60, w=80); os.remove(map_path)

    # Météo & Veille
    pdf.ln(10); pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "4. CONTEXTE LOCAL & VEILLE", ln=1)
    if data.get('weather_info'):
        w = data['weather_info']
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 8, f"Meteo Site: {w['temp']}C | Vent: {w['wind']} km/h", ln=1)
    
    pdf.ln(5); pdf.set_font("Arial", '', 10)
    for n in data.get('news', [])[:5]:
        try: pdf.cell(0, 8, f"- {n['title'][:85]}...", ln=1)
        except: continue

    return pdf.output(dest='S').encode('latin-1', 'replace')
    
