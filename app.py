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
from thefuzz import process
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="AquaRisk 9.0 : Intégral", page_icon="🧿", layout="wide")
st.title("🧿 AquaRisk 9.0 : Finance, Risque & Recherche Documentaire")

# --- INITIALISATION ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
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
    agents = ["Aqua_V9", "Full_Scanner", "Geo_Risk_Pro"]
    for i in range(3):
        try:
            ua = f"{agents[i]}_{randint(100,999)}"
            geolocator = Nominatim(user_agent=ua, timeout=5)
            loc = geolocator.geocode(f"{ville}, {pays}", language='en')
            if loc: return loc
        except: time.sleep(1)
    return None

def trouver_meilleur_nom(nom_cherche, liste_options, seuil=75):
    if not nom_cherche or len(liste_options) == 0: return None
    meilleur_match, score = process.extractOne(str(nom_cherche), liste_options.astype(str))
    if score >= seuil: return meilleur_match
    return None

# --- 3. MODULES RECHERCHE (WEB, NEWS, WIKI) ---
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
    try: return wikipedia.page(company_name).summary[:1500]
    except: return ""

def scan_website(url):
    if not url or len(url) < 5: return ""
    if not url.startswith("http"): url = "https://" + url
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            # On prend les paragraphes
            return ' '.join([p.text for p in soup.find_all('p')])[:5000]
    except: return ""
    return ""

def get_company_news(company_name):
    # Recherche élargie
    query = urllib.parse.quote(f"{company_name} water environment risk")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    def clean(r): return re.sub(re.compile('<.*?>'), '', r).replace("&nbsp;", " ").replace("&#39;", "'")
    try:
        feed = feedparser.parse(rss_url)
        return [{"title": e.title, "link": e.link, "summary": clean(e.summary if 'summary' in e else e.title)[:250]} for e in feed.entries[:5]]
    except: return []

def extract_text_from_pdfs(uploaded_files):
    full_text = ""
    file_names = []
    if not uploaded_files: return "", []
    for pdf_file in uploaded_files:
        try:
            with pdfplumber.open(pdf_file) as pdf:
                text = ""
                for page in pdf.pages[:15]: text += page.extract_text() or ""
                full_text += text + " "
                file_names.append(pdf_file.name)
        except: continue
    return full_text, file_names

# --- 4. MODULES FINANCE ---
def get_pappers_financials(company_name, api_key):
    if not api_key: return None
    try:
        s_url = f"https://api.pappers.fr/v2/recherche?q={urllib.parse.quote(company_name)}&api_token={api_key}&par_page=1"
        r = requests.get(s_url, timeout=5).json()
        if not r.get('resultats'): return None
        match = r['resultats'][0]
        siren = match['siren']
        f_url = f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={siren}"
        f_data = requests.get(f_url, timeout=5).json()
        ca = 0
        annee = "N/A"
        for c in f_data.get('finances', []):
            if c.get('chiffre_affaires'):
                ca = c['chiffre_affaires']
                annee = c['annee_cloture_exercice']
                break
        return {"nom": match['nom_entreprise'], "ca": ca, "annee": annee}
    except: return None

def get_stock_valuation(ticker):
    try: return yf.Ticker(ticker).info.get('marketCap', 0)
    except: return 0

# --- 5. MOTEUR ANALYSE ---
def analyser_site(ville, pays, region_forcee=None):
    try:
        geolocator = Nominatim(user_agent=f"Global_Scan_{randint(100,999)}", timeout=10)
        loc = geolocator.geocode(f"{ville}, {pays}", language='en')
    except: loc = None

    if not loc:
        st.error(f"❌ GPS : Impossible de localiser '{ville}, {pays}'.")
        return None
    
    reg_gps = ""
    try:
        details = geolocator.reverse(f"{loc.latitude}, {loc.longitude}", language='en').raw['address']
        reg_gps = details.get('state', details.get('region', details.get('county', '')))
    except: pass
    
    reg_cible = region_forcee if region_forcee else reg_gps
    
    liste_pays = df_actuel['name_0'].unique()
    pays_trouve = trouver_meilleur_nom(pays, liste_pays, seuil=70)
    
    if not pays_trouve:
        st.error(f"❌ Pays '{pays}' non trouvé dans la base WRI.")
        return None
        
    df_pays = df_actuel[df_actuel['name_0'] == pays_trouve]
    match_now = pd.DataFrame()
    nom_region_officiel = "Moyenne Nationale"
    
    if reg_cible:
        liste_regions = df_pays['name_1'].unique()
        region_trouvee = trouver_meilleur_nom(reg_cible, liste_regions, seuil=80)
        if region_trouvee:
            match_now = df_pays[df_pays['name_1'] == region_trouvee]
            nom_region_officiel = region_trouvee
        else:
            match_now = df_pays
    else:
        match_now = df_pays

    s25 = match_now['score'].mean() if not match_now.empty else 0
    s30 = 0 
    if df_futur is not None:
        df_f_pays = df_futur[df_futur['name_0'] == pays_trouve]
        if not df_f_pays.empty: s30 = df_f_pays['score'].mean()

    return {
        "ent": "N/A", "ville": ville, "pays": pays_trouve, "region": nom_region_officiel,
        "lat": loc.latitude, "lon": loc.longitude,
        "s25": s25, "s30": s30, "found": True
    }

# --- 6. PDF COMPLET ---
def create_pdf(data):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    pdf.add_page()
    
    # TITRE
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, clean(f"AUDIT V9: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    # INFOS CLES
    pdf.set_font("Arial", size=11)
    pdf.cell(0, 10, clean(f"Loc: {data['ville']} ({data['region']}, {data['pays']})"), ln=1)
    if data.get('valeur_entreprise'):
        pdf.cell(0, 10, clean(f"Valuation: {data['valeur_entreprise']:,.0f} $ ({data.get('source_ca', 'Manuel')})"), ln=1)
    pdf.cell(0, 10, clean(f"VaR Climatique: -{data['var']:,.0f} $"), ln=1)
    pdf.ln(5)

    # METEO & DOCS
    if data['pluie_90j']: pdf.cell(0, 10, clean(f"Meteo (90j): {data['pluie_90j']} mm"), ln=1)
    if data.get('doc_files'):
        pdf.set_font("Arial", 'I', 9)
        pdf.cell(0, 10, clean(f"Docs Analyses: {', '.join(data['doc_files'])}"), ln=1)
    pdf.ln(5)
    
    # SCORE
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, f"Score Risque: {data['s25_display']:.2f} / 5", ln=1)
    pdf.ln(5)
    
    # SYNTHESE
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 6, clean(f"Synthese IA:\n{data['txt_ia']}"))
    pdf.ln(10)

    # --- SECTION SOURCES (RÉINTÉGRÉE !) ---
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Sources & Bibliographie:", ln=1)
    
    # News
    if data['news']:
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 8, "Presse Recente:", ln=1)
        pdf.set_font("Arial", size=8)
        for n in data['news']:
            pdf.cell(0, 5, clean(f"- {n['title'][:90]}"), ln=1)
    
    # Wiki
    if data.get('wiki'):
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 8, "Wikipedia Context:", ln=1)
        pdf.set_font("Arial", 'I', 8)
        pdf.multi_cell(0, 4, clean(f"{data['wiki'][:500]}..."))
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 7. INTERFACE ---
with st.sidebar:
    st.header("⚙️ API Keys")
    pappers_key = st.text_input("Pappers (France)", type="password")

c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("1. Cible & Recherche")
    ent = st.text_input("Nom Entreprise", "Danone")
    v = st.text_input("Ville", "Paris")
    p = st.text_input("Pays", "France")
    website = st.text_input("Site Web (Optionnel)", "")
    
    # BOUTONS CHASSEUR DE RAPPORTS (NOUVEAU)
    st.caption("🔍 **Chasseur de Rapports** (Liens rapides)")
    col_search1, col_search2 = st.columns(2)
    with col_search1:
        # Génère un lien Google vers les rapports PDF
        q_pdf = urllib.parse.quote(f"{ent} rapport développement durable filetype:pdf")
        st.markdown(f"[📄 Trouver Rapports PDF](https://www.google.com/search?q={q_pdf})", unsafe_allow_html=True)
    with col_search2:
        # Génère un lien Google News
        q_news = urllib.parse.quote(f"{ent} pollution amende")
        st.markdown(f"[📰 Vérifier Scandales](https://www.google.com/search?q={q_news})", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("2. Finance")
    mode_val = st.radio("Mode", ["Cotée", "Non Cotée"])
    valeur_finale = 0.0
    source_info = "Manuel"
    
    if mode_val == "Cotée":
        ticker = st.text_input("Ticker (ex: BN.PA)", "BN.PA")
        if st.button("📈 Bourse"):
            mcap = get_stock_valuation(ticker)
            if mcap > 0: st.session_state['auto_val'] = mcap
        valeur_finale = st.number_input("Valo ($)", value=st.session_state.get('auto_val', 1000000.0))
        source_info = f"Bourse ({ticker})"
    else:
        if st.button("🇫🇷 Pappers Auto"):
            if pappers_key:
                i = get_pappers_financials(ent, pappers_key)
                if i: st.session_state.pappers_data = i
        
        ca_val = 500000.0
        if st.session_state.pappers_data:
            ca_val = float(st.session_state.pappers_data['ca'])
            source_info = f"Pappers ({st.session_state.pappers_data['annee']})"
            st.success(f"CA Pappers : {ca_val:,.0f} €")
            
        ca = st.number_input("Chiffre d'Affaires", value=ca_val)
        secteur = st.selectbox("Secteur", ["Industrie (0.8x)", "Tech (5.0x)", "Agri (1.0x)"])
        coeffs = {"Industrie (0.8x)":0.8, "Tech (5.0x)":5.0, "Agri (1.0x)":1.0}
        valeur_finale = st.number_input("Valo Retenue", value=ca * coeffs[secteur])

    st.markdown("---")
    st.write("📂 **3. Data Room (Intégration)**")
    # NOTES MANUELLES (RETOUR)
    notes_manuelles = st.text_area("📋 Notes & Extraits (Collez du texte ici)", height=100)
    uploaded_docs = st.file_uploader("Drop PDF", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 AUDIT COMPLET"):
        with st.spinner("Analyse Intégrale..."):
            res = analyser_site(v, p)
            if res and res['found']:
                # Collecte
                news = get_company_news(ent)
                web_txt = scan_website(website)
                wiki_txt = get_wiki_summary(ent)
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_text, doc_names = extract_text_from_pdfs(uploaded_docs)
                
                # FUSION DE TOUTES LES SOURCES
                corpus = f"{notes_manuelles} {web_txt} {wiki_txt} {doc_text} {' '.join([n['title'] for n in news])}"
                
                # Mots clés
                m_pos = ['durable', 'recyclage', 'économie', 'biologique', 'iso 14001', 'b corp']
                m_neg = ['pollution', 'plainte', 'fuite', 'non-conformité']
                m_risk = ['provision', 'litige', 'amende', 'redressement', 'procès']
                
                s_pos = sum(1 for w in m_pos if w in corpus.lower())
                s_neg = sum(1 for w in m_neg if w in corpus.lower())
                s_risk = sum(1 for w in m_risk if w in corpus.lower())
                
                bonus = 0.0
                txt = "Neutre."
                if pluie and pluie < 50: bonus -= 0.10
                
                if s_pos > s_neg: bonus += 0.10; txt = "✅ Tendance positive (Sources concordantes)."
                elif s_neg > s_pos: bonus -= 0.10; txt = "⚠️ Tendance négative."
                if s_risk > 0: bonus -= 0.20; txt += f"\n🚨 ALERTE: Risques financiers détectés ({s_risk})."

                res['ent'] = ent
                res['valeur_entreprise'] = valeur_finale
                res['source_ca'] = source_info
                res['pluie_90j'] = pluie
                res['doc_files'] = doc_names
                res['s25_brut'] = res['s25']
                res['s25_display'] = res['s25'] * (1 - bonus)
                res['var'] = valeur_finale * (res['s25_display'] / 5) * 0.2
                res['txt_ia'] = txt
                res['news'] = news
                res['wiki'] = wiki_txt
                
                st.session_state.audit_unique = res
                st.rerun()
            else:
                st.error("Localisation impossible.")

with c2:
    if st.session_state.audit_unique:
        r = st.session_state.audit_unique
        st.success(f"Résultats : {r['ent']}")
        
        c0, c1, c2 = st.columns(3)
        c0.metric("Valorisation", f"{r['valeur_entreprise']:,.0f} $", delta=r.get('source_ca',''))
        c1.metric("Risque Final", f"{r['s25_display']:.2f}/5", delta=f"Base: {r['s25_brut']:.2f}", delta_color="inverse")
        c2.metric("VaR", f"-{r['var']:,.0f} $", delta="Impact", delta_color="inverse")
        
        st.info(f"🤖 **Synthèse :** {r['txt_ia']}")
        
        t1, t2, t3, t4 = st.tabs(["📝 Notes & Docs", "📰 News", "📚 Wiki", "🌍 Météo"])
        with t1: 
             if r['doc_files']: st.write(f"📂 Docs: {', '.join(r['doc_files'])}")
             st.caption("Texte analysé (Extrait) :")
             st.text("..." + notes_manuelles[:200] + "...")
        with t2:
            for n in r['news']: st.markdown(f"- [{n['title']}]({n['link']})")
        with t3: st.write(r['wiki'])
        with t4: st.metric("Pluie Récente", f"{r['pluie_90j']} mm")

        m = folium.Map([r['lat'], r['lon']], zoom_start=9, tiles="cartodbpositron")
        folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color="red")).add_to(m)
        st_folium(m, height=250)
        
        pdf = create_pdf(r)
        st.download_button("📄 Rapport PDF Complet (Sources incluses)", pdf, file_name="Rapport_V9.pdf")
        
