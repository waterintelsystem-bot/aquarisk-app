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
import xlsxwriter

# ==============================================================================
# 1. CONFIGURATION & SESSION
# ==============================================================================
st.set_page_config(page_title="AquaRisk V19 : Force Update", page_icon="⚡", layout="wide")
st.title("⚡ AquaRisk V19 : Audit Temps Réel & OCR Force")

# Initialisation des variables de mémoire (Session State) pour les champs
if 'finance_ca' not in st.session_state: st.session_state.finance_ca = 1000000.0
if 'finance_res' not in st.session_state: st.session_state.finance_res = 100000.0
if 'finance_cap' not in st.session_state: st.session_state.finance_cap = 200000.0
if 'finance_ebitda' not in st.session_state: st.session_state.finance_ebitda = 125000.0

if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'stock_data' not in st.session_state: st.session_state.stock_data = {"mcap": 0, "ev": 0}
if 'comparables' not in st.session_state: st.session_state.comparables = None

# ==============================================================================
# 2. CHARGEMENT DATA
# ==============================================================================
@st.cache_data
def load_data():
    BACKUP_DATA = pd.DataFrame({
        'name_0': ['France', 'United States', 'Germany', 'China', 'India'],
        'name_1': ['Ile-de-France', 'California', 'Bavaria', 'Beijing', 'Maharashtra'],
        'score': [2.5, 3.8, 2.2, 4.1, 4.5]
    })
    
    def smart_read(filename):
        if not os.path.exists(filename): return None
        try:
            df = pd.read_csv(filename, sep=None, engine='python', on_bad_lines='skip')
            df.columns = [c.lower().strip() for c in df.columns]
            if 'name_0' in df.columns: return df
            return None
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
# 3. MOTEUR OCR V3 (ROBUSTE & NETTOYAGE)
# ==============================================================================
def parse_french_number(text_num):
    try:
        # Nettoyage profond : suppression espaces, guillemets, parenthèses
        clean = text_num.replace(' ', '').replace(')', '').replace('(', '-').replace('"', '').replace("'", "")
        # On garde chiffres, virgule, point, moins
        clean = re.sub(r'[^\d,\.-]', '', clean)
        clean = clean.replace(',', '.')
        # Gestion multi-points (ex: 1.000.000.00)
        if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except: return None

def extract_financials_from_text(text):
    data = {"ca": 0, "resultat": 0, "capitaux": 0, "found": False}
    lines = text.split('\n')
    
    target_labels = {
        "ca": ["CHIFFRES D'AFFAIRES NETS", "TOTAL DES PRODUITS D'EXPLOITATION", "VENTES DE MARCHANDISES"],
        "resultat": ["BENEFICE OU PERTE", "RESULTAT DE L'EXERCICE", "RESULTAT NET"],
        "capitaux": ["TOTAL CAPITAUX PROPRES", "CAPITAUX PROPRES", "SITUATION NETTE"]
    }
    
    for line in lines:
        if len(line) < 5: continue
        line_upper = line.strip().upper()
        
        for metric, keywords in target_labels.items():
            if data[metric] == 0:
                # Recherche Fuzzy (Tolérance)
                best_match, score = process.extractOne(line_upper, keywords)
                
                # Si match > 85% ou présence littérale
                if score >= 85 or any(k in line_upper for k in keywords):
                    # Regex large pour capturer les nombres
                    nums = re.findall(r'-?\s*[\d]+[ \d]*[\.,]?[ \d]*', line)
                    valid_nums = [parse_french_number(n) for n in nums if parse_french_number(n) is not None]
                    
                    if valid_nums:
                        # Logique de sélection
                        if metric == "ca": data["ca"] = max(valid_nums)
                        elif metric == "resultat": data["resultat"] = valid_nums[0] # Souvent le premier
                        elif metric == "capitaux": data["capitaux"] = valid_nums[0]
                        data["found"] = True
    return data

def extract_text_from_pdfs_robust(files):
    t = ""
    if not files: return ""
    for f in files:
        try:
            f.seek(0) # IMPORTANT : Rembobiner le fichier
            with pdfplumber.open(f) as pdf:
                # On lit 40 pages pour être sûr
                for p in pdf.pages[:40]: 
                    extracted = p.extract_text()
                    if extracted: t += extracted + "\n"
        except: continue
    return t

# ==============================================================================
# 4. FONCTIONS TECH (AUXILIAIRES)
# ==============================================================================
class MockLocation:
    def __init__(self, lat, lon): self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    clean_v = ville.lower().strip()
    fallback = {"paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "issy-les-moulineaux": (48.823, 2.269)}
    if clean_v in fallback: return MockLocation(*fallback[clean_v])
    try:
        ua = f"AR_V19_{randint(1000,9999)}"
        loc = Nominatim(user_agent=ua, timeout=5).geocode(f"{ville}, {pays}")
        if loc: return loc
    except: pass
    return MockLocation(48.8566, 2.3522)

def get_weather_history(lat, lon):
    try:
        url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={(datetime.now()-timedelta(days=90)).strftime('%Y-%m-%d')}&end_date={datetime.now().strftime('%Y-%m-%d')}&daily=precipitation_sum&timezone=auto"
        r = requests.get(url, timeout=3).json()
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
        return {"nom": res[0]['nom_entreprise'], "ca": ca, "resultat": res, "capitaux": cap, "ebitda": res*1.25}
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

def get_wiki_summary(name):
    try:
        wikipedia.set_lang('fr')
        s = wikipedia.search(name)
        if s: return wikipedia.page(s[0]).summary[:1000]
    except: pass
    return "Pas de données."

def scan_website(url):
    if len(url)<5: return ""
    if not url.startswith("http"): url="https://"+url
    try:
        r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=3)
        return ' '.join([p.text for p in BeautifulSoup(r.text,'html.parser').find_all('p')])[:3000]
    except: return ""

def calculate_ratios(ca, res, cap):
    r = {}
    r['Marge Nette'] = (res/ca)*100 if ca>0 else 0
    r['ROE'] = (res/cap)*100 if cap>0 else 0
    return r

def get_sector_comparables(sector):
    m = {"Agro": ["BN.PA", "NESN.SW"], "Indus": ["AIR.PA", "SAF.PA"], "Tech": ["DSY.PA", "CAP.PA"]}
    return m.get(sector.split()[0][:4], ["BN.PA"])

def fetch_comparables(tickers):
    d=[]
    for t in tickers:
        try:
            s=yf.Ticker(t)
            i=s.info
            if i.get('marketCap'): d.append({"Ticker":t,"PE":i.get('trailingPE'),"MktCap":i.get('marketCap')/1e9})
        except: continue
    return pd.DataFrame(d)

def generate_excel(data, ratios):
    o = io.BytesIO()
    w = xlsxwriter.Workbook(o, {'in_memory':True})
    s = w.add_worksheet()
    rows = [("Entité", data['ent']), ("Valo", data['valeur_entreprise']), ("CA", data['ca']), ("Marge", ratios['Marge Nette'])]
    for i, (k,v) in enumerate(rows): s.write(i,0,k); s.write(i,1,v)
    w.close()
    return o.getvalue()

# ==============================================================================
# 5. ANALYSE & PDF
# ==============================================================================
def analyser_risque_geo(ville, pays):
    loc = get_location_safe(ville, pays)
    pays_match, score = process.extractOne(str(pays), df_actuel['name_0'].unique().astype(str))
    if score < 60: pays_match = pays
    s24 = 2.5
    if pays_match in df_actuel['name_0'].values: s24 = df_actuel[df_actuel['name_0'] == pays_match]['score'].mean()
    s30 = s24 * 1.1
    if df_futur is not None and pays_match in df_futur['name_0'].values: s30 = df_futur[df_futur['name_0'] == pays_match]['score'].mean()
    s26 = s24 + ((s30 - s24) * 0.33)
    return {"ent": "N/A", "ville": ville, "pays": pays_match, "lat": loc.latitude, "lon": loc.longitude, "s2024": s24, "s2026": s26, "s2030": s30, "found": True}

def create_pdf(data, corpus, notes, ratios):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, clean(f"AUDIT V19: {data.get('ent', 'N/A').upper()}"), ln=1, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. FINANCE", ln=1)
    pdf.set_font("Arial", size=11)
    pdf.cell(60, 10, clean(f"Valo: {data.get('valeur_entreprise',0):,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"Marge: {ratios.get('Marge Nette',0):.1f}%"), border=1)
    pdf.ln(15)
    pdf.cell(0, 10, clean(f"Contexte: {data.get('txt_ia', '')[:500]}..."), ln=1)
    return pdf.output(dest='S').encode('latin-1', 'replace')

# ==============================================================================
# 6. INTERFACE (FORCE UPDATE)
# ==============================================================================
with st.sidebar:
    st.header("⚙️ Config")
    pappers_key = st.text_input("Clé Pappers", type="password")

c1, c2 = st.columns([1, 2])

with c1:
    st.subheader("1. Cible")
    ent = st.text_input("Nom", "Michel et Augustin")
    v = st.text_input("Ville", "Issy-les-Moulineaux")
    p = st.text_input("Pays", "France")
    website = st.text_input("Web", "")
    
    st.markdown("---")
    st.subheader("2. Finance")
    mode_val = st.radio("Type", ["Non Cotée", "Cotée", "Startup"])
    valeur_finale = 0.0; source_info = "Manuel"
    
    secteur_risk = st.selectbox("Secteur", ["Agroalimentaire (100%)", "Industrie (70%)", "BTP (40%)", "Commerce (20%)", "Logiciel (5%)"])
    vuln_factor = {"Agroalimentaire": 1.0, "Industrie": 0.7, "BTP": 0.4, "Commerce": 0.2, "Logiciel": 0.05}.get(secteur_risk.split()[0], 0.5)

    if mode_val == "Non Cotée":
        col_api, col_pdf = st.columns(2)
        with col_api:
            if st.button("🔍 Pappers"):
                with st.spinner("API..."):
                    i = get_pappers_financials(ent, pappers_key)
                    if i:
                        st.session_state.finance_ca = float(i['ca'])
                        st.session_state.finance_res = float(i['resultat'])
                        st.session_state.finance_cap = float(i['capitaux'])
                        st.session_state.finance_ebitda = float(i['ebitda'])
                        st.success("Pappers Sync!")
        
        with col_pdf:
            uploaded_bilan = st.file_uploader("Bilan PDF", type=["pdf"], key="bilan_upload")
            if uploaded_bilan:
                with st.spinner("OCR..."):
                    txt = extract_text_from_pdfs_robust([uploaded_bilan])
                    fin = extract_financials_from_text(txt)
                    if fin['found']:
                        # FORCE UPDATE SESSION STATE
                        st.session_state.finance_ca = float(fin['ca'])
                        st.session_state.finance_res = float(fin['resultat'])
                        st.session_state.finance_cap = float(fin['capitaux'])
                        # Approx Ebitda si non trouvé
                        st.session_state.finance_ebitda = float(fin['resultat']) * 1.25
                        st.success(f"Lu! CA={fin['ca']:,.0f}")

        # WIDGETS CONNECTÉS AU SESSION STATE (KEY)
        m_pme = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "DCF", "Patrimonial"])
        
        val_calc = 0.0
        if "Multiple CA" in m_pme:
            # ICI : On utilise la key pour lier le widget à la variable mise à jour
            base = st.number_input("Chiffre d'Affaires (€)", key="finance_ca")
            mult_ca = st.slider("Multiple CA", 0.1, 5.0, 1.5, 0.1)
            val_calc = base * mult_ca
            source_info = f"CA x{mult_ca}"
            
        elif "Multiple EBITDA" in m_pme:
            base = st.number_input("EBITDA (€)", key="finance_ebitda")
            mult_ebitda = st.slider("Multiple EBITDA", 1.0, 20.0, 7.0, 0.5)
            val_calc = base * mult_ebitda
            source_info = f"EBITDA x{mult_ebitda}"
            
        elif "DCF" in m_pme:
            fcf = st.number_input("Free Cash Flow (€)", key="finance_res") # Proxy
            c3, c4 = st.columns(2)
            with c3: wacc = st.number_input("WACC (%)", 1.0, 20.0, 10.0, 0.5)/100
            with c4: g = st.number_input("Croissance g (%)", 0.0, 10.0, 2.0, 0.1)/100
            if wacc > g: val_calc = fcf * (1+g) / (wacc - g)
            else: val_calc = 0
            source_info = f"DCF (WACC {wacc*100}%)"
            
        else:
            val_calc = st.number_input("Capitaux Propres", key="finance_cap")
            source_info = "Actif Net"
            
        valeur_finale = st.number_input("Valo Retenue", value=val_calc)

    elif mode_val == "Cotée":
        ticker = st.text_input("Ticker", "BN.PA")
        if st.button("Yahoo"):
            m, e = get_stock_advanced(ticker)
            if m > 0: st.session_state.stock_data = {"mcap":m, "ev":e}
        ref = st.session_state.stock_data.get('mcap', 0)
        valeur_finale = st.number_input("Valo", value=ref if ref > 0 else 1000000.0)
        source_info = f"Bourse {ticker}"

    else: 
        stade = st.selectbox("Stade", ["Pre-Seed", "Seed", "Series A", "Series B"])
        valeur_finale = st.slider("Valo", 1e6, 8e7, 5e6)
        source_info = f"VC {stade}"

    st.markdown("---")
    st.write("📂 **3. Data Room**")
    notes = st.text_area("Notes", height=100)
    uploaded_docs = st.file_uploader("PDFs (Analyse Risques)", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 AUDIT"):
        with st.spinner("Analyse..."):
            res = analyser_risque_geo(v, p)
            if res['found']:
                news = get_company_news(ent)
                wiki = get_wiki_summary(ent)
                web = scan_website(website)
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_txt = extract_text_from_pdfs_robust(uploaded_docs)
                corpus = f"{notes} {web} {wiki} {doc_txt} {' '.join([n['title'] for n in news])}"
                
                delta_risk = res['s2030'] - res['s2024']
                impact_30 = valeur_finale * (delta_risk / 5.0) * vuln_factor
                
                alerts = sum(1 for w in ['litige', 'procès', 'amende', 'pollution'] if w in corpus.lower())
                txt_ia = f"Analyse docs. {alerts} alertes. Contexte: {wiki[:300]}..."
                
                # Fetch comparables
                tickers_comp = get_sector_comparables(secteur_risk)
                st.session_state.comparables = fetch_comparables(tickers_comp)
                
                final = {
                    "ent": ent, "ville": v, "pays": res['pays'], 
                    "lat": res['lat'], "lon": res['lon'],
                    "valeur_entreprise": valeur_finale, "source_ca": source_info,
                    "ca": st.session_state.finance_ca, "res": st.session_state.finance_res, "cap": st.session_state.finance_cap,
                    "s2024": res['s2024'], "s2026": res['s2026'], "s2030": res['s2030'],
                    "var_2030": impact_30, "vuln_percent": vuln_factor,
                    "news": news, "txt_ia": txt_ia, "pluie_90j": pluie, "full_text": corpus
                }
                st.session_state.audit_unique = final
                st.rerun()

with c2:
    if st.session_state.audit_unique:
        r = st.session_state.audit_unique
        st.success(f"Audit : {r.get('ent')}")
        k1, k2, k3 = st.columns(3)
        k1.metric("Valo", f"{r.get('valeur_entreprise',0):,.0f} $", delta=r.get('source_ca'))
        
        # Ratios
        ratios = calculate_ratios(r.get('ca', 0), r.get('res', 0), r.get('cap', 0))
        k2.metric("Marge Nette", f"{ratios['Marge Nette']:.1f}%")
        
        var_30 = r.get('var_2030', 0)
        k3.metric("Impact 2030", f"{var_30:,.0f} $", delta_color="inverse" if var_30 > 0 else "normal")
        
        st.info(f"Météo: {r.get('pluie_90j')} mm | Vulnérabilité: {r.get('vuln_percent',0)*100:.0f}%")
        
        t1, t2, t3 = st.tabs(["Rapport & Excel", "Comparables", "Sources"])
        with t1:
            if r.get('full_text'):
                pdf = create_pdf(r, r['full_text'], notes, ratios)
                st.download_button("📥 PDF", pdf, file_name="Rapport.pdf")
                excel = generate_excel(r, ratios)
                st.download_button("📊 Excel", excel, file_name="Data.xlsx")
            if r.get('lat'):
                m = folium.Map([r['lat'], r['lon']], zoom_start=10)
                folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color='red')).add_to(m)
                st_folium(m, height=250)
        with t2:
            if st.session_state.comparables is not None: st.dataframe(st.session_state.comparables)
        with t3:
            for n in r.get('news', []): st.markdown(f"- [{n['title']}]({n['link']})")
                
