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
st.set_page_config(page_title="AquaRisk 15.1 : Stable", page_icon="🛡️", layout="wide")
st.title("🛡️ AquaRisk 15.1 : Audit Blindé & Valorisation")

# Initialisation sécurisée
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = {}
if 'pappers_data' not in st.session_state: st.session_state.pappers_data = None
if 'live_multiples' not in st.session_state: st.session_state.live_multiples = None
if 'stock_data' not in st.session_state: st.session_state.stock_data = {"mcap": 0, "ev": 0}

# ==============================================================================
# 2. CHARGEMENT DATA
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
    if df_now is None: 
        df_now = pd.DataFrame({'name_0': ['France'], 'name_1': ['Ile-de-France'], 'score': [2.5]})
    elif 'score' in df_now.columns:
        df_now['score'] = pd.to_numeric(df_now['score'].astype(str).str.replace(',', '.'), errors='coerce')

    df_fut = smart_read("risk_futur.csv")
    if df_fut is not None and 'score' in df_fut.columns:
        df_fut['score'] = pd.to_numeric(df_fut['score'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'year' in df_fut.columns:
            df_fut = df_fut[(df_fut['year'] == 2030) & (df_fut['scenario'] == 'bau')]
            
    return df_now, df_fut

try:
    df_actuel, df_futur = load_data()
except: st.stop()

# ==============================================================================
# 3. OUTILS API (ROBUSTES)
# ==============================================================================

# --- PAPPERS (SECURISE) ---
def get_pappers_financials(company_name, api_key):
    if not api_key: return None
    try:
        q = urllib.parse.quote(company_name)
        s_url = f"https://api.pappers.fr/v2/recherche?q={q}&api_token={api_key}&par_page=1"
        r = requests.get(s_url, timeout=5)
        
        if r.status_code != 200: return None # Erreur clé ou quota
        
        data = r.json()
        if not data.get('resultats'): return None
        
        match = data['resultats'][0]
        siren = match['siren']
        
        f_url = f"https://api.pappers.fr/v2/entreprise?api_token={api_key}&siren={siren}"
        f_r = requests.get(f_url, timeout=5)
        if f_r.status_code != 200: return None
        
        f_data = f_r.json()
        
        ca=0; res=0; cap=0; ebitda=0; annee="N/A"
        for c in f_data.get('finances', []):
            if c.get('annee_cloture_exercice'):
                ca = c.get('chiffre_affaires', 0) or 0
                res = c.get('resultat', 0) or 0
                cap = c.get('capitaux_propres', 0) or 0
                ebitda = res * 1.25 if res > 0 else 0 
                annee = c['annee_cloture_exercice']
                break
                
        return {
            "nom": match['nom_entreprise'], "siren": siren, "annee": annee,
            "ca": ca, "resultat": res, "capitaux": cap, "ebitda": ebitda
        }
    except: return None

# --- YAHOO FINANCE ---
def get_stock_advanced(ticker):
    try:
        stock = yf.Ticker(ticker)
        mcap = stock.fast_info.get('market_cap')
        if not mcap: mcap = stock.info.get('marketCap', 0)
        ev = stock.info.get('enterpriseValue', 0)
        if not ev or ev == 0: ev = mcap
        return mcap, ev
    except: return 0, 0

# --- GPS ---
class MockLocation:
    def __init__(self, lat, lon):
        self.latitude = lat; self.longitude = lon

def get_location_safe(ville, pays):
    ville_clean = ville.lower().strip()
    fallback = {
        "paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "marseille": (43.2965, 5.3698),
        "bordeaux": (44.8378, -0.5792), "toulouse": (43.6047, 1.4442), "boulogne-billancourt": (48.8397, 2.2399),
        "new york": (40.7128, -74.0060), "berlin": (52.5200, 13.4050), "london": (51.5074, -0.1278)
    }
    if ville_clean in fallback: return MockLocation(*fallback[ville_clean])

    for i in range(2): 
        try:
            ua = f"AR_V151_{randint(1000,9999)}"
            geolocator = Nominatim(user_agent=ua, timeout=8)
            loc = geolocator.geocode(f"{ville}, {pays}", language='en')
            if loc: return loc
        except: time.sleep(1); continue
    return MockLocation(48.8566, 2.3522) # Default Paris

# --- MÉTÉO ---
def get_weather_history(lat, lon):
    if not lat or not lon: return "N/A"
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}&daily=precipitation_sum&timezone=auto"
    try:
        r = requests.get(url, timeout=5)
        d = r.json()
        if 'daily' in d and 'precipitation_sum' in d['daily']:
            val = sum([x for x in d['daily']['precipitation_sum'] if x is not None])
            return f"{val:.0f}"
    except: return "N/A"
    return "N/A"

# --- NEWS & WEB ---
def get_company_news(company_name):
    q = urllib.parse.quote(f'"{company_name}" (eau OR pollution OR environnement)')
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
                for page in
                
