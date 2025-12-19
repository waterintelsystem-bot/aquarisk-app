import streamlit as st
import pandas as pd
try:
    from geopy.geocoders import Nominatim
except: pass
import time
from random import randint
from fpdf import FPDF
import io
import re
import os
import requests
from bs4 import BeautifulSoup
import pdfplumber
import yfinance as yf
from thefuzz import process
from datetime import datetime, timedelta
from staticmap import StaticMap, CircleMarker
import xlsxwriter
import feedparser

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
st.set_page_config(page_title="AquaRisk V25 : Version Finale", page_icon="💎", layout="wide")
st.title("💎 AquaRisk V25 : L'Audit Ultime (Restored Features)")

# Gestionnaire de Session Robuste
defaults = {
    'finance_ca': 1000000.0, 'finance_res': 100000.0, 'finance_cap': 200000.0, 'finance_ebitda': 125000.0,
    'audit_done': False, 'audit_data': {}, 'stock_data': {"mcap": 0, "ev": 0},
    'comparables': None, 'ocr_log': "En attente de fichier...", 'pdf_financials': None
}

for k, v in defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# ==============================================================================
# 2. MOTEUR OCR & INTELLIGENCE
# ==============================================================================
def clean_number(text_num):
    try:
        clean = text_num.replace(' ', '').replace(')', '').replace('(', '-').replace("'", "").replace('"', "")
        clean = re.sub(r'[^\d,\.-]', '', clean).replace(',', '.')
        if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except: return None

def extract_financials_smart(text):
    data = {"ca": 0, "res": 0, "cap": 0, "found": False}
    lines = text.split('\n')
    patterns = {
        "ca": [r"CHIFFRES? D['’\s]?AFFAIRES?", r"TOTAL DES PRODUITS D['’\s]?EXPLOITATION", r"VENTES DE MARCHANDISES"],
        "res": [r"BENEFICE OU PERTE", r"RESULTAT DE L['’\s]?EXERCICE", r"RESULTAT NET"],
        "cap": [r"TOTAL CAPITAUX PROPRES", r"CAPITAUX PROPRES", r"SITUATION NETTE"]
    }
    
    for metric, keywords in patterns.items():
        if data[metric] != 0: continue
        for line in lines:
            line_up = line.upper()
            if any(k in line_up for k in keywords) or process.extractOne(line_up, keywords)[1] > 90:
                nums_str = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', line)
                valid_nums = [clean_number(ns) for ns in nums_str if clean_number(ns) and abs(clean_number(ns)) > 2030]
                if valid_nums:
                    if metric == "ca": data["ca"] = max(valid_nums, key=abs)
                    else: data[metric] = valid_nums[0] 
                    data["found"] = True
                    break
    return data

def read_pdf(file):
    if not file: return ""
    text = ""
    try:
        file.seek(0)
        with pdfplumber.open(file) as pdf:
            for p in pdf.pages[:50]:
                extracted = p.extract_text()
                if extracted: text += extracted + "\n"
    except: pass
    return text

def get_news_and_wiki(name):
    news = []; wiki = "Information non disponible."
    try:
        url = f"https://fr.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(name)}"
        r = requests.get(url, timeout=2)
        if r.status_code == 200: wiki = r.json().get('extract', wiki)
    except: pass
    
    try:
        q = urllib.parse.quote(f'"{name}" (finance OR business OR environnement)')
        f = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
        news = [{"title": e.title, "link": e.link, "summary": e.title} for e in f.entries[:5]]
    except: pass
    return news, wiki

def get_weather_history(lat, lon):
    try:
        url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={(datetime.now()-timedelta(days=90)).strftime('%Y-%m-%d')}&end_date={datetime.now().strftime('%Y-%m-%d')}&daily=precipitation_sum&timezone=auto"
        r = requests.get(url, timeout=3).json()
        if 'daily' in r: return f"{sum([x for x in r['daily']['precipitation_sum'] if x]):.0f}"
    except: pass
    return "N/A"

def get_stock_advanced(ticker):
    try:
        s = yf.Ticker(ticker)
        m = s.fast_info.get('market_cap')
        if not m: m = s.info.get('marketCap', 0)
        return m
    except: return 0

# ==============================================================================
# 4. GENERATEUR DE RAPPORT PDF SECURISE
# ==============================================================================
def create_pdf_expert(data):
    pdf = FPDF()
    
    # --- PAGE 1 ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, f"RAPPORT D'AUDIT: {data.get('ent', 'N/A').upper()}", ln=1, align='C')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 10, f"Généré le {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. SYNTHESE EXECUTIVE", ln=1)
    pdf.set_font("Arial", '', 11)
    
    txt = data.get('txt_ia', 'Analyse en cours...')
    try: txt = txt.encode('latin-1', 'replace').decode('latin-1')
    except: txt = "Texte non encodable."
        
    pdf.multi_cell(0, 6, txt)
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "2. DONNEES FINANCIERES", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(60, 10, f"Valorisation: {data.get('valo',0):,.0f} EUR", border=1)
    pdf.cell(60, 10, f"Source: {data.get('source_ca', 'Manuel')}", border=1)
    pdf.ln(15)

    # --- PAGE 2 ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "3. ANALYSE RISQUE & CLIMAT", ln=1)
    pdf.set_font("Arial", '', 11)
    
    pdf.cell(0, 8, f"Localisation: {data.get('ville', 'N/A')} ({data.get('pays', 'N/A')})", ln=1)
    pdf.cell(0, 8, f"Score Risque Eau 2030: {data.get('s30', 0):.2f} / 5", ln=1)
    pdf.cell(0, 8, f"Pluviométrie (90j): {data.get('pluie_90j', 'N/A')} mm", ln=1)
    pdf.ln(5)
    
    var = data.get('var', 0)
    color = (200, 0, 0) if var > 0 else (0, 100, 0)
    pdf.set_text_color(*color)
    sign = "-" if var > 0 else "+"
    pdf.cell(0, 10, f"IMPACT FINANCIER (VAR 2030): {sign}{abs(var):,.0f} EUR", ln=1)
    pdf.set_text_color(0, 0, 0)
    
    # --- PAGE 3 ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "4. SOURCES & REFERENCES", ln=1)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Presse", ln=1)
    pdf.set_font("Arial", '', 10)
    
    for n in data.get('news', []):
        try:
            title = n['title'].encode('latin-1', 'replace').decode('latin-1')
            pdf.set_text_color(0, 0, 255)
            pdf.cell(0, 6, f">> {title}", ln=1, link=n['link'])
        except: continue
    pdf.set_text_color(0, 0, 0)
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# ==============================================================================
# 5. INTERFACE
# ==============================================================================
with st.sidebar:
    st.header("⚙️ Config")
    pappers_key = st.text_input("Clé Pappers", type="password")
    if st.button("🔄 Nouveau Dossier (Reset)"):
        st.session_state.clear()
        st.rerun()

col_left, col_right = st.columns([1, 1.5])

with col_left:
    st.subheader("1. Entreprise")
    ent_name = st.text_input("Nom", "Michel et Augustin")
    ville = st.text_input("Ville", "Issy-les-Moulineaux")
    pays = st.text_input("Pays", "France")
    
    st.markdown("---")
    st.subheader("2. Mode Valorisation")
    
    # --- LE RETOUR DU MENU DE CHOIX ---
    mode_val = st.radio("Sélectionnez le type d'entreprise :", ["Non Cotée (PME/ETI)", "Cotée (Bourse)", "Startup (VC)"])
    val_finale = 0.0
    source_info = "Manuel"

    # ------------------ MODE PME (NON COTEE) ------------------
    if mode_val == "Non Cotée (PME/ETI)":
        uploaded_pdf = st.file_uploader("Liasse Fiscale (PDF)", type=["pdf"])
        if uploaded_pdf:
            txt = read_pdf(uploaded_pdf)
            fin = extract_financials_smart(txt)
            if fin['found']:
                st.session_state.finance_ca = fin['ca']
                st.session_state.finance_res = fin['res']
                st.session_state.finance_cap = fin['cap']
                st.success(f"✅ PDF Lu ! CA: {fin['ca']:,.0f}€")
        
        ca = st.number_input("Chiffre d'Affaires (€)", key="finance_ca")
        res = st.number_input("Résultat Net (€)", key="finance_res")
        cap = st.number_input("Capitaux Propres (€)", key="finance_cap")
        
        methode = st.selectbox("Méthode Valo", ["Multiple CA", "Multiple EBITDA", "DCF"])
        
        if methode == "Multiple CA":
            mult = st.slider("Multiple", 0.5, 5.0, 1.5)
            val_finale = ca * mult
            source_info = f"CA x{mult}"
        elif methode == "Multiple EBITDA":
            ebitda = res * 1.25 # Approx
            mult = st.slider("Multiple", 2.0, 15.0, 7.0)
            val_finale = ebitda * mult
            source_info = f"EBITDA x{mult}"
        else: # DCF
            val_finale = res * 10
            source_info = "DCF Simplifié"

    # ------------------ MODE BOURSE (COTEE) ------------------
    elif mode_val == "Cotée (Bourse)":
        ticker = st.text_input("Ticker Yahoo Finance", "BN.PA")
        if st.button("Charger Cours"):
            mcap = get_stock_advanced(ticker)
            if mcap > 0:
                st.session_state.stock_data['mcap'] = mcap
                st.success(f"Market Cap trouvée : {mcap:,.0f} €")
            else:
                st.error("Ticker introuvable.")
        
        val_finale = st.number_input("Capitalisation Boursière (€)", value=float(st.session_state.stock_data['mcap']))
        source_info = f"Bourse ({ticker})"
        # Valeurs par défaut pour les ratios si non trouvées
        ca = val_finale * 0.5 
        res = val_finale * 0.05
        cap = val_finale * 0.3

    # ------------------ MODE STARTUP (VC) ------------------
    else:
        stade = st.selectbox("Stade de Maturité", ["Seed (2-8M)", "Series A (8-30M)", "Series B (30-80M)"])
        ranges = {"Seed": (2e6, 8e6), "Series A": (8e6, 30e6), "Series B": (30e6, 80e6)}
        mini, maxi = ranges.get(stade.split()[0], (1e6, 5e6))
        val_finale = st.slider("Valorisation (€)", mini, maxi, (mini+maxi)/2)
        source_info = f"Venture Capital ({stade})"
        # Startups font peu de CA/Res
        ca = val_finale * 0.1
        res = -val_finale * 0.2
        cap = val_finale * 0.2

    # --- CLIMAT ---
    st.markdown("---")
    secteur = st.selectbox("Secteur", ["Agroalimentaire (100%)", "Industrie (70%)", "Tech (5%)"])
    vuln = float(re.findall(r'\d+', secteur)[0])/100

    st.markdown("---")
    if st.button("🚀 LANCER L'AUDIT & RAPPORT", type="primary"):
        with st.spinner("Analyse en cours..."):
            news, wiki = get_news_and_wiki(ent_name)
            pluie = get_weather_history(48.85, 2.35)
            s24 = 2.5; s30 = s24 * 1.1
            var_amount = val_finale * (s30 - s24) * vuln
            
            txt_ia = f"Rapport généré pour {ent_name}.\n\nCONTEXTE :\n{wiki}\n\nANALYSE FINANCIERE :\nValorisation retenue : {val_finale:,.0f} EUR ({source_info}).\nDonnées clés : CA {ca:,.0f} EUR | Résultat {res:,.0f} EUR."
            
            st.session_state.audit_data = {
                "ent": ent_name, "ville": ville, "pays": pays,
                "valo": val_finale, "source_ca": source_info,
                "ca": ca, "res": res, "cap": cap,
                "s30": s30, "var": var_amount, "vuln": vuln, "pluie_90j": pluie,
                "news": news, "txt_ia": txt_ia
            }
            st.session_state.audit_done = True
            st.rerun()

with col_right:
    st.subheader("📊 Résultats de l'Audit")
    
    if st.session_state.audit_done:
        d = st.session_state.audit_data
        
        c1, c2 = st.columns(2)
        c1.metric("Valorisation", f"{d.get('valo', 0):,.0f} €", delta=d.get('source_ca'))
        c2.metric("Impact Climat 2030", f"{d.get('var', 0):,.0f} €", delta_color="inverse")
        
        summary = d.get('txt_ia', "Analyse en cours...")
        st.info(f"Résumé : {summary[:300]}...")
        
        st.write("### 📥 Téléchargements")
        pdf_bytes = create_pdf_expert(d)
        st.download_button("📄 Télécharger le Rapport Complet (PDF)", pdf_bytes, file_name="Audit_Expert_V25.pdf", mime="application/pdf")
        
        with st.expander("Voir les Sources"):
            for n in d.get('news', []): st.write(f"- [{n['title']}]({n['link']})")
            
    else:
        st.info("👈 Configurez l'entreprise à gauche et lancez l'audit.")
        
