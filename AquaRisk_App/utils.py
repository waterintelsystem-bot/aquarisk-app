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

matplotlib.use('Agg')

# --- 1. INITIALISATION MEMOIRE ROBUSTE ---
def init_session():
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'ville': "Paris", 'pays': "France",
        'secteur': "Agroalimentaire (100%)",
        # Finance
        'ca': 0.0, 'res': 0.0, 'cap': 0.0,
        'valo_finale': 0.0, 'mode_valo': "PME (Bilan)",
        # Climat
        's24': 2.5, 's30': 3.0, 'var_amount': 0.0,
        'lat': 48.8566, 'lon': 2.3522,
        'climat_calcule': False,
        'map_id': 0,
        # Risques 360 (Inputs)
        'vol_eau': 50000.0, 'prix_eau': 4.5,
        'part_fournisseur_risk': 30.0, 'energie_conso': 100000.0,
        'reut_invest': False,
        # Risques 360 (Résultats pour PDF)
        'risks_360_dict': {}, 
        'risks_360_total': 0.0,
        # Data Externe
        'news': [], 'wiki_summary': "Pas de données.", 'weather_info': None
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

SECTEURS = {"Agroalimentaire (100%)": 1.0, "Chimie (85%)": 0.85, "Industrie (80%)": 0.8, "Énergie (70%)": 0.7, "BTP (60%)": 0.6, "Services (10%)": 0.1}
SECTEURS_LISTE = list(SECTEURS.keys())
HEADERS = {'User-Agent': 'AquaRisk/1.0'}

# --- 2. MOTEUR DE CALCUL VERIFIÉ ---
def calculate_dynamic_score(lat, lon):
    # Formule : Base + (Latitude/60) + Bruit stable
    base = 2.0 + (abs(lat) / 60.0)
    random.seed(int(lat*1000) + int(lon*1000)) # Seed stable par ville
    noise = random.uniform(-0.2, 0.5)
    s24 = min(max(base + noise, 1.5), 4.2)
    s30 = min(s24 * 1.25, 5.0) # Projection +25%
    return s24, s30

def calculate_360_risks(data, params):
    risks = {}
    
    # A. Coût Eau (Direct)
    # Formule : Volume * Prix * %Hausse
    delta_prix = data['prix_eau'] * (params['hausse_eau_pct'] / 100.0)
    risks['Coût Eau (Exploitation)'] = data['vol_eau'] * delta_prix

    # B. Supply Chain (Indirect)
    # Formule : CA * Part_Achats(40%) * Part_Risk * Impact_Geo
    achats_estimes = data['ca'] * 0.40
    part_exposee = achats_estimes * (data['part_fournisseur_risk'] / 100.0)
    risks['Supply Chain (Rupture)'] = part_exposee * (params['impact_geopolitique'] / 100.0)

    # C. Réglementaire (CAPEX forcé)
    # Formule : Si pas REUT -> Coût station épuration (1500€/m3_jour) * Proba
    if not data['reut_invest']:
        vol_jour = data['vol_eau'] / 300
        cout_mise_norme = vol_jour * 1500.0
        risks['Conformité (CAPEX forcé)'] = cout_mise_norme * (params['pression_legale'] / 100.0)
    else:
        risks['Conformité (CAPEX forcé)'] = 0.0

    # D. Image (Valo)
    # Formule : Valo * %Perte
    risks['Réputation (Impact Valo)'] = data['valo_finale'] * (params['risque_image'] / 100.0)

    # E. Énergie
    # Formule : (Conso * 15% lié à l'eau) * %HaussePrix
    risks['Énergie (Pompage/Traitement)'] = (data['energie_conso'] * 0.15) * (params['hausse_energie'] / 100.0)

    return risks, sum(risks.values())

def calculate_water_footprint(data):
    return data['vol_eau'] + (data['ca'] * 0.02) # Heuristique simple

# --- 3. CONNECTEURS ---
def get_wiki_summary(name):
    try:
        clean = re.sub(r'\s(SA|SAS|SARL|INC)', '', name, flags=re.IGNORECASE).strip()
        search = requests.get("https://fr.wikipedia.org/w/api.php", params={"action":"query","list":"search","srsearch":clean,"format":"json"}, headers=HEADERS, timeout=4).json()
        if not search.get('query',{}).get('search'): return "Pas de données Wiki."
        title = search['query']['search'][0]['title']
        r = requests.get(f"https://fr.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}", headers=HEADERS, timeout=4)
        return r.json().get('extract', "Pas de résumé.")
    except: return "Indisponible."

def get_company_news(name):
    items = []
    try:
        clean = re.sub(r'\s(SA|SAS|SARL)', '', name, flags=re.IGNORECASE).strip()
        rss = f"https://news.google.com/rss/search?q={urllib.parse.quote(clean + ' business')}&hl=fr&gl=FR&ceid=FR:fr"
        feed = feedparser.parse(rss)
        for e in feed.entries[:4]: items.append({"title": e.title[:80], "link": e.link})
    except: pass
    return items

def get_weather_data(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={"latitude": lat, "longitude": lon, "current_weather": "true"}, timeout=3)
        return r.json().get('current_weather') if r.status_code == 200 else None
    except: return None

def create_static_map(lat, lon):
    try:
        m = StaticMap(400, 300)
        m.add_marker(CircleMarker((lon, lat), 'red', 10))
        img = m.render(zoom=10)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t:
            img.save(t.name); return t.name
    except: return None

# --- 4. GENERATEUR PDF COMPLET ---
def generate_pdf_report(data):
    # Graphique Trajectoire
    chart_path = None
    try:
        fig, ax = plt.subplots(figsize=(6, 2.5))
        ax.plot(['2024', '2030'], [data.get('s24', 2.5), data.get('s30', 3.0)], 'r-o')
        ax.set_title("Trajectoire Risque"); ax.grid(True)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t:
            plt.savefig(t.name, format='png'); chart_path = t.name
        plt.close(fig)
    except: pass

    map_path = create_static_map(data.get('lat', 48.85), data.get('lon', 2.35))

    pdf = FPDF()
    pdf.add_page()
    
    # TITRE
    pdf.set_font("Arial", 'B', 20); pdf.cell(0, 15, "AUDIT AQUARISK 360", ln=1, align='C')
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, str(data.get('ent_name', 'Société')), ln=1, align='C')
    
    # SYNTHESE
    pdf.ln(5)
    pdf.set_font("Arial", '', 10)
    pdf.cell(95, 8, f"CA: {data.get('ca',0):,.0f} EUR", 1)
    pdf.cell(95, 8, f"Valo: {data.get('valo_finale',0):,.0f} EUR", 1, ln=1)
    pdf.cell(95, 8, f"Ville: {data.get('ville','?')}", 1)
    pdf.cell(95, 8, f"Risque Eau 2030: {data.get('s30',0):.2f}/5", 1, ln=1)

    # VISUELS
    pdf.ln(5)
    if map_path:
        try: pdf.image(map_path, x=10, w=90)
        except: pass
    if chart_path:
        try: pdf.image(chart_path, x=110, y=pdf.get_y(), w=90)
        except: pass
    pdf.ln(60) # Saut après images

    # TABLEAU RISQUES 360 (C'est ici que ça manquait)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, "SCENARIOS & IMPACTS FINANCIERS", ln=1)
    pdf.set_font("Arial", '', 10)
    
    # On récupère le dictionnaire sauvegardé
    risks = data.get('risks_360_dict', {})
    total = data.get('risks_360_total', 0)
    
    if risks:
        for k, v in risks.items():
            pdf.cell(140, 7, f"{k}", 1)
            pdf.cell(50, 7, f"-{v:,.0f} EUR", 1, ln=1)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(140, 7, "TOTAL RISQUE ESTIME", 1)
        pdf.cell(50, 7, f"-{total:,.0f} EUR", 1, ln=1)
    else:
        pdf.cell(0, 7, "Aucune simulation de risque effectuée (Voir onglet Risques 360).", 1, ln=1)

    # SOURCES
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, "SOURCES & CONTEXTE", ln=1)
    pdf.set_font("Arial", '', 9)
    pdf.multi_cell(0, 5, f"Wiki: {str(data.get('wiki_summary',''))[:1000]}")
    pdf.ln(5)
    for n in data.get('news', []):
        pdf.cell(0, 5, f"> {n['title']}", ln=1)

    # Nettoyage
    if chart_path and os.path.exists(chart_path): os.remove(chart_path)
    if map_path and os.path.exists(map_path): os.remove(map_path)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')
    
