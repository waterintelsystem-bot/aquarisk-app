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
matplotlib.use('Agg') # Pour éviter les erreurs de serveur

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
        
        # Docs
        'news': [], 'wiki_summary': "Pas de données.",
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- LISTE SECTEURS ETENDUE ---
SECTEURS = {
    "Agroalimentaire (100%)": 1.0,
    "Mines & Métaux (90%)": 0.9,
    "Chimie / Pétrochimie (85%)": 0.85,
    "Industrie Lourde (80%)": 0.8,
    "Énergie / Pétrole (70%)": 0.7,
    "Textile / Habillement (65%)": 0.65,
    "BTP / Construction (60%)": 0.6,
    "Transport / Logistique (50%)": 0.5,
    "Tourisme / Hôtellerie (50%)": 0.5,
    "Commerce / Retail (40%)": 0.4,
    "Santé / Pharma (30%)": 0.3,
    "Immobilier (Gestion) (25%)": 0.25,
    "Télécoms (20%)": 0.2,
    "Banque / Assurance (15%)": 0.15,
    "Services / Logiciel (10%)": 0.1,
    "Consulting / Audit (5%)": 0.05
}
SECTEURS_LISTE = list(SECTEURS.keys())

# --- CONNECTEUR PAPPERS (SIREN + NOM) ---
def get_pappers_data(query, api_key):
    if not api_key: return None, "Clé API manquante."
    try:
        # Détection automatique SIREN (9 chiffres)
        is_siren = re.fullmatch(r'\d{9}', query.replace(' ', ''))
        
        if is_siren:
            url = f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={query.replace(' ', '')}"
            r = requests.get(url, timeout=5)
            if r.status_code != 200: return None, "SIREN introuvable."
            details = r.json()
            nom = details.get('nom_entreprise', 'Inconnu')
        else:
            # Recherche par nom
            url_search = "https://api.pappers.fr/v2/recherche"
            r = requests.get(url_search, params={"q": query, "api_token": api_key, "par_page": 1}, timeout=5)
            data = r.json()
            if not data.get('resultats'): return None, "Entreprise introuvable."
            company = data['resultats'][0]
            nom = company['nom_entreprise']
            r2 = requests.get(f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={company['siren']}", timeout=5)
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
        t = yf.Ticker(ticker)
        # Tente de récupérer le nom long pour confirmer
        name = t.info.get('longName')
        if not name: 
            # Essai avec .PA si non fourni
            if not ticker.endswith(".PA"):
                return get_yahoo_data(ticker + ".PA")
            return 0.0, None, None, None

        mcap = t.info.get('marketCap') or t.fast_info.get('market_cap')
        sector = t.info.get('sector', 'Inconnu')
        return float(mcap), name, sector, ticker
    except: return 0.0, None, None, None

# --- OCR PDF ---
def clean_number(text_num):
    if not isinstance(text_num, str): return 0.0
    try:
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
            for p in pdf.pages[:30]: full_text += (p.extract_text() or "") + "\n"
        
        text_upper = full_text.upper()
        # Mots clés étendus
        patterns = {
            'ca': ["CHIFFRES D'AFFAIRES", "PRODUITS D'EXPLOITATION", "VENTES", "TOTAL DES PRODUITS"],
            'res': ["RESULTAT NET", "BENEFICE OU PERTE", "RESULTAT DE L'EXERCICE"],
            'cap': ["CAPITAUX PROPRES", "SITUATION NETTE", "TOTAL PASSIF"]
        }

        for key, keywords in patterns.items():
            for kw in keywords:
                if kw in text_upper:
                    idx = text_upper.find(kw)
                    window = text_upper[idx:idx+400]
                    nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', window)
                    
                    valid_nums = []
                    for n in nums:
                        val = clean_number(n)
                        # Filtre années et incohérences
                        if abs(val) > 2050 or (abs(val) > 0 and abs(val) < 1900):
                            valid_nums.append(val)
                    
                    if valid_nums:
                        if key == 'ca': stats['ca'] = max(valid_nums, key=abs)
                        else: stats[key] = valid_nums[0]
                        stats['found'] = True
                        break
    except Exception as e: return stats, f"Erreur technique: {str(e)}"
    
    msg = "Données trouvées" if stats['found'] else "Aucun chiffre financier identifié"
    return stats, msg

# --- INTELLIGENCE (Wiki Fallback) ---
def get_wiki_summary(name):
    # Nettoyage du nom pour la recherche (enlève SA, SAS, etc)
    clean_name = re.sub(r'\s(SA|SAS|SARL|INC|LTD)', '', name, flags=re.IGNORECASE).strip()
    try:
        import urllib.parse
        url = f"https://fr.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(clean_name)}"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            return r.json().get('extract', "Pas de résumé trouvé.")
        return "Page Wikipedia introuvable."
    except: return "Erreur de connexion Wikipedia."

# --- GENERATEUR PDF AVEC GRAPHIQUE ---
def generate_pdf_report(data):
    # 1. Générer le graphique en image
    try:
        fig, ax = plt.subplots(figsize=(6, 3))
        years = ['2024', '2030']
        scores = [data.get('s24', 0), data.get('s30', 0)]
        ax.plot(years, scores, marker='o', color='red', linestyle='-')
        ax.set_title('Trajectoire Risque Eau')
        ax.set_ylim(0, 5)
        ax.grid(True, linestyle='--', alpha=0.6)
        
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png', dpi=100)
        img_buf.seek(0)
    except: img_buf = None

    # 2. Créer le PDF
    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("Arial", 'B', 22)
    pdf.cell(0, 20, "RAPPORT D'AUDIT", ln=1, align='C')
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"{data.get('ent_name', 'Société').upper()}", ln=1, align='C')
    pdf.ln(10)
    
    # Finance
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. FINANCE & VALORISATION", ln=1, fill=True)
    pdf.set_font("Arial", '', 12)
    pdf.ln(5)
    pdf.cell(0, 8, f"Valorisation: {data.get('valo_finale', 0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"Methode: {data.get('mode_valo', 'Manuel')}", ln=1)
    pdf.cell(0, 8, f"Chiffre d'Affaires: {data.get('ca', 0):,.0f} EUR", ln=1)
    pdf.ln(10)

    # Climat
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "2. RISQUE CLIMATIQUE", ln=1, fill=True)
    pdf.set_font("Arial", '', 12)
    pdf.ln(5)
    pdf.cell(0, 8, f"Localisation: {data.get('ville', '?')}", ln=1)
    pdf.cell(0, 8, f"Secteur: {data.get('secteur', '?')}", ln=1)
    
    var = data.get('var_amount', 0)
    txt_var = f"IMPACT FINANCIER (VaR): -{abs(var):,.0f} EUR" if var > 0 else "Impact: Faible"
    if var > 0: pdf.set_text_color(200, 0, 0)
    pdf.cell(0, 8, txt_var, ln=1)
    pdf.set_text_color(0, 0, 0)
    
    # Insertion Graphique
    if img_buf:
        pdf.ln(5)
        # x, y, w, h
        pdf.image(img_buf, x=50, w=100)
        pdf.ln(5)

    # Contexte
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "3. CONTEXTE & SOURCES", ln=1, fill=True)
    pdf.set_font("Arial", '', 10)
    pdf.ln(5)
    
    wiki = data.get('wiki_summary', '')
    try: wiki = wiki.encode('latin-1', 'replace').decode('latin-1')
    except: wiki = "Erreur encodage."
    pdf.multi_cell(0, 5, f"Resume:\n{wiki}")
    pdf.ln(5)
    
    pdf.cell(0, 10, "Sources Web:", ln=1)
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
        ["VaR", data.get('var_amount')]
    ]
    for i, r in enumerate(rows): ws.write_row(i, 0, r)
    workbook.close()
    return output.getvalue()
    
