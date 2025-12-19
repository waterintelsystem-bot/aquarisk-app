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
from thefuzz import process

# --- 1. INITIALISATION UNIVERSELLE (ANTI-CRASH) ---
def init_session():
    """Cette fonction doit être appelée au début de CHAQUE page."""
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'ville': "Paris", 'pays': "France",
        'secteur': "Agroalimentaire (100%)",
        
        'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'ebitda': 0.0,
        'valo_finale': 0.0, 'mode_valo': "PME (Bilan)", 'source_data': "Manuel",
        
        's24': 2.5, 's26': 2.7, 's30': 3.0,
        'var_amount': 0.0, 'lat': 48.85, 'lon': 2.35,
        
        'news': [], 'wiki_summary': "",
        'audit_launched': False
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

# --- 2. CONSTANTES SECTEURS (CORRIGEES) ---
# Les clés doivent correspondre EXACTEMENT au menu déroulant
SECTEURS = {
    "Agroalimentaire (100%)": 1.0,
    "Industrie Lourde (80%)": 0.8,
    "Énergie / Pétrole (70%)": 0.7,
    "BTP / Construction (60%)": 0.6,
    "Transport / Logistique (50%)": 0.5,
    "Luxe / Textile (50%)": 0.5,
    "Commerce / Retail (40%)": 0.4,
    "Santé / Pharma (30%)": 0.3,
    "Services / Logiciel (10%)": 0.1
}
SECTEURS_LISTE = list(SECTEURS.keys())

# --- 3. API PAPPERS (RESTAURÉE) ---
def get_pappers_data(name, api_key):
    if not api_key: return None, "Pas de clé API"
    try:
        # Recherche
        r = requests.get(f"https://api.pappers.fr/v2/recherche?q={name}&api_token={api_key}&par_page=1", timeout=5)
        if r.status_code != 200: return None, "Erreur Recherche"
        data = r.json()
        if not data['resultats']: return None, "Aucun résultat"
        
        # Détails Entreprise
        siren = data['resultats'][0]['siren']
        nom = data['resultats'][0]['nom_entreprise']
        r2 = requests.get(f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={siren}", timeout=5)
        finances = r2.json().get('finances', [])
        
        stats = {'ca': 0.0, 'res': 0.0, 'cap': 0.0}
        if finances:
            last = finances[0] # Dernier bilan
            stats['ca'] = float(last.get('chiffre_affaires') or 0)
            stats['res'] = float(last.get('resultat') or 0)
            stats['cap'] = float(last.get('capitaux_propres') or 0)
            
        return stats, nom
    except Exception as e: return None, str(e)

# --- 4. OCR AGRESSIF ---
def clean_number(text_num):
    if not isinstance(text_num, str): return 0.0
    try:
        clean = text_num.replace(' ', '').replace(')', '').replace('(', '-').replace("'", "").replace('"', "")
        clean = re.sub(r'[^\d,\.-]', '', clean).replace(',', '.')
        if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except: return 0.0

def run_ocr_scan(file_obj):
    stats = {'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'found': False}
    full_text = ""
    try:
        with pdfplumber.open(file_obj) as pdf:
            for p in pdf.pages[:20]: full_text += (p.extract_text() or "") + "\n"
        
        text_upper = full_text.upper()
        patterns = {
            'ca': ["CHIFFRES D'AFFAIRES", "PRODUITS D'EXPLOITATION", "VENTES", "TOTAL PRODUITS"],
            'res': ["RESULTAT NET", "BENEFICE OU PERTE", "RESULTAT DE L'EXERCICE"],
            'cap': ["CAPITAUX PROPRES", "SITUATION NETTE", "TOTAL PASSIF"]
        }
        for key, keywords in patterns.items():
            for kw in keywords:
                if kw in text_upper:
                    idx = text_upper.find(kw)
                    window = text_upper[idx:idx+400]
                    nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', window)
                    valid_nums = [clean_number(n) for n in nums if abs(clean_number(n)) > 2050 or (abs(clean_number(n)) > 500 and abs(clean_number(n)) < 1900)]
                    if valid_nums:
                        if key == 'ca': stats['ca'] = max(valid_nums, key=abs)
                        else: stats[key] = valid_nums[0]
                        stats['found'] = True
                        break
    except Exception as e: return stats, str(e)
    return stats, full_text

# --- 5. INTELLIGENCE ---
def get_company_intelligence(name):
    wiki_text = "Pas de données Wikipedia."
    try:
        import urllib.parse
        url = f"https://fr.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(name)}"
        r = requests.get(url, timeout=2)
        if r.status_code == 200: wiki_text = r.json().get('extract', wiki_text)
    except: pass

    news_items = []
    try:
        import urllib.parse
        q = urllib.parse.quote(f'"{name}" (finance OR business OR climat)')
        f = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
        news_items = [{"title": e.title, "link": e.link} for e in f.entries[:5]]
    except: pass
    return wiki_text, news_items

# --- 6. BOURSE ---
def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker)
        mcap = t.info.get('marketCap') or t.fast_info.get('market_cap')
        name = t.info.get('shortName') or t.info.get('longName')
        sector = t.info.get('sector', "Inconnu")
        return (float(mcap), name, sector) if mcap else (0.0, None, None)
    except: return 0.0, None, None

# --- 7. EXPORTS ---
def generate_excel(data):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet("Audit")
    headers = ["Métrique", "Valeur", "Détail"]
    rows = [
        ["Entreprise", data.get('ent_name'), data.get('secteur')],
        ["Valorisation", data.get('valo_finale'), data.get('mode_valo')],
        ["CA", data.get('ca'), data.get('source_data')],
        ["Score Climat 2030", data.get('s30'), "/ 5.0"],
        ["Impact VaR", data.get('var_amount'), "EUR"]
    ]
    for col, h in enumerate(headers): ws.write(0, col, h)
    for row, record in enumerate(rows):
        for col, val in enumerate(record): ws.write(row+1, col, val)
    workbook.close()
    return output.getvalue()

def generate_pdf_report(data):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, f"RAPPORT D'AUDIT: {data.get('ent_name', 'N/A')}", ln=1, align='C')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='C')
    pdf.ln(10)
    
    # Finance
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "1. FINANCE", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Valorisation: {data.get('valo_finale', 0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"CA: {data.get('ca', 0):,.0f} EUR", ln=1)
    
    # Climat
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "2. CLIMAT", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Score Risque 2030: {data.get('s30', 0):.2f} / 5.00", ln=1)
    var = data.get('var_amount', 0)
    pdf.cell(0, 8, f"Impact Financier (VaR): -{abs(var):,.0f} EUR", ln=1)
    
    # Intelligence
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "3. INTELLIGENCE", ln=1)
    pdf.set_font("Arial", '', 10)
    txt = data.get('wiki_summary', '')[:1000]
    try: txt = txt.encode('latin-1', 'replace').decode('latin-1')
    except: txt = "Erreur encodage."
    pdf.multi_cell(0, 5, txt)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

