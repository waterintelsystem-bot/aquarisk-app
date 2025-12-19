import streamlit as st
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
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
# 1. CONFIGURATION & STATE
# ==============================================================================
st.set_page_config(page_title="AquaRisk V15.3 : Stable", page_icon="🛡️", layout="wide")
st.title("🛡️ AquaRisk V15.3 : Version Blindée (Données & API)")

if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'live_multiples' not in st.session_state: st.session_state.live_multiples = None
if 'stock_data' not in st.session_state: st.session_state.stock_data = {"mcap": 0, "ev": 0}

# ==============================================================================
# 2. CHARGEMENT DATA (AVEC SÉCURITÉ RENFORCÉE)
# ==============================================================================
@st.cache_data
def load_data():
    # Données par défaut si le CSV plante ou n'existe pas
    DEFAULT_DATA = pd.DataFrame({
        'name_0': ['France', 'United States', 'Germany', 'China', 'India', 'Brazil', 'United Kingdom'],
        'name_1': ['Ile-de-France', 'California', 'Bavaria', 'Beijing', 'Maharashtra', 'Sao Paulo', 'London'],
        'score': [2.5, 3.8, 2.2, 4.1, 4.5, 2.8, 1.9]
    })

    def smart_read(filename):
        if not os.path.exists(filename): return None
        try:
            # Essai lecture standard
            df = pd.read_csv(filename, sep=None, engine='python', on_bad_lines='skip')
            df.columns = [c.lower().strip() for c in df.columns]
            
            # Vérification des colonnes vitales
            required = ['name_0', 'score']
            if not all(col in df.columns for col in required):
                return None # Fichier invalide, on rejette
            
            return df
        except: return None

    # Chargement Actuel
    df_now = smart_read("risk_actuel.csv")
    if df_now is None:
        df_now = DEFAULT_DATA # On utilise les données de secours
    else:
        df_now['score'] = pd.to_numeric(df_now['score'].astype(str).str.replace(',', '.'), errors='coerce')

    # Chargement Futur
    df_fut = smart_read("risk_futur.csv")
    if df_fut is None:
        # On simule le futur avec le présent + 10% de risque
        df_fut = df_now.copy()
        df_fut['score'] = df_fut['score'] * 1.1
    else:
        df_fut['score'] = pd.to_numeric(df_fut['score'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'year' in df_fut.columns:
            df_fut = df_fut[(df_fut['year'] == 2030) & (df_fut['scenario'] == 'bau')]
            
    return df_now, df_fut

try:
    df_actuel, df_futur = load_data()
except: st.stop()

# ==============================================================================
# 3. OUTILS API (PAPPERS & YAHOO)
# ==============================================================================

def get_pappers_financials(company_name, api_key):
    if not api_key: return None
    try:
        clean_key = api_key.strip()
        q = urllib.parse.quote(company_name)
        
        # 1. Recherche
        r = requests.get(f"https://api.pappers.fr/v2/recherche?q={q}&api_token={clean_key}&par_page=1", timeout=5)
        if r.status_code != 200 or not r.json().get('resultats'): return None
        
        match = r.json()['resultats'][0]
        siren = match['siren']
        
        # 2. Bilan
        f_r = requests.get(f"https://api.pappers.fr/v2/entreprise?api_token={clean_key}&siren={siren}", timeout=5)
        if f_r.status_code != 200: return None
        
        f_data = f_r.json()
        ca=0; res=0; cap=0; ebitda=0; annee="N/A"
        
        for c in f_data.get('finances', []):
            if c.get('annee_cloture_exercice'):
                ca = c.get('chiffre_affaires', 0) or 0
                res = c.get('resultat', 0) or 0
                cap = c.get('capitaux_propres', 0) or 0
                ebitda = res * 1.25 if res > 0 else 0 
                annee = c['annee_cloture_exercice']
                break
                
        return {"nom": match['nom_entreprise'], "ca": ca, "resultat": res, "capitaux": cap, "ebitda": ebitda, "annee": annee}
    except: return None

def get_stock_advanced(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.fast_info
        mcap = info.get('market_cap', 0)
        # Fallback classique
        if not mcap: mcap = stock.info.get('marketCap', 0)
        ev = stock.info.get('enterpriseValue', mcap)
        return mcap, ev
    except: return 0, 0

# ==============================================================================
# 4. GÉOGRAPHIE & INTELLIGENCE
# ==============================================================================
class MockLocation:
    def __init__(self, lat, lon): self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    # Base de secours
    fallback = {"paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "marseille": (43.2965, 5.3698), "bordeaux": (44.8378, -0.5792), "new york": (40.7128, -74.0060)}
    clean_v = ville.lower().strip()
    if clean_v in fallback: return MockLocation(*fallback[clean_v])

    for i in range(2):
        try:
            ua = f"AR_V153_{randint(1000,9999)}"
            loc = Nominatim(user_agent=ua, timeout=5).geocode(f"{ville}, {pays}", language='en')
            if loc: return loc
        except: time.sleep(1); continue
    return MockLocation(48.8566, 2.3522)

def get_company_news(company_name):
    q = urllib.parse.quote(f'"{company_name}" (eau OR pollution OR environnement)')
    try:
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
        return [{"title": e.title, "link": e.link, "summary": e.summary[:200]} for e in feed.entries[:5]]
    except: return []

def get_wiki_summary(company_name):
    wikipedia.set_lang('fr')
    try: return wikipedia.page(company_name).summary[:1000]
    except: return ""

def scan_website(url):
    if len(url) < 5: return ""
    if not url.startswith("http"): url = "https://" + url
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        return ' '.join([p.text for p in BeautifulSoup(r.text, 'html.parser').find_all('p')])[:5000]
    except: return ""

def extract_text_from_pdfs(uploaded_files):
    txt = ""; names = []
    if not uploaded_files: return "", []
    for f in uploaded_files:
        try:
            with pdfplumber.open(f) as pdf:
                for p in pdf.pages[:10]: txt += p.extract_text() or ""
                names.append(f.name)
        except: continue
    return txt, names

# ==============================================================================
# 5. MOTEUR ANALYSE
# ==============================================================================
def analyser_risque_geo(ville, pays):
    loc = get_location_safe(ville, pays)
    
    # Matching
    liste_pays = df_actuel['name_0'].unique()
    match_pays, score = process.extractOne(str(pays), liste_pays.astype(str))
    if score < 60: match_pays = pays

    # Scores
    s24 = 2.5
    if match_pays in df_actuel['name_0'].values:
        s24 = df_actuel[df_actuel['name_0'] == match_pays]['score'].mean()
    
    s30 = s24 * 1.1
    if df_futur is not None and match_pays in df_futur['name_0'].values:
        s30 = df_futur[df_futur['name_0'] == match_pays]['score'].mean()

    # Interpolation
    s26 = s24 + ((s30 - s24) * 0.33)
    
    return {
        "ent": "N/A", "ville": ville, "pays": match_pays, 
        "lat": loc.latitude, "lon": loc.longitude, 
        "s2024": s24, "s2026": s26, "s2030": s30, "found": True
    }

# ==============================================================================
# 6. PDF & CARTE
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
    
    # Header
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(0, 10, clean(f"AUDIT V15.3: {data.get('ent', 'N/A').upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    # Carte
    if data.get('lat'):
        f = generer_carte(data['lat'], data['lon'])
        if f: pdf.image(f, x=20, w=170)
    pdf.ln(5)
    
    # Chiffres
    pdf.set_font("Arial", 'B', 12)
    val = data.get('valeur_entreprise', 0)
    var = data.get('var_2030', 0)
    pdf.cell(0, 10, clean(f"Valorisation: {val:,.0f} $ | VaR 2030: {var:,.0f} $"), ln=1)
    
    # Risque
    s24 = data.get('s2024', 2.5); s30 = data.get('s2030', 2.5)
    pdf.cell(0, 10, f"Trajectoire Risque Eau: {s24:.2f} (2024) -> {s30:.2f} (2030)", ln=1)
    
    # Texte
    pdf.ln(5)
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 5, clean(f"Synthese: {data.get('txt_ia', '')}"))
    
    # Sources
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "SOURCES", ln=1)
    pdf.set_font("Arial", size=10)
    
    if data.get('news'):
        for n in data['news']:
            pdf.set_text_color(0,0,255)
            pdf.cell(0, 6, clean(f">> {n['title']}"), ln=1, link=n['link'])
            pdf.set_text_color(0,0,0)
            pdf.multi_cell(0, 5, clean(f"{n['summary']}"))
            pdf.ln(2)
            
    return pdf.output(dest='S').encode('latin-1', 'replace')

# ==============================================================================
# 7. INTERFACE
# ==============================================================================
with st.sidebar:
    st.header("⚙️ Config")
    pappers_key = st.text_input("Clé Pappers", type="password")
    if st.button("Actualiser Taux"):
        st.session_state.live_multiples = {"Logiciel": {"ca": 5.5, "ebitda": 18.0}, "Industrie": {"ca": 0.8, "ebitda": 7.0}}
        st.success("Taux mis à jour")

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
    
    # Vulnérabilité
    secteur_risk = st.selectbox("Secteur (Vulnérabilité)", ["Agroalimentaire", "Industrie", "BTP", "Commerce", "Logiciel"])
    vuln_factor = {"Agroalimentaire": 1.0, "Industrie": 0.7, "BTP": 0.4, "Commerce": 0.2, "Logiciel": 0.05}.get(secteur_risk, 0.5)

    if mode_val == "Non Cotée":
        if st.button("🔍 Pappers"):
            with st.spinner("API..."):
                i = get_pappers_financials(ent, pappers_key)
                if i: 
                    st.session_state.pappers_data = i
                    st.success("Bilan trouvé !")
                else: st.warning("Pas de bilan trouvé (Mode Manuel)")
        
        ca_val = 1000000.0; res_val = 100000.0; cap_val = 200000.0
        if st.session_state.pappers_data:
            d = st.session_state.pappers_data
            if d['ca']: ca_val = float(d['ca'])
            if d['resultat']: res_val = float(d['resultat'])
            if d['capitaux']: cap_val = float(d['capitaux'])

        m_pme = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "DCF", "Patrimonial"])
        
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

    elif mode_val == "Cotée":
        ticker = st.text_input("Ticker", "BN.PA")
        if st.button("Yahoo"):
            m, e = get_stock_advanced(ticker)
            if m > 0: st.session_state.stock_data = {"mcap": m, "ev": e}
        valeur_finale = st.number_input("Valo", value=st.session_state.stock_data['mcap'])
    
    else: # Startup
        valeur_finale = st.slider("Valo", 1000000.0, 50000000.0, 5000000.0)

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
                doc_txt, doc_n = extract_text_from_pdfs(uploaded_docs)
                
                corpus = f"{notes} {web} {wiki} {doc_txt} {' '.join([n['title'] for n in news])}"
                
                d26 = max(0, res['s2026'] - 1.5)
                d30 = max(0, res['s2030'] - 1.5)
                var26 = valeur_finale * (d26/5) * vuln_factor
                var30 = valeur_finale * (d30/5) * vuln_factor
                
                alerts = sum(1 for w in ['litige', 'procès', 'amende'] if w in corpus.lower())
                txt_ia = f"Analyse sur {len(doc_n)} documents. {alerts} alertes détectées."
                
                final = {
                    "ent": ent, "ville": v, "pays": res['pays'], 
                    "lat": res['lat'], "lon": res['lon'],
                    "valeur_entreprise": valeur_finale, "source_ca": source_info,
                    "s2024": res['s2024'], "s2026": res['s2026'], "s2030": res['s2030'],
                    "var_2030": var30, "var_2026": var26,
                    "news": news, "doc_files": doc_n, "txt_ia": txt_ia,
                    "pluie_90j": get_weather_history(res['lat'], res['lon']),
                    "full_text": corpus
                }
                st.session_state.audit_unique = final
                st.rerun()

with c2:
    if st.session_state.audit_unique:
        r = st.session_state.audit_unique
        st.success(f"Audit : {r.get('ent')}")
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Valo", f"{r.get('valeur_entreprise',0):,.0f} $")
        k2.metric("Risque 2030", f"{r.get('s2030',0):.2f}/5", delta=f"{r.get('s2030',0)-r.get('s2024',0):.2f}", delta_color="inverse")
        k3.metric("Perte 2030", f"{r.get('var_2030',0):,.0f} $", delta="-Impact", delta_color="inverse")
        
        st.info(f"Météo: {r.get('pluie_90j')} mm | Synthèse: {r.get('txt_ia')}")
        
        t1, t2 = st.tabs(["Rapport", "Sources"])
        with t1:
            if r.get('full_text'):
                pdf = create_pdf(r, r['full_text'], notes)
                st.download_button("Télécharger PDF", pdf, file_name="Rapport.pdf")
            if r.get('lat'):
                m = folium.Map([r['lat'], r['lon']], zoom_start=10)
                folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color='red')).add_to(m)
                st_folium(m, height=300)
        with t2:
            for n in r.get('news', []): st.markdown(f"- [{n['title']}]({n['link']})")
                
