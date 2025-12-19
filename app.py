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
st.set_page_config(page_title="AquaRisk V15 : Ultimate", page_icon="💎", layout="wide")
st.title("💎 AquaRisk V15 : Audit Financier, Climatique & Documentaire Complet")

if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'live_multiples' not in st.session_state: st.session_state.live_multiples = None
if 'stock_data' not in st.session_state: st.session_state.stock_data = {"mcap": 0, "ev": 0}

# ==============================================================================
# 2. CHARGEMENT DATA (RISQUE EAU)
# ==============================================================================
@st.cache_data
def load_data():
    def smart_read(filename):
        if not os.path.exists(filename): return None
        if os.path.getsize(filename) < 50: return None
        try:
            df = pd.read_csv(filename, sep=',', engine='python', on_bad_lines='skip')
            df.columns = [c.lower().strip() for c in df.columns]
            return df
        except: return None

    df_now = smart_read("risk_actuel.csv")
    # Fallback pour ne pas planter si pas de CSV
    if df_now is None: 
        df_now = pd.DataFrame({'name_0': ['France'], 'name_1': ['Ile-de-France'], 'score': [2.5]})
    elif 'score' in df_now.columns:
        df_now['score'] = pd.to_numeric(df_now['score'].astype(str).str.replace(',', '.'), errors='coerce')

    df_fut = smart_read("risk_futur.csv")
    if df_fut is not None and 'score' in df_fut.columns:
        df_fut['score'] = pd.to_numeric(df_fut['score'].astype(str).str.replace(',', '.'), errors='coerce')
        # Filtre sur 2030 BAU
        if 'year' in df_fut.columns:
            df_fut = df_fut[(df_fut['year'] == 2030) & (df_fut['scenario'] == 'bau')]
            
    return df_now, df_fut

try:
    df_actuel, df_futur = load_data()
except: st.stop()

# ==============================================================================
# 3. OUTILS API (PAPPERS, YAHOO, GPS, METEO)
# ==============================================================================

# --- PAPPERS (BILAN ENTREPRISE) ---
def get_pappers_financials(company_name, api_key):
    if not api_key: return None
    try:
        # 1. Recherche Siren
        q = urllib.parse.quote(company_name)
        s_url = f"https://api.pappers.fr/v2/recherche?q={q}&api_token={api_key}&par_page=1"
        r = requests.get(s_url, timeout=5).json()
        if not r.get('resultats'): return None
        
        match = r['resultats'][0]
        siren = match['siren']
        
        # 2. Récupération Bilan
        f_url = f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={siren}"
        f_data = requests.get(f_url, timeout=5).json()
        
        ca=0; res=0; cap=0; ebitda=0; annee="N/A"
        # On cherche le dernier bilan disponible
        for c in f_data.get('finances', []):
            if c.get('annee_cloture_exercice'):
                ca = c.get('chiffre_affaires', 0) or 0
                res = c.get('resultat', 0) or 0
                cap = c.get('capitaux_propres', 0) or 0
                # Approximation EBITDA standard (Résultat + 25%)
                ebitda = res * 1.25 if res > 0 else 0 
                annee = c['annee_cloture_exercice']
                break
                
        return {
            "nom": match['nom_entreprise'], "siren": siren, "annee": annee,
            "ca": ca, "resultat": res, "capitaux": cap, "ebitda": ebitda
        }
    except: return None

# --- YAHOO FINANCE (BOURSE) ---
def get_stock_advanced(ticker):
    try:
        stock = yf.Ticker(ticker)
        mcap = stock.fast_info.get('market_cap')
        if not mcap: mcap = stock.info.get('marketCap', 0)
        ev = stock.info.get('enterpriseValue', 0)
        if not ev or ev == 0: ev = mcap
        return mcap, ev
    except: return 0, 0

# --- GPS BLINDÉ ---
class MockLocation:
    def __init__(self, lat, lon):
        self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    # Base locale pour éviter les timeouts sur les grandes villes
    ville_clean = ville.lower().strip()
    fallback = {
        "paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "marseille": (43.2965, 5.3698),
        "bordeaux": (44.8378, -0.5792), "toulouse": (43.6047, 1.4442), "boulogne-billancourt": (48.8397, 2.2399),
        "new york": (40.7128, -74.0060), "berlin": (52.5200, 13.4050), "london": (51.5074, -0.1278)
    }
    if ville_clean in fallback: return MockLocation(*fallback[ville_clean])

    for i in range(2): # 2 essais API
        try:
            ua = f"AquaRisk_V15_{randint(1000,9999)}"
            geolocator = Nominatim(user_agent=ua, timeout=8)
            loc = geolocator.geocode(f"{ville}, {pays}", language='en')
            if loc: return loc
        except: time.sleep(1); continue
    return MockLocation(48.8566, 2.3522) # Default Paris

# --- MÉTÉO ---
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

# --- NEWS & WEB ---
def get_company_news(company_name):
    # Recherche stricte pour éviter le bruit
    q = urllib.parse.quote(f'"{company_name}" (eau OR pollution OR sécheresse OR environnement)')
    rss_url = f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr"
    try:
        feed = feedparser.parse(rss_url)
        return [{"title": e.title, "link": e.link, "summary": e.summary[:300]} for e in feed.entries[:5]]
    except: return []

def get_wiki_summary(company_name):
    wikipedia.set_lang('fr')
    try: return wikipedia.page(company_name).summary[:2000]
    except: return "Pas de Wikipedia."

def scan_website(url):
    if not url or len(url) < 5: return ""
    if not url.startswith("http"): url = "https://" + url
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        return ' '.join([p.text for p in soup.find_all('p')])[:5000]
    except: return ""

def extract_text_from_pdfs(uploaded_files):
    full_text = ""; file_names = []
    if not uploaded_files: return "", []
    for pdf_file in uploaded_files:
        try:
            with pdfplumber.open(pdf_file) as pdf:
                text = ""
                for page in pdf.pages[:20]: text += page.extract_text() or ""
                full_text += text + " "
                file_names.append(pdf_file.name)
        except: continue
    return full_text, file_names

# ==============================================================================
# 4. MOTEUR ANALYSE (RISQUE CLIMATIQUE & RÉGION)
# ==============================================================================
def analyser_risque_geo(ville, pays):
    loc = get_location_safe(ville, pays)
    
    # 1. Fuzzy Match Pays
    liste_pays = df_actuel['name_0'].unique()
    pays_match, score = process.extractOne(str(pays), liste_pays.astype(str))
    if score < 60: pays_match = pays # Garde l'original si pas trouvé

    # 2. Score 2024
    s2024 = 2.5
    if pays_match in df_actuel['name_0'].values:
        s2024 = df_actuel[df_actuel['name_0'] == pays_match]['score'].mean()

    # 3. Score 2030 (+10% risque par défaut si pas de donnée)
    s2030 = s2024 * 1.1
    if df_futur is not None and pays_match in df_futur['name_0'].values:
        s2030 = df_futur[df_futur['name_0'] == pays_match]['score'].mean()

    # 4. Interpolation 2026
    delta = s2030 - s2024
    s2026 = s2024 + (delta * 0.33)
    
    return {
        "ent": "N/A", "ville": ville, "pays": pays_match, 
        "lat": loc.latitude, "lon": loc.longitude, 
        "s2024": s2024, "s2026": s2026, "s2030": s2030,
        "found": True
    }

# ==============================================================================
# 5. PDF GENERATOR
# ==============================================================================
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

def create_pdf(data, corpus_text, notes):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    
    # --- PAGE 1 ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, clean(f"RAPPORT V15: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    # Carte
    map_file = generer_image_carte(data['lat'], data['lon'])
    if map_file and os.path.exists(map_file):
        pdf.image(map_file, x=20, w=170)
        pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. SYNTHESE FINANCIERE & CLIMATIQUE", ln=1)
    pdf.set_font("Arial", size=11)
    
    # Tableau Valeur
    pdf.cell(60, 10, clean(f"Valuation: {data['valeur_entreprise']:,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"Methode: {data.get('source_ca', 'Manuel')}"), border=1)
    pdf.cell(60, 10, clean(f"VaR 2030: {data['var_2030']:,.0f} $"), border=1)
    pdf.ln(15)
    
    # Tableau Risque Eau
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 8, clean(f"Risque Eau (Score/5) - Localisation: {data['ville']}"), ln=1)
    pdf.set_font("Arial", size=11)
    pdf.cell(60, 10, f"Actuel 2024: {data['s2024']:.2f}", border=1, align='C')
    pdf.cell(60, 10, f"Moyen 2026: {data['s2026']:.2f}", border=1, align='C')
    pdf.cell(60, 10, f"Futur 2030: {data['s2030']:.2f}", border=1, align='C')
    pdf.ln(10)
    
    # Météo & IA
    if data['pluie_90j']: pdf.cell(0, 10, f"Precipitations recentes (90j): {data['pluie_90j']} mm", ln=1)
    pdf.ln(5)
    pdf.set_font("Arial", 'I', 11)
    pdf.multi_cell(0, 6, clean(f"Synthese IA: {data['txt_ia']}"))
    
    # --- PAGE 2 ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "2. DETAILS, SOURCES & LIENS", ln=1)
    pdf.ln(5)
    
    if data['news']:
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Presse Analyse (Cliquable)", ln=1)
        for n in data['news']:
            pdf.set_font("Arial", 'U', 10) 
            pdf.set_text_color(0, 0, 255) 
            pdf.cell(0, 6, clean(f">> {n['title']}"), ln=1, link=n['link'])
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Arial", '', 9)
            pdf.multi_cell(0, 5, clean(f"{n['summary']}"))
            pdf.ln(3)
    
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Documents & Notes", ln=1)
    pdf.set_font("Arial", size=9)
    if data['doc_files']:
        pdf.multi_cell(0, 5, clean(f"Fichiers: {', '.join(data['doc_files'])}"))
        extract = corpus_text[:1200].replace('\n', ' ')
        pdf.multi_cell(0, 5, clean(f"Extrait Data Room: {extract}..."))
    
    if notes:
        pdf.ln(5)
        pdf.set_font("Arial", 'I', 10)
        pdf.multi_cell(0, 6, clean(f"Notes: {notes}"))
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# ==============================================================================
# 6. INTERFACE (SIDEBAR & MAIN)
# ==============================================================================
with st.sidebar:
    st.header("⚙️ Configuration")
    pappers_key = st.text_input("Clé API Pappers", type="password")
    
    st.markdown("---")
    st.header("🔄 Live Market")
    # Simulation des taux live si on ne veut pas scraper 50 tickers à chaque fois
    if st.button("Actualiser Taux Bourse"):
        st.session_state.live_multiples = {
            "Logiciel": {"ca": 5.5, "ebitda": 18.0},
            "Industrie": {"ca": 0.8, "ebitda": 7.0},
            "Agro": {"ca": 1.1, "ebitda": 9.5},
            "Services": {"ca": 1.2, "ebitda": 8.0}
        }
        st.success("Taux mis à jour (Simulé pour rapidité)")

c1, c2 = st.columns([1, 2])

# --- COLONNE GAUCHE : INPUTS ---
with c1:
    st.subheader("1. Entreprise & Localisation")
    ent = st.text_input("Nom", "Michel et Augustin")
    v = st.text_input("Ville", "Boulogne-Billancourt")
    p = st.text_input("Pays", "France")
    website = st.text_input("Site Web", "")
    
    st.markdown("---")
    st.subheader("2. Valorisation & Finance")
    
    # Choix Type
    mode_val = st.radio("Type d'entreprise", ["Non Cotée (PME/ETI)", "Cotée (Bourse)", "Startup (VC)"])
    valeur_finale = 0.0
    source_info = "Manuel"
    
    # Choix Secteur (Pour Risque ET Finance)
    secteur_full = st.selectbox("Secteur d'Activité", [
        "Agroalimentaire (Risk: Haut | Valo: x1.1)", 
        "Industrie (Risk: Moyen | Valo: x0.8)", 
        "Logiciel / SaaS (Risk: Faible | Valo: x5.5)",
        "Services / ESN (Risk: Faible | Valo: x1.2)"
    ])
    
    # Mapping Vulnérabilité (Pour VaR) & Coefficients (Pour Valo)
    sec_key = secteur_full.split()[0] # "Agroalimentaire", "Industrie"...
    vuln_map = {"Agroalimentaire": 1.0, "Industrie": 0.7, "Logiciel": 0.1, "Services": 0.2}
    vuln_factor = vuln_map.get(sec_key, 0.5)
    
    # --- LOGIQUE NON COTÉE (LE COEUR DU PROBLÈME) ---
    if "Non Cotée" in mode_val:
        # 1. Pappers Button
        if st.button("🔍 Récupérer Bilan (Pappers)"):
            with st.spinner("Connexion API Pappers..."):
                i = get_pappers_financials(ent, pappers_key)
                if i: 
                    st.session_state.pappers_data = i
                    st.success(f"Bilan {i['annee']} trouvé !")
                else:
                    st.error("Entreprise introuvable ou Clé API invalide.")
        
        # 2. Input Fields (Remplis par Pappers ou Manuel)
        ca_val = 1000000.0; res_val = 100000.0; cap_val = 200000.0
        if st.session_state.pappers_data:
            d = st.session_state.pappers_data
            if d['ca']: ca_val = float(d['ca'])
            if d['resultat']: res_val = float(d['resultat'])
            if d['capitaux']: cap_val = float(d['capitaux'])
            st.info(f"Données chargées : CA={ca_val:,.0f}€")

        # 3. Choix Méthode
        method_pme = st.selectbox("Méthode de Calcul", [
            "Multiple du CA", 
            "Multiple EBITDA (Rentabilité)", 
            "DCF (Flux Futurs)", 
            "Patrimonial (Capitaux Propres)"
        ])
        
        val_calc = 0.0
        if "Multiple du CA" in method_pme:
            base = st.number_input("Chiffre d'Affaires (€)", value=ca_val)
            # On prend le coeff du secteur choisi plus haut
            coeff_ca = {"Agroalimentaire": 1.1, "Industrie": 0.8, "Logiciel": 5.5, "Services": 1.2}.get(sec_key, 1.0)
            st.caption(f"Coeff Secteur : x{coeff_ca}")
            val_calc = base * coeff_ca
            source_info = f"CA x{coeff_ca}"
            
        elif "Multiple EBITDA" in method_pme:
            base = st.number_input("EBITDA / Résultat (€)", value=res_val)
            coeff_ebitda = {"Agroalimentaire": 9.5, "Industrie": 7.0, "Logiciel": 18.0, "Services": 8.0}.get(sec_key, 7.0)
            st.caption(f"Coeff Rentabilité : x{coeff_ebitda}")
            val_calc = base * coeff_ebitda
            source_info = f"EBITDA x{coeff_ebitda}"
            
        elif "DCF" in method_pme:
            fcf = st.number_input("Flux Trésorerie (FCF)", value=res_val)
            g = st.slider("Croissance %", 0.0, 10.0, 2.0)/100
            wacc = st.slider("WACC %", 5.0, 15.0, 10.0)/100
            if wacc > g: val_calc = fcf * (1+g) / (wacc-g)
            source_info = "DCF Gordon"
            
        elif "Patrimonial" in method_pme:
            val_calc = st.number_input("Capitaux Propres", value=cap_val)
            source_info = "Actif Net"

        st.success(f"Valorisation Calculée : {val_calc:,.0f} €")
        valeur_finale = st.number_input("Valo Retenue", value=val_calc)

    # --- LOGIQUE COTÉE ---
    elif "Cotée" in mode_val:
        ticker = st.text_input("Ticker", "BN.PA")
        ind = st.selectbox("Indicateur", ["Market Cap", "Enterprise Value"])
        if st.button("Live Yahoo"):
            m, e = get_stock_advanced(ticker)
            if m > 0: st.session_state.stock_data = {"mcap":m, "ev":e}
        
        ref = st.session_state.stock_data['mcap']
        if ind == "Enterprise Value": ref = st.session_state.stock_data['ev']
        valeur_finale = st.number_input("Valo Retenue", value=ref if ref > 0 else 1000000.0)
        source_info = f"Bourse {ticker}"

    # --- LOGIQUE STARTUP ---
    elif "Startup" in mode_val:
        stade = st.selectbox("Stade", ["Seed (3-8M)", "Series A (10-30M)", "Series B (30-80M)"])
        valeur_finale = st.slider("Valo", 1000000.0, 80000000.0, 5000000.0)
        source_info = f"VC {stade}"

    st.markdown("---")
    st.write("📂 **3. Data Room & Analyse**")
    notes_manuelles = st.text_area("Notes / Extraits", height=100)
    uploaded_docs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 LANCER L'AUDIT FINAL"):
        with st.spinner("Analyse Croisée en cours..."):
            # 1. Analyse Geo & Climat
            res_geo = analyser_risque_geo(v, p)
            
            if res_geo['found']:
                # 2. Collecte Intelligence
                news = get_company_news(ent)
                wiki = get_wiki_summary(ent)
                web = scan_website(website)
                pluie = get_weather_history(res_geo['lat'], res_geo['lon'])
                doc_text, doc_names = extract_text_from_pdfs(uploaded_docs)
                
                # 3. Synthèse IA & Texte
                corpus = f"{notes_manuelles} {web} {wiki} {doc_text} {' '.join([n['title'] for n in news])}"
                
                # Calcul VaR Financière
                risk_delta_26 = max(0, res_geo['s2026'] - 1.5)
                risk_delta_30 = max(0, res_geo['s2030'] - 1.5)
                
                impact_26 = valeur_finale * (risk_delta_26 / 5.0) * vuln_factor
                impact_30 = valeur_finale * (risk_delta_30 / 5.0) * vuln_factor
                
                # Génération du résumé
                risk_words = sum(1 for w in ['procès', 'litige', 'amende', 'pollution'] if w in corpus.lower())
                txt_ia = f"Analyse basée sur {len(doc_names)} documents et le web. "
                if risk_words > 0: txt_ia += f"ATTENTION: {risk_words} alertes détectées."
                else: txt_ia += "Aucune alerte majeure détectée."
                
                # Stockage Résultat
                final_res = {
                    "ent": ent, "ville": v, "pays": res_geo['pays'],
                    "lat": res_geo['lat'], "lon": res_geo['lon'],
                    "valeur_entreprise": valeur_finale, "source_ca": source_info,
                    "s2024": res_geo['s2024'], "s2026": res_geo['s2026'], "s2030": res_geo['s2030'],
                    "var_2026": impact_26, "var_2030": impact_30,
                    "pluie_90j": pluie,
                    "news": news, "doc_files": doc_names, "txt_ia": txt_ia,
                    "full_text": corpus
                }
                st.session_state.audit_unique = final_res
                st.rerun()

# --- COLONNE DROITE : RÉSULTATS ---
with c2:
    if st.session_state.audit_unique:
        r = st.session_state.audit_unique
        st.success(f"✅ Audit Terminé : {r['ent']}")
        
        # KPI
        k1, k2, k3 = st.columns(3)
        k1.metric("Valorisation", f"{r['valeur_entreprise']:,.0f} €", delta=r['source_ca'])
        k2.metric("Risque Eau 2030", f"{r['s2030']:.2f} / 5", delta=f"{r['s2030']-r['s2024']:.2f}", delta_color="inverse")
        k3.metric("VaR (Perte 2030)", f"{r['var_2030']:,.0f} €", delta="-Impact", delta_color="inverse")
        
        # Météo & Synthèse
        st.info(f"🌧️ Météo Locale (90j) : {r['pluie_90j']} mm | 🤖 Synthèse : {r['txt_ia']}")
        
        # Onglets Détails
        t1, t2 = st.tabs(["📄 Rapport & PDF", "📊 Sources"])
        with t1:
            st.write("### Aperçu du Rapport")
            pdf_bytes = create_pdf(r, r['full_text'], notes_manuelles)
            st.download_button("📥 Télécharger Rapport PDF Complet", pdf_bytes, file_name=f"Audit_{r['ent']}.pdf")
            
            m = folium.Map([r['lat'], r['lon']], zoom_start=10)
            folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color='red')).add_to(m)
            st_folium(m, height=300)
            
        with t2:
            st.write("#### Revue de Presse")
            for n in r['news']: st.markdown(f"- [{n['title']}]({n['link']})")
                
