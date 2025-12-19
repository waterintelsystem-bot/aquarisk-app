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
st.set_page_config(page_title="AquaRisk 11.1 : Stable", page_icon="🛡️", layout="wide")
st.title("🛡️ AquaRisk 11.1 : Version Stabilisée (GPS & Finance)")

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

# --- 2. FONCTIONS TECH (CORRECTIF ROBUSTE) ---
def get_location_safe(ville, pays):
    """
    Tente de géolocaliser avec plusieurs essais et un User-Agent unique
    pour éviter les blocages de l'API Nominatim.
    """
    max_retries = 3
    for i in range(max_retries):
        try:
            # User Agent unique à chaque essai pour éviter le ban
            ua = f"AquaRisk_Explorer_V11_{randint(1000,9999)}_{int(time.time())}"
            geolocator = Nominatim(user_agent=ua, timeout=10) # Timeout augmenté à 10s
            
            # On force la requête
            loc = geolocator.geocode(f"{ville}, {pays}", language='en')
            if loc:
                return loc
            
        except (GeocoderTimedOut, GeocoderServiceError):
            time.sleep(1 + i) # Attente progressive (1s, 2s, 3s)
            continue
        except Exception as e:
            # En cas d'autre erreur, on continue
            continue
            
    return None

def trouver_meilleur_nom(nom_cherche, liste_options, seuil=75):
    if not nom_cherche or len(liste_options) == 0: return None
    meilleur_match, score = process.extractOne(str(nom_cherche), liste_options.astype(str))
    if score >= seuil: return meilleur_match
    return None

# --- 3. SOURCES EXTERNES ---
def get_market_news(sector_keywords):
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
        r = requests.get(url, timeout=10) # Timeout augmenté
        d = r.json()
        if 'daily' in d and 'precipitation_sum' in d['daily']:
            return sum


