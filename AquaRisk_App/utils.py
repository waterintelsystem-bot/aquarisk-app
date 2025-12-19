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
        'map_id': 0, # FORCE LE RAFRAICHISSEMENT CARTE
        # Docs
        'news': [], 'wiki_summary': "Pas de données.",
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- CONSTANTES ---
SECTEURS = {
    "Agroalimentaire (100%)": 1.0, "Mines & Métaux (90%)": 0.9,
    "Chimie / Pétrochimie (85%)": 0.85, "Industrie Lourde (80%)": 0.8,
    "Énergie / Pétrole (70%)": 0.7, "Textile / Habillement (65%)": 0.65,
    "BTP / Construction (60%)": 0.6, "Transport / Logistique (50%)": 0.5,
    "Tourisme / Hôtellerie (50%)": 0.5, "Commerce / Retail (40%)": 0.4,
    "Santé / Pharma (30%)": 0.3, "Services / Logiciel (10%)": 0.1
}
SECTEURS_LISTE = list(SECTEURS.keys())
HEADERS = {'User-Agent': 'AquaRisk/1.0 (Educational Project)'}

# --- FONCTIONS CALCUL ---
def calculate_dynamic_score(lat, lon):
    # Score basé sur la latitude (proche équateur = plus risqué) + petite variation stable
    base = 2.0 + (abs(lat) / 60.0)
    random.seed(int(lat*100) + int(lon*100)) # Stable pour une même ville
    noise = random.uniform(-0.3, 0.8)
    s24 = min(max(base + noise, 1.5), 4.2)
    s30 = min(s24 * 1.2, 5.0)
    return s24, s30

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
        if not t.info.get('longName') and not ticker.endswith(".PA"): return get_yahoo_data(ticker + ".PA")
        mcap = t.info.get('marketCap') or t.fast_info.get('market_cap')
        return float(mcap), t.info.get('longName'), t.info.get('sector', 'N/A'), ticker
    except: return 0.0, None, None, None

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
                    sub = text[text.find(w):text.find(w)+400]
                    nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', sub)
                    valid = [clean(n) for n in nums if abs(clean(n)) > 1000 and abs(clean(n)) < 2030 or abs(clean(n)) > 2050]
                    if valid:
                        stats[k] = max(valid, key=abs) if k == 'ca' else valid[0]
                        stats['found'] = True; break
    except: pass
    return stats, "OK" if stats['found'] else "Rien trouvé"

# --- WIKIPEDIA INTELLIGENT (SEARCH FIRST) ---
def get_wiki_summary(name):
    try:
        # 1. On nettoie le nom
        clean_name = re.sub(r'\s(SA|SAS|SARL|INC|LTD|GROUP|GROUPE)', '', name, flags=re.IGNORECASE).strip()
        
        # 2. On CHERCHE la page (Search API) pour avoir le vrai titre
        search_url = "https://fr.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": clean_name,
            "format": "json"
        }
        r_search = requests.get(search_url, params=params, headers=HEADERS, timeout=5)
        data_search = r_search.json()
        
        if not data_search.get('query', {}).get('search'):
            return "Aucune page Wikipedia trouvée."
            
        # 3. On prend le premier résultat (le plus pertinent)
        true_title = data_search['query']['search'][0]['title']
        
        # 4. On demande le résumé de ce titre exact
        summary_url = f"https://fr.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(true_title)}"
        r_sum = requests.get(summary_url, headers=HEADERS, timeout=5)
        
        if r_sum.status_code == 200:
            return r_sum.json().get('extract', "Résumé non disponible.")
        return "Page trouvée mais sans résumé."
        
    except Exception as e: return f"Erreur Wiki: {str(e)}"

# --- PDF & EXCEL ---
def generate_pdf_report(data):
    # Graph
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
    pdf.set_font("Arial", 'B', 22); pdf.cell(0, 20, "AUDIT AQUARISK", ln=1, align='C')
    
    pdf.set_font("Arial", 'B', 16); pdf.cell(0, 10, str(data.get('ent_name', '?')), ln=1, align='C')
    pdf.set_font("Arial", '', 12); pdf.ln(10)
    
    pdf.cell(0, 8, f"Valorisation: {data.get('valo_finale',0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"CA: {data.get('ca',0):,.0f} EUR", ln=1)
    pdf.ln(5)
    pdf.cell(0, 8, f"Lieu: {data.get('ville','?')} ({data.get('pays','?')})", ln=1)
    pdf.cell(0, 8, f"Score Risque 2030: {data.get('s30',0):.2f}/5", ln=1)
    pdf.cell(0, 8, f"VaR: -{abs(data.get('var_amount',0)):,.0f} EUR", ln=1)
    
    if temp_path:
        try: pdf.image(temp_path, x=50, w=100); os.remove(temp_path)
        except: pass

    pdf.ln(10); pdf.multi_cell(0, 5, f"Resume:\n{str(data.get('wiki_summary',''))[:2000]}")
    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_excel(data):
    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {'in_memory': True})
    ws = wb.add_worksheet()
    rows = [["Nom", data.get('ent_name')], ["Valo", data.get('valo_finale')], ["VaR", data.get('var_amount')]]
    for i, r in enumerate(rows): ws.write_row(i, 0, r)
    wb.close()
    return out.getvalue()
    
