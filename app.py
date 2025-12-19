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

# --- CONFIGURATION ---
st.set_page_config(page_title="AquaRisk V13 : Master", page_icon="🏛️", layout="wide")
st.title("🏛️ AquaRisk V13 : Plateforme d'Audit & Valorisation Intégrale")

# --- INITIALISATION SESSION ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'live_multiples' not in st.session_state: st.session_state.live_multiples = None
if 'stock_mcap' not in st.session_state: st.session_state.stock_mcap = 0.0

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
    if df_now is None: 
        df_now = pd.DataFrame({'name_0': ['France'], 'name_1': ['Ile-de-France'], 'score': [2.5]})
    elif 'score' in df_now.columns:
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

# --- 2. GPS & GEOLOC (BLINDÉ) ---
class MockLocation:
    def __init__(self, lat, lon):
        self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    ville_clean = ville.lower().strip()
    fallback = {
        "paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "marseille": (43.2965, 5.3698),
        "bordeaux": (44.8378, -0.5792), "toulouse": (43.6047, 1.4442), "lille": (50.6292, 3.0573),
        "berlin": (52.5200, 13.4050), "london": (51.5074, -0.1278), "new york": (40.7128, -74.0060),
        "tokyo": (35.6762, 139.6503), "boulogne-billancourt": (48.8397, 2.2399),
        "munich": (48.1351, 11.5820)
    }
    if ville_clean in fallback: return MockLocation(*fallback[ville_clean])

    for i in range(2):
        try:
            ua = f"AR_V13_{randint(10000,99999)}"
            geolocator = Nominatim(user_agent=ua, timeout=5)
            loc = geolocator.geocode(f"{ville}, {pays}", language='en')
            if loc: return loc
        except: time.sleep(1); continue
    return MockLocation(48.8566, 2.3522) # Default Paris si échec total

def trouver_meilleur_nom(nom_cherche, liste_options, seuil=75):
    if not nom_cherche or len(liste_options) == 0: return None
    meilleur_match, score = process.extractOne(str(nom_cherche), liste_options.astype(str))
    if score >= seuil: return meilleur_match
    return None

# --- 3. RECHERCHE INTELLIGENCE (NEWS, WEB, PDF) ---
def get_market_news(sector_keywords):
    q = urllib.parse.quote(f"{sector_keywords} (acquisition OR rachat OR fusion OR valorisation)")
    rss_url = f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr"
    try:
        feed = feedparser.parse(rss_url)
        return [{"title": e.title, "link": e.link, "summary": e.summary[:200]} for e in feed.entries[:3]]
    except: return []

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
    try: return wikipedia.page(company_name).summary[:2000]
    except: return "Pas de données Wikipedia."

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

def get_company_news_strict(company_name, country="France"):
    is_france = "france" in country.lower().strip()
    def clean(r): return re.sub(re.compile('<.*?>'), '', r).replace("&nbsp;", " ").replace("&#39;", "'")
    
    # Mots clés stricts pour éviter le bruit (LGBT, Politique...)
    if is_france:
        q = urllib.parse.quote(f'"{company_name}" (eau OR pollution OR sécheresse OR environnement OR amende)')
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr"
    else:
        q = urllib.parse.quote(f'"{company_name}" (water OR pollution OR drought OR environment OR fine)')
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    
    try:
        feed = feedparser.parse(rss_url)
        items = []
        name_parts = company_name.lower().split()
        main_keyword = name_parts[0] if len(name_parts) > 0 else company_name.lower()
        
        for e in feed.entries:
            title = e.title.lower()
            summary = clean(e.summary if 'summary' in e else "").lower()
            # Filtre : Le nom de la boite doit être cité
            if main_keyword not in title and main_keyword not in summary: continue
            
            items.append({
                "title": e.title,
                "link": e.link,
                "summary": clean(e.summary if 'summary' in e else e.title)[:400]
            })
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
                for page in pdf.pages[:20]: text += page.extract_text() or ""
                full_text += text + " "
                file_names.append(pdf_file.name)
        except: continue
    return full_text, file_names

# --- 4. FINANCE (LE RETOUR DU COMPLET) ---
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
        mcap = stock.fast_info.get('market_cap')
        if not mcap: mcap = stock.info.get('marketCap', 0)
        ev = stock.info.get('enterpriseValue', 0)
        if not ev or ev == 0: ev = mcap
        return mcap, ev
    except: return 0, 0

def calculate_live_multiples():
    # Paniers de référence
    sectors_proxies = {
        "Logiciel": ["CRM", "ADBE"], 
        "ESN": ["CAP.PA", "ACN"],
        "Industrie": ["SIE.DE", "SU.PA"], 
        "Agro": ["BN.PA", "NESN.SW"],
        "Commerce": ["CA.PA", "WMT"], 
        "BTP": ["DG.PA", "EN.PA"]
    }
    results = {}
    for i, (sector, tickers) in enumerate(sectors_proxies.items()):
        mev_rev = []; mev_ebitda = []
        for t in tickers:
            try:
                stock = yf.Ticker(t)
                ev_rev = stock.info.get('enterpriseToRevenue')
                ev_ebitda = stock.info.get('enterpriseToEbitda')
                if ev_rev: mev_rev.append(ev_rev)
                if ev_ebitda: mev_ebitda.append(ev_ebitda)
            except: continue
        avg_rev = sum(mev_rev)/len(mev_rev) if mev_rev else 1.0
        avg_ebitda = sum(mev_ebitda)/len(mev_ebitda) if mev_ebitda else 8.0
        # On applique la décote PME (30%) directement ici
        results[sector] = {"ca_multiple": avg_rev * 0.70, "ebitda_multiple": avg_ebitda * 0.70, "sample": ", ".join(tickers)}
    return results

# --- 5. MOTEUR ANALYSE ---
def analyser_site(ville, pays):
    loc = get_location_safe(ville, pays)
    
    # Matching Pays
    liste_pays = df_actuel['name_0'].unique()
    pays_trouve = trouver_meilleur_nom(pays, liste_pays, seuil=70)
    if not pays_trouve: pays_trouve = pays

    # Score 2024
    s2024 = 2.5
    if pays_trouve in df_actuel['name_0'].values:
        df_pays = df_actuel[df_actuel['name_0'] == pays_trouve]
        s2024 = df_pays['score'].mean()

    # Score 2030 (+10% risque par défaut)
    s2030 = s2024 * 1.1
    if df_futur is not None and pays_trouve in df_futur['name_0'].values:
        df_f_pays = df_futur[df_futur['name_0'] == pays_trouve]
        s2030 = df_f_pays['score'].mean()

    # Interpolation 2026 (1/3 du chemin)
    delta = s2030 - s2024
    s2026 = s2024 + (delta * 0.33)
    
    return {
        "ent": "N/A", "ville": ville, "pays": pays_trouve, 
        "lat": loc.latitude, "lon": loc.longitude, 
        "s2024": s2024, "s2026": s2026, "s2030": s2030,
        "found": True
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

# --- 7. PDF INTERACTIF & RICHE ---
def create_pdf(data, corpus_text, notes):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    
    # --- PAGE 1 : SYNTHÈSE ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, clean(f"RAPPORT V13: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(5)
    
    # Carte
    map_file = generer_image_carte(data['lat'], data['lon'])
    if map_file and os.path.exists(map_file):
        pdf.image(map_file, x=20, w=170)
        pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. VALORISATION & RISQUE FINANCIER", ln=1)
    
    pdf.set_font("Arial", size=11)
    # Tableau Valeur
    pdf.cell(60, 10, clean(f"Valuation: {data['valeur_entreprise']:,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"Methode: {data.get('source_ca', 'Manuel')}"), border=1)
    pdf.cell(60, 10, clean(f"VaR 2030: {data['var_2030']:,.0f} $"), border=1)
    pdf.ln(15)
    
    # Tableau Climat
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "2. TRAJECTOIRE CLIMATIQUE", ln=1)
    pdf.set_font("Arial", size=11)
    pdf.cell(60, 10, f"Risque 2024: {data['s2024']:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Risque 2026: {data['s2026']:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Risque 2030: {data['s2030']:.2f}/5", border=1, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'I', 11)
    pdf.multi_cell(0, 6, clean(f"Synthese IA: {data['txt_ia']}"))
    
    # --- PAGE 2 : DETAILS & LIENS ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "3. REVUE DE PRESSE & DATA ROOM", ln=1)
    pdf.ln(5)
    
    # ARTICLES CLIQUABLES
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Articles de Presse (Cliquables)", ln=1)
    
    if data['news']:
        for n in data['news']:
            # Titre Bleu Souligné
            pdf.set_font("Arial", 'U', 10) 
            pdf.set_text_color(0, 0, 255) 
            pdf.cell(0, 6, clean(f">> {n['title']}"), ln=1, link=n['link'])
            
            # Résumé Noir
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Arial", '', 9)
            pdf.multi_cell(0, 5, clean(f"{n['summary']}"))
            pdf.ln(3)
    else:
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 10, "Aucun signal faible detecte.", ln=1)
    
    pdf.ln(5)
    
    # DOCUMENTS & NOTES
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Analyse Documents & Notes", ln=1)
    pdf.set_font("Arial", size=9)
    if data['doc_files']:
        pdf.multi_cell(0, 5, clean(f"Fichiers inclus: {', '.join(data['doc_files'])}"))
        # Extrait corpus
        extract = corpus_text[:1200].replace('\n', ' ')
        pdf.multi_cell(0, 5, clean(f"Extrait Data Room: {extract}..."))
    
    if notes:
        pdf.ln(5)
        pdf.set_font("Arial", 'I', 10)
        pdf.multi_cell(0, 6, clean(f"Notes Analyste: {notes}"))
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 8. INTERFACE ---
with st.sidebar:
    st.header("⚙️ Config & API")
    pappers_key = st.text_input("Pappers (France)", type="password")
    
    st.markdown("---")
    st.header("🔄 Live Market")
    if st.button("Actualiser Taux du Jour"):
        with st.spinner("Connexion Bourses Mondiales..."): 
            st.session_state.live_multiples = calculate_live_multiples()
        st.success("Taux mis à jour !")

c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("1. Cible")
    ent = st.text_input("Entreprise", "Michel et Augustin")
    v = st.text_input("Ville", "Boulogne-Billancourt")
    p = st.text_input("Pays", "France")
    website = st.text_input("Site Web", "")
    
    st.markdown("---")
    st.subheader("2. Finance & Valorisation")
    
    # TYPE ENTREPRISE (MENU COMPLET)
    mode_val = st.radio("Type", ["Cotée (Bourse)", "Non Cotée (PME/ETI)", "Startup (VC)"])
    valeur_finale = 0.0
    source_info = "Manuel"
    
    # SECTEUR (Pour le risque ET la valo)
    secteur_list = [
        "Agroalimentaire (Risk: Haut | Valo: x0.9)", 
        "Industrie (Risk: Moyen | Valo: x0.7)", 
        "BTP (Risk: Moyen | Valo: x0.4)", 
        "Commerce (Risk: Faible | Valo: x0.5)", 
        "Logiciel (Risk: Nul | Valo: x5.0)",
        "ESN / Services (Risk: Nul | Valo: x1.1)"
    ]
    secteur_choix = st.selectbox("Secteur d'Activité", secteur_list)
    
    # Mapping des coefficients (Fixed fallback)
    sec_map = {
        "Agro": {"vuln": 1.0, "mult_ca": 0.9, "mult_ebitda": 8.0},
        "Industrie": {"vuln": 0.7, "mult_ca": 0.7, "mult_ebitda": 6.0},
        "BTP": {"vuln": 0.4, "mult_ca": 0.4, "mult_ebitda": 4.5},
        "Commerce": {"vuln": 0.2, "mult_ca": 0.5, "mult_ebitda": 5.0},
        "Logiciel": {"vuln": 0.05, "mult_ca": 5.0, "mult_ebitda": 15.0},
        "ESN": {"vuln": 0.05, "mult_ca": 1.1, "mult_ebitda": 9.0}
    }
    # Clé simple (premier mot)
    sec_key = secteur_choix.split()[0]
    sec_data = sec_map.get(sec_key, sec_map["Agro"]) # Default Agro

    # --- LOGIQUE COTÉE ---
    if "Cotée" in mode_val:
        ticker = st.text_input("Ticker", "BN.PA")
        methode_cotee = st.selectbox("Indicateur", ["Market Cap", "Enterprise Value"])
        if st.button("Live Data"):
            m, e = get_stock_advanced(ticker)
            if m > 0: 
                st.session_state.stock_mcap = m; st.session_state.stock_ev = e
        
        val_ref = st.session_state.get('stock_mcap', 1000000.0)
        if methode_cotee == "Enterprise Value": 
            val_ref = st.session_state.get('stock_ev', val_ref)
        valeur_finale = st.number_input("Valo ($)", value=val_ref)
        source_info = f"Bourse {ticker}"
    
    # --- LOGIQUE STARTUP ---
    elif "Startup" in mode_val:
        stade = st.selectbox("Stade Maturité", ["Seed", "Series A", "Series B"])
        ranges = {"Seed": (3e6, 8e6), "Series A": (10e6, 30e6), "Series B": (30e6, 80e6)}
        min_v, max_v = ranges[stade]
        valeur_finale = st.slider("Valo ($)", min_v, max_v, (min_v+max_v)/2)
        source_info = f"VC Market ({stade})"
    
    # --- LOGIQUE PME / NON COTÉE (COMPLÈTE) ---
    else:
        if st.button("Pappers Auto"):
            i = get_pappers_financials(ent, pappers_key)
            if i: st.session_state.pappers_data = i
        
        # MENU MÉTHODES COMPLET
        method_pme = st.selectbox("Méthode", [
            "1. Multiple du CA (Comparables)",
            "2. Multiple de l'EBITDA (Rentabilité)",
            "3. DCF (Discounted Cash Flow)",
            "4. Patrimonial (Capitaux Propres)"
        ])

        ca_val = 1000000.0; res_val = 100000.0; cap_val = 200000.0
        if st.session_state.pappers_data:
            d = st.session_state.pappers_data
            if d['ca']: ca_val = float(d['ca'])
            if d['ebitda']: res_val = float(d['ebitda'])
            if d['capitaux']: cap_val = float(d['capitaux'])

        val_calc = 0.0
        
        # Calculs selon méthode
        if "Multiple" in method_pme:
            is_ca = "CA" in method_pme
            base = ca_val if is_ca else res_val
            
            # Priorité Live Market > Fixe
            coeff = sec_data['mult_ca'] if is_ca else sec_data['mult_ebitda']
            live = st.session_state.live_multiples
            if live and sec_key in live:
                d_live = live[sec_key]
                coeff = d_live['ca_multiple'] if is_ca else d_live['ebitda_multiple']
                st.caption(f"Taux Live ({d_live['sample']}) : x{coeff:.2f}")
            else:
                st.caption(f"Taux Standard : x{coeff:.2f}")

            val_calc = st.number_input(f"Base Calcul ($)", value=base) * coeff
            source_info = f"{method_pme} ({sec_key})"

        elif "DCF" in method_pme:
            fcf = st.number_input("Flux Trésorerie (FCF) $", value=res_val)
            g = st.slider("Croissance %", 0.0, 5.0, 1.5)/100
            wacc = st.slider("WACC (Risque) %", 5.0, 20.0, 10.0)/100
            if wacc > g: val_calc = fcf * (1 + g) / (wacc - g)
            source_info = "DCF Model"

        elif "Patrimonial" in method_pme:
            val_calc = st.number_input("Capitaux Propres ($)", value=cap_val)
            source_info = "Actif Net"

        st.info(f"Valo Calculée : {val_calc:,.0f} $")
        valeur_finale = st.number_input("Valo Retenue", value=val_calc)

    st.markdown("---")
    st.write("📂 **3. Data Room**")
    notes_manuelles = st.text_area("Notes", height=100)
    uploaded_docs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 LANCER L'AUDIT"):
        with st.spinner("Analyse 360° en cours..."):
            res = analyser_site(v, p)
            if res and res['found']:
                news = get_company_news_strict(ent, country=p)
                ma_news = get_market_news(ent)
                wiki_txt = get_wiki_summary(ent)
                web_txt = scan_website(website)
                doc_text, doc_names = extract_text_from_pdfs(uploaded_docs)
                
                full_corpus = f"{notes_manuelles} {web_txt} {wiki_txt} {doc_text} {' '.join([n['title'] for n in news])}"
                
                # VaR avec facteur de vulnérabilité du secteur choisi
                vuln = sec_data['vuln']
                delta_risk_2026 = max(0, res['s2026'] - 1.5)
                delta_risk_2030 = max(0, res['s2030'] - 1.5)
                
                impact_2026 = valeur_finale * (delta_risk_2026 / 5.0) * vuln
                impact_2030 = valeur_finale * (delta_risk_2030 / 5.0) * vuln

                risk_count = sum(1 for w in ['litige', 'procès', 'amende'] if w in full_corpus.lower())
                txt_ia = "Situation stable."
                if risk_count > 0: txt_ia = f"⚠️ ALERTE : {risk_count} mentions de risques légaux détectées."

                res['ent'] = ent; res['valeur_entreprise'] = valeur_finale; res['source_ca'] = source_info
                res['var_2026'] = impact_2026; res['var_2030'] = impact_2030
                res['doc_files'] = doc_names; res['txt_ia'] = txt_ia; res['news'] = news + ma_news
                res['full_text'] = full_corpus
                
                st.session_state.audit_unique = res
                st.rerun()

with c2:
    if st.session_state.audit_unique:
        r = st.session_state.audit_unique
        st.success(f"Audit Terminé : {r['ent']}")
        
        c0, c1, c2 = st.columns(3)
        c0.metric("Valorisation", f"{r['valeur_entreprise']:,.0f} $", delta=r.get('source_ca',''))
        c1.metric("Risque 2024 -> 2030", f"{r['s2024']:.2f} ➔ {r['s2030']:.2f}")
        c2.metric("Perte Potentielle 2030", f"{r['var_2030']:,.0f} $", delta="-Impact", delta_color="inverse")
        
        st.info(f"📅 **Impact 2026 :** {r['var_2026']:,.0f} $ | Vulnérabilité Secteur : {sec_data['vuln']*100}%")
        
        t1, t2 = st.tabs(["📄 Rapport PDF", "📊 Détails"])
        with t1:
            pdf = create_pdf(r, r['full_text'], notes_manuelles)
            st.download_button("Télécharger Rapport Complet (PDF)", pdf, file_name="Rapport_Audit_V12.5.pdf")
            
        with t2:
            st.write("### Articles")
            for n in r['news']: st.markdown(f"- [{n['title']}]({n['link']})")
            
        m = folium.Map([r['lat'], r['lon']], zoom_start=9)
        folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color="red")).add_to(m)
        st_folium(m, height=250)
