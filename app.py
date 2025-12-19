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

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
st.set_page_config(page_title="AquaRisk V18.1 : OCR Expert", page_icon="🤖", layout="wide")
st.title("🤖 AquaRisk V18.1 : Audit avec Lecture Intelligente de Bilan")

if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'stock_data' not in st.session_state: st.session_state.stock_data = {"mcap": 0, "ev": 0}
if 'pdf_financials' not in st.session_state: st.session_state.pdf_financials = None

# ==============================================================================
# 2. CHARGEMENT DATA
# ==============================================================================
@st.cache_data
def load_data():
    BACKUP_DATA = pd.DataFrame({
        'name_0': ['France', 'United States', 'Germany', 'China'],
        'name_1': ['Ile-de-France', 'California', 'Bavaria', 'Beijing'],
        'score': [2.5, 3.8, 2.2, 4.1]
    })
    
    def smart_read(filename):
        if not os.path.exists(filename): return None
        try:
            df = pd.read_csv(filename, sep=',', engine='python', on_bad_lines='skip')
            df.columns = [c.lower().strip() for c in df.columns]
            return df
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
# 3. MOTEUR OCR FINANCIER AVANCÉ (V2)
# ==============================================================================
def parse_french_number(text_num):
    """Nettoie et convertit '1 230 500' ou '(10 000)' en float"""
    try:
        # Nettoyage
        clean = text_num.replace(' ', '').replace(')', '').replace('(', '-')
        # Gestion des caractères invisibles
        clean = re.sub(r'[^\d,\.-]', '', clean)
        clean = clean.replace(',', '.')
        # Gestion des multiples points
        if clean.count('.') > 1:
            clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except:
        return None

def extract_financials_from_text(text):
    """
    Analyse ligne par ligne pour extraire les données d'une liasse fiscale.
    Cherche les mots clés et prend le nombre le plus pertinent sur la ligne.
    """
    data = {"ca": 0, "resultat": 0, "capitaux": 0, "found": False}
    lines = text.split('\n')
    
    # Motifs cibles (Ordre de priorité)
    patterns = {
        "ca": ["CHIFFRES D'AFFAIRES NETS", "Total des produits d'exploitation", "Ventes de marchandises"],
        "resultat": ["BENEFICE OU PERTE", "RESULTAT DE L'EXERCICE (bénéfice ou perte)", "RESULTAT DE L'EXERCICE"],
        "capitaux": ["TOTAL CAPITAUX PROPRES", "CAPITAUX PROPRES", "Situation nette"]
    }
    
    for line in lines:
        line_clean = line.strip().upper()
        
        # 1. Analyse CA
        for p in patterns["ca"]:
            if p in line_clean and data["ca"] == 0:
                # On cherche tous les nombres sur la ligne
                nums = re.findall(r'-?[\d\s]+(?:,[\d]+)?', line)
                valid_nums = [parse_french_number(n) for n in nums if parse_french_number(n) is not None]
                # Heuristique : Le CA est souvent le plus grand chiffre de la ligne
                if valid_nums:
                    data["ca"] = max(valid_nums)
                    data["found"] = True

        # 2. Analyse Résultat
        for p in patterns["resultat"]:
            if p in line_clean and data["resultat"] == 0:
                nums = re.findall(r'-?[\d\s]+(?:,[\d]+)?', line)
                valid_nums = [parse_french_number(n) for n in nums if parse_french_number(n) is not None]
                if valid_nums:
                    # On prend le dernier chiffre (souvent colonne N) ou le plus grand en valeur absolue
                    data["resultat"] = valid_nums[0] # Souvent le premier après le libellé dans les PDF extraits
                    data["found"] = True

        # 3. Analyse Capitaux
        for p in patterns["capitaux"]:
            if p in line_clean and data["capitaux"] == 0:
                nums = re.findall(r'-?[\d\s]+(?:,[\d]+)?', line)
                valid_nums = [parse_french_number(n) for n in nums if parse_french_number(n) is not None]
                if valid_nums:
                    data["capitaux"] = max(valid_nums)
                    data["found"] = True

    return data

# ==============================================================================
# 4. FONCTIONS TECH CLASSIQUES
# ==============================================================================
class MockLocation:
    def __init__(self, lat, lon): self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    clean_v = ville.lower().strip()
    fallback = {
        "paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "marseille": (43.2965, 5.3698),
        "bordeaux": (44.8378, -0.5792), "toulouse": (43.6047, 1.4442), "boulogne-billancourt": (48.8397, 2.2399),
        "issy-les-moulineaux": (48.823, 2.269) # Ajout pour votre cas
    }
    if clean_v in fallback: return MockLocation(*fallback[clean_v])
    for i in range(2):
        try:
            ua = f"AR_V181_{randint(1000,9999)}"
            loc = Nominatim(user_agent=ua, timeout=8).geocode(f"{ville}, {pays}")
            if loc: return loc
        except: time.sleep(1); continue
    return MockLocation(48.8566, 2.3522)

def get_weather_history(lat, lon):
    try:
        url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={(datetime.now()-timedelta(days=90)).strftime('%Y-%m-%d')}&end_date={datetime.now().strftime('%Y-%m-%d')}&daily=precipitation_sum&timezone=auto"
        r = requests.get(url, timeout=5).json()
        if 'daily' in r: return f"{sum([x for x in r['daily']['precipitation_sum'] if x]):.0f}"
    except: pass
    return "N/A"

def get_pappers_financials(company_name, api_key):
    # (Code Pappers inchangé et robuste)
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
        return {"nom": res[0]['nom_entreprise'], "ca": ca, "resultat": res, "capitaux": cap, "ebitda": res*1.25, "annee": annee}
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
        search = wikipedia.search(name)
        if search: return wikipedia.page(search[0]).summary[:1500]
    except: pass
    return "Pas de données Wikipedia."

def scan_website(url):
    if len(url) < 5: return ""
    if not url.startswith("http"): url = "https://" + url
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        return ' '.join([p.text for p in BeautifulSoup(r.text, 'html.parser').find_all('p')])[:5000]
    except: return ""

def extract_text_from_pdfs(files):
    t=""; n=[]
    if not files: return "", []
    for f in files:
        try:
            with pdfplumber.open(f) as pdf:
                # On scanne plus de pages pour être sûr de trouver le bilan
                for p in pdf.pages[:30]: t += p.extract_text() or ""
                n.append(f.name)
        except: continue
    return t, n

# ==============================================================================
# 5. MOTEUR ANALYSE
# ==============================================================================
def analyser_risque_geo(ville, pays):
    loc = get_location_safe(ville, pays)
    pays_match, score = process.extractOne(str(pays), df_actuel['name_0'].unique().astype(str))
    if score < 60: pays_match = pays

    s24 = 2.5
    if pays_match in df_actuel['name_0'].values:
        s24 = df_actuel[df_actuel['name_0'] == pays_match]['score'].mean()
    
    s30 = s24 * 1.1
    if df_futur is not None and pays_match in df_futur['name_0'].values:
        s30 = df_futur[df_futur['name_0'] == pays_match]['score'].mean()

    s26 = s24 + ((s30 - s24) * 0.33)
    
    return {
        "ent": "N/A", "ville": ville, "pays": pays_match, 
        "lat": loc.latitude, "lon": loc.longitude, 
        "s2024": s24, "s2026": s26, "s2030": s30, "found": True
    }

# ==============================================================================
# 6. PDF
# ==============================================================================
def generer_carte(lat, lon):
    try:
        m = StaticMap(800, 400)
        m.add_marker(CircleMarker((lon, lat), 'red', 18))
        img = m.render(zoom=10)
        img.save("temp_map.png")
        return "temp_map.png"
    except: return None

def create_pdf(data, corpus, notes):
    def clean(t): return str(t).encode('latin-1', 'replace').decode('latin-1')
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, clean(f"AUDIT V18.1: {data.get('ent', 'N/A').upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    if data.get('lat'):
        f = generer_carte(data['lat'], data['lon'])
        if f: pdf.image(f, x=20, w=170)
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. FINANCE & IMPACT", ln=1)
    pdf.set_font("Arial", size=11)
    
    val = data.get('valeur_entreprise', 0)
    var = data.get('var_2030', 0)
    
    pdf.cell(60, 10, clean(f"Valorisation: {val:,.0f} $"), border=1)
    pdf.cell(60, 10, clean(f"Methode: {data.get('source_ca', 'Manuel')}"), border=1)
    
    if var > 0:
        pdf.set_text_color(200,0,0)
        txt_var = f"PERTE Estimee 2030: -{abs(var):,.0f} $"
    elif var < 0:
        pdf.set_text_color(0,100
                           
