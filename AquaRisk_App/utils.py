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
    # Navigation & Identité
    if 'current_client_id' not in st.session_state: st.session_state['current_client_id'] = None
    if 'current_client_name' not in st.session_state: st.session_state['current_client_name'] = "Nouveau Client"
    if 'current_site_id' not in st.session_state: st.session_state['current_site_id'] = None
    if 'current_site_name' not in st.session_state: st.session_state['current_site_name'] = "Site Inconnu"
    
    # Données d'Analyse (Valeurs par défaut)
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'ville': "Paris", 'pays': "France", 'secteur': "Agroalimentaire (100%)",
        'lat': 48.8566, 'lon': 2.3522, 'climat_calcule': False, 'map_id': 0,
        'vol_eau': 50000.0, 'prix_eau': 4.5, 'part_fournisseur_risk': 30.0, 
        'energie_conso': 100000.0, 'reut_invest': False,
        'score_global': 0.0, 'var_amount': 0.0,
        'score_physique': 0.0, 'score_reglementaire': 0.0, 'score_reputation': 0.0, 'score_resilience': 0.0,
        'news': [], 'wiki_summary': "Pas de données.", 'weather_info': None,
        'valo_finale': 0.0, 'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'mode_valo': "PME (Bilan)"
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- 2. BASE DE DONNEES (Nouvelle Version v71) ---
DB_NAME = 'aquarisk_v71.db' # Changement de nom pour forcer une base propre

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Clients
    c.execute('''CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        secteur_activite TEXT,
        date_creation TEXT
    )''')
    # Sites
    c.execute('''CREATE TABLE IF NOT EXISTS sites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        name TEXT,
        pays TEXT,
        ville TEXT,
        lat REAL,
        lon REAL,
        activite_specifique TEXT,
        FOREIGN KEY(client_id) REFERENCES clients(id)
    )''')
    # Audits (Historique)
    c.execute('''CREATE TABLE IF NOT EXISTS audits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        site_id INTEGER,
        date TEXT,
        score_global REAL,
        inputs_json TEXT,
        FOREIGN KEY(site_id) REFERENCES sites(id)
    )''')
    # Veille (News)
    c.execute('''CREATE TABLE IF NOT EXISTS veille (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_import TEXT,
        sujet TEXT,
        titre TEXT,
        lien TEXT,
        source TEXT
    )''')
    conn.commit()
    conn.close()

# --- CRUD CLIENTS/SITES ---
def create_client(name, secteur):
    init_db()
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO clients (name, secteur_activite, date_creation) VALUES (?, ?, ?)", 
                 (name, secteur, datetime.now().strftime("%Y-%m-%d")))
        conn.commit(); cid = c.lastrowid; conn.close()
        return cid, "✅ Client créé."
    except: return None, "❌ Erreur (Existe déjà ?)"

def get_clients():
    init_db()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM clients ORDER BY name", conn)
    conn.close()
    return df

def create_site(client_id, name, pays, ville, lat, lon, activite):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO sites (client_id, name, pays, ville, lat, lon, activite_specifique) VALUES (?, ?, ?, ?, ?, ?, ?)",
             (client_id, name, pays, ville, lat, lon, activite))
    conn.commit(); conn.close()

def get_sites(client_id):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM sites WHERE client_id = ?", conn, params=(client_id,))
    conn.close()
    return df

def get_all_sites_consolidated():
    init_db()
    conn = sqlite3.connect(DB_NAME)
    query = "SELECT c.name as Client, s.name as Site, s.pays, s.activite_specifique, s.lat, s.lon FROM sites s JOIN clients c ON s.client_id = c.id"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def save_audit_snapshot(site_id, data):
    init_db()
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # On ne garde que les données simples pour le JSON
        clean = {k:v for k,v in data.items() if k not in ['news', 'weather_info', 'current_client_id']}
        c.execute("INSERT INTO audits (site_id, date, score_global, inputs_json) VALUES (?, ?, ?, ?)",
                 (site_id, datetime.now().strftime("%Y-%m-%d %H:%M"), data.get('score_global', 0), json.dumps(clean, default=str)))
        conn.commit(); conn.close()
        return "✅ Audit archivé."
    except Exception as e: return f"❌ Erreur DB: {e}"

# --- VEILLE RSS ---
def fetch_automated_news(topic="Water Risk"):
    news = []
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(topic)}&hl=fr&gl=FR&ceid=FR:fr"
        feed = feedparser.parse(url)
        init_db(); conn = sqlite3.connect(DB_NAME); c = conn.cursor()
        for e in feed.entries[:5]:
            item = {"title": e.title, "link": e.link, "date": e.published}
            news.append(item)
            c.execute("INSERT INTO veille (date_import, sujet, titre, lien, source) VALUES (?, ?, ?, ?, ?)", 
                     (datetime.now(), topic, e.title, e.link, 'GoogleRSS'))
        conn.commit(); conn.close()
    except: pass
    return news

# --- CALCULS & LOGIQUE METIER ---
SECTEURS = {
    "Agroalimentaire (100%)": 1.0, "Mines (90%)": 0.9, "Chimie (85%)": 0.85, 
    "Textile (80%)": 0.8, "Energie (75%)": 0.75, "Data Centers (70%)": 0.7, 
    "BTP (60%)": 0.6, "Automobile (55%)": 0.55, "Luxe (45%)": 0.45, "Santé (30%)": 0.3
}
SECTEURS_LISTE = list(SECTEURS.keys())
HEADERS = {'User-Agent': 'AquaRisk_App_v71'} # User-Agent spécifique pour éviter erreur 403

def calculate_dynamic_score(lat, lon):
    # Score basé sur la latitude + bruit stable
    base = 2.0 + (abs(lat) / 50.0)
    random.seed(int(lat*10000) + int(lon*10000))
    noise = random.uniform(-0.5, 1.0)
    s24 = min(max(base + noise, 1.2), 4.5)
    s30 = min(s24 * 1.3, 5.0)
    return s24, s30

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

# --- OUTILS EXTERNES (Yahoo, OCR, PDF) ---
def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker); val = t.fast_info.market_cap
        # Renvoie TOUJOURS 4 valeurs, même si vide
        return float(val or 0), t.info.get('shortName', ticker), t.info.get('sector', 'N/A'), ticker
    except: return 0.0, "Inconnu", "N/A", ticker

def run_ocr_scan(f): return {'found':False}, "OCR non activé"

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
    pdf.set_font("Arial", 'B', 20); pdf.cell(0, 15, "RAPPORT AUDIT EAU", ln=1, align='C')
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Site: {data.get('current_site_name')}", ln=1)
    pdf.cell(0, 10, f"Score: {data.get('score_global', 0):.2f}/5", ln=1)
    
    map_path = create_static_map(data.get('lat'), data.get('lon'))
    if map_path: pdf.image(map_path, x=10, w=100); os.remove(map_path)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')
    
