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
st.set_page_config(page_title="AquaRisk 12.5 : Ultimate", page_icon="💎", layout="wide")
st.title("💎 AquaRisk 12.5 : Audit, Valorisation Expert & PDF Interactif")

# --- INITIALISATION ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'live_multiples' not in st.session_state: st.session_state.live_multiples = None

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

# --- 2. FONCTIONS TECH (GPS FALLBACK) ---
class MockLocation:
    def __init__(self, lat, lon):
        self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    ville_clean = ville.lower().strip()
    fallback = {
        "paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "marseille": (43.2965, 5.3698),
        "bordeaux": (44.8378, -0.5792), "toulouse": (43.6047, 1.4442), "lille": (50.6292, 3.0573),
        "berlin": (52.5200, 13.4050), "london": (51.5074, -0.1278), "new york": (40.7128, -74.0060),
        "tokyo": (35.6762, 139.6503), "boulogne-billancourt": (48.8397, 2.2399)
    }
    if ville_clean in fallback: return MockLocation(*fallback[ville_clean])

    for i in range(2):
        try:
            ua = f"AR_Ent_{randint(10000,99999)}"
            geolocator = Nominatim(user_agent=ua, timeout=5)
            loc = geolocator.geocode(f"{ville}, {pays}", language='en')
            if loc: return loc
        except: time.sleep(1); continue
    return MockLocation(48.8566, 2.3522)

def trouver_meilleur_nom(nom_cherche, liste_options, seuil=75):
    if not nom_cherche or len(liste_options) == 0: return None
    meilleur_match, score = process.extractOne(str(nom_cherche), liste_options.astype(str))
    if score >= seuil: return meilleur_match
    return None

# --- 3. NEWS & WEB ---
def get_market_news(sector_keywords):
    q = urllib.parse.quote(f"{sector_keywords} (acquisition OR rachat OR fusion OR valorisation)")
    rss_url = f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr"
    try:
        feed = feedparser.parse(rss_url)
        return [{"title": e.title, "link": e.link, "summary": e.summary if 'summary' in e else e.title} for e in feed.entries[:3]]
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
    except: return "Pas de page Wikipedia trouvée."

def scan_website(url):
    if not url or len(url) < 5: return ""
    if not url.startswith("http"): url = "https://" + url
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            return ' '.join([p.text for p in soup.find_all('p')])[:8000]
    except: return ""
    return ""

def get_company_news_strict(company_name, country="France"):
    is_france = "france" in country.lower().strip()
    def clean(r): return re.sub(re.compile('<.*?>'), '', r).replace("&nbsp;", " ").replace("&#39;", "'")
    if is_france:
        q = urllib.parse.quote(f'"{company_name}" (eau OR pollution OR environnement OR climat)')
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr"
    else:
        q = urllib.parse.quote(f'"{company_name}" (water OR pollution OR environment OR climate)')
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(rss_url)
        items = []
        name_parts = company_name.lower().split()
        main_keyword = name_parts[0] if len(name_parts) > 0 else company_name.lower()
        for e in feed.entries:
            title = e.title.lower()
            if main_keyword not in title and main_keyword not in clean(e.summary).lower(): continue
            items.append({"title": e.title, "link": e.link, "summary": clean(e.summary)[:500]})
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
        ca=0; res=0; cap=0; ebitda=0; annee="N/A"
        for c in f_data.get('finances', []):
            if c.get('annee_cloture_exercice'):
                ca = c.get('chiffre_affaires', 0)
                res = c.get('resultat', 0)
                cap = c.get('capitaux_propres', 0)
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
    sectors_proxies = {
        "Logiciel (SaaS)": ["CRM", "ADBE"], "Service Info (ESN)": ["CAP.PA"],
        "Industrie": ["SIE.DE", "SU.PA"], "Agroalimentaire": ["BN.PA", "NESN.SW"],
        "Commerce / Retail": ["CA.PA", "WMT"], "BTP / Construction": ["DG.PA", "EN.PA"]
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

    # Score 2030
    s2030 = s2024 * 1.1
    if df_futur is not None and pays_trouve in df_futur['name_0'].values:
        df_f_pays = df_futur[df_futur['name_0'] == pays_trouve]
        s2030 = df_f_pays['score'].mean()

    # Interpolation 2026
    delta = s2030 - s2024
    s2026 = s2024 + (delta * (2/6))
    
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

# --- 7. PDF INTERACTIF ---
def create_pdf(data, corpus_text, notes):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    
    # PAGE 1 : DASHBOARD
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, clean(f"RAPPORT D'AUDIT: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    map_file = generer_image_carte(data['lat'], data['lon'])
    if map_file and os.path.exists(map_file):
        pdf.image(map_file, x=20, w=170)
        pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "SYNTHESE FINANCIERE & CLIMATIQUE", ln=1)
    pdf.set_font("Arial", size=11)
    
    # Tableau Valeur
    pdf.cell(60, 10, clean(f"Valorisation: {data['valeur_entreprise']:,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"Methode: {data.get('source_ca', 'Manuel')}"), border=1)
    pdf.cell(60, 10, clean(f"Perte 2030: {data['var_2030']:,.0f} $"), border=1)
    pdf.ln(15)
    
    # Trajectoire
    pdf.cell(60, 10, f"Risque 2024: {data['s2024']:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Risque 2026: {data['s2026']:.2f}/5", border=1, align='C')
    pdf.cell(60, 10, f"Risque 2030: {data['s2030']:.2f}/5", border=1, align='C')
    pdf.ln(15)

    pdf.set_font("Arial", 'I', 11)
    pdf.multi_cell(0, 6, clean(f"Conclusion: {data['txt_ia']}"))
    
    # PAGE 2 : SOURCES CLIQUABLES
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "REVUE DE PRESSE & DATA ROOM", ln=1)
    pdf.ln(5)
    
    # ARTICLES
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "1. Sources Web & Presse (Cliquable)", ln=1)
    
    if data['news']:
        for n in data['news']:
            # TITRE BLEU ET CLIQUABLE
            pdf.set_font("Arial", 'U', 10) # Souligné
            pdf.set_text_color(0, 0, 255) # Bleu
            pdf.cell(0, 6, clean(f"- {n['title']}"), ln=1, link=n['link'])
            
            # RÉSUMÉ NOIR
            pdf.set_text_color(0, 0, 0) # Noir
            pdf.set_font("Arial", '', 9)
            pdf.multi_cell(0, 5, clean(f"{n['summary']}"))
            pdf.ln(3)
    else:
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 10, "Aucun article critique detecte.", ln=1)
    
    pdf.ln(5)
    
    # DOCUMENTS
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "2. Analyse Fichiers Internes", ln=1)
    pdf.set_font("Arial", size=9)
    if data['doc_files']:
        pdf.multi_cell(0, 5, clean(f"Fichiers: {', '.join(data['doc_files'])}"))
        extract = corpus_text[:1500].replace('\n', ' ')
        pdf.multi_cell(0, 5, clean(f"Extrait analyse: {extract}..."))
    else:
        pdf.cell(0, 10, "Aucun document fourni.", ln=1)

    if notes:
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "3. Notes Auditeur", ln=1)
        pdf.set_font("Arial", 'I', 10)
        pdf.multi_cell(0, 6, clean(notes))
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 8. INTERFACE ---
with st.sidebar:
    st.header("⚙️ Config")
    pappers_key = st.text_input("Clé API Pappers", type="password")
    if st.button("Actualiser Marchés"):
        with st.spinner("Wait..."): st.session_state.live_multiples = calculate_live_multiples()

c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("1. Cible")
    ent = st.text_input("Entreprise", "Michel et Augustin")
    v = st.text_input("Ville", "Boulogne-Billancourt")
    p = st.text_input("Pays", "France")
    website = st.text_input("Site Web", "")
    
    st.markdown("---")
    st.subheader("2. Finance & Valorisation Expert")
    
    # TYPE ENTREPRISE
    mode_val = st.radio("Type", ["Cotée (Bourse)", "Non Cotée (PME/ETI)", "Startup (VC)"])
    valeur_finale = 0.0
    source_info = "Manuel"
    
    # FACTEUR VULNÉRABILITÉ (Pour le risque VaR)
    secteur_risk = st.selectbox("Niveau Vulnérabilité (Pour VaR Climatique)", [
        "Agroalimentaire (Critique - 100%)", 
        "Industrie Lourde (Élevé - 70%)",
        "BTP / Construction (Moyen - 40%)",
        "Commerce / Retail (Faible - 20%)",
        "Logiciel / Tech (Nul - 5%)"
    ])
    vuln_factor = {
        "Agroalimentaire": 1.0, "Industrie": 0.7, "BTP": 0.4, 
        "Commerce": 0.2, "Logiciel": 0.05
    }[secteur_risk.split()[0]]

    # --- LOGIQUE COTÉE ---
    if "Cotée" in mode_val:
        ticker = st.text_input("Ticker", "BN.PA")
        methode_cotee = st.selectbox("Indicateur", ["Market Cap", "Enterprise Value"])
        if st.button("Live Data"):
            m, e = get_stock_advanced(ticker)
            if m > 0: 
                st.session_state.stock_mcap = m
                st.session_state.stock_ev = e
        
        val_ref = st.session_state.get('stock_mcap', 1000000.0)
        if methode_cotee == "Enterprise Value": val_ref = st.session_state.get('stock_ev', val_ref)
        valeur_finale = st.number_input("Valo ($)", value=val_ref)
        source_info = f"Bourse {ticker}"
    
    # --- LOGIQUE STARTUP ---
    elif "Startup" in mode_val:
        stade = st.selectbox("Stade de Maturité", ["Seed", "Series A", "Series B"])
        ranges = {"Seed": (3e6, 8e6), "Series A": (10e6, 30e6), "Series B": (30e6, 80e6)}
        min_v, max_v = ranges[stade]
        valeur_finale = st.slider("Valorisation ($)", min_v, max_v, (min_v+max_v)/2)
        source_info = f"VC Market ({stade})"
    
    # --- LOGIQUE PME / NON COTÉE (LE RETOUR DU COMPLET) ---
    else:
        if st.button("Pappers Auto"):
            i = get_pappers_financials(ent, pappers_key)
            if i: st.session_state.pappers_data = i
        
        method_pme = st.selectbox("Méthode Valorisation", [
            "1. Multiple du Chiffre d'Affaires",
            "2. Multiple de l'EBITDA (Rentabilité)",
            "3. DCF (Discounted Cash Flow)",
            "4. Patrimonial (Capitaux Propres)"
        ])

        # Initialisation valeurs
        ca_val = 1000000.0; res_val = 100000.0; cap_val = 200000.0
        if st.session_state.pappers_data:
            d = st.session_state.pappers_data
            if d['ca']: ca_val = float(d['ca'])
            if d['ebitda']: res_val = float(d['ebitda'])
            if d['capitaux']: cap_val = float(d['capitaux'])

        val_calc = 0.0
        
        if "Multiple" in method_pme:
            # Choix du secteur pour le multiple
            secteur_valo = st.selectbox("Secteur d'Activité (Pour Multiple)", [
                "Logiciel (SaaS)", "Service Info (ESN)", "Industrie", 
                "Agroalimentaire", "Commerce / Retail", "BTP / Construction"
            ])
            
            # Récupération Live ou Fixe
            coeff = 1.0
            live = st.session_state.live_multiples
            if live and secteur_valo in live:
                d_live = live[secteur_valo]
                if "Affaires" in method_pme: coeff = d_live['ca_multiple']
                else: coeff = d_live['ebitda_multiple']
                st.caption(f"Multiple Live ({d_live['sample']}) : x{coeff:.2f}")
            else:
                # Fallback fixe
                defaults_ca = {"Logiciel": 5.0, "Agro": 0.9, "Industrie": 0.7, "Service": 1.1, "Commerce": 0.4, "BTP": 0.3}
                key_sec = secteur_valo.split()[0]
                coeff = defaults_ca.get(key_sec, 1.0)
                if "EBITDA" in method_pme: coeff *= 8.0 # Ratio approx EBITDA vs CA
                st.caption(f"Multiple Standard : x{coeff:.2f}")

            base = ca_val if "Affaires" in method_pme else res_val
            metric_label = "CA" if "Affaires" in method_pme else "EBITDA"
            input_val = st.number_input(f"{metric_label} ($)", value=base)
            val_calc = input_val * coeff
            source_info = f"{method_pme} ({secteur_valo})"

        elif "DCF" in method_pme:
            fcf = st.number_input("Flux Trésorerie (FCF) $", value=res_val)
            g = st.slider("Croissance %", 0.0, 5.0, 1.5)/100
            wacc = st.slider("WACC %", 5.0, 20.0, 10.0)/100
            if wacc > g: val_calc = fcf * (1 + g) / (wacc - g)
            source_info = "DCF Model"

        elif "Patrimonial" in method_pme:
            cap = st.number_input("Capitaux Propres ($)", value=cap_val)
            val_calc = cap
            source_info = "Actif Net"

        st.info(f"Valo Calculée : {val_calc:,.0f} $")
        valeur_finale = st.number_input("Valo Retenue", value=val_calc)

    st.markdown("---")
    st.write("📂 **3. Data Room**")
    notes_manuelles = st.text_area("Notes", height=100)
    uploaded_docs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 AUDIT"):
        with st.spinner("Calculs..."):
            res = analyser_site(v, p)
            if res and res['found']:
                news = get_company_news_strict(ent, country=p)
                ma_news = get_market_news(ent)
                wiki_txt = get_wiki_summary(ent)
                web_txt = scan_website(website)
                doc_text, doc_names = extract_text_from_pdfs(uploaded_docs)
                
                full_corpus = f"{notes_manuelles} {web_txt} {wiki_txt} {doc_text} {' '.join([n['title'] for n in news])}"
                
                delta_risk_2026 = max(0, res['s2026'] - 1.5)
                delta_risk_2030 = max(0, res['s2030'] - 1.5)
                
                impact_2026 = valeur_finale * (delta_risk_2026 / 5.0) * vuln_factor
                impact_2030 = valeur_finale * (delta_risk_2030 / 5.0) * vuln_factor

                risk_count = sum(1 for w in ['litige', 'procès', 'amende'] if w in full_corpus.lower())
                txt_ia = "Situation stable."
                if risk_count > 0: txt_ia = f"⚠️ ALERTE : {risk_count} mentions de risques légaux détectées."

                res['ent'] = ent; res['valeur_entreprise'] = valeur_finale; res['source_ca'] = source_info
                res['var_2026'] = impact_2026
                res['var_2030'] = impact_2030
                res['doc_files'] = doc_names
                res['txt_ia'] = txt_ia; res['news'] = news + ma_news
                res['full_text'] = full_corpus
                
                st.session_state.audit_unique = res
                st.rerun()

with c2:
    if st.session_state.audit_unique:
        r = st.session_state.audit_unique
        st.success(f"Audit Terminé : {r['ent']}")
        
        c0, c1, c2 = st.columns(3)
        c0.metric("Valorisation", f"{r['valeur_entreprise']:,.0f} $")
        c1.metric("Risque 2024 -> 2030", f"{r['s2024']:.2f} ➔ {r['s2030']:.2f}")
        c2.metric("Perte Potentielle 2030", f"{r['var_2030']:,.0f} $", delta="-Impact", delta_color="inverse")
        
        st.info(f"📅 **Impact à moyen terme (2026) :** {r['var_2026']:,.0f} $ de perte estimée.")
        
        t1, t2 = st.tabs(["📄 Rapport PDF", "📊 Détails"])
        with t1:
            pdf = create_pdf(r, r['full_text'], notes_manuelles)
            st.download_button("Télécharger Rapport Complet (PDF)", pdf, file_name="Rapport_Audit_V12.5.pdf")
            
        with t2:
            st.write("### Articles Analysés")
            for n in r['news']: st.markdown(f"- [{n['title']}]({n['link']})")
            
        m = folium.Map([r['lat'], r['lon']], zoom_start=9)
        folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color="red")).add_to(m)
        st_folium(m, height=250)
        
