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
import tempfile # <--- NOUVEAU : Pour gérer les images PDF sans crash
import os

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
        
        # Docs
        'news': [], 'wiki_summary': "Pas de données.",
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- SECTEURS ---
SECTEURS = {
    "Agroalimentaire (100%)": 1.0, "Mines & Métaux (90%)": 0.9,
    "Chimie / Pétrochimie (85%)": 0.85, "Industrie Lourde (80%)": 0.8,
    "Énergie / Pétrole (70%)": 0.7, "Textile / Habillement (65%)": 0.65,
    "BTP / Construction (60%)": 0.6, "Transport / Logistique (50%)": 0.5,
    "Tourisme / Hôtellerie (50%)": 0.5, "Commerce / Retail (40%)": 0.4,
    "Santé / Pharma (30%)": 0.3, "Services / Logiciel (10%)": 0.1
}
SECTEURS_LISTE = list(SECTEURS.keys())

# --- API EXTERNES (PAPPERS / YAHOO) ---
def get_pappers_data(query, api_key):
    if not api_key: return None, "Clé API manquante."
    try:
        if re.fullmatch(r'\d{9}', query.replace(' ', '')):
            url = f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={query.replace(' ', '')}"
            r = requests.get(url, timeout=5)
        else:
            r = requests.get("https://api.pappers.fr/v2/recherche", params={"q": query, "api_token": api_key, "par_page": 1}, timeout=5)
            if r.status_code == 200 and r.json().get('resultats'):
                siren = r.json()['resultats'][0]['siren']
                r = requests.get(f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={siren}", timeout=5)
        
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

# --- OCR ---
def clean_number(text_num):
    if not isinstance(text_num, str): return 0.0
    try:
        clean = re.sub(r'[^\d,\.-]', '', text_num.replace(' ', '')).replace(',', '.')
        if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except: return 0.0

def run_ocr_scan(file_obj):
    stats = {'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'found': False}
    try:
        full_text = ""
        with pdfplumber.open(file_obj) as pdf:
            for p in pdf.pages[:20]: full_text += (p.extract_text() or "") + "\n"
        text = full_text.upper()
        patterns = {'ca': ["CHIFFRES D'AFFAIRES", "VENTES"], 'res': ["RESULTAT NET", "BENEFICE"], 'cap': ["CAPITAUX PROPRES"]}
        
        for k, words in patterns.items():
            for w in words:
                if w in text:
                    nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', text[text.find(w):text.find(w)+400])
                    valid = [clean_number(n) for n in nums if abs(clean_number(n)) > 1000 and abs(clean_number(n)) < 2030 or abs(clean_number(n)) > 2050]
                    if valid:
                        stats[k] = max(valid, key=abs) if k == 'ca' else valid[0]
                        stats['found'] = True
                        break
    except Exception as e: return stats, str(e)
    return stats, "OK"

def get_wiki_summary(name):
    try:
        import urllib.parse
        clean = re.sub(r'\s(SA|SAS|SARL|INC)', '', name, flags=re.IGNORECASE).strip()
        r = requests.get(f"https://fr.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(clean)}", timeout=3)
        return r.json().get('extract', "Pas de résumé.") if r.status_code == 200 else "Introuvable."
    except: return "Erreur Wiki."

# --- GENERATEUR PDF ROBUSTE (AVEC TEMPFILE) ---
def generate_pdf_report(data):
    # 1. Création Graphique Temporaire
    temp_chart_path = None
    try:
        fig, ax = plt.subplots(figsize=(6, 3))
        years = ['2024', '2030']
        scores = [data.get('s24', 2.5), data.get('s30', 3.0)]
        ax.plot(years, scores, marker='o', color='red', linestyle='-', linewidth=2)
        ax.set_title('Trajectoire Risque Eau')
        ax.set_ylim(0, 5)
        ax.grid(True, linestyle='--', alpha=0.6)
        
        # SAUVEGARDE DANS UN FICHIER TEMPORAIRE PHYSIQUE (Pas en mémoire RAM)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            plt.savefig(tmp.name, format='png', dpi=100)
            temp_chart_path = tmp.name
        plt.close(fig)
    except: pass

    # 2. PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 22)
    pdf.cell(0, 20, "RAPPORT D'AUDIT", ln=1, align='C')
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, str(data.get('ent_name', 'Société')).upper(), ln=1, align='C')
    pdf.ln(10)
    
    # Finance
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "1. FINANCE", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Valorisation: {data.get('valo_finale', 0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"CA: {data.get('ca', 0):,.0f} EUR", ln=1)
    pdf.ln(5)
    
    # Climat
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "2. CLIMAT & RISQUE", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Score Risque 2030: {data.get('s30', 0):.2f} / 5", ln=1)
    pdf.cell(0, 8, f"VaR (Impact): -{abs(data.get('var_amount', 0)):,.0f} EUR", ln=1)
    pdf.ln(5)
    
    # Image Graphique
    if temp_chart_path and os.path.exists(temp_chart_path):
        try:
            pdf.image(temp_chart_path, x=50, w=100)
        except: pass
        
    # Nettoyage fichier temporaire
    if temp_chart_path and os.path.exists(temp_chart_path):
        try: os.remove(temp_chart_path)
        except: pass

    # Texte Wiki (Encodage safe)
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "3. CONTEXTE", ln=1)
    pdf.set_font("Arial", '', 10)
    wiki = str(data.get('wiki_summary', ''))
    try: wiki = wiki.encode('latin-1', 'replace').decode('latin-1')
    except: wiki = "Erreur encodage."
    pdf.multi_cell(0, 5, wiki)

    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_excel(data):
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = wb.add_worksheet()
    rows = [["Entité", data.get('ent_name')], ["Valo", data.get('valo_finale')], ["VaR", data.get('var_amount')]]
    for i, r in enumerate(rows): ws.write_row(i, 0, r)
    wb.close()
    return output.getvalue()
    
