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
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="AquaRisk 7.1", page_icon="🗂️", layout="wide")
st.title("🗂️ AquaRisk 7.1 : Audit PME & Grands Comptes")

# --- INITIALISATION ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None

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
    agents = ["Auditor_V7", "Doc_Reader", "Risk_Scanner"]
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
    try:
        return wikipedia.page(company_name).summary[:1000]
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

# --- 4. MODULE PDF ---
def extract_text_from_pdfs(uploaded_files):
    full_text = ""
    file_names = []
    if not uploaded_files: return "", []
    for pdf_file in uploaded_files:
        try:
            with pdfplumber.open(pdf_file) as pdf:
                text = ""
                for page in pdf.pages[:10]:
                    text += page.extract_text() or ""
                full_text += text + " "
                file_names.append(pdf_file.name)
        except: continue
    return full_text, file_names

# --- 5. MOTEUR CENTRAL ---
def analyser_site(ville, pays, region_forcee=None):
    loc = get_location_safe(ville, pays)
    if not loc: return None
    
    loc_details = get_region_safe(loc.latitude, loc.longitude)
    reg_auto = ""
    if loc_details:
        addr = loc_details.raw['address']
        reg_auto = addr.get('state', addr.get('region', addr.get('county', ''))).strip()
    
    region_final = region_forcee if region_forcee else reg_auto
    
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

# --- 6. PDF EXPORT ---
def create_pdf(data):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, clean(f"AUDIT 7.1: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, clean(f"Loc: {data['loc']}"), ln=1)
    if data['pluie_90j']: pdf.cell(0, 10, clean(f"Pluie (90j): {data['pluie_90j']} mm"), ln=1)
    if data['doc_files']: pdf.cell(0, 10, clean(f"Docs: {', '.join(data['doc_files'])}"), ln=1)
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"Score Final: {data['s25_display']:.2f} / 5", ln=1)
    pdf.ln(5)
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 8, clean(f"Synthese IA:\n{data['txt_ia']}"))
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 7. INTERFACE ---
c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("📁 Documents & Cible")
    
    ent = st.text_input("Entreprise", "PME Exemple")
    website = st.text_input("Site Web", "")
    v = st.text_input("Ville", "Lyon")
    p = st.text_input("Pays", "France")
    reg = st.text_input("Région", "Auvergne-Rhône-Alpes")
    
    # --- CHANGEMENT ICI : INPUT FLEXIBLE ---
    cap = st.number_input(
        "Valeur de l'Actif / CA ($)", 
        value=100000,   # Valeur par défaut plus basse (PME)
        min_value=0,    # Pas de négatif
        step=1000,      # On peut ajuster finement
        help="Saisissez le montant total exposé au risque (Chiffre d'Affaires ou Valeur de l'usine)."
    )
    
    st.markdown("---")
    st.write("📂 **Data Room (Compta / RSE)**")
    uploaded_docs = st.file_uploader("Drop PDF", type=["pdf"], accept_multiple_files=True)
    
    if st.button("Lancer l'Audit"):
        with st.spinner("Analyse complète en cours..."):
            res = analyser_site(v, p, reg)
            
            if res and res['found']:
                news = get_company_news(ent)
                web_txt = scan_website(website)
                wiki_txt = get_wiki_summary(ent, 'fr')
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_text, doc_names = extract_text_from_pdfs(uploaded_docs)
                
                corpus = f"{web_txt} {wiki_txt} {doc_text} {' '.join([n['title'] for n in news])}"
                m_pos = ['durable', 'recyclage', 'économie', 'biologique', 'local', 'traitement']
                m_neg = ['pollution', 'plainte', 'fuite', 'non-conformité', 'dépassement']
                m_risk = ['provision', 'litige', 'amende', 'redressement', 'pénalité']
                
                s_pos = sum(1 for w in m_pos if w in corpus.lower())
                s_neg = sum(1 for w in m_neg if w in corpus.lower())
                s_risk = sum(1 for w in m_risk if w in corpus.lower())
                
                bonus = 0.0
                txt = "Analyse neutre."
                if pluie is not None and pluie < 50: bonus -= 0.10
                
                if s_pos > s_neg: 
                    bonus += 0.10
                    txt = "✅ Tendance positive."
                elif s_neg > s_pos: 
                    bonus -= 0.10
                    txt = "⚠️ Tendance négative."
                
                if s_risk > 0:
                    bonus -= 0.20
                    txt += f"\n🚨 ALERTE COMPTABLE ({s_risk} mentions)."

                res['ent'] = ent
                res['pluie_90j'] = pluie
                res['doc_files'] = doc_names
                res['s25_brut'] = res['s25']
                res['s25_display'] = res['s25'] * (1 - bonus)
                res['s30_display'] = res['s30'] * (1 - bonus)
                res['var'] = cap * (res['s25_display'] / 5)
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
        st.success(f"Audit : {r['ent']}")
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Score", f"{r['s25_display']:.2f}/5", delta=f"Base: {r['s25_brut']:.2f}", delta_color="inverse")
        c2.metric("Météo (90j)", f"{r['pluie_90j']} mm" if r['pluie_90j'] else "N/A")
        c3.metric("VaR Financière", f"{r['var']:,.0f} $") # La VaR se calcule avec le montant PME
        
        st.info(f"🤖 **Synthèse :** {r['txt_ia']}")
        
        if r['doc_files']: st.write(f"📂 Docs: {', '.join(r['doc_files'])}")
        
        t1, t2, t3 = st.tabs(["📄 Docs", "📰 News", "📚 Wiki"])
        with t1: st.caption("Texte scanné pour risques financiers.")
        with t2:
            for n in r['news']: st.markdown(f"- [{n['title']}]({n['link']})")
        with t3:
            if r['wiki']: st.write(r['wiki'] + "...")

        m = folium.Map([r['lat'], r['lon']], zoom_start=9, tiles="cartodbpositron")
        folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color="red")).add_to(m)
        st_folium(m, height=250)
        
        pdf = create_pdf(r)
        st.download_button("📄 Rapport Audit PDF", pdf, file_name="Audit.pdf")
        
