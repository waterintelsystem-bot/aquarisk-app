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
# 1. CONFIGURATION & STATE
# ==============================================================================
st.set_page_config(page_title="AquaRisk V21 : Precision OCR", page_icon="🎯", layout="wide")
st.title("🎯 AquaRisk V21 : Audit Expert & OCR Haute Précision")

# Variables Session State (Mémoire)
defaults = {
    'finance_ca': 1000000.0, 'finance_res': 100000.0, 'finance_cap': 200000.0, 'finance_ebitda': 125000.0,
    'audit_unique': None, 'pappers_data': None, 'stock_data': {"mcap": 0, "ev": 0}, 
    'pdf_financials': None, 'comparables': None
}

for key, val in defaults.items():
    if key not in st.session_state: st.session_state[key] = val

# ==============================================================================
# 2. CHARGEMENT DATA
# ==============================================================================
@st.cache_data
def load_data():
    BACKUP = pd.DataFrame({
        'name_0': ['France', 'United States', 'Germany', 'China', 'India'],
        'name_1': ['Ile-de-France', 'California', 'Bavaria', 'Beijing', 'Maharashtra'],
        'score': [2.5, 3.8, 2.2, 4.1, 4.5]
    })
    
    def smart_read(f):
        if not os.path.exists(f): return None
        try:
            d = pd.read_csv(f, sep=None, engine='python', on_bad_lines='skip')
            d.columns = [c.lower().strip() for c in d.columns]
            return d if 'name_0' in d.columns else None
        except: return None

    df_now = smart_read("risk_actuel.csv") or BACKUP
    if 'score' in df_now.columns: df_now['score'] = pd.to_numeric(df_now['score'].astype(str).str.replace(',', '.'), errors='coerce')

    df_fut = smart_read("risk_futur.csv")
    if df_fut is None: df_fut = df_now.copy(); df_fut['score'] = df_fut['score'] * 1.15
    else:
        df_fut['score'] = pd.to_numeric(df_fut['score'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'year' in df_fut.columns: df_fut = df_fut[df_fut['year'] == 2030]
            
    return df_now, df_fut

try: df_actuel, df_futur = load_data()
except: st.stop()

# ==============================================================================
# 3. MOTEUR OCR V5 (SÉLECTION INTELLIGENTE DES CHIFFRES)
# ==============================================================================
def parse_french_number(text_num):
    try:
        # Nettoyage profond
        clean = text_num.replace(' ', '').replace(')', '').replace('(', '-').replace('"', '').replace("'", "")
        clean = re.sub(r'[^\d,\.-]', '', clean) # Garde chiffres, , . -
        clean = clean.replace(',', '.')
        # Gestion multi-points (ex: 1.234.567.00)
        if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except: return None

def extract_financials_from_text(text):
    data = {"ca": 0, "resultat": 0, "capitaux": 0, "found": False}
    lines = text.split('\n')
    
    # Mots-clés cibles
    targets = {
        "ca": ["CHIFFRES D'AFFAIRES NETS", "TOTAL DES PRODUITS D'EXPLOITATION", "VENTES DE MARCHANDISES"],
        "resultat": ["BENEFICE OU PERTE", "RESULTAT DE L'EXERCICE", "RESULTAT NET"],
        "capitaux": ["TOTAL CAPITAUX PROPRES", "CAPITAUX PROPRES", "SITUATION NETTE"]
    }
    
    for line in lines:
        if len(line) < 5: continue
        line_up = line.strip().upper()
        
        for metric, keywords in targets.items():
            if data[metric] == 0:
                # 1. Détection Mots-Clés (Fuzzy)
                best_match, score = process.extractOne(line_up, keywords)
                
                # 2. Si match pertinent
                if score >= 85 or any(k in line_up for k in keywords):
                    # 3. Extraction Nombres
                    nums = re.findall(r'-?\s*[\d]+[ \d]*[\.,]?[ \d]*', line)
                    valid_nums = [parse_french_number(n) for n in nums if parse_french_number(n) is not None]
                    
                    # 4. Filtrage & Sélection (NOUVEAU)
                    # On ignore les "petits" chiffres qui pourraient être des années (2022) ou des notes (1, 2)
                    # Sauf si c'est la seule valeur dispo
                    big_nums = [n for n in valid_nums if abs(n) > 3000] # Filtre années/notes
                    
                    final_candidates = big_nums if big_nums else valid_nums
                    
                    if final_candidates:
                        # On prend la plus grande valeur ABSOLUE pour éviter les erreurs
                        # Ex: Ligne "2022 | -10 000 000". Max(abs) -> 10 000 000 -> On récupère -10 000 000
                        val = max(final_candidates, key=abs)
                        data[metric] = val
                        data["found"] = True
    return data

def extract_text_from_pdfs_robust(files):
    t = ""
    if not files: return ""
    for f in files:
        try:
            f.seek(0)
            with pdfplumber.open(f) as pdf:
                for p in pdf.pages[:50]: # Scan large
                    xt = p.extract_text()
                    if xt: t += xt + "\n"
        except: continue
    return t

# ==============================================================================
# 4. FONCTIONS TECH (API, GPS, CALCULS)
# ==============================================================================
class MockLocation:
    def __init__(self, lat, lon): self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    clean = ville.lower().strip()
    fallback = {"paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "issy-les-moulineaux": (48.823, 2.269)}
    if clean in fallback: return MockLocation(*fallback[clean])
    try:
        ua = f"AR_V21_{randint(1000,9999)}"
        loc = Nominatim(user_agent=ua, timeout=4).geocode(f"{ville}, {pays}")
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

def get_pappers_financials(name, key):
    if not key: return None
    try:
        k = key.strip()
        r = requests.get(f"https://api.pappers.fr/v2/recherche?q={urllib.parse.quote(name)}&api_token={k}&par_page=1", timeout=5)
        if r.status_code!=200: return None
        res = r.json().get('resultats')
        if not res: return None
        siren = res[0]['siren']
        fr = requests.get(f"https://api.pappers.fr/v2/entreprise?api_token={k}&siren={siren}", timeout=5)
        fd = fr.json()
        ca=0; res=0; cap=0
        for c in fd.get('finances', []):
            if c.get('annee_cloture_exercice'):
                ca = c.get('chiffre_affaires', 0) or 0
                res = c.get('resultat', 0) or 0
                cap = c.get('capitaux_propres', 0) or 0
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

def get_news_and_wiki(name):
    news = []; wiki = "Pas de Wikipedia."
    try:
        q = urllib.parse.quote(f'"{name}" (eau OR pollution)')
        f = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
        news = [{"title": e.title, "link": e.link, "summary": e.summary[:200]} for e in f.entries[:5]]
    except: pass
    try:
        wikipedia.set_lang('fr')
        s = wikipedia.search(name)
        if s: wiki = wikipedia.page(s[0]).summary[:800]
    except: pass
    return news, wiki

def scan_website(url):
    if len(url)<5: return ""
    if not url.startswith("http"): url="https://"+url
    try:
        r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=3)
        return ' '.join([p.text for p in BeautifulSoup(r.text,'html.parser').find_all('p')])[:3000]
    except: return ""

def calculate_ratios(ca, res, cap):
    return {
        'Marge Nette': (res/ca)*100 if ca else 0,
        'ROE': (res/cap)*100 if cap else 0
    }

def get_comparables(sector):
    m = {"Agro": ["BN.PA", "NESN.SW"], "Indus": ["AIR.PA"], "Tech": ["DSY.PA"], "BTP": ["DG.PA"], "Comm": ["CA.PA"]}
    tickers = m.get(sector.split()[0][:4], ["BN.PA"])
    data = []
    for t in tickers:
        try:
            i = yf.Ticker(t).info
            if i.get('marketCap'): data.append({"Ticker": t, "PE": i.get('trailingPE'), "Cap(Md)": i.get('marketCap')/1e9})
        except: continue
    return pd.DataFrame(data)

def generate_excel(data, ratios):
    o = io.BytesIO()
    w = xlsxwriter.Workbook(o, {'in_memory':True})
    s = w.add_worksheet()
    rows = [("Entité", data['ent']), ("Valo", data['valeur_entreprise']), ("CA", data['ca']), ("Res", data['res']), ("Marge %", ratios['Marge Nette'])]
    for i, (k,v) in enumerate(rows): s.write(i,0,k); s.write(i,1,v)
    w.close()
    return o.getvalue()

# ==============================================================================
# 5. ANALYSE GEO & PDF
# ==============================================================================
def analyser_risque_geo(ville, pays):
    loc = get_location_safe(ville, pays)
    best, score = process.extractOne(str(pays), df_actuel['name_0'].unique().astype(str))
    pays_match = best if score > 60 else pays
    s24 = 2.5
    if pays_match in df_actuel['name_0'].values: s24 = df_actuel[df_actuel['name_0'] == pays_match]['score'].mean()
    s30 = s24 * 1.1
    if not df_futur.empty and pays_match in df_futur['name_0'].values: s30 = df_futur[df_futur['name_0'] == pays_match]['score'].mean()
    s26 = s24 + ((s30 - s24) * 0.33)
    return {"ent": "N/A", "ville": ville, "pays": pays_match, "lat": loc.latitude, "lon": loc.longitude, "s2024": s24, "s2026": s26, "s2030": s30, "found": True}

def create_pdf(data, corpus, notes, ratios):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20); pdf.cell(0, 15, clean(f"AUDIT V21: {data.get('ent', 'N/A').upper()}"), ln=1, align='C'); pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "1. FINANCE", ln=1)
    pdf.set_font("Arial", size=11)
    pdf.cell(60, 10, clean(f"Valo: {data.get('valeur_entreprise',0):,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"CA: {data.get('ca',0):,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"Marge: {ratios.get('Marge Nette',0):.1f}%"), border=1)
    pdf.ln(15)
    
    var = data.get('var_2030', 0)
    col = (200,0,0) if var > 0 else (0,100,0)
    pdf.set_text_color(*col)
    pdf.cell(0, 10, clean(f"IMPACT VAR 2030: {'-' if var>0 else '+'}{abs(var):,.0f} $"), ln=1)
    pdf.set_text_color(0,0,0)
    
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "2. CLIMAT", ln=1); pdf.set_font("Arial", size=11)
    pdf.cell(0, 10, f"Score 2030: {data.get('s30',0):.2f}/5 (Pluie 90j: {data.get('pluie_90j','N/A')}mm)", ln=1)
    pdf.ln(5)
    
    pdf.set_font("Arial", 'I', 10); pdf.multi_cell(0, 5, clean(f"Synthese:\n{data.get('txt_ia','')[:800]}..."))
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
    v = st.text_input("Ville", "Issy-les-Moulineaux")
    p = st.text_input("Pays", "France")
    website = st.text_input("Web", "")
    
    st.markdown("---")
    st.subheader("2. Finance")
    mode_val = st.radio("Type", ["Non Cotée", "Cotée", "Startup"])
    valeur_finale = 0.0; source_info = "Manuel"
    
    secteur = st.selectbox("Secteur", ["Agroalimentaire (100%)", "Industrie (70%)", "BTP (40%)", "Commerce (20%)", "Logiciel (5%)"])
    vuln = float(secteur.split('(')[1].replace('%)',''))/100

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
                        st.success("OK Pappers")
        
        with col_pdf:
            uploaded_bilan = st.file_uploader("Bilan PDF", type=["pdf"], key="bilan_upload")
            if uploaded_bilan:
                with st.spinner("OCR V5..."):
                    txt = extract_text_from_pdfs_robust([uploaded_bilan])
                    fin = extract_financials_from_text(txt)
                    if fin['found']:
                        # MISE A JOUR DES VARIABLES
                        st.session_state.finance_ca = float(fin['ca'])
                        st.session_state.finance_res = float(fin['resultat'])
                        st.session_state.finance_cap = float(fin['capitaux'])
                        st.session_state.finance_ebitda = float(fin['resultat']) * 1.25 # Approx
                        
                        # TABLEAU DE CONTROLE VISUEL
                        st.success("Données détectées !")
                        st.dataframe(pd.DataFrame({
                            "Métrique": ["Chiffre d'Affaires", "Résultat Net", "Capitaux Propres"],
                            "Valeur (€)": [fin['ca'], fin['resultat'], fin['capitaux']]
                        }))

        # INPUTS CONNECTÉS AU SESSION STATE
        m_pme = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "DCF", "Patrimonial"])
        
        if "CA" in m_pme:
            base = st.number_input("Chiffre d'Affaires (€)", key="finance_ca")
            mult = st.slider("Multiple", 0.1, 5.0, 1.5, 0.1)
            valeur_finale = base * mult
            source_info = f"CA x{mult}"
        elif "EBITDA" in m_pme:
            base = st.number_input("EBITDA (€)", key="finance_ebitda")
            mult = st.slider("Multiple", 1.0, 20.0, 7.0, 0.5)
            valeur_finale = base * mult
            source_info = f"EBITDA x{mult}"
        elif "DCF" in m_pme:
            base = st.number_input("Free Cash Flow (Résultat) (€)", key="finance_res")
            wacc = st.number_input("WACC (%)", 1.0, 20.0, 10.0, 0.5)/100
            g = st.number_input("Croissance g (%)", 0.0, 10.0, 2.0, 0.1)/100
            valeur_finale = base * (1+g)/(wacc-g) if wacc>g else 0
            source_info = "DCF"
        else:
            base = st.number_input("Capitaux Propres (€)", key="finance_cap")
            valeur_finale = base
            source_info = "Actif Net"
            
    elif mode_val == "Cotée":
        ticker = st.text_input("Ticker", "BN.PA")
        if st.button("Yahoo"):
            m, e = get_stock_advanced(ticker)
            if m > 0: st.session_state.stock_data = {"mcap":m, "ev":e}
        valeur_finale = st.number_input("Valo", value=st.session_state.stock_data['mcap'])
        source_info = f"Bourse {ticker}"

    else:
        stade = st.selectbox("Stade", ["Pre-Seed", "Seed", "Series A", "Series B"])
        ranges = {"Pre-Seed": (0.5, 2), "Seed": (2, 8), "Series A": (8, 30), "Series B": (30, 80)}
        mini, maxi = ranges.get(stade, (1, 5))
        st.info(f"Fourchette: {mini}M€ - {maxi}M€")
        valeur_finale = st.slider("Valo (M€)", mini*1e6, maxi*1e6, (mini+maxi)/2*1e6)
        source_info = f"VC {stade}"

    st.markdown("---")
    st.write("📂 **3. Data Room**")
    notes = st.text_area("Notes", height=100)
    docs = st.file_uploader("Documents Annexes", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 AUDIT"):
        with st.spinner("Analyse..."):
            res = analyser_risque_geo(v, p)
            if res['found']:
                news, wiki = get_news_and_wiki(ent)
                web = scan_website(website)
                pluie = get_weather_history(res['lat'], res['lon'])
                doc_txt = extract_text_from_pdfs_robust(docs)
                corpus = f"{notes} {web} {wiki} {doc_txt} {' '.join([n['title'] for n in news])}"
                
                delta_risk = res['s2030'] - res['s2024']
                impact_30 = valeur_finale * (delta_risk / 5.0) * vuln
                alerts = sum(1 for w in ['litige', 'procès', 'amende'] if w in corpus.lower())
                txt_ia = f"Analyse {len(docs)} docs. {alerts} alertes.\nContexte: {wiki[:300]}..."
                st.session_state.comparables = get_comparables(secteur_risk)
                
                final = {
                    "ent": ent, "ville": v, "pays": res['pays'], "lat": res['lat'], "lon": res['lon'],
                    "valeur_entreprise": valeur_finale, "source_ca": source_info,
                    "ca": st.session_state.finance_ca, "res": st.session_state.finance_res, "cap": st.session_state.finance_cap,
                    "s2024": res['s2024'], "s30": res['s2030'], "var_2030": impact_30,
                    "news": news, "txt_ia": txt_ia, "pluie_90j": pluie
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
        ratios = calculate_ratios(r.get('ca',0), r.get('res',0), r.get('cap',0))
        k2.metric("Marge Nette", f"{ratios['Marge Nette']:.1f}%")
        
        var = r.get('var_2030', 0)
        label_var = f"{'-' if var>0 else '+'}{abs(var):,.0f} $"
        k3.metric("Impact 2030", label_var, delta_color="inverse" if var>0 else "normal")
        
        st.info(f"Météo: {r.get('pluie_90j')} mm")
        
        t1, t2, t3 = st.tabs(["Rapport", "Comparables", "Sources"])
        with t1:
            pdf = create_pdf(r, "", notes, ratios)
            st.download_button("📥 PDF", pdf, file_name="Rapport.pdf")
            xls = generate_excel(r, ratios)
            st.download_button("📊 Excel", xls, file_name="Data.xlsx")
            if r.get('lat'):
                m = folium.Map([r['lat'], r['lon']], zoom_start=10)
                folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color='red')).add_to(m)
                st_folium(m, height=250)
        with t2:
            if st.session_state.comparables is not None: st.dataframe(st.session_state.comparables)
        with t3:
            for n in r.get('news', []): st.markdown(f"- [{n['title']}]({n['link']})")
                
