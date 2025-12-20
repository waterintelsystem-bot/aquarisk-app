import streamlit as st
import pandas as pd
import re
import pdfplumber
import yfinance as yf
from fpdf import FPDF
from datetime import datetime
import io
import requests
import feedparser # Pour la veille RSS décrite dans votre texte
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

# --- 1. INITIALISATION MEMOIRE (Restauration) ---
def init_session():
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'ville': "Paris", 'pays': "France",
        'secteur': "Agroalimentaire (100%)",
        # Finance
        'ca': 0.0, 'res': 0.0, 'cap': 0.0,
        'valo_finale': 0.0, 'mode_valo': "PME (Bilan)",
        # Climat & GPS
        'lat': 48.8566, 'lon': 2.3522,
        'climat_calcule': False,
        'map_id': 0,
        # Inputs Risques
        'vol_eau': 50000.0, 'prix_eau': 4.5,
        'part_fournisseur_risk': 30.0, 'energie_conso': 100000.0,
        'reut_invest': False,
        # Scores détaillés (Méthodologie Bloomberg)
        'score_physique': 0.0, 'score_reglementaire': 0.0,
        'score_reputation': 0.0, 'score_resilience': 0.0,
        'score_global': 0.0,
        'var_amount': 0.0,
        # Data Externe
        'news': [], 'wiki_summary': "Pas de données.", 'weather_info': None
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- 2. BASE DE DONNEES (ARCHITECTURE SQL) ---
# Comme décrit dans votre fichier texte : Stockage structuré
def init_db():
    try:
        conn = sqlite3.connect('aquarisk.db')
        c = conn.cursor()
        # Table 1 : Audits (Données structurées)
        c.execute('''
            CREATE TABLE IF NOT EXISTS audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                entreprise TEXT,
                ville TEXT,
                pays TEXT,
                secteur TEXT,
                score_global REAL,
                risque_financier REAL,
                full_json TEXT
            )
        ''')
        # Table 2 : Veille (Actualités & RSS) - Pour alimenter le terminal
        c.execute('''
            CREATE TABLE IF NOT EXISTS veille (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_import TEXT,
                sujet TEXT,
                titre TEXT,
                lien TEXT,
                source TEXT
            )
        ''')
        conn.commit()
        conn.close()
    except: pass

def save_audit_to_db(data):
    init_db()
    try:
        conn = sqlite3.connect('aquarisk.db')
        c = conn.cursor()
        clean_data = {k: v for k, v in data.items() if k not in ['news', 'weather_info']}
        
        c.execute('''
            INSERT INTO audits (date, entreprise, ville, pays, secteur, score_global, risque_financier, full_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            data.get('ent_name'), data.get('ville'), data.get('pays'), data.get('secteur'),
            data.get('score_global'), data.get('var_amount'),
            json.dumps(clean_data, default=str)
        ))
        conn.commit()
        conn.close()
        return "✅ Audit enregistré dans le Terminal."
    except Exception as e: return f"❌ Erreur DB: {e}"

def load_history():
    init_db()
    try:
        conn = sqlite3.connect('aquarisk.db')
        df = pd.read_sql_query("SELECT id, date, entreprise, score_global, risque_financier FROM audits ORDER BY date DESC", conn)
        conn.close()
        return df
    except: return pd.DataFrame()

# --- 3. MOTEUR DE SCORING (METHODOLOGIE PONDEREE) ---
# Basé sur votre tableau de pondération 
def calculate_bloomberg_score(data, params):
    # 1. Risque Physique (40%) 
    # Basé sur GPS + Conso
    base_lat = 2.0 + (abs(data['lat']) / 50.0) 
    physique = min(max(base_lat, 1), 5) * 0.40
    
    # 2. Risque Réglementaire (30%) [cite: 421]
    # Basé sur investissement REUT et Pression légale
    if data['reut_invest']: reg = 1.0 # Bon élève
    else: reg = 4.0 + (params['pression_legale']/100.0)
    reg = min(reg, 5) * 0.30
    
    # 3. Risque Réputation (10%) [cite: 422]
    # Basé sur l'impact Image choisi
    rep = (params['risque_image'] / 4.0) # Normalisation approx
    rep = min(max(rep, 1), 5) * 0.10
    
    # 4. Résilience (20%) [cite: 424]
    # Inversement proportionnel à la dépendance fournisseur
    res = 1.0 + (data['part_fournisseur_risk'] / 20.0)
    res = min(res, 5) * 0.20
    
    # Score Global
    global_score = (physique + reg + rep + res) * (10/3.5) # Ajustement échelle 5
    return min(global_score, 5.0), physique, reg, rep, res

def calculate_financial_impact(data, score_global):
    # Formule simplifiée de votre méthodologie : Impact = Probabilité (Score) x Impact Financier
    vuln = data['valo_finale'] * 0.05 # 5% de la valo exposée par défaut
    impact = vuln * (score_global / 5.0)
    return impact

# --- 4. VEILLE AUTOMATISEE (RSS) ---
# Intègre la logique de flux RSS 
def fetch_automated_news(topic="Water Risk"):
    news_items = []
    try:
        # Recherche Google News RSS
        encoded_topic = urllib.parse.quote(topic)
        url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=fr&gl=FR&ceid=FR:fr"
        feed = feedparser.parse(url)
        
        # Sauvegarde en base (ETL léger)
        init_db()
        conn = sqlite3.connect('aquarisk.db')
        c = conn.cursor()
        
        for entry in feed.entries[:5]:
            item = {
                "title": entry.title,
                "link": entry.link,
                "date": entry.published if 'published' in entry else str(datetime.now())
            }
            news_items.append(item)
            # Insert pour historique
            c.execute("INSERT INTO veille (date_import, sujet, titre, lien, source) VALUES (?, ?, ?, ?, ?)", 
                      (datetime.now(), topic, item['title'], item['link'], 'GoogleRSS'))
        
        conn.commit()
        conn.close()
    except: pass
    return news_items

# --- 5. OUTILS EXTERNES & PDF ---
# (Code Yahoo, OCR, PDF optimisé conservé et nettoyé)
SECTEURS_LISTE = ["Agroalimentaire", "Chimie", "Energie", "Textile", "Semiconducteurs", "Mines", "Autre"]
HEADERS = {'User-Agent': 'AquaRisk/1.0'}

def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker); val = t.fast_info.market_cap
        return float(val or 0), t.info.get('shortName', ticker), t.info.get('sector', 'N/A'), ticker
    except: return 0.0, None, None, None

def run_ocr_scan(f): return {'found':False}, "OCR non activé" # Simplifié pour focus code

def create_static_map(lat, lon):
    try:
        m = StaticMap(400, 300)
        m.add_marker(CircleMarker((lon, lat), 'red', 10))
        img = m.render(zoom=10)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t:
            img.save(t.name); return t.name
    except: return None

def generate_pdf_report(data):
    # PDF Génération utilisant les Scores Pondérés
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20); pdf.cell(0, 15, "BLOOMBERG DE L'EAU - AUDIT", ln=1, align='C')
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Entreprise: {data.get('ent_name')}", ln=1)
    pdf.cell(0, 10, f"Score Global: {data.get('score_global', 0):.2f} / 5", ln=1)
    pdf.cell(0, 10, f"Risque Financier (VaR): -{data.get('var_amount', 0):,.0f} EUR", ln=1)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "Détail du Scoring (Pondéré)", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"1. Risque Physique (40%): {data.get('score_physique',0):.2f}", ln=1)
    pdf.cell(0, 8, f"2. Réglementaire (30%): {data.get('score_reglementaire',0):.2f}", ln=1)
    pdf.cell(0, 8, f"3. Réputation (10%): {data.get('score_reputation',0):.2f}", ln=1)
    pdf.cell(0, 8, f"4. Résilience (20%): {data.get('score_resilience',0):.2f}", ln=1)
    
    # Carte
    map_path = create_static_map(data.get('lat'), data.get('lon'))
    if map_path: pdf.image(map_path, x=10, w=100); os.remove(map_path)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')
    
