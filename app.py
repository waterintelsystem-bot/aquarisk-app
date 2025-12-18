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
from staticmap import StaticMap, CircleMarker

# --- CONFIGURATION ---
st.set_page_config(page_title="AquaRisk 9.5 : Valo Réaliste", page_icon="⚖️", layout="wide")
st.title("⚖️ AquaRisk 9.5 : Valorisation Financière Calibrée")

# --- INITIALISATION ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'auto_val' not in st.session_state: st.session_state.auto_val = 0.0

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
    try:
        ua = f"Fix_V95_{randint(100,999)}"
        geolocator = Nominatim(user_agent=ua, timeout=5)
        loc = geolocator.geocode(f"{ville}, {pays}", language='en')
        if loc: return loc
    except: return None
    return None

def trouver_meilleur_nom(nom_cherche, liste_options, seuil=75):
    if not nom_cherche or len(liste_options) == 0: return None
    meilleur_match, score = process.extractOne(str(nom_cherche), liste_options.astype(str))
    if score >= seuil: return meilleur_match
    return None

# --- 3. SOURCES EXTERNES ---
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
            return ' '.join([p.text for p in soup.find_all('p')])[:5000]
    except: return ""
    return ""

def get_company_news(company_name, country="France"):
    is_france = "france" in country.lower().strip()
    def clean(r): return re.sub(re.compile('<.*?>'), '', r).replace("&nbsp;", " ").replace("&#39;", "'")

    if is_france:
        q = urllib.parse.quote(f'"{company_name}" (eau OR pollution OR sécheresse OR environnement)')
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr"
    else:
        q = urllib.parse.quote(f'"{company_name}" (water OR pollution OR drought OR environment)')
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

    try:
        feed = feedparser.parse(rss_url)
        items = []
        name_parts = company_name.lower().split()
        main_keyword = name_parts[0] if len(name_parts) > 0 else company_name.lower()

        for e in feed.entries:
            title = e.title.lower()
            summary = clean(e.summary if 'summary' in e else e.title).lower()
            full_content = title + " " + summary
            if main_keyword not in full_content: continue
            items.append({"title": e.title, "link": e.link, "summary": clean(e.summary if 'summary' in e else e.title)[:250]})
            if len(items) >= 5: break
        return items
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

# --- 4. FINANCE ---
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
        resultat_net = 0 # Nouveau
        annee = "N/A"
        for c in f_data.get('finances', []):
            if c.get('chiffre_affaires'):
                ca = c['chiffre_affaires']
                resultat_net = c.get('resultat', 0)
                annee = c['annee_cloture_exercice']
                break
        return {"nom": match['nom_entreprise'], "ca": ca, "resultat": resultat_net, "annee": annee}
    except: return None

def get_stock_valuation(ticker):
    try:
        stock = yf.Ticker(ticker)
        mcap = stock.fast_info.get('market_cap')
        if mcap and mcap > 0: return mcap
        return stock.info.get('marketCap', 0)
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

# --- 6. CARTE ---
def generer_image_carte(lat, lon):
    try:
        m = StaticMap(800, 400)
        marker = CircleMarker((lon, lat), 'red', 18)
        m.add_marker(marker)
        image = m.render(zoom=10)
        img_path = "temp_map.png"
        image.save(img_path)
        return img_path
    except: return None

# --- 7. PDF ---
def create_pdf(data):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, clean(f"AUDIT V9.5: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(5)
    
    pdf.set_font("Arial", size=11)
    pdf.cell(0, 10, clean(f"Loc: {data['ville']} ({data['region']}, {data['pays']})"), ln=1)
    if data.get('valeur_entreprise'):
        # On affiche le secteur retenu si dispo
        info_supp = f" ({data.get('source_ca', 'Manuel')})"
        pdf.cell(0, 10, clean(f"Valuation Retenue: {data['valeur_entreprise']:,.0f} $ {info_supp}"), ln=1)
    
    pdf.set_text_color(200, 0, 0)
    pdf.cell(0, 10, clean(f"Perte Estimee (VaR): {data['var']:,.0f} $"), ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    map_file = generer_image_carte(data['lat'], data['lon'])
    if map_file and os.path.exists(map_file):
        pdf.image(map_file, x=10, w=190)
        pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, f"Score Risque: {data['s25_display']:.2f} / 5", ln=1)
    pdf.ln(5)
    
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 6, clean(f"Synthese IA:\n{data['txt_ia']}"))
    pdf.ln(10)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Sources & Bibliographie:", ln=1)
    
    if data['news']:
        pdf.set_font("Arial", size=9)
        for n in data['news']: pdf.cell(0, 5, clean(f"- {n['title'][:90]}"), ln=1)
    else:
        pdf.set_font("Arial", 'I', 9)
        pdf.cell(0, 5, "Pas de news environnementale critique trouvee.", ln=1)

    if data.get('wiki'):
        pdf.ln(5)
        pdf.set_font("Arial", 'I', 8)
        pdf.multi_cell(0, 4, clean(f"{data['wiki'][:600]}..."))
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 8. INTERFACE ---
with st.sidebar:
    st.header("⚙️ API Keys")
    pappers_key = st.text_input("Pappers (France)", type="password")

c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("1. Cible")
    ent = st.text_input("Nom Entreprise", "Michel et Augustin")
    v = st.text_input("Ville", "Boulogne-Billancourt")
    p = st.text_input("Pays", "France")
    website = st.text_input("Site Web", "")
    
    st.caption("🔍 **Chasseur de Rapports**")
    col_s1, col_s2 = st.columns(2)
    with col_s1: st.markdown(f"[📄 PDF](https://www.google.com/search?q={urllib.parse.quote(ent + ' rapport durable filetype:pdf')})", unsafe_allow_html=True)
    with col_s2: st.markdown(f"[📰 News](https://www.google.com/search?q={urllib.parse.quote(ent + ' pollution amende')})", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("2. Finance & Valorisation")
    mode_val = st.radio("Mode", ["Cotée", "Non Cotée (PME/ETI)"])
    valeur_finale = 0.0
    source_info = "Manuel"
    
    if mode_val == "Cotée":
        ticker = st.text_input("Ticker (ex: BN.PA)", "BN.PA")
        if st.button("📈 Bourse"):
            mcap = get_stock_valuation(ticker)
            if mcap > 0: 
                st.session_state.auto_val = mcap
                st.success(f"Valo : {mcap:,.0f} $")
            else:
                st.error("Erreur Bourse.")
        val_default = st.session_state.auto_val if st.session_state.auto_val > 0 else 1000000.0
        valeur_finale = st.number_input("Valo ($)", value=val_default)
        source_info = f"Bourse ({ticker})"
    
    else:
        # LOGIQUE PAPPERS AMÉLIORÉE
        if st.button("🇫🇷 Pappers Auto"):
            if pappers_key:
                i = get_pappers_financials(ent, pappers_key)
                if i: st.session_state.pappers_data = i
            else:
                st.warning("Clé API manquante !")
        
        ca_val = 500000.0
        is_beneficiaire = True # Par défaut
        
        if st.session_state.pappers_data:
            ca_val = float(st.session_state.pappers_data['ca'])
            # Détection rentabilité simple
            if st.session_state.pappers_data.get('resultat', 0) < 0:
                is_beneficiaire = False
            
            source_info = f"Pappers ({st.session_state.pappers_data['annee']})"
            st.success(f"CA: {ca_val:,.0f} €")
            if not is_beneficiaire: st.warning("⚠️ Entreprise déficitaire détectée")

        ca = st.number_input("Chiffre d'Affaires ($)", value=ca_val)
        
        # --- NOUVEAUX SECTEURS & MULTIPLES ---
        secteur_label = st.selectbox("Secteur d'Activité", [
            "Logiciel / SaaS (4.0x)", 
            "Service Info / ESN (0.9x)",
            "Industrie / Manuf. (0.5x)",
            "Commerce / Retail (0.4x)",
            "BTP / Construction (0.3x)",
            "Agroalimentaire (0.7x)",
            "Services aux Entr. (0.8x)"
        ])
        
        # Extraction du chiffre entre parenthèses
        coeff = float(re.search(r"([\d\.]+)x", secteur_label).group(1))
        
        # --- FACTEUR RENTABILITÉ ---
        rentable = st.checkbox("L'entreprise est rentable (Bénéficiaire) ?", value=is_beneficiaire)
        
        val_brute = ca * coeff
        if not rentable:
            val_brute = val_brute * 0.7 # Décote de 30%
            st.caption("📉 Décote de 30% appliquée (Non rentable)")
        
        st.info(f"Valo Estimée : {val_brute:,.0f} $")
        valeur_finale = st.number_input("Valo Retenue", value=val_brute)

    st.markdown("---")
    st.write("📂 **3. Data Room**")
    notes_manuelles = st.text_area("📋 Notes Manuelles", height=100)
    uploaded_docs = st.file_uploader("Drop PDF", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 AUDIT COMPLET"):
        with st.spinner("Analyse Intégrale..."):
            res = analyser_site(v, p)
            if res and res['found']:
                news = get_company_news(ent, country=p)
                wiki_lang = 'fr' if "france" in p.lower() else 'en'
                wiki_txt = get_wiki_summary(ent, lang=wiki_lang)
                web_txt = scan_website(website)
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_text, doc_names = extract_text_from_pdfs(uploaded_docs)
                
                corpus = f"{notes_manuelles} {web_txt} {wiki_txt} {doc_text} {' '.join([n['title'] for n in news])}"
                
