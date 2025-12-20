import streamlit as st
import pandas as pd
import re
import pdfplumber
import yfinance as yf
from fpdf import FPDF
from datetime import datetime
import io
import requests
import feedparser
import xlsxwriter
import matplotlib.pyplot as plt
import matplotlib
import tempfile
import os
import random
import urllib.parse
from staticmap import StaticMap, CircleMarker
import sqlite3
import json

matplotlib.use('Agg')

# --- 1. INITIALISATION MEMOIRE ---
def init_session():
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'ville': "Paris", 'pays': "France",
        'secteur': "Agroalimentaire (Transformation) (65%)", # Valeur par défaut mise à jour
        # Finance
        'ca': 0.0, 'res': 0.0, 'cap': 0.0,
        'valo_finale': 0.0, 'mode_valo': "PME (Bilan)",
        # Climat
        'lat': 48.8566, 'lon': 2.3522,
        'climat_calcule': False,
        'map_id': 0,
        # Risques 360
        'vol_eau': 50000.0, 'prix_eau': 4.5,
        'part_fournisseur_risk': 30.0, 'energie_conso': 100000.0,
        'reut_invest': False,
        # Scores
        'score_global': 0.0, 'var_amount': 0.0,
        'score_physique': 0.0, 'score_reglementaire': 0.0,
        'score_reputation': 0.0, 'score_resilience': 0.0,
        # Data
        'news': [], 'wiki_summary': "Pas de données.", 'weather_info': None
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- 2. MATRICE SECTORIELLE DETAILLÉE ---
# Format : "Nom du Secteur (Risque%)" : Coefficient (0.0 à 1.0)
SECTEURS = {
    # --- ZONE CRITIQUE (80-100%) ---
    "Agriculture / Irrigation (100%)": 1.0,
    "Aquaculture / Pêche (100%)": 1.0,
    "Eaux en bouteille / Boissons (95%)": 0.95,
    "Mines & Extraction (Minerais) (90%)": 0.9,
    "Papier & Pâte à papier (90%)": 0.9,
    "Semi-conducteurs / Puces (High-Tech) (90%)": 0.9,
    "Textile / Tannerie / Cuir (85%)": 0.85,
    "Chimie de base / Pétrochimie (85%)": 0.85,
    "Énergie Thermique (Charbon/Gaz) (80%)": 0.8,
    "Énergie Nucléaire (80%)": 0.8,
    "Métallurgie / Sidérurgie (80%)": 0.8,

    # --- ZONE HAUTE (60-79%) ---
    "Raffinage Pétrolier (75%)": 0.75,
    "Data Centers / Cloud (Refroidissement) (70%)": 0.7,
    "Agroalimentaire (Transformation) (65%)": 0.65,
    "Matériaux Construction (Ciment/Béton) (65%)": 0.65,
    "Pharmaceutique / Biotech (60%)": 0.6,
    "Gestion des Déchets / Recyclage (60%)": 0.6,
    "Hôtellerie / Tourisme (Zones arides) (60%)": 0.6,

    # --- ZONE MOYENNE (40-59%) ---
    "Automobile (Construction) (55%)": 0.55,
    "Cosmétiques / Luxe (50%)": 0.5,
    "Transport Maritime (50%)": 0.5,
    "Nettoyage Industriel (45%)": 0.45,
    "Hôtellerie / Tourisme (Urbain) (45%)": 0.45,
    "Immobilier (Construction) (45%)": 0.45,
    "Grande Distribution / Retail (40%)": 0.4,

    # --- ZONE FAIBLE (20-39%) ---
    "Immobilier (Exploitation/Bureaux) (35%)": 0.35,
    "Logistique / Entrepôts (30%)": 0.3,
    "Électronique Grand Public (Assemblage) (30%)": 0.3,
    "Santé / Hôpitaux (30%)": 0.3,
    "Télécoms (Réseau) (25%)": 0.25,
    "Éducation / Universités (20%)": 0.2,

    # --- ZONE TRES FAIBLE (0-19%) ---
    "Banque / Assurance / Finance (15%)": 0.15,
    "Médias / Publicité (10%)": 0.1,
    "Services Informatiques / Logiciel (10%)": 0.1,
    "Consulting / Audit / Juridique (5%)": 0.05
}
SECTEURS_LISTE = list(SECTEURS.keys())
HEADERS = {'User-Agent': 'AquaRisk/1.0'}

# --- 3. BASE DE DONNEES & ETL ---
def init_db():
    try:
        conn = sqlite3.connect('aquarisk.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, entreprise TEXT, secteur TEXT, score_global REAL, risque_financier REAL, full_json TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS veille (id INTEGER PRIMARY KEY AUTOINCREMENT, date_import TEXT, sujet TEXT, titre TEXT, lien TEXT, source TEXT)''')
        conn.commit(); conn.close()
    except: pass

def save_audit_to_db(data):
    init_db()
    try:
        conn = sqlite3.connect('aquarisk.db')
        c = conn.cursor()
        clean = {k: v for k, v in data.items() if k not in ['news', 'weather_info']}
        c.execute('INSERT INTO audits (date, entreprise, secteur, score_global, risque_financier, full_json) VALUES (?, ?, ?, ?, ?, ?)', 
                 (datetime.now().strftime("%Y-%m-%d"), data.get('ent_name'), data.get('secteur'), data.get('score_global'), data.get('var_amount'), json.dumps(clean, default=str)))
        conn.commit(); conn.close()
        return "✅ Audit enregistré."
    except Exception as e: return f"❌ Erreur: {e}"

def load_history():
    init_db()
    try:
        conn = sqlite3.connect('aquarisk.db')
        df = pd.read_sql_query("SELECT date, entreprise, secteur, score_global, risque_financier FROM audits ORDER BY date DESC", conn)
        conn.close(); return df
    except: return pd.DataFrame()

# --- 4. VEILLE AUTOMATISEE ---
def fetch_automated_news(topic="Water Risk"):
    news = []
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(topic)}&hl=fr&gl=FR&ceid=FR:fr"
        feed = feedparser.parse(url)
        init_db(); conn = sqlite3.connect('aquarisk.db'); c = conn.cursor()
        for e in feed.entries[:6]:
            item = {"title": e.title, "link": e.link, "date": e.published}
            news.append(item)
            c.execute("INSERT INTO veille (date_import, sujet, titre, lien, source) VALUES (?, ?, ?, ?, ?)", (datetime.now(), topic, e.title, e.link, 'GoogleRSS'))
        conn.commit(); conn.close()
    except: pass
    return news

# --- 5. MOTEUR DE CALCUL PONDERÉ ---
def calculate_bloomberg_score(data, params):
    # Récupération du coefficient secteur (ex: 0.95 pour Semi-conducteurs)
    secteur_nom = data.get('secteur', list(SECTEURS.keys())[0])
    coeff_secteur = SECTEURS.get(secteur_nom, 0.5)

    # 1. Physique (40%) : Latitude + Secteur (Si secteur gourmand, physique compte plus)
    phys = (2.0 + (abs(data['lat'])/40.0)) * coeff_secteur * 1.5
    s_phys = min(max(phys, 1), 5) * 0.40
    
    # 2. Réglementaire (30%)
    reg = 4.0 if not data['reut_invest'] else 1.5
    reg += (params['pression_legale']/100.0)
    s_reg = min(reg, 5) * 0.30
    
    # 3. Réputation (10%)
    s_rep = (params['risque_image']/20.0) * 0.10
    
    # 4. Résilience (20%)
    s_res = (1 + (data['part_fournisseur_risk']/20.0)) * 0.20
    
    global_score = (s_phys + s_reg + s_rep + s_res) * (10/3.5)
    return min(global_score, 5.0), s_phys, s_reg, s_rep, s_res

def calculate_financial_impact(data, score):
    # VaR = Valo * %ExpositionSecteur * (Score/5)
    secteur_nom = data.get('secteur', list(SECTEURS.keys())[0])
    vuln_secteur = SECTEURS.get(secteur_nom, 0.1) # 10% min
    impact = data['valo_finale'] * vuln_secteur * (score / 10.0) # Impact conservateur
    return impact

# --- 6. OUTILS EXTERNES ---
def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker); val = t.fast_info.market_cap
        return float(val or 0), t.info.get('shortName', ticker), t.info.get('sector', 'N/A'), ticker
    except: return 0.0, None, None, None

def run_ocr_scan(f): return {'found':False}, "OCR Désactivé"

def get_wiki_summary(n): return "Données Wiki non disponibles" # Simplification pour stabilité

def get_weather_data(lat, lon):
    try: return requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true").json().get('current_weather')
    except: return None

def create_static_map(lat, lon):
    try:
        m = StaticMap(400, 300); m.add_marker(CircleMarker((lon, lat), 'red', 10))
        img = m.render(zoom=10)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t:
            img.save(t.name); return t.name
    except: return None

# --- 7. PDF ---
def generate_pdf_report(data):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20); pdf.cell(0, 15, "AUDIT AQUARISK", ln=1, align='C')
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Entreprise: {data.get('ent_name')}", ln=1)
    pdf.cell(0, 10, f"Secteur: {data.get('secteur')}", ln=1)
    pdf.cell(0, 10, f"Score Global: {data.get('score_global', 0):.2f} / 5", ln=1)
    pdf.cell(0, 10, f"Risque Financier: -{data.get('var_amount', 0):,.0f} EUR", ln=1)
    
    map_path = create_static_map(data.get('lat'), data.get('lon'))
    if map_path: pdf.image(map_path, x=10, w=100); os.remove(map_path)
    
    pdf.ln(10); pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "Veille & Actualites", ln=1)
    pdf.set_font("Arial", '', 10)
    for n in data.get('news', [])[:5]:
        try: pdf.cell(0, 8, f"- {n['title'][:90]}...", ln=1)
        except: continue
        
    return pdf.output(dest='S').encode('latin-1', 'replace')
    
