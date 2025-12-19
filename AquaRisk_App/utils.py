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

matplotlib.use('Agg')

# --- INITIALISATION MEMOIRE ---
def init_session():
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'siren': "",
        'ville': "Paris", 'pays': "France",
        'secteur': "Agroalimentaire (100%)",
        # Finance
        'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'fcf': 0.0,
        'valo_finale': 0.0, 'mode_valo': "PME (Bilan)", 'source_data': "Manuel",
        # Climat
        's24': 2.5, 's30': 3.0, 'var_amount': 0.0,
        'lat': 48.8566, 'lon': 2.3522,
        'climat_calcule': False,
        'map_id': 0, # IMPORTANT POUR LE GPS
        # Risques 360
        'vol_eau': 50000.0, 'prix_eau': 4.5,
        'part_fournisseur_risk': 30.0, 'energie_conso': 100000.0,
        'reut_invest': False,
        # Docs
        'news': [], 'wiki_summary': "Pas de données.",
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- SECTEURS & PARAMETRES ---
SECTEURS = {
    "Agroalimentaire (100%)": 1.0, "Mines & Métaux (90%)": 0.9,
    "Chimie (85%)": 0.85, "Industrie (80%)": 0.8,
    "Énergie (70%)": 0.7, "Textile (65%)": 0.65,
    "BTP (60%)": 0.6, "Transport (50%)": 0.5,
    "Services (10%)": 0.1
}
SECTEURS_LISTE = list(SECTEURS.keys())
HEADERS = {'User-Agent': 'AquaRisk/1.0'}

# --- CALCUL CLIMAT DYNAMIQUE ---
def calculate_dynamic_score(lat, lon):
    # Score basé sur la latitude + variation pseudo-aléatoire stable
    base = 2.0 + (abs(lat) / 60.0)
    random.seed(int(lat*100) + int(lon*100))
    noise = random.uniform(-0.3, 0.8)
    s24 = min(max(base + noise, 1.5), 4.2)
    s30 = min(s24 * 1.2, 5.0)
    return s24, s30

# --- CALCUL RISQUES 360 ---
def calculate_360_risks(data, params):
    risks = {}
    # 1. Opérationnel
    delta_prix = data['prix_eau'] * (params['hausse_eau_pct'] / 100.0)
    risks['Coût Eau (Opérationnel)'] = data['vol_eau'] * delta_prix
    # 2. Supply Chain
    achats = data['ca'] * 0.40 
    part_exposee = achats * (data['part_fournisseur_risk'] / 100.0)
    risks['Supply Chain (Rupture)'] = part_exposee * (params['impact_geopolitique'] / 100.0)
    # 3. Réglementaire
    if not data['reut_invest']:
        vol_jour = data['vol_eau'] / 300
        capex_reut = vol_jour * 1500 
        risks['Réglementaire (Mise aux normes)'] = capex_reut * (params['pression_legale'] / 100.0)
    else:
        risks['Réglementaire (Mise aux normes)'] = 0.0
    # 4. Image
    risks['Réputation (Boycott)'] = data['valo_finale'] * (params['risque_image'] / 100.0)
    # 5. Énergie
    risks['Surcoût Énergie'] = (data['energie_conso'] * 0.15) * (params['hausse_energie'] / 100.0)

    total_risk = sum(risks.values())
    return risks, total_risk

def calculate_water_footprint(data):
    return data['vol_eau'] + (data['ca'] * 0.02)

# --- APIS ---
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

def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker)
        try: name = t.info.get('longName')
        except: name = None
        if not name and not ticker.endswith(".PA"): return get_yahoo_data(ticker + ".PA")
        mcap = t.info.get('marketCap') or t.fast_info.get('market_cap')
        sector = t.info.get('sector', 'N/A')
        return float(mcap or 0), name, sector, ticker
    except: return 0.0, None, None, None

# --- OCR ---
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

# --- WIKI (CORRIGÉ) ---
def get_wiki_summary(name):
    try:
        # CORRECTION ICI : flags=re.IGNORECASE pour éviter l'AttributeError
        clean = re.sub(r'\s(SA|SAS|SARL|INC)', '', name, flags=re.IGNORECASE).strip()
        search = requests.get("https://fr.wikipedia.org/w/api.php", params={"action":"query","list":"search","srsearch":clean,"format":"json"}, headers=HEADERS, timeout=5).json()
        if not search.get('query',{}).get('search'): return "Pas de page Wiki."
        title = search['query']['search'][0]['title']
        r = requests.get(f"https://fr.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}", headers=HEADERS, timeout=5)
        return r.json().get('extract', "Pas de résumé.")
    except: return "Erreur Wiki."

# --- PDF GENERATOR (SECURISE) ---
def generate_pdf_report(data):
    # Image
    temp_path = None
    try:
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.plot(['2024', '2030'], [data.get('s24', 2.5), data.get('s30', 3.0)], 'r-o', lw=2)
        ax.set_title("Risque Eau"); ax.set_ylim(0, 5); ax.grid(True)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            plt.savefig(tmp.name, format='png', dpi=100); temp_path = tmp.name
        plt.close(fig)
    except: pass

    # PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20); pdf.cell(0, 20, "RAPPORT D'AUDIT 360", ln=1, align='C')
    pdf.set_font("Arial", 'B', 16); pdf.cell(0, 10, str(data.get('ent_name', '?')), ln=1, align='C')
    
    pdf.ln(10)
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Valorisation: {data.get('valo_finale',0):,.0f} EUR", ln=1)
    pdf.cell(0, 10, f"Risque Climat 2030: {data.get('s30',0):.2f}/5", ln=1)
    pdf.cell(0, 10, f"Impact VaR: -{abs(data.get('var_amount',0)):,.0f} EUR", ln=1)
    
    if temp_path:
        try: pdf.image(temp_path, x=50, w=100); os.remove(temp_path)
        except: pass

    pdf.ln(10)
    pdf.multi_cell(0, 5, f"Resume:\n{str(data.get('wiki_summary',''))[:2000]}")
    
    # SORTIE SECURISEE (Bytes ou String selon version)
    val = pdf.output(dest='S')
    if isinstance(val, str):
        return val.encode('latin-1', 'replace')
    return val

def generate_excel(data):
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = wb.add_worksheet()
    rows = [["Entité", data.get('ent_name')], ["Valo", data.get('valo_finale')], ["VaR", data.get('var_amount')]]
    for i, r in enumerate(rows): ws.write_row(i, 0, r)
    wb.close()
    return output.getvalue()
    
