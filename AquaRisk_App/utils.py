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

# --- INITIALISATION MEMOIRE (A appeler sur chaque page) ---
def init_session():
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'ville': "Paris", 'pays': "France",
        'secteur': "Agroalimentaire (100%)",
        
        # Finance
        'ca': 0.0, 'res': 0.0, 'cap': 0.0,
        'valo_finale': 0.0, 'mode_valo': "PME (Bilan)", 'source_data': "Manuel",
        
        # Climat
        's24': 2.5, 's30': 3.0, 'var_amount': 0.0,
        'lat': 48.8566, 'lon': 2.3522,
        
        # Docs
        'news': [], 'wiki_summary': "Pas de données.",
        'pappers_token': "", # Stockage temporaire clé
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            import streamlit as st
            st.session_state[k] = v

# --- CONNECTEUR PAPPERS (Renforcé) ---
def get_pappers_data(name, api_key):
    if not api_key: return None, "Clé API manquante."
    try:
        # 1. Recherche
        url_search = "https://api.pappers.fr/v2/recherche"
        params = {"q": name, "api_token": api_key, "par_page": 1}
        r = requests.get(url_search, params=params, timeout=5)
        
        if r.status_code == 401: return None, "Clé API invalide."
        if r.status_code != 200: return None, f"Erreur API: {r.status_code}"
        
        data = r.json()
        if not data.get('resultats'): return None, "Entreprise introuvable."
        
        # 2. Données Financières
        company = data['resultats'][0]
        siren = company['siren']
        nom = company['nom_entreprise']
        
        r2 = requests.get("https://api.pappers.fr/v2/entreprise", params={"api_token": api_key, "siren": siren}, timeout=5)
        details = r2.json()
        
        stats = {'ca': 0.0, 'res': 0.0, 'cap': 0.0}
        finances = details.get('finances', [])
        if finances:
            last = finances[0]
            stats['ca'] = float(last.get('chiffre_affaires') or 0)
            stats['res'] = float(last.get('resultat') or 0)
            stats['cap'] = float(last.get('capitaux_propres') or 0)
            
        return stats, nom
    except Exception as e: return None, str(e)

# --- CONNECTEUR YAHOO (Renforcé) ---
def get_yahoo_data(ticker):
    try:
        # Tente d'ajouter .PA si oublié
        suffixes = ["", ".PA", ".DE", ".L"]
        for suf in suffixes:
            full_ticker = f"{ticker}{suf}" if not ticker.endswith(suf) else ticker
            t = yf.Ticker(full_ticker)
            
            # Méthode Fast Info (Plus rapide/stable)
            mcap = t.fast_info.get('market_cap')
            if mcap and mcap > 0:
                name = t.info.get('shortName') or t.info.get('longName') or full_ticker
                sector = t.info.get('sector', 'Inconnu')
                return float(mcap), name, sector, full_ticker
        
        return 0.0, None, None, None
    except: return 0.0, None, None, None

# --- OCR PDF (Nettoyage agressif) ---
def clean_number(text_num):
    if not isinstance(text_num, str): return 0.0
    try:
        # Nettoyage des caractères invisibles et format français
        clean = text_num.replace(' ', '').replace('\xa0', '').replace('€', '')
        clean = clean.replace(')', '').replace('(', '-')
        clean = re.sub(r'[^\d,\.-]', '', clean).replace(',', '.')
        if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except: return 0.0

def run_ocr_scan(file_obj):
    stats = {'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'found': False}
    try:
        full_text = ""
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
                    # Fenêtre réduite pour éviter de prendre une date (ex: 2024) comme montant
                    window = text_upper[idx:idx+300]
                    nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', window)
                    
                    valid_nums = []
                    for n in nums:
                        val = clean_number(n)
                        # On exclut les années probables (1990-2030) sauf si c'est un très petit CA (peu probable)
                        if abs(val) > 2030 or (abs(val) > 0 and abs(val) < 1900):
                            valid_nums.append(val)
                    
                    if valid_nums:
                        if key == 'ca': stats['ca'] = max(valid_nums, key=abs)
                        else: stats[key] = valid_nums[0]
                        stats['found'] = True
                        break
    except Exception as e: return stats, str(e)
    return stats, "OK"

# --- INTELLIGENCE (Wiki Fallback) ---
def get_wiki_summary(name):
    try:
        import urllib.parse
        # Recherche Wiki générique
        url = f"https://fr.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(name)}"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            return r.json().get('extract', "Pas de résumé trouvé.")
        return "Page Wikipedia introuvable."
    except: return "Erreur de connexion Wikipedia."

# --- GENERATEUR PDF ---
def generate_pdf_report(data):
    pdf = FPDF()
    pdf.add_page()
    
    # 1. Header
    pdf.set_font("Arial", 'B', 22)
    pdf.cell(0, 20, "RAPPORT D'AUDIT COMPLET", ln=1, align='C')
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"Societe: {data.get('ent_name', 'Inconnu')}", ln=1, align='C')
    pdf.ln(10)
    
    # 2. Finance
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. ANALYSE FINANCIERE", ln=1, fill=True)
    pdf.set_font("Arial", '', 12)
    pdf.ln(5)
    pdf.cell(0, 8, f"Valorisation Retenue: {data.get('valo_finale', 0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"Source des donnees: {data.get('source_data', 'Manuel')}", ln=1)
    pdf.cell(0, 8, f"Chiffre d'Affaires: {data.get('ca', 0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"Resultat Net: {data.get('res', 0):,.0f} EUR", ln=1)
    pdf.ln(10)

    # 3. Climat
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "2. RISQUES CLIMATIQUES & VAR", ln=1, fill=True)
    pdf.set_font("Arial", '', 12)
    pdf.ln(5)
    pdf.cell(0, 8, f"Localisation: {data.get('ville', '?')} ({data.get('pays', '?')})", ln=1)
    pdf.cell(0, 8, f"Score Risque Eau 2030: {data.get('s30', 0):.2f} / 5.00", ln=1)
    pdf.cell(0, 8, f"Secteur Vulnérable: {data.get('secteur', '?')}", ln=1)
    
    var = data.get('var_amount', 0)
    txt_var = f"PERTE POTENTIELLE (VaR): -{abs(var):,.0f} EUR" if var > 0 else "Impact Financier: Faible"
    pdf.set_text_color(200, 0, 0) if var > 0 else pdf.set_text_color(0, 100, 0)
    pdf.cell(0, 8, txt_var, ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(10)

    # 4. Contexte
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "3. CONTEXTE & SOURCES", ln=1, fill=True)
    pdf.set_font("Arial", '', 10)
    pdf.ln(5)
    
    wiki = data.get('wiki_summary', '')
    try: wiki = wiki.encode('latin-1', 'replace').decode('latin-1')
    except: wiki = "Erreur encodage."
    pdf.multi_cell(0, 5, f"Resume:\n{wiki}")
    pdf.ln(5)
    
    pdf.cell(0, 10, "Sources Presse:", ln=1)
    for n in data.get('news', []):
        try:
            t = n['title'].encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 5, f"- {t}", ln=1, link=n['link'])
        except: continue

    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_excel(data):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet()
    rows = [
        ["Entité", data.get('ent_name')],
        ["Valo", data.get('valo_finale')],
        ["CA", data.get('ca')],
        ["Résultat", data.get('res')],
        ["Risque 2030", data.get('s30')],
        ["VaR", data.get('var_amount')]
    ]
    for i, r in enumerate(rows): ws.write_row(i, 0, r)
    workbook.close()
    return output.getvalue()
    
