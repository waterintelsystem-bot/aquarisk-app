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

# --- 1. INITIALISATION MEMOIRE ---
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
        # Risques 360
        'vol_eau': 50000.0, 'prix_eau': 4.5,
        'part_fournisseur_risk': 30.0, 'energie_conso': 100000.0,
        'reut_invest': False,
        'risks_360_dict': {}, 'risks_360_total': 0.0,
        # Data
        'news': [], 'wiki_summary': "Pas de données.", 'weather_info': None
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- 2. LISTE COMPLETE DES SECTEURS (NOUVEAU) ---
SECTEURS = {
    # TRES HAUT RISQUE (0.9 - 1.0)
    "Agroalimentaire / Boissons (100%)": 1.0,
    "Agriculture / Élevage (100%)": 1.0,
    "Semi-conducteurs / Puces (95%)": 0.95,
    "Mines & Extraction (90%)": 0.9,
    "Papier & Carton (90%)": 0.9,
    
    # HAUT RISQUE (0.7 - 0.85)
    "Chimie / Pétrochimie (85%)": 0.85,
    "Textile / Cuir / Habillement (80%)": 0.8,
    "Industrie Lourde / Métallurgie (80%)": 0.8,
    "Énergie (Thermique/Nucléaire) (75%)": 0.75,
    "Data Centers / Cloud (70%)": 0.7,
    "Matériaux de Construction (Ciment) (70%)": 0.7,
    
    # RISQUE MOYEN (0.4 - 0.6)
    "Pharmaceutique / Biotech (60%)": 0.6,
    "BTP / Construction (60%)": 0.6,
    "Automobile (Fabrication) (55%)": 0.55,
    "Tourisme / Hôtellerie / Loisirs (50%)": 0.5,
    "Transport / Logistique (50%)": 0.5,
    "Luxe / Cosmétiques (45%)": 0.45,
    "Commerce de Détail / Retail (40%)": 0.4,
    "Immobilier (Exploitation) (40%)": 0.4,
    
    # RISQUE FAIBLE (0.1 - 0.3)
    "Électronique Grand Public (30%)": 0.3,
    "Santé / Hôpitaux (30%)": 0.3,
    "Télécoms (Réseau) (25%)": 0.25,
    "Banque / Assurance (15%)": 0.15,
    "Services / Logiciel / IT (10%)": 0.1,
    "Consulting / Audit (5%)": 0.05,
    "Autre (50%)": 0.5
}
SECTEURS_LISTE = list(SECTEURS.keys())
HEADERS = {'User-Agent': 'AquaRisk/1.0'}

# --- 3. CALCULS ---
def calculate_dynamic_score(lat, lon):
    base = 2.0 + (abs(lat) / 60.0)
    random.seed(int(lat*1000) + int(lon*1000))
    noise = random.uniform(-0.2, 0.5)
    s24 = min(max(base + noise, 1.5), 4.2)
    s30 = min(s24 * 1.25, 5.0)
    return s24, s30

def calculate_360_risks(data, params):
    risks = {}
    delta_prix = data['prix_eau'] * (params['hausse_eau_pct'] / 100.0)
    risks['Coût Eau (Exploitation)'] = data['vol_eau'] * delta_prix

    achats = data['ca'] * 0.40
    part_exposee = achats * (data['part_fournisseur_risk'] / 100.0)
    risks['Supply Chain (Rupture)'] = part_exposee * (params['impact_geopolitique'] / 100.0)

    if not data['reut_invest']:
        vol_jour = data['vol_eau'] / 300
        risks['Conformité (CAPEX)'] = (vol_jour * 1500.0) * (params['pression_legale'] / 100.0)
    else: risks['Conformité (CAPEX)'] = 0.0

    risks['Réputation (Valo)'] = data['valo_finale'] * (params['risque_image'] / 100.0)
    risks['Énergie'] = (data['energie_conso'] * 0.15) * (params['hausse_energie'] / 100.0)
    
    return risks, sum(risks.values())

def calculate_water_footprint(data):
    return data['vol_eau'] + (data['ca'] * 0.02)

# --- 4. DATA EXTERNE (YAHOO CORRIGÉ) ---
def get_yahoo_data(ticker):
    """Récupère les données Bourse en renvoyant TOUJOURS 4 valeurs"""
    try:
        t = yf.Ticker(ticker)
        try: name = t.info.get('longName') or t.info.get('shortName')
        except: name = None
        
        # Si pas de nom, on tente avec .PA
        if not name and not ticker.endswith(".PA"):
             return get_yahoo_data(ticker + ".PA")
        
        mcap = t.info.get('marketCap') or t.fast_info.get('market_cap')
        sector = t.info.get('sector', 'N/A')
        
        # Le return doit contenir exactement 4 éléments
        return float(mcap or 0), name, sector, ticker
    except: 
        # En cas d'erreur totale, on renvoie des valeurs vides mais au bon format
        return 0.0, None, None, None

def get_pappers_data(query, api_key):
    if not api_key: return None, "Clé manquante"
    try:
        if re.fullmatch(r'\d{9}', query.replace(' ', '')):
            url = f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={query.replace(' ', '')}"
            r = requests.get(url, headers=HEADERS, timeout=5)
        else:
            r = requests.get("https://api.pappers.fr/v2/recherche", params={"q": query, "api_token": api_key, "par_page": 1}, headers=HEADERS, timeout=5)
            if r.status_code == 200 and r.json().get('resultats'):
                siren = r.json()['resultats'][0]['siren']
                r = requests.get(f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={siren}", headers=HEADERS, timeout=5)
        
        if r.status_code != 200: return None, "Introuvable"
        d = r.json()
        f = d.get('finances', [{}])[0]
        stats = {'ca': float(f.get('chiffre_affaires') or 0), 'res': float(f.get('resultat') or 0), 'cap': float(f.get('capitaux_propres') or 0)}
        return stats, d.get('nom_entreprise', 'Inconnu')
    except Exception as e: return None, str(e)

def run_ocr_scan(file_obj):
    stats = {'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'found': False}
    try:
        full = ""
        with pdfplumber.open(file_obj) as pdf:
            for p in pdf.pages[:20]: full += (p.extract_text() or "") + "\n"
        text = full.upper()
        def clean(s): 
            try: return float(re.sub(r'[^\d,\.-]', '', s).replace(',', '.'))
            except: return 0.0
        patterns = {'ca': ["CHIFFRES D'AFFAIRES", "VENTES"], 'res': ["RESULTAT NET", "BENEFICE"], 'cap': ["CAPITAUX PROPRES"]}
        for k, words in patterns.items():
            for w in words:
                if w in text:
                    nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', text[text.find(w):text.find(w)+400])
                    valid = [clean(n) for n in nums if abs(clean(n)) > 1000]
                    if valid:
                        stats[k] = max(valid, key=abs) if k == 'ca' else valid[0]
                        stats['found'] = True; break
    except: pass
    return stats, "OK" if stats['found'] else "Rien trouvé"

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

# --- 5. GENERATEUR PDF ---
def generate_pdf_report(data):
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
    pdf.set_font("Arial", 'B', 20); pdf.cell(0, 15, "AUDIT AQUARISK 360", ln=1, align='C')
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, str(data.get('ent_name', 'Société')), ln=1, align='C')
    
    pdf.ln(5)
    pdf.set_font("Arial", '', 10)
    pdf.cell(95, 8, f"CA: {data.get('ca',0):,.0f} EUR", 1)
    pdf.cell(95, 8, f"Valo: {data.get('valo_finale',0):,.0f} EUR", 1, ln=1)
    pdf.cell(95, 8, f"Secteur: {data.get('secteur','?')}", 1)
    pdf.cell(95, 8, f"Risque 2030: {data.get('s30',0):.2f}/5", 1, ln=1)

    pdf.ln(5)
    if map_path:
        try: pdf.image(map_path, x=10, w=90)
        except: pass
    if chart_path:
        try: pdf.image(chart_path, x=110, y=pdf.get_y(), w=90)
        except: pass
    pdf.ln(60)

    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, "SCENARIOS & IMPACTS FINANCIERS", ln=1)
    pdf.set_font("Arial", '', 10)
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
        pdf.cell(0, 7, "Aucune simulation (Voir onglet Risques 360).", 1, ln=1)

    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, "SOURCES & CONTEXTE", ln=1)
    pdf.set_font("Arial", '', 9)
    pdf.multi_cell(0, 5, f"Wiki: {str(data.get('wiki_summary',''))[:1000]}")
    pdf.ln(5)
    for n in data.get('news', []):
        pdf.cell(0, 5, f"> {n['title']}", ln=1)

    if chart_path and os.path.exists(chart_path): os.remove(chart_path)
    if map_path and os.path.exists(map_path): os.remove(map_path)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_excel(data):
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = wb.add_worksheet()
    rows = [["Entité", data.get('ent_name')], ["Valo", data.get('valo_finale')], ["VaR", data.get('var_amount')]]
    for i, r in enumerate(rows): ws.write_row(i, 0, r)
    wb.close()
    return output.getvalue()
    
