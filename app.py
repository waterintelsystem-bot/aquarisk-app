import streamlit as st
import pandas as pd
from geopy.geocoders import Nominatim
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
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="AquaRisk 8.0 : Ultimate Valuation", page_icon="💎", layout="wide")
st.title("💎 AquaRisk 8.0 : Audit, Risque & Valorisation Automatique")

# --- INITIALISATION ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
# On garde en mémoire les infos trouvées pour éviter de recharger
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None

# --- 1. CHARGEMENT DATA ---
@st.cache_data
def load_data():
    def smart_read(filename):
        if not os.path.exists(filename): return None
        if os.path.getsize(filename) < 50: return None
        for sep in [',', ';', '\t']:
            try:
                df = pd.read_csv(filename, sep=sep, engine='python', on_bad_lines='skip')
                if len(df.columns) > 1:
                    df.columns = [c.lower().strip() for c in df.columns]
                    return df
            except: continue
        return None

    df_now = smart_read("risk_actuel.csv")
    if df_now is not None and 'score' in df_now.columns:
        df_now['score'] = pd.to_numeric(df_now['score'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'indicator_name' in df_now.columns: df_now = df_now[df_now['indicator_name'] == 'bws']

    df_fut = smart_read("risk_futur.csv")
    if df_fut is not None and 'score' in df_fut.columns:
        df_fut['score'] = pd.to_numeric(df_fut['score'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'year' in df_fut.columns:
            mask = (df_fut['year'] == 2030) & (df_fut['scenario'] == 'bau') & (df_fut['indicator_name'] == 'bws')
            df_fut = df_fut[mask]
    return df_now, df_fut

try:
    df_actuel, df_futur = load_data()
except: st.stop()
if df_actuel is None or df_futur is None: st.stop()

# --- 2. FONCTIONS TECH ---
def get_location_safe(ville, pays):
    agents = ["Auditor_V8", "Valuation_Bot", "Risk_Scanner_Pro"]
    for i in range(3):
        try:
            ua = f"{agents[i]}_{randint(100,999)}"
            geolocator = Nominatim(user_agent=ua, timeout=5)
            loc = geolocator.geocode(f"{ville}, {pays}")
            if loc: return loc
        except: time.sleep(1)
    return None

def get_region_safe(lat, lon):
    try:
        ua = f"Rev_Geo_{randint(100,999)}"
        geolocator = Nominatim(user_agent=ua, timeout=5)
        return geolocator.reverse(f"{lat}, {lon}", language='en')
    except: return None

# --- 3. MODULES EXTERNES ---
def get_weather_history(lat, lon):
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}&daily=precipitation_sum&timezone=auto"
    try:
        r = requests.get(url, timeout=5)
        d = r.json()
        if 'daily' in d and 'precipitation_sum' in d['daily']:
            return sum([x for x in d['daily']['precipitation_sum'] if x is not None])
    except: return None
    return None

def get_wiki_summary(company_name, lang='fr'):
    wikipedia.set_lang(lang)
    try: return wikipedia.page(company_name).summary[:1000]
    except: return ""

def scan_website(url):
    if not url or len(url) < 5: return ""
    if not url.startswith("http"): url = "https://" + url
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            return ' '.join([p.text for p in soup.find_all('p')])[:4000]
    except: return ""
    return ""

def get_company_news(company_name):
    query = urllib.parse.quote(f"{company_name} water environment")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    def clean(r): return re.sub(re.compile('<.*?>'), '', r).replace("&nbsp;", " ").replace("&#39;", "'")
    try:
        feed = feedparser.parse(rss_url)
        return [{"title": e.title, "link": e.link, "summary": clean(e.summary if 'summary' in e else e.title)[:200]} for e in feed.entries[:5]]
    except: return []

def extract_text_from_pdfs(uploaded_files):
    full_text = ""
    file_names = []
    if not uploaded_files: return "", []
    for pdf_file in uploaded_files:
        try:
            with pdfplumber.open(pdf_file) as pdf:
                text = ""
                for page in pdf.pages[:10]: text += page.extract_text() or ""
                full_text += text + " "
                file_names.append(pdf_file.name)
        except: continue
    return full_text, file_names

# --- 4. MODULE PAPPERS (NOUVEAU - FRANCE) ---
def get_pappers_financials(company_name, api_key):
    """Récupère le CA via Pappers"""
    if not api_key: return None
    
    # 1. Recherche de l'entreprise
    search_url = f"https://api.pappers.fr/v2/recherche?q={urllib.parse.quote(company_name)}&api_token={api_key}&par_page=1"
    try:
        r = requests.get(search_url, timeout=5)
        data = r.json()
        if not data.get('resultats'): return None
        
        best_match = data['resultats'][0]
        siren = best_match['siren']
        nom_officiel = best_match['nom_entreprise']
        ville = best_match['siege']['ville']
        
        # 2. Récupération des finances
        fin_url = f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={siren}"
        r_fin = requests.get(fin_url, timeout=5)
        data_fin = r_fin.json()
        
        # On cherche le dernier CA disponible
        derniers_comptes = data_fin.get('finances', [])
        ca = 0
        annee = "N/A"
        
        if derniers_comptes:
            # On prend le plus récent qui a un CA renseigné
            for compte in derniers_comptes:
                if compte.get('chiffre_affaires'):
                    ca = compte['chiffre_affaires']
                    annee = compte['annee_cloture_exercice']
                    break
        
        return {
            "nom": nom_officiel,
            "siren": siren,
            "ville": ville,
            "ca": ca,
            "annee": annee
        }
    except:
        return None

# --- 5. MODULE BOURSE (MONDE) ---
def get_stock_valuation(ticker):
    try:
        stock = yf.Ticker(ticker)
        return stock.info.get('marketCap', 0)
    except: return 0

# --- 6. MOTEUR ANALYSE ---
def analyser_site(ville, pays, region_forcee=None):
    loc = get_location_safe(ville, pays)
    if not loc: return None
    
    loc_details = get_region_safe(loc.latitude, loc.longitude)
    reg_auto = ""
    if loc_details:
        addr = loc_details.raw['address']
        reg_auto = addr.get('state', addr.get('region', addr.get('county', ''))).strip()
    
    region_final = region_forcee if region_forcee else reg_auto
    
    # Match CSV
    if 'name_0' not in df_actuel.columns: return None
    mask_pays = df_actuel['name_0'].astype(str).str.lower().str.contains(pays.lower().strip(), na=False)
    df_pays = df_actuel[mask_pays]
    match_now = df_pays[df_pays['name_1'].astype(str).str.lower().str.contains(region_final.lower().strip(), na=False)]
    
    mask_pays_f = df_futur['name_0'].astype(str).str.lower().str.contains(pays.lower().strip(), na=False)
    df_f_pays = df_futur[mask_pays_f]
    match_fut = df_f_pays[df_f_pays['name_1'].astype(str).str.lower().str.contains(region_final.lower().strip(), na=False)]

    return {
        "ent": "N/A", "ville": ville, "pays": pays, "region": region_final,
        "lat": loc.latitude, "lon": loc.longitude,
        "s25": match_now['score'].mean() if not match_now.empty else 0,
        "s30": match_fut['score'].mean() if not match_fut.empty else 0,
        "found": not match_now.empty
    }

# --- 7. PDF ---
def create_pdf(data):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, clean(f"RAPPORT V8: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, clean(f"Cible: {data['ent']} ({data['loc']})"), ln=1)
    
    # Section Finance
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, clean(f"Valorisation Estimee: {data['valeur_entreprise']:,.0f} $"), ln=1)
    pdf.cell(0, 10, clean(f"VaR (Risque Financier): -{data['var']:,.0f} $"), ln=1)
    pdf.ln(5)
    
    if data.get('source_ca'):
         pdf.set_font("Arial", 'I', 10)
         pdf.cell(0, 10, clean(f"Source Financiere: {data['source_ca']}"), ln=1)
         pdf.ln(5)

    pdf.set_font("Arial", size=12)
    if data['pluie_90j']: pdf.cell(0, 10, clean(f"Meteo (90j): {data['pluie_90j']} mm"), ln=1)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"Score Risque: {data['s25_display']:.2f} / 5", ln=1)
    pdf.ln(5)
    
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 8, clean(f"Analyse IA:\n{data['txt_ia']}"))
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 8. INTERFACE ---
with st.sidebar:
    st.header("⚙️ Configuration")
    pappers_key = st.text_input("Clé API Pappers (Optionnel)", type="password", help="Pour les sociétés françaises")
    st.caption("[Obtenir une clé gratuite](https://www.pappers.fr/api)")

c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("1. Cible")
    ent = st.text_input("Nom Entreprise", "Danone")
    v = st.text_input("Ville", "Paris")
    p = st.text_input("Pays", "France")
    reg = st.text_input("Région", "Ile-de-France")
    website = st.text_input("Site Web", "")
    
    st.markdown("---")
    st.subheader("2. Valorisation")
    
    mode_val = st.radio("Type", ["Cotée (Bourse)", "Non Cotée (PME/ETI)"])
    valeur_finale = 0.0
    source_info = "Manuel"
    
    if mode_val == "Cotée (Bourse)":
        ticker = st.text_input("Symbole (ex: BN.PA, AAPL)", "BN.PA")
        if st.button("📈 Market Cap (Yahoo)"):
            mcap = get_stock_valuation(ticker)
            if mcap > 0: st.session_state['auto_val'] = mcap
        valeur_finale = st.number_input("Capitalisation ($)", value=st.session_state.get('auto_val', 1000000.0))
        source_info = f"Bourse ({ticker})"

    else:
        # LOGIQUE PAPPERS
        col_p1, col_p2 = st.columns([2,1])
        with col_p2:
            st.write("")
            st.write("")
            if st.button("🇫🇷 Auto Pappers"):
                if pappers_key:
                    with st.spinner("Interrogation INPI..."):
                        info_pap = get_pappers_financials(ent, pappers_key)
                        if info_pap:
                            st.session_state.pappers_data = info_pap
                            st.success("Trouvé !")
                        else:
                            st.error("Pas de bilan trouvé.")
                else:
                    st.warning("Entrez une clé API à gauche.")
        
        # Pré-remplissage si Pappers a trouvé
        default_ca = 500000.0
        if st.session_state.pappers_data:
            default_ca = float(st.session_state.pappers_data['ca'])
            st.caption(f"✅ Bilan {st.session_state.pappers_data['annee']} pour {st.session_state.pappers_data['nom']}")
            source_info = f"Pappers (Bilan {st.session_state.pappers_data['annee']})"

        ca = st.number_input("Chiffre d'Affaires ($)", value=default_ca)
        
        secteur = st.selectbox("Secteur", 
                               ["Industrie (0.8x)", "Tech/SaaS (5.0x)", "Agri (1.0x)", "Services (1.2x)"])
        coeffs = {"Industrie (0.8x)": 0.8, "Tech/SaaS (5.0x)": 5.0, "Agri (1.0x)": 1.0, "Services (1.2x)": 1.2}
        
        val_estimee = ca * coeffs[secteur]
        st.info(f"Val. Estimée : {val_estimee:,.0f} $")
        valeur_finale = st.number_input("Retenu ($)", value=val_estimee)

    st.markdown("---")
    st.write("📂 **3. Data Room**")
    uploaded_docs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 LANCER L'AUDIT V8"):
        with st.spinner("Analyse 360° en cours..."):
            res = analyser_site(v, p, reg)
            
            if res and res['found']:
                news = get_company_news(ent)
                web_txt = scan_website(website)
                wiki_txt = get_wiki_summary(ent, 'fr')
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_text, doc_names = extract_text_from_pdfs(uploaded_docs)
                
                corpus = f"{web_txt} {wiki_txt} {doc_text} {' '.join([n['title'] for n in news])}"
                m_pos = ['durable', 'recyclage', 'économie', 'biologique', 'iso 14001']
                m_neg = ['pollution', 'plainte', 'fuite', 'non-conformité']
                m_risk = ['provision', 'litige', 'amende', 'redressement']
                
                s_pos = sum(1 for w in m_pos if w in corpus.lower())
                s_neg = sum(1 for w in m_neg if w in corpus.lower())
                s_risk = sum(1 for w in m_risk if w in corpus.lower())
                
                bonus = 0.0
                txt = "Neutre."
                if pluie and pluie < 50: bonus -= 0.10
                
                if s_pos > s_neg: bonus += 0.10; txt = "✅ Tendance positive."
                elif s_neg > s_pos: bonus -= 0.10; txt = "⚠️ Tendance négative."
                if s_risk > 0: bonus -= 0.20; txt += f"\n🚨 ALERTE COMPTABLE ({s_risk} mentions)."

                res['ent'] = ent
                res['valeur_entreprise'] = valeur_finale
                res['source_ca'] = source_info
                res['pluie_90j'] = pluie
                res['doc_files'] = doc_names
                res['s25_brut'] = res['s25']
                res['s25_display'] = res['s25'] * (1 - bonus)
                res['s30_display'] = res['s30'] * (1 - bonus)
                res['var'] = valeur_finale * (res['s25_display'] / 5) * 0.2
                res['txt_ia'] = txt
                res['news'] = news
                res['wiki'] = wiki_txt[:500] if wiki_txt else None
                res['loc'] = f"{res['ville']}, {res['pays']}"
                
                st.session_state.audit_unique = res
                st.rerun()
            else:
                st.error("Lieu introuvable.")

with c2:
    if st.session_state.audit_unique:
        r = st.session_state.audit_unique
        st.success(f"Audit V8 : {r['ent']}")
        
        c0, c1, c2 = st.columns(3)
        c0.metric("Valorisation", f"{r['valeur_entreprise']:,.0f} $", delta=r.get('source_ca', ''))
        c1.metric("Score Risque", f"{r['s25_display']:.2f}/5", delta=f"Base: {r['s25_brut']:.2f}", delta_color="inverse")
        c2.metric("Perte Potentielle (VaR)", f"-{r['var']:,.0f} $", delta="Risque", delta_color="inverse")
        
        st.info(f"🤖 **Synthèse :** {r['txt_ia']}")
        
        t1, t2, t3 = st.tabs(["📄 Docs", "📰 News", "📚 Wiki"])
        with t1: 
             if r['doc_files']: st.write(f"Sources: {', '.join(r['doc_files'])}")
             else: st.write("Aucun document uploadé.")
        with t2:
            for n in r['news']: st.markdown(f"- [{n['title']}]({n['link']})")
        with t3:
            if r['wiki']: st.write(r['wiki'] + "...")

        m = folium.Map([r['lat'], r['lon']], zoom_start=9, tiles="cartodbpositron")
        folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color="red")).add_to(m)
        st_folium(m, height=250)
        
        pdf = create_pdf(r)
        st.download_button("📄 Rapport V8 PDF", pdf, file_name="Audit_V8.pdf")
        
