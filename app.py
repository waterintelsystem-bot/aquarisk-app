import streamlit as st
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import folium
from streamlit_folium import st_folium
import time
from random import randint
from fpdf import FPDF
import io
import feedparser
import urllib.parse
import re
import os
import requests
from bs4 import BeautifulSoup
import wikipedia
import pdfplumber
import yfinance as yf
from thefuzz import process
from datetime import datetime, timedelta
from staticmap import StaticMap, CircleMarker

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
st.set_page_config(page_title="AquaRisk V17.3 : Sans Échec", page_icon="🛡️", layout="wide")
st.title("🛡️ AquaRisk V17.3 : Plateforme Audit (Mode Résilient)")

# Initialisation Session
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'live_multiples' not in st.session_state: st.session_state.live_multiples = None
if 'stock_data' not in st.session_state: st.session_state.stock_data = {"mcap": 0, "ev": 0}

# ==============================================================================
# 2. CHARGEMENT DATA (GARANTI SANS CRASH)
# ==============================================================================
@st.cache_data
def get_dataset():
    # 1. Création de données de secours (Backup)
    data_backup = {
        'name_0': ['France', 'United States', 'Germany', 'China', 'India', 'Brazil', 'United Kingdom', 'Italy', 'Spain'],
        'name_1': ['Ile-de-France', 'California', 'Bavaria', 'Beijing', 'Maharashtra', 'Sao Paulo', 'London', 'Lombardy', 'Madrid'],
        'score': [2.5, 3.8, 2.2, 4.1, 4.5, 2.8, 1.9, 2.6, 3.1]
    }
    df_backup = pd.DataFrame(data_backup)

    # 2. Tentative de lecture CSV Actuel
    df_now = df_backup.copy()
    if os.path.exists("risk_actuel.csv"):
        try:
            temp = pd.read_csv("risk_actuel.csv", sep=None, engine='python', on_bad_lines='skip')
            temp.columns = [c.lower().strip() for c in temp.columns]
            if 'name_0' in temp.columns and 'score' in temp.columns:
                temp['score'] = pd.to_numeric(temp['score'].astype(str).str.replace(',', '.'), errors='coerce')
                df_now = temp
        except: pass # Si erreur, on garde le backup

    # 3. Tentative de lecture CSV Futur
    df_fut = df_now.copy()
    df_fut['score'] = df_fut['score'] * 1.15 # Projection par défaut
    
    if os.path.exists("risk_futur.csv"):
        try:
            temp = pd.read_csv("risk_futur.csv", sep=None, engine='python', on_bad_lines='skip')
            temp.columns = [c.lower().strip() for c in temp.columns]
            if 'name_0' in temp.columns and 'score' in temp.columns:
                temp['score'] = pd.to_numeric(temp['score'].astype(str).str.replace(',', '.'), errors='coerce')
                # Filtre 2030 si colonnes existent
                if 'year' in temp.columns:
                    temp = temp[(temp['year'] == 2030)]
                df_fut = temp
        except: pass

    return df_now, df_fut

# Chargement direct sans Try/Except bloquant
df_actuel, df_futur = get_dataset()

# ==============================================================================
# 3. FONCTIONS TECHNIQUES (API & CALCULS)
# ==============================================================================

# --- GPS ---
class MockLocation:
    def __init__(self, lat, lon): self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    # Fallback immédiat pour éviter les temps d'attente
    clean_v = ville.lower().strip()
    fallback = {
        "paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "marseille": (43.2965, 5.3698),
        "bordeaux": (44.8378, -0.5792), "toulouse": (43.6047, 1.4442), "lille": (50.6292, 3.0573),
        "new york": (40.7128, -74.0060), "london": (51.5074, -0.1278), "berlin": (52.5200, 13.4050), 
        "boulogne-billancourt": (48.8397, 2.2399)
    }
    if clean_v in fallback: return MockLocation(*fallback[clean_v])

    try:
        ua = f"AR_V173_{randint(1000,9999)}"
        loc = Nominatim(user_agent=ua, timeout=5).geocode(f"{ville}, {pays}")
        if loc: return loc
    except: pass
    
    return MockLocation(48.8566, 2.3522) # Default Paris

# --- API EXTERNES ---
def get_pappers_financials(company_name, api_key):
    if not api_key: return None
    try:
        clean_key = api_key.strip()
        r = requests.get(f"https://api.pappers.fr/v2/recherche?q={urllib.parse.quote(company_name)}&api_token={clean_key}&par_page=1", timeout=5)
        if r.status_code != 200: return None
        res = r.json().get('resultats')
        if not res: return None
        
        siren = res[0]['siren']
        fr = requests.get(f"https://api.pappers.fr/v2/entreprise?api_token={clean_key}&siren={siren}", timeout=5)
        fd = fr.json()
        
        ca=0; res=0; cap=0; annee="N/A"
        for c in fd.get('finances', []):
            if c.get('annee_cloture_exercice'):
                ca = c.get('chiffre_affaires', 0) or 0
                res = c.get('resultat', 0) or 0
                cap = c.get('capitaux_propres', 0) or 0
                annee = c['annee_cloture_exercice']
                break
        return {"nom": res[0]['nom_entreprise'], "ca": ca, "resultat": res, "capitaux": cap, "annee": annee}
    except: return None

def get_stock_advanced(ticker):
    try:
        s = yf.Ticker(ticker)
        m = s.fast_info.get('market_cap')
        if not m: m = s.info.get('marketCap', 0)
        e = s.info.get('enterpriseValue', m)
        return m, e
    except: return 0, 0

def get_weather_history(lat, lon):
    try:
        url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={(datetime.now()-timedelta(days=90)).strftime('%Y-%m-%d')}&end_date={datetime.now().strftime('%Y-%m-%d')}&daily=precipitation_sum&timezone=auto"
        r = requests.get(url, timeout=4).json()
        if 'daily' in r: return f"{sum([x for x in r['daily']['precipitation_sum'] if x]):.0f}"
    except: pass
    return "N/A"

def get_company_news(name):
    try:
        q = urllib.parse.quote(f'"{name}" (eau OR pollution OR environnement)')
        f = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
        return [{"title": e.title, "link": e.link, "summary": e.summary[:200]} for e in f.entries[:5]]
    except: return []

def get_wiki_summary(name):
    try:
        wikipedia.set_lang('fr')
        # Recherche d'abord
        search = wikipedia.search(name)
        if search: return wikipedia.page(search[0]).summary[:1000]
    except: pass
    return "Pas de données Wikipedia."

def scan_website(url):
    if len(url) < 5: return ""
    if not url.startswith("http"): url = "https://" + url
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        return ' '.join([p.text for p in BeautifulSoup(r.text, 'html.parser').find_all('p')])[:5000]
    except: return ""

def extract_text_from_pdfs(files):
    t=""; n=[]
    if not files: return "", []
    for f in files:
        try:
            with pdfplumber.open(f) as pdf:
                for p in pdf.pages[:5]: t += p.extract_text() or ""
                n.append(f.name)
        except: continue
    return t, n

# ==============================================================================
# 4. MOTEUR ANALYSE (RISQUE & VALO)
# ==============================================================================
def analyser_risque_geo(ville, pays):
    loc = get_location_safe(ville, pays)
    
    # Matching simple
    pays_match = pays
    if not df_actuel.empty:
        best, score = process.extractOne(str(pays), df_actuel['name_0'].unique().astype(str))
        if score > 60: pays_match = best

    # Scores
    s24 = 2.5
    if pays_match in df_actuel['name_0'].values:
        s24 = df_actuel[df_actuel['name_0'] == pays_match]['score'].mean()
    
    s30 = s24 * 1.1
    if not df_futur.empty and pays_match in df_futur['name_0'].values:
        s30 = df_futur[df_futur['name_0'] == pays_match]['score'].mean()

    s26 = s24 + ((s30 - s24) * 0.33)
    
    return {
        "ent": "N/A", "ville": ville, "pays": pays_match, 
        "lat": loc.latitude, "lon": loc.longitude, 
        "s2024": s24, "s2026": s26, "s2030": s30, "found": True
    }

# ==============================================================================
# 5. PDF
# ==============================================================================
def generer_carte(lat, lon):
    try:
        m = StaticMap(800, 400)
        m.add_marker(CircleMarker((lon, lat), 'red', 18))
        img = m.render(zoom=10)
        img.save("temp_map.png")
        return "temp_map.png"
    except: return None

def create_pdf(data, corpus, notes):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(0, 15, clean(f"AUDIT V17.3: {data.get('ent', 'N/A').upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    if data.get('lat'):
        f = generer_carte(data['lat'], data['lon'])
        if f: pdf.image(f, x=20, w=170)
    pdf.ln(5)
    
    # Finance
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. FINANCE & IMPACT", ln=1)
    pdf.set_font("Arial", size=11)
    
    val = data.get('valeur_entreprise', 0)
    var = data.get('var_2030', 0)
    
    pdf.cell(60, 10, clean(f"Valo: {val:,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"Methode: {data.get('source_ca', 'Manuel')}"), border=1)
    
    if var > 0:
        pdf.set_text_color(200,0,0) # Rouge
        txt_var = f"PERTE Estimee 2030: -{abs(var):,.0f} $"
    elif var < 0:
        pdf.set_text_color(0,100,0) # Vert
        txt_var = f"GAIN / STABILITE: +{abs(var):,.0f} $"
    else:
        pdf.set_text_color(0,0,0)
        txt_var = "Impact Neutre"
        
    pdf.cell(60, 10, clean(txt_var), border=1)
    pdf.set_text_color(0,0,0)
    pdf.ln(15)
    
    # Climat
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "2. CLIMAT & SYNTHESE", ln=1)
    pdf.set_font("Arial", size=11)
    
    s24 = data.get('s2024', 2.5); s30 = data.get('s2030', 2.5)
    pdf.cell(60, 10, f"Score 2024: {s24:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Proj 2030: {s30:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Meteo (90j): {data.get('pluie_90j', 'N/A')} mm", border=1, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 5, clean(f"Synthese IA:\n{data.get('txt_ia', '')}"))
    pdf.ln(5)
    
    # Sources
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "3. SOURCES", ln=1)
    pdf.set_font("Arial", size=10)
    
    if data.get('news'):
        for n in data['news']:
            pdf.set_text_color(0,0,255)
            pdf.cell(0, 6, clean(f">> {n['title']}"), ln=1, link=n['link'])
            pdf.set_text_color(0,0,0)
            pdf.multi_cell(0, 5, clean(f"{n['summary']}"))
            pdf.ln(2)
            
    if notes:
        pdf.ln(5)
        pdf.set_font("Arial", 'I', 10)
        pdf.multi_cell(0, 6, clean(f"Notes Analyste: {notes}"))
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# ==============================================================================
# 6. INTERFACE
# ==============================================================================
with st.sidebar:
    st.header("⚙️ Config")
    pappers_key = st.text_input("Clé Pappers", type="password")

c1, c2 = st.columns([1, 2])

with c1:
    st.subheader("1. Cible")
    ent = st.text_input("Nom", "Michel et Augustin")
    v = st.text_input("Ville", "Boulogne-Billancourt")
    p = st.text_input("Pays", "France")
    website = st.text_input("Web", "")
    
    st.markdown("---")
    st.subheader("2. Finance")
    mode_val = st.radio("Type", ["Non Cotée", "Cotée", "Startup"])
    valeur_finale = 0.0
    source_info = "Manuel"
    
    secteur_risk = st.selectbox("Secteur (Vulnérabilité)", ["Agroalimentaire (100%)", "Industrie (70%)", "BTP (40%)", "Commerce (20%)", "Logiciel (5%)"])
    vuln_factor = {"Agroalimentaire": 1.0, "Industrie": 0.7, "BTP": 0.4, "Commerce": 0.2, "Logiciel": 0.05}.get(secteur_risk.split()[0], 0.5)

    # --- NON COTÉE ---
    if mode_val == "Non Cotée":
        if st.button("🔍 Pappers"):
            with st.spinner("API..."):
                i = get_pappers_financials(ent, pappers_key)
                if i: 
                    st.session_state.pappers_data = i
                    st.success("Bilan trouvé !")
                else: st.warning("Pas de bilan (Clé ou Ent. invalide)")
        
        ca_val = 1000000.0; res_val = 100000.0; cap_val = 200000.0
        if st.session_state.pappers_data:
            d = st.session_state.pappers_data
            if d['ca']: ca_val = float(d['ca'])
            if d['resultat']: res_val = float(d['resultat'])
            if d['capitaux']: cap_val = float(d['capitaux'])

        m_pme = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "DCF", "Patrimonial"])
        
        val_calc = 0.0
        if "CA" in m_pme:
            val_calc = st.number_input("CA (€)", value=ca_val) * 1.5
        elif "EBITDA" in m_pme:
            val_calc = st.number_input("EBITDA (€)", value=res_val) * 7.0
        elif "DCF" in m_pme:
            fcf = st.number_input("FCF", value=res_val)
            val_calc = fcf * (1.02) / (0.10 - 0.02)
        else:
            val_calc = st.number_input("Capitaux", value=cap_val)
            
        valeur_finale = st.number_input("Valo Retenue", value=val_calc)
        source_info = m_pme

    # --- COTÉE ---
    elif mode_val == "Cotée":
        ticker = st.text_input("Ticker", "BN.PA")
        ind = st.selectbox("Indicateur", ["Market Cap", "Enterprise Value"])
        if st.button("Yahoo"):
            m, e = get_stock_advanced(ticker)
            if m > 0: st.session_state.stock_data = {"mcap":m, "ev":e}
        
        ref = st.session_state.stock_data.get('mcap', 0)
        if ind == "Enterprise Value": ref = st.session_state.stock_data.get('ev', 0)
        valeur_finale = st.number_input("Valo Retenue", value=ref if ref > 0 else 1000000.0)
        source_info = f"Bourse {ticker}"

    # --- STARTUP ---
    else: 
        st.info("Méthode VC Standard")
        stade = st.selectbox("Stade", ["Pre-Seed", "Seed", "Series A", "Series B"])
        ranges = {"Pre-Seed": (0.5, 2), "Seed": (2, 8), "Series A": (8, 30), "Series B": (30, 80)}
        mini, maxi = ranges.get(stade, (1, 5))
        st.caption(f"Range: {mini}M - {maxi}M")
        valeur_finale = st.slider("Valo (M$)", mini*1e6, maxi*1e6, (mini+maxi)/2 * 1e6)
        source_info = f"VC {stade}"

    st.markdown("---")
    st.write("📂 **3. Data Room**")
    notes = st.text_area("Notes", height=100)
    uploaded_docs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 AUDIT"):
        with st.spinner("Analyse..."):
            res = analyser_risque_geo(v, p)
            if res['found']:
                news = get_company_news(ent)
                wiki = get_wiki_summary(ent)
                web = scan_website(website)
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_txt, doc_n = extract_text_from_pdfs(uploaded_docs)
                
                corpus = f"{notes} {web} {wiki} {doc_txt} {' '.join([n['title'] for n in news])}"
                
                # Calcul Delta VaR
                delta_risk = res['s2030'] - res['s2024']
                impact_30 = valeur_finale * (delta_risk / 5.0) * vuln_factor
                impact_26 = valeur_finale * ((res['s2026'] - res['s2024']) / 5.0) * vuln_factor
                
                alerts = sum(1 for w in ['litige', 'procès', 'amende', 'pollution'] if w in corpus.lower())
                txt_ia = f"Analyse {len(doc_n)} docs. {alerts} alertes. Contexte: {wiki[:300]}..."
                
                final = {
                    "ent": ent, "ville": v, "pays": res['pays'], 
                    "lat": res['lat'], "lon": res['lon'],
                    "valeur_entreprise": valeur_finale, "source_ca": source_info,
                    "s2024": res['s2024'], "s2026": res['s2026'], "s2030": res['s2030'],
                    "var_2030": impact_30, "var_2026": impact_26, "vuln_percent": vuln_factor,
                    "news": news, "doc_files": doc_n, "txt_ia": txt_ia,
                    "pluie_90j": pluie, "full_text": corpus
                }
                st.session_state.audit_unique = final
                st.rerun()

with c2:
    if st.session_state.audit_unique:
        r = st.session_state.audit_unique
        st.success(f"Audit : {r.get('ent')}")
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Valo", f"{r.get('valeur_entreprise',0):,.0f} $")
        
        delta_r = r.get('s2030',0)-r.get('s2024',0)
        k2.metric("Trajectoire", f"{r.get('s2030',0):.2f}/5", delta=f"{delta_r:.2f}", delta_color="inverse")
        
        var_30 = r.get('var_2030', 0)
        label_var = f"{var_30:,.0f} $"
        color_var = "inverse" if var_30 > 0 else "normal"
        k3.metric("Impact 2030", label_var, delta="VaR", delta_color=color_var)
        
        st.info(f"Météo: {r.get('pluie_90j')} mm | Vulnérabilité: {r.get('vuln_percent',0)*100:.0f}%")
        
        t1, t2 = st.tabs(["Rapport PDF", "Sources"])
        with t1:
            if r.get('full_text'):
                pdf = create_pdf(r, r['full_text'], notes)
                st.download_button("📥 Télécharger PDF", pdf, file_name="Rapport.pdf")
            if r.get('lat'):
                m = folium.Map([r['lat'], r['lon']], zoom_start=10)
                folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color='red')).add_to(m)
                st_folium(m, height=300)
        with t2:
            for n in r.get('news', []): st.markdown(f"- [{n['title']}]({n['link']})")
                
