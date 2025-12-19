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
st.set_page_config(page_title="AquaRisk 11.0 : Live Market", page_icon="📈", layout="wide")
st.title("📈 AquaRisk 11.0 : Valorisation Connectée au Marché (Temps Réel)")

# --- INITIALISATION ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'live_multiples' not in st.session_state: st.session_state.live_multiples = None # Stockage des taux du jour

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
if df_actuel is None: st.stop()

# --- 2. FONCTIONS TECH ---
def get_location_safe(ville, pays):
    try:
        ua = f"Fix_V11_{randint(100,999)}"
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

# --- 3. SOURCES EXTERNES (M&A NEWS) ---
def get_market_news(sector_keywords):
    """Cherche des news spécifiques sur les fusions/acquisitions du secteur"""
    # Ex: "Agroalimentaire acquisition rachat valorisation"
    q = urllib.parse.quote(f"{sector_keywords} (acquisition OR rachat OR fusion OR valorisation OR M&A)")
    rss_url = f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr"
    try:
        feed = feedparser.parse(rss_url)
        return [{"title": e.title, "link": e.link} for e in feed.entries[:3]]
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

def get_company_news_strict(company_name, country="France"):
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
            full_content = title + " " + clean(e.summary if 'summary' in e else e.title).lower()
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

# --- 4. FINANCE PRO (PAPPERS + YAHOO + LIVE MULTIPLES) ---
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
        
        ca = 0; resultat_net = 0; capitaux_propres = 0; ebitda_proxy = 0; annee = "N/A"
        
        for c in f_data.get('finances', []):
            if c.get('annee_cloture_exercice'):
                ca = c.get('chiffre_affaires', 0)
                resultat_net = c.get('resultat', 0)
                capitaux_propres = c.get('capitaux_propres', 0)
                ebitda_proxy = resultat_net * 1.25 if resultat_net > 0 else 0
                annee = c['annee_cloture_exercice']
                break
        
        return {"nom": match['nom_entreprise'], "ca": ca, "resultat": resultat_net, "capitaux": capitaux_propres, "ebitda": ebitda_proxy, "annee": annee}
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

# --- NOUVEAU : CALCULATEUR DE MULTIPLES TEMPS RÉEL ---
def calculate_live_multiples():
    """
    Scrape Yahoo Finance pour des paniers d'actions représentatifs
    et calcule le multiple moyen du jour.
    """
    # Paniers de référence (Proxies Boursiers)
    sectors_proxies = {
        "Logiciel (SaaS)": ["CRM", "ADBE", "NOW", "HUBS"], # Salesforce, Adobe, ServiceNow...
        "Service Info (ESN)": ["CAP.PA", "ACN", "INF.L"], # Capgemini, Accenture...
        "Industrie": ["SIE.DE", "SU.PA", "GE"], # Siemens, Schneider, GE
        "Agroalimentaire": ["BN.PA", "NESN.SW", "KHC"], # Danone, Nestlé, Kraft
        "Commerce / Retail": ["CA.PA", "WMT", "TGT"], # Carrefour, Walmart
        "BTP / Construction": ["DG.PA", "EN.PA", "ACS.MC"] # Vinci, Bouygues
    }
    
    results = {}
    progress_bar = st.progress(0)
    total = len(sectors_proxies)
    
    for i, (sector, tickers) in enumerate(sectors_proxies.items()):
        multiples_ev_rev = []
        multiples_ev_ebitda = []
        
        for t in tickers:
            try:
                stock = yf.Ticker(t)
                info = stock.info
                # Récupération EV/Revenue et EV/EBITDA
                ev_rev = info.get('enterpriseToRevenue')
                ev_ebitda = info.get('enterpriseToEbitda')
                
                if ev_rev: multiples_ev_rev.append(ev_rev)
                if ev_ebitda: multiples_ev_ebitda.append(ev_ebitda)
            except: continue
            
        # Moyenne du secteur
        avg_rev = sum(multiples_ev_rev)/len(multiples_ev_rev) if multiples_ev_rev else 1.0
        avg_ebitda = sum(multiples_ev_ebitda)/len(multiples_ev_ebitda) if multiples_ev_ebitda else 8.0
        
        # Application de la "Décote de Non-Cotation" (Private Discount) ~30%
        # Car une PME est moins liquide qu'une action cotée
        results[sector] = {
            "ca_multiple": avg_rev * 0.70, 
            "ebitda_multiple": avg_ebitda * 0.70,
            "sample": ", ".join(tickers)
        }
        progress_bar.progress((i + 1) / total)
        
    progress_bar.empty()
    return results

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
    if not pays_trouve: return None
        
    df_pays = df_actuel[df_actuel['name_0'] == pays_trouve]
    match_now = pd.DataFrame()
    nom_region_officiel = "Moyenne Nationale"
    
    if reg_cible:
        liste_regions = df_pays['name_1'].unique()
        region_trouvee = trouver_meilleur_nom(reg_cible, liste_regions, seuil=80)
        if region_trouvee:
            match_now = df_pays[df_pays['name_1'] == region_trouvee]
            nom_region_officiel = region_trouvee
        else: match_now = df_pays
    else: match_now = df_pays

    s25 = match_now['score'].mean() if not match_now.empty else 0
    s30 = 0 
    if df_futur is not None:
        df_f_pays = df_futur[df_futur['name_0'] == pays_trouve]
        if not df_f_pays.empty: s30 = df_f_pays['score'].mean()

    return {"ent": "N/A", "ville": ville, "pays": pays_trouve, "region": nom_region_officiel, "lat": loc.latitude, "lon": loc.longitude, "s25": s25, "s30": s30, "found": True}

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
    pdf.cell(0, 10, clean(f"AUDIT V11.0: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(5)
    
    pdf.set_font("Arial", size=11)
    pdf.cell(0, 10, clean(f"Loc: {data['ville']} ({data['region']}, {data['pays']})"), ln=1)
    
    if data.get('valeur_entreprise'):
        methode = data.get('source_ca', 'Manuel')
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, clean(f"Valuation: {data['valeur_entreprise']:,.0f} $"), ln=1)
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 8, clean(f"Methode: {methode}"), ln=1)
    
    pdf.set_font("Arial", size=11)
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
        pdf.cell(0, 5, "Pas de news environnementale critique.", ln=1)
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 8. INTERFACE ---
with st.sidebar:
    st.header("⚙️ API Keys")
    pappers_key = st.text_input("Pappers (France)", type="password")
    
    st.markdown("---")
    st.header("🔄 Live Market")
    if st.button("Actualiser les Taux"):
        with st.spinner("Analyse des marchés en cours (Yahoo Finance)..."):
            st.session_state.live_multiples = calculate_live_multiples()
        st.success("Taux du jour mis à jour !")
    
    if st.session_state.live_multiples:
        st.caption(f"Dernière maj: {datetime.now().strftime('%H:%M')}")

c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("1. Cible")
    ent = st.text_input("Nom Entreprise", "Danone")
    v = st.text_input("Ville", "Paris")
    p = st.text_input("Pays", "France")
    website = st.text_input("Site Web", "")
    
    col_s1, col_s2 = st.columns(2)
    with col_s1: st.markdown(f"[📄 PDF](https://www.google.com/search?q={urllib.parse.quote(ent + ' rapport durable filetype:pdf')})", unsafe_allow_html=True)
    with col_s2: st.markdown(f"[📰 News](https://www.google.com/search?q={urllib.parse.quote(ent + ' pollution amende')})", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("2. Finance & Valorisation")
    mode_val = st.radio("Type", ["Cotée", "Non Cotée (PME)", "Startup (VC)"])
    valeur_finale = 0.0
    source_info = "Manuel"
    
    if mode_val == "Cotée":
        ticker = st.text_input("Ticker", "BN.PA")
        choix_bourse = st.selectbox("Indicateur", ["1. Market Cap", "2. Enterprise Value"])
        if st.button("📈 Données Live"):
            mcap, ev = get_stock_advanced(ticker)
            if mcap > 0:
                st.session_state.stock_mcap = mcap
                st.session_state.stock_ev = ev
                st.success("Données Live OK")
        
        val_ref = st.session_state.get('stock_mcap', 1000000.0)
        if "Enterprise Value" in choix_bourse: val_ref = st.session_state.get('stock_ev', val_ref)
        valeur_finale = st.number_input("Valo ($)", value=val_ref)
        source_info = f"Bourse ({ticker})"
    
    elif mode_val == "Startup (VC)":
        stade = st.selectbox("Stade", ["Seed", "Series A", "Series B"])
        ranges = {"Seed": (3e6, 8e6), "Series A": (10e6, 30e6), "Series B": (30e6, 80e6)}
        min_v, max_v = ranges[stade]
        valeur_finale = st.slider("Valo ($)", min_v, max_v, (min_v+max_v)/2)
        source_info = f"VC Market ({stade})"

    else:
        if st.button("🇫🇷 Pappers Auto"):
            if pappers_key:
                i = get_pappers_financials(ent, pappers_key)
                if i: st.session_state.pappers_data = i
        
        method_val = st.selectbox("Méthode", ["1. Multiple CA (Live)", "2. Multiple EBITDA (Live)", "3. DCF", "4. Patrimonial"])
        
        # Sélection Secteur pour Live Multiples
        secteur_choisi = st.selectbox("Secteur (Pour calcul Live)", [
            "Logiciel (SaaS)", "Service Info (ESN)", "Industrie", 
            "Agroalimentaire", "Commerce / Retail", "BTP / Construction"
        ])
        
        # --- LOGIQUE LIVE ---
        live_data = st.session_state.live_multiples
        coeff_ca = 1.0
        coeff_ebitda = 6.0
        
        if live_data and secteur_choisi in live_data:
            d_sec = live_data[secteur_choisi]
            coeff_ca = d_sec['ca_multiple']
            coeff_ebitda = d_sec['ebitda_multiple']
            st.success(f"📊 Marché en direct ({d_sec['sample']})")
            st.caption(f"Multiples du jour (avec décote non-coté 30%): CA x{coeff_ca:.2f} | EBITDA x{coeff_ebitda:.2f}")
        else:
            if not live_data: st.warning("⚠️ Cliquez sur 'Actualiser les Taux' à gauche pour avoir les vrais chiffres du jour.")

        ca_val = 1000000.0
        res_val = 100000.0
        cap_val = 200000.0
        
        if st.session_state.pappers_data:
            d = st.session_state.pappers_data
            if d['ca']: ca_val = float(d['ca'])
            if d['ebitda']: res_val = float(d['ebitda'])
            if d['capitaux']: cap_val = float(d['capitaux'])

        val_calc = 0.0
        
        if "Multiple CA" in method_val:
            ca = st.number_input("CA ($)", value=ca_val)
            val_calc = ca * coeff_ca
            source_info = f"Live CA ({secteur_choisi})"
            
        elif "Multiple EBITDA" in method_val:
            res = st.number_input("EBITDA ($)", value=res_val)
            val_calc = res * coeff_ebitda
            source_info = f"Live EBITDA ({secteur_choisi})"

        elif "DCF" in method_val:
            fcf = st.number_input("Free Cash Flow $", value=res_val)
            g = st.slider("Croissance %", 0.0, 5.0, 1.5)/100
            wacc = st.slider("WACC %", 5.0, 20.0, 10.0)/100
            if wacc > g: val_calc = fcf * (1 + g) / (wacc - g)
            source_info = "DCF Model"

        elif "Patrimonial" in method_val:
            cap = st.number_input("Capitaux ($)", value=cap_val)
            val_calc = cap
            source_info = "Actif Net"

        st.info(f"Estimée : {val_calc:,.0f} $")
        valeur_finale = st.number_input("Retenue", value=val_calc)

    st.markdown("---")
    st.write("📂 **3. Data Room**")
    notes_manuelles = st.text_area("📋 Notes", height=100)
    uploaded_docs = st.file_uploader("Drop PDF", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 AUDIT COMPLET"):
        with st.spinner("Analyse Intégrale..."):
            res = analyser_site(v, p)
            if res and res['found']:
                news = get_company_news_strict(ent, country=p)
                # Ajout news M&A
                ma_news = get_market_news(secteur_choisi if 'secteur_choisi' in locals() else ent)
                
                wiki_lang = 'fr' if "france" in p.lower() else 'en'
                wiki_txt = get_wiki_summary(ent, lang=wiki_lang)
                web_txt = scan_website(website)
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_text, doc_names = extract_text_from_pdfs(uploaded_docs)
                
                corpus = f"{notes_manuelles} {web_txt} {wiki_txt} {doc_text} {' '.join([n['title'] for n in news])}"
                m_pos = ['durable', 'recyclage', 'économie', 'biologique', 'iso 14001', 'b corp']
                m_neg = ['pollution', 'plainte', 'fuite', 'non-conformité']
                m_risk = ['provision', 'litige', 'amende', 'redressement', 'procès']
                
                s_pos = sum(1 for w in m_pos if w in corpus.lower())
                s_neg = sum(1 for w in m_neg if w in corpus.lower())
                s_risk = sum(1 for w in m_risk if w in corpus.lower())
                
                bonus = 0.0
                txt = "Neutre."
                if pluie and pluie < 50: bonus -= 0.10
                
                if s_pos > s_neg: bonus += 0.10; txt = "✅ Tendance positive."
                elif s_neg > s_pos: bonus -= 0.10; txt = "⚠️ Tendance négative."
                
                finance_danger = False
                if s_risk > 0: 
                    finance_danger = True
                    txt += f"\n🚨 ALERTE ROUGE : Risques financiers détectés ({s_risk}). SCORE MAX."

                res['ent'] = ent
                res['valeur_entreprise'] = valeur_finale
                res['source_ca'] = source_info
                res['pluie_90j'] = pluie
                res['doc_files'] = doc_names
                res['s25_brut'] = res['s25']
                
                score_temp = res['s25'] * (1 - bonus)
                if finance_danger: res['s25_display'] = 5.0
                else: res['s25_display'] = min(5.0, score_temp)
                
                res['var'] = valeur_finale * (res['s25_display'] / 5) * 0.2
                res['txt_ia'] = txt
                res['news'] = news + ma_news # On combine les news
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
        c1.metric("Risque Final", f"{r['s25_display']:.2f}/5", delta="ALERTE" if r['s25_display'] == 5 else "Normal", delta_color="inverse")
        c2.metric("Perte Estimée", f"{r['var']:,.0f} $", delta="VaR", delta_color="inverse")
        
        st.info(f"🤖 **Synthèse :** {r['txt_ia']}")
        
        t1, t2, t3, t4 = st.tabs(["📝 Notes", "📰 News", "📚 Wiki", "🌍 Météo"])
        with t1: 
             if r['doc_files']: st.write(f"📂 Docs: {', '.join(r['doc_files'])}")
             st.text("..." + notes_manuelles[:200] + "...")
        with t2:
            if r['news']:
                for n in r['news']: st.markdown(f"- [{n['title']}]({n['link']})")
            else:
                st.write("Pas de news.")
        with t3: st.write(r['wiki'])
        with t4: st.metric("Pluie Récente", f"{r['pluie_90j']} mm")

        m = folium.Map([r['lat'], r['lon']], zoom_start=9, tiles="cartodbpositron")
        folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color="red")).add_to(m)
        st_folium(m, height=250)
        
        pdf = create_pdf(r)
        st.download_button("📄 Rapport PDF (V11.0 Live)", pdf, file_name="Rapport_Live.pdf")
        
