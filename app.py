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
st.set_page_config(page_title="AquaRisk V17.2 : Expert", page_icon="💎", layout="wide")
st.title("💎 AquaRisk V17.2 : Audit Financier, Climatique & Documentaire")

if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'stock_data' not in st.session_state: st.session_state.stock_data = {"mcap": 0, "ev": 0}

# ==============================================================================
# 2. CHARGEMENT DATA (DATASET)
# ==============================================================================
@st.cache_data
def load_data():
    BACKUP_DATA = pd.DataFrame({
        'name_0': ['France', 'United States', 'Germany', 'China'],
        'name_1': ['Ile-de-France', 'California', 'Bavaria', 'Beijing'],
        'score': [2.5, 3.8, 2.2, 4.1]
    })
    
    def smart_read(filename):
        if not os.path.exists(filename): return None
        try:
            df = pd.read_csv(filename, sep=',', engine='python', on_bad_lines='skip')
            df.columns = [c.lower().strip() for c in df.columns]
            return df
        except: return None

    df_now = smart_read("risk_actuel.csv")
    if df_now is None: df_now = BACKUP_DATA
    else: df_now['score'] = pd.to_numeric(df_now['score'].astype(str).str.replace(',', '.'), errors='coerce')

    df_fut = smart_read("risk_futur.csv")
    if df_fut is None:
        df_fut = df_now.copy()
        df_fut['score'] = df_fut['score'] * 1.15
    else:
        df_fut['score'] = pd.to_numeric(df_fut['score'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'year' in df_fut.columns:
            df_fut = df_fut[(df_fut['year'] == 2030) & (df_fut['scenario'] == 'bau')]
            
    return df_now, df_fut

try:
    df_actuel, df_futur = load_data()
except: st.stop()

# ==============================================================================
# 3. TOUTES LES FONCTIONS TECHNIQUES (DÉFINIES ICI POUR ÉVITER NameError)
# ==============================================================================

# --- WEBSITE SCANNER (CORRECTION NameError) ---
def scan_website(url):
    if not url or len(url) < 5: return ""
    if not url.startswith("http"): url = "https://" + url
    try:
        # Timeout court pour ne pas bloquer l'app
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            # On prend les 5000 premiers caractères de texte
            return ' '.join([p.text for p in soup.find_all('p')])[:5000]
    except: return ""
    return ""

# --- GPS ---
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
            ua = f"AR_V172_{randint(1000,9999)}"
            loc = Nominatim(user_agent=ua, timeout=8).geocode(f"{ville}, {pays}")
            if loc: return loc
        except: time.sleep(1); continue
    return MockLocation(48.8566, 2.3522)

# --- INTELLIGENCE ---
def get_wiki_summary(company_name):
    try:
        wikipedia.set_lang('fr')
        search = wikipedia.search(company_name)
        if search: return wikipedia.page(search[0]).summary[:1500]
    except: pass
    return "Pas de données Wikipedia."

def get_company_news(company_name):
    q = urllib.parse.quote(f'"{company_name}" (eau OR pollution OR environnement OR climat)')
    try:
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
        return [{"title": e.title, "link": e.link, "summary": e.summary[:250]} for e in feed.entries[:5]]
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

# --- FINANCE & METEO ---
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

    s26 = s24 + ((s30 - s24) * (2/6))
    
    return {
        "ent": "N/A", "ville": ville, "pays": pays_match, 
        "lat": loc.latitude, "lon": loc.longitude, 
        "s2024": s24, "s2026": s26, "s2030": s30, "found": True
    }

# ==============================================================================
# 5. PDF GENERATOR
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
    pdf.cell(0, 15, clean(f"RAPPORT V17.2: {data.get('ent', 'N/A').upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    if data.get('lat'):
        f = generer_carte(data['lat'], data['lon'])
        if f: pdf.image(f, x=20, w=170)
    pdf.ln(5)
    
    # 1. FINANCE
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. VALORISATION & IMPACT CLIMATIQUE", ln=1)
    pdf.set_font("Arial", size=11)
    
    val = data.get('valeur_entreprise', 0)
    var = data.get('var_2030', 0)
    vuln = data.get('vuln_percent', 0) * 100
    
    pdf.cell(60, 10, clean(f"Valorisation: {val:,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"Methode: {data.get('source_ca', 'Manuel')}"), border=1)
    
    if var > 0:
        pdf.set_text_color(200,0,0)
        txt_var = f"PERTE Estimee 2030: -{abs(var):,.0f} $"
    elif var < 0:
        pdf.set_text_color(0,100,0)
        txt_var = f"GAIN / EVITEMENT 2030: +{abs(var):,.0f} $"
    else:
        pdf.set_text_color(0,0,0)
        txt_var = "Impact Financier: NEUTRE"
        
    pdf.cell(60, 10, clean(txt_var), border=1)
    pdf.set_text_color(0,0,0)
    pdf.ln(15)
    
    pdf.set_font("Arial", 'I', 10)
    explication = f"Analyse basee sur une vulnerabilite sectorielle de {vuln:.0f}%. L'evolution du score de risque hydrique entre 2024 et 2030 impacte directement la valorisation."
    pdf.multi_cell(0, 5, clean(explication))
    pdf.ln(5)

    # 2. CLIMAT
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "2. CONTEXTE CLIMATIQUE & SYNTHESE", ln=1)
    pdf.set_font("Arial", size=11)
    
    s24 = data.get('s2024', 2.5); s26 = data.get('s2026', 2.5); s30 = data.get('s2030', 2.5)
    pdf.cell(60, 10, f"Score 2024: {s24:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Proj 2026: {s26:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Proj 2030: {s30:.2f}/5", border=1, align='C')
    pdf.ln(10)
    
    pdf.cell(0, 10, f"Meteo Locale (90j): {data.get('pluie_90j', 'N/A')} mm", ln=1)
    pdf.ln(5)
    pdf.set_font("Arial", 'I', 11)
    pdf.multi_cell(0, 6, clean(f"Synthese IA: {data.get('txt_ia', '')}"))
    
    # 3. DETAILS
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "3. SOURCES, PRESSE & NOTES", ln=1)
    pdf.ln(5)
    
    if data.get('news'):
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Revue de Presse (Liens Cliquables)", ln=1)
        pdf.set_font("Arial", '', 10)
        for n in data['news']:
            pdf.set_text_color(0,0,255)
            pdf.cell(0, 6, clean(f">> {n['title']}"), ln=1, link=n['link'])
            pdf.set_text_color(0,0,0)
            pdf.multi_cell(0, 5, clean(f"{n['summary']}"))
            pdf.ln(2)
            
    if notes:
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Notes de l'Analyste", ln=1)
        pdf.set_font("Arial", 'I', 10)
        pdf.multi_cell(0, 5, clean(notes))
        
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
    
    # SECTEUR AVEC % EXPLICITE
    secteur_risk = st.selectbox("Secteur (Vulnérabilité)", [
        "Agroalimentaire (100% Impact)", 
        "Industrie (70% Impact)", 
        "BTP (40% Impact)", 
        "Commerce (20% Impact)", 
        "Logiciel (5% Impact)"
    ])
    
    # Extraction du facteur (%)
    if "100%" in secteur_risk: vuln_factor = 1.0
    elif "70%" in secteur_risk: vuln_factor = 0.7
    elif "40%" in secteur_risk: vuln_factor = 0.4
    elif "20%" in secteur_risk: vuln_factor = 0.2
    else: vuln_factor = 0.05

    # --- MODE PME ---
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

        m_pme = st.selectbox("Méthode de Calcul", ["Multiple CA", "Multiple EBITDA", "DCF", "Patrimonial"])
        
        val_calc = 0.0
        if "Multiple CA" in m_pme:
            base = st.number_input("Chiffre d'Affaires (€)", value=ca_val)
            val_calc = base * 1.5
        elif "Multiple EBITDA" in m_pme:
            base = st.number_input("EBITDA (€)", value=res_val)
            val_calc = base * 7.0
        elif "DCF" in m_pme:
            fcf = st.number_input("FCF", value=res_val)
            val_calc = fcf * (1.02) / (0.10 - 0.02)
        else:
            val_calc = st.number_input("Capitaux", value=cap_val)
            
        valeur_finale = st.number_input("Valo Retenue", value=val_calc)
        source_info = m_pme

    # --- MODE BOURSE ---
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

    # --- MODE STARTUP (CORRIGÉ & EXPLIQUÉ) ---
    else: # Startup
        st.info("💡 Méthode Venture Capital (Fourchettes standards)")
        stade = st.selectbox("Stade de Maturité", [
            "Pre-Seed (Idée/MVP)", 
            "Seed (Produit lancé)", 
            "Series A (Traction)", 
            "Series B (Expansion)"
        ])
        
        # Données marché (simplifiées)
        ranges = {
            "Pre-Seed": (1000000.0, 3000000.0),
            "Seed": (3000000.0, 8000000.0),
            "Series A": (8000000.0, 30000000.0),
            "Series B": (30000000.0, 80000000.0)
        }
        
        # On extrait la clé (premier mot)
        key = stade.split()[0]
        if key == "Series": key = stade.split()[0] + " " + stade.split()[1] # "Series A"
        
        mini, maxi = ranges.get(key, (1000000.0, 5000000.0))
        
        st.caption(f"Fourchette typique : {mini/1e6}M€ - {maxi/1e6}M€")
        valeur_finale = st.slider("Valorisation ($)", mini, maxi, (mini+maxi)/2)
        source_info = f"VC {key}"

    st.markdown("---")
    st.write("📂 **3. Data Room**")
    notes = st.text_area("Notes", height=100)
    uploaded_docs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 AUDIT"):
        with st.spinner("Analyse..."):
            res = analyser_risque_geo(v, p)
            if res['found']:
                # Appel des fonctions
                news = get_company_news(ent)
                wiki = get_wiki_summary(ent)
                web = scan_website(website)
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_txt, doc_n = extract_text_from_pdfs(uploaded_docs)
                
                # Corpus global
                corpus = f"{notes} {web} {wiki} {doc_txt} {' '.join([n['title'] for n in news])}"
                
                # LOGIQUE VaR CORRIGÉE (DELTA)
                # Delta = 2030 - 2024
                # Si 2030 > 2024 => Risque augmente => Perte
                # Si 2030 < 2024 => Risque baisse => Gain
                
                delta_risk = res['s2030'] - res['s2024'] # Ex: 2.11 - 2.31 = -0.20
                
                impact_30 = valeur_finale * (delta_risk / 5.0) * vuln_factor
                impact_26 = valeur_finale * ((res['s2026'] - res['s2024']) / 5.0) * vuln_factor
                
                alerts = sum(1 for w in ['litige', 'procès', 'amende', 'pollution'] if w in corpus.lower())
                
                # Synthèse IA Riche
                txt_ia = f"Analyse basée sur {len(doc_n)} documents internes et le web.\n\n"
                txt_ia += f"CONTEXTE :\n{wiki[:400]}...\n\n"
                txt_ia += f"WEB SCAN :\n{web[:300]}...\n\n"
                if alerts > 0: txt_ia += f"ALERTE : {alerts} signaux faibles détectés (litiges/risques)."
                else: txt_ia += "RAS : Pas d'alerte majeure détectée."
                
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
        
        # Delta Risque (Vert si négatif)
        delta_r = r.get('s2030',0)-r.get('s2024',0)
        k2.metric("Trajectoire Risque", f"{r.get('s2030',0):.2f}/5", delta=f"{delta_r:.2f}", delta_color="inverse")
        
        # Delta VaR (Vert si gain)
        var_30 = r.get('var_2030', 0)
        if var_30 > 0: # Perte
            label_var = f"-{abs(var_30):,.0f} $"
            color_delta = "inverse"
        else: # Gain
            label_var = f"+{abs(var_30):,.0f} $"
            color_delta = "normal"
            
        k3.metric("Impact Financier 2030", label_var, delta="Impact Estimé", delta_color=color_delta)
        
        st.info(f"Météo: {r.get('pluie_90j')} mm | Vulnérabilité: {r.get('vuln_percent',0)*100:.0f}%")
        
        t1, t2 = st.tabs(["Rapport PDF", "Sources"])
        with t1:
            if r.get('full_text'):
                pdf = create_pdf(r, r['full_text'], notes)
                st.download_button("📥 Télécharger Rapport PDF Complet", pdf, file_name="Rapport.pdf")
            if r.get('lat'):
                m = folium.Map([r['lat'], r['lon']], zoom_start=10)
                folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color='red')).add_to(m)
                st_folium(m, height=300)
        with t2:
            st.write("### Revue de Presse")
            for n in r.get('news', []): st.markdown(f"- **{n['title']}** : {n['summary']}")

            
