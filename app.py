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
st.set_page_config(page_title="AquaRisk V16.2 : Expert", page_icon="💎", layout="wide")
st.title("💎 AquaRisk V16.2 : Audit Financier & Climatique Détaillé")

if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'live_multiples' not in st.session_state: st.session_state.live_multiples = None
if 'stock_data' not in st.session_state: st.session_state.stock_data = {"mcap": 0, "ev": 0}

# ==============================================================================
# 2. CHARGEMENT DATA (SECURISE)
# ==============================================================================
@st.cache_data
def load_data():
    # Données de secours
    BACKUP_DATA = pd.DataFrame({
        'name_0': ['France', 'United States', 'Germany', 'China', 'India', 'Brazil', 'United Kingdom'],
        'name_1': ['Ile-de-France', 'California', 'Bavaria', 'Beijing', 'Maharashtra', 'Sao Paulo', 'London'],
        'score': [2.5, 3.8, 2.2, 4.1, 4.5, 2.8, 1.9]
    })

    def smart_read(filename):
        if not os.path.exists(filename): return None
        try:
            for sep in [',', ';', '\t']:
                try:
                    df = pd.read_csv(filename, sep=sep, engine='python', on_bad_lines='skip')
                    df.columns = [c.lower().strip() for c in df.columns]
                    if 'name_0' in df.columns and 'score' in df.columns: return df
                except: continue
            return None
        except: return None

    df_now = smart_read("risk_actuel.csv")
    if df_now is None: df_now = BACKUP_DATA
    else: df_now['score'] = pd.to_numeric(df_now['score'].astype(str).str.replace(',', '.'), errors='coerce')

    df_fut = smart_read("risk_futur.csv")
    if df_fut is None:
        df_fut = df_now.copy()
        df_fut['score'] = df_fut['score'] * 1.15 # Projection par défaut
    else:
        df_fut['score'] = pd.to_numeric(df_fut['score'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'year' in df_fut.columns:
            df_fut = df_fut[(df_fut['year'] == 2030) & (df_fut['scenario'] == 'bau')]

    return df_now, df_fut

try:
    df_actuel, df_futur = load_data()
except: st.stop()

# ==============================================================================
# 3. OUTILS TECH (GPS, API, METEO)
# ==============================================================================
class MockLocation:
    def __init__(self, lat, lon): self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    clean_v = ville.lower().strip()
    fallback = {
        "paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "marseille": (43.2965, 5.3698),
        "bordeaux": (44.8378, -0.5792), "toulouse": (43.6047, 1.4442), "new york": (40.7128, -74.0060),
        "london": (51.5074, -0.1278), "berlin": (52.5200, 13.4050), "boulogne-billancourt": (48.8397, 2.2399)
    }
    if clean_v in fallback: return MockLocation(*fallback[clean_v])

    for i in range(2):
        try:
            ua = f"AR_V162_{randint(1000,9999)}"
            loc = Nominatim(user_agent=ua, timeout=8).geocode(f"{ville}, {pays}")
            if loc: return loc
        except: time.sleep(1); continue
    return MockLocation(48.8566, 2.3522)

def get_weather_history(lat, lon):
    try:
        url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={(datetime.now()-timedelta(days=90)).strftime('%Y-%m-%d')}&end_date={datetime.now().strftime('%Y-%m-%d')}&daily=precipitation_sum&timezone=auto"
        r = requests.get(url, timeout=5).json()
        if 'daily' in r: return f"{sum([x for x in r['daily']['precipitation_sum'] if x]):.0f}"
    except: pass
    return "N/A"

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
        # Estime EBITDA ~ Résultat + 25%
        return {"nom": res[0]['nom_entreprise'], "ca": ca, "resultat": res, "capitaux": cap, "ebitda": res*1.25, "annee": annee}
    except: return None

def get_stock_advanced(ticker):
    try:
        s = yf.Ticker(ticker)
        m = s.fast_info.get('market_cap')
        if not m: m = s.info.get('marketCap', 0)
        e = s.info.get('enterpriseValue', m)
        return m, e
    except: return 0, 0

def get_company_news(name):
    try:
        q = urllib.parse.quote(f'"{name}" (eau OR pollution OR environnement)')
        f = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
        return [{"title": e.title, "link": e.link, "summary": e.summary[:250]} for e in f.entries[:5]]
    except: return []

def extract_text_from_pdfs(files):
    t=""; n=[]
    if not files: return "", []
    for f in files:
        try:
            with pdfplumber.open(f) as pdf:
                for p in pdf.pages[:10]: t += p.extract_text() or ""
                n.append(f.name)
        except: continue
    return t, n

# ==============================================================================
# 4. MOTEUR ANALYSE
# ==============================================================================
def analyser_risque_geo(ville, pays):
    loc = get_location_safe(ville, pays)
    pays_match, score = process.extractOne(str(pays), df_actuel['name_0'].unique().astype(str))
    if score < 60: pays_match = pays

    s24 = 2.5
    if pays_match in df_actuel['name_0'].values:
        s24 = df_actuel[df_actuel['name_0'] == pays_match]['score'].mean()
    
    s30 = s24 * 1.1
    if df_futur is not None and pays_match in df_futur['name_0'].values:
        s30 = df_futur[df_futur['name_0'] == pays_match]['score'].mean()

    # Interpolation linéaire
    s26 = s24 + ((s30 - s24) * (2/6))
    
    return {
        "ent": "N/A", "ville": ville, "pays": pays_match, 
        "lat": loc.latitude, "lon": loc.longitude, 
        "s2024": s24, "s2026": s26, "s2030": s30, "found": True
    }

# ==============================================================================
# 5. PDF GENERATOR (COMPLET)
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
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, clean(f"RAPPORT D'AUDIT: {data.get('ent', 'N/A').upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    # Carte
    if data.get('lat'):
        f = generer_carte(data['lat'], data['lon'])
        if f: pdf.image(f, x=20, w=170)
    pdf.ln(5)
    
    # 1. FINANCE
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. VALORISATION & IMPACT FINANCIER", ln=1)
    pdf.set_font("Arial", size=11)
    
    val = data.get('valeur_entreprise', 0)
    var = data.get('var_2030', 0)
    vuln = data.get('vuln_percent', 0) * 100
    
    pdf.cell(60, 10, clean(f"Valorisation: {val:,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"Methode: {data.get('source_ca', 'Manuel')}"), border=1)
    
    # Affichage intelligent du risque
    if var > 0:
        pdf.set_text_color(200, 0, 0) # Rouge
        label_var = f"PERTE Estimee (VaR): -{var:,.0f} $"
    else:
        pdf.set_text_color(0, 100, 0) # Vert
        label_var = "Impact Financier: STABLE"
        
    pdf.cell(60, 10, clean(label_var), border=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(10)
    
    # Explication VaR
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 5, clean(f"Explication: Ce calcul prend en compte une vulnerabilite sectorielle de {vuln:.0f}% et l'evolution du stress hydrique local."))
    pdf.ln(5)

    # 2. CLIMAT & METEO
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "2. TRAJECTOIRE CLIMATIQUE & METEO", ln=1)
    pdf.set_font("Arial", size=11)
    
    s24 = data.get('s2024', 2.5); s26 = data.get('s2026', 2.5); s30 = data.get('s2030', 2.5)
    pdf.cell(60, 10, f"Score 2024: {s24:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Proj 2026: {s26:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Proj 2030: {s30:.2f}/5", border=1, align='C')
    pdf.ln(10)
    
    # Météo
    pluie = data.get('pluie_90j', 'N/A')
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 10, f"Meteo Locale (Cumul Pluie 90j): {pluie} mm", ln=1)
    pdf.ln(5)
    
    # IA Synthèse
    pdf.set_font("Arial", 'I', 11)
    pdf.multi_cell(0, 6, clean(f"Synthese IA: {data.get('txt_ia', '')}"))
    
    # 3. DETAILS
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "3. NOTES, SOURCES & DATA ROOM", ln=1)
    pdf.ln(5)
    
    # Notes manuelles
    if notes:
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Vos Notes d'Audit:", ln=1)
        pdf.set_font("Arial", '', 10)
        pdf.multi_cell(0, 5, clean(notes))
        pdf.ln(5)

    # News
    if data.get('news'):
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Revue de Presse (Liens Cliquables)", ln=1)
        for n in data['news']:
            pdf.set_font("Arial", 'U', 10) 
            pdf.set_text_color(0, 0, 255) 
            pdf.cell(0, 6, clean(f">> {n['title']}"), ln=1, link=n['link'])
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Arial", '', 9)
            pdf.multi_cell(0, 5, clean(f"{n['summary']}"))
            pdf.ln(2)
            
    return pdf.output(dest='S').encode('latin-1', 'replace')

# ==============================================================================
# 6. INTERFACE
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
    st.subheader("2. Finance & Impact")
    
    mode_val = st.radio("Type", ["Non Cotée", "Cotée", "Startup"])
    valeur_finale = 0.0; source_info = "Manuel"
    
    # Vulnérabilité (IMPACT EAU)
    secteur_risk = st.selectbox("Secteur (Vulnérabilité & Multiples)", 
                                ["Agroalimentaire (Risk: 100%)", "Industrie (Risk: 70%)", 
                                 "BTP (Risk: 40%)", "Commerce (Risk: 20%)", "Logiciel (Risk: 5%)"])
    
    # Extraction du facteur de vulnérabilité (0.0 à 1.0)
    vuln_factor = {"Agroalimentaire": 1.0, "Industrie": 0.7, "BTP": 0.4, "Commerce": 0.2, "Logiciel": 0.05}.get(secteur_risk.split()[0], 0.5)

    if mode_val == "Non Cotée":
        if st.button("🔍 Pappers"):
            with st.spinner("API..."):
                i = get_pappers_financials(ent, pappers_key)
                if i: 
                    st.session_state.pappers_data = i
                    st.success("Données Pappers chargées !")
                else: st.warning("Pas de donnée (Clé ou Ent. invalide)")
        
        ca_val = 1000000.0; res_val = 100000.0; cap_val = 200000.0
        if st.session_state.pappers_data:
            d = st.session_state.pappers_data
            if d['ca']: ca_val = float(d['ca'])
            if d['resultat']: res_val = float(d['resultat'])
            if d['capitaux']: cap_val = float(d['capitaux'])

        m_pme = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "DCF", "Patrimonial"])
        
        val_calc = 0.0
        if "Multiple CA" in m_pme:
            base = st.number_input("Chiffre d'Affaires (€)", value=ca_val)
            coeff = {"Agroalimentaire": 1.1, "Industrie": 0.8, "Logiciel": 5.5}.get(secteur_risk.split()[0], 1.0)
            val_calc = base * coeff
            source_info = f"CA x{coeff}"
            
        elif "Multiple EBITDA" in m_pme:
            base = st.number_input("EBITDA (€)", value=res_val)
            coeff = {"Agroalimentaire": 9.5, "Industrie": 7.0, "Logiciel": 18.0}.get(secteur_risk.split()[0], 7.0)
            val_calc = base * coeff
            source_info = f"EBITDA x{coeff}"
            
        elif "DCF" in m_pme:
            fcf = st.number_input("Flux Trésorerie (FCF)", value=res_val)
            g = st.slider("Croissance %", 0.0, 10.0, 2.0)/100
            wacc = st.slider("WACC %", 5.0, 15.0, 10.0)/100
            if wacc > g: val_calc = fcf * (1+g) / (wacc-g)
            source_info = "DCF Gordon"
            
        elif "Patrimonial" in m_pme:
            val_calc = st.number_input("Capitaux Propres", value=cap_val)
            source_info = "Actif Net"

        st.info(f"Calculé: {val_calc:,.0f} €")
        valeur_finale = st.number_input("Valo Retenue", value=val_calc)

    elif mode_val == "Cotée":
        ticker = st.text_input("Ticker", "BN.PA")
        ind = st.selectbox("Indicateur", ["Market Cap", "Enterprise Value"])
        if st.button("Yahoo"):
            m, e = get_stock_advanced(ticker)
            if m > 0: st.session_state.stock_data = {"mcap":m, "ev":e}
        
        ref = st.session_state.stock_data.get('mcap', 0)
        if ind == "Enterprise Value": ref = st.session_state.stock_data.get('ev', 0)
        valeur_finale = st.number_input("Valo", value=ref if ref > 0 else 1000000.0)
        source_info = f"Bourse {ticker}"
    
    else: # Startup
        stade = st.selectbox("Stade", ["Seed (3-8M)", "Series A (10-30M)", "Series B (30-80M)"])
        ranges = {"Seed": (3e6, 8e6), "Series A": (1e7, 3e7), "Series B": (3e7, 8e7)}
        min_v, max_v = ranges.get(stade.split()[0], (1e6, 5e6))
        valeur_finale = st.slider("Valo", 1000000.0, 100000000.0, (min_v+max_v)/2)
        source_info = f"VC {stade}"

    st.markdown("---")
    st.write("📂 **3. Data Room & Analyse**")
    notes = st.text_area("Notes Manuelles", height=100)
    uploaded_docs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 LANCER L'AUDIT"):
        with st.spinner("Analyse..."):
            res = analyser_risque_geo(v, p)
            if res['found']:
                news = get_company_news(ent)
                wiki = get_wiki_summary(ent)
                web = scan_website(website)
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_txt, doc_n = extract_text_from_pdfs(uploaded_docs)
                
                corpus = f"{notes} {web} {wiki} {doc_txt} {' '.join([n['title'] for n in news])}"
                
                # Calcul VaR INTELLIGENT (Avec Sens Gain/Perte)
                # Si le risque augmente (s2030 > s2024), c'est une perte. Sinon 0.
                delta_risk = res['s2030'] - res['s2024']
                
                if delta_risk > 0:
                    impact = valeur_finale * (delta_risk / 5.0) * vuln_factor
                else:
                    impact = 0 # Pas de perte si le risque baisse
                
                alerts = sum(1 for w in ['litige', 'procès', 'amende'] if w in corpus.lower())
                txt_ia = f"Analyse sur {len(doc_n)} documents. {alerts} alertes détectées. Secteur vulnérable à {vuln_factor*100}%."
                
                final = {
                    "ent": ent, "ville": v, "pays": res['pays'], 
                    "lat": res['lat'], "lon": res['lon'],
                    "valeur_entreprise": valeur_finale, "source_ca": source_info,
                    "s2024": res['s2024'], "s2026": res['s2026'], "s2030": res['s2030'],
                    "var_2030": impact, "vuln_percent": vuln_factor,
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
        
        # Gestion couleur Delta (Si risque augmente = Rouge/Inverse)
        delta_risk = r.get('s2030',0)-r.get('s2024',0)
        k2.metric("Risque 2030", f"{r.get('s2030',0):.2f}/5", delta=f"{delta_risk:.2f}", delta_color="inverse")
        
        # Gestion couleur VaR (Si perte > 0 = Rouge/Inverse)
        var_val = r.get('var_2030', 0)
        label_var = f"-{var_val:,.0f} $" if var_val > 0 else "STABLE"
        k3.metric("VaR (Impact 2030)", label_var, delta="-Impact" if var_val > 0 else "Neutre", delta_color="inverse")
        
        st.info(f"🌧️ Météo (90j): {r.get('pluie_90j')} mm | 🏭 Vulnérabilité: {r.get('vuln_percent',0)*100}%")
        st.caption(f"📝 Synthèse: {r.get('txt_ia')}")
        
        t1, t2 = st.tabs(["Rapport PDF", "Sources"])
        with t1:
            if r.get('full_text'):
                # Notez que nous passons 'notes' explicitement
                pdf = create_pdf(r, r['full_text'], notes) 
                st.download_button("📥 Télécharger Rapport PDF Complet", pdf, file_name="Rapport.pdf")
            if r.get('lat'):
                m = folium.Map([r['lat'], r['lon']], zoom_start=10)
                folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color='red')).add_to(m)
                st_folium(m, height=300)
        with t2:
            for n in r.get('news', []): st.markdown(f"- [{n['title']}]({n['link']})")
                
