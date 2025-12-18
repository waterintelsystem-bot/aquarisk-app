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
from bs4 import BeautifulSoup # Pour lire les sites web

# --- CONFIGURATION ---
st.set_page_config(page_title="AquaRisk 5.0 : Audit Universel", page_icon="🌐", layout="wide")
st.title("🌐 AquaRisk 5.0 : Audit Entreprises (Cotées & Non Cotées)")

# --- MÉMOIRE ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None

# --- 1. CHARGEMENT DATA (ROBUSTE) ---
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
    if df_now is not None:
        if 'score' in df_now.columns:
            df_now['score'] = pd.to_numeric(df_now['score'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'indicator_name' in df_now.columns:
            df_now = df_now[df_now['indicator_name'] == 'bws']

    df_fut = smart_read("risk_futur.csv")
    if df_fut is not None:
        if 'score' in df_fut.columns:
            df_fut['score'] = pd.to_numeric(df_fut['score'].astype(str).str.replace(',', '.'), errors='coerce')
        if 'year' in df_fut.columns:
            mask = (df_fut['year'] == 2030) & (df_fut['scenario'] == 'bau') & (df_fut['indicator_name'] == 'bws')
            df_fut = df_fut[mask]

    return df_now, df_fut

try:
    df_actuel, df_futur = load_data()
except: st.stop()

if df_actuel is None or df_futur is None: st.stop()

# --- 2. FONCTIONS GÉO ---
def get_location_safe(ville, pays):
    agents = ["Auditor_Web_1", "Risk_Tool_V5", "Global_Scanner"]
    for i in range(3):
        try:
            ua = f"{agents[i]}_{randint(100,999)}"
            geolocator = Nominatim(user_agent=ua, timeout=5)
            loc = geolocator.geocode(f"{ville}, {pays}")
            if loc: return loc
        except: time.sleep(1)
    return None

def get_region_safe(lat, lon):
    try:
        ua = f"Rev_Geo_{randint(100,999)}"
        geolocator = Nominatim(user_agent=ua, timeout=5)
        return geolocator.reverse(f"{lat}, {lon}", language='en')
    except: return None

# --- 3. MOTEUR WEB SCRAPER (NOUVEAU !) ---
def scan_website(url):
    if not url or len(url) < 5: return ""
    
    # On ajoute http si l'utilisateur l'a oublié
    if not url.startswith("http"): url = "https://" + url
    
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'}
    
    try:
        # On essaie de lire la page avec un timeout de 5 secondes
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # On prend tout le texte des paragraphes
            text = ' '.join([p.text for p in soup.find_all('p')])
            return text[:5000] # On limite aux 5000 premiers caractères
    except:
        return "" # Si échec (site sécurisé ou introuvable), on renvoie vide
    return ""

# --- 4. MOTEUR NEWS (RSS) ---
def get_company_news(company_name):
    query = urllib.parse.quote(f"{company_name} water environment")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    def clean_html(raw):
        cleanr = re.compile('<.*?>')
        return re.sub(cleanr, '', raw).replace("&nbsp;", " ").replace("&#39;", "'")
    try:
        feed = feedparser.parse(rss_url)
        items = []
        for entry in feed.entries[:5]:
            summary = clean_html(entry.summary if 'summary' in entry else entry.title)
            items.append({"title": entry.title, "link": entry.link, "summary": summary[:200]})
        return items
    except: return []

# --- 5. MOTEUR ANALYSE ---
def analyser_site(ville, pays, region_forcee=None):
    loc = get_location_safe(ville, pays)
    if not loc: return None
    
    loc_details = get_region_safe(loc.latitude, loc.longitude)
    reg_auto = ""
    if loc_details:
        addr = loc_details.raw['address']
        reg_auto = addr.get('state', addr.get('region', addr.get('county', ''))).strip()
    
    region_final = region_forcee if region_forcee else reg_auto
    
    if 'name_0' not in df_actuel.columns: return None

    mask_pays = df_actuel['name_0'].astype(str).str.lower().str.contains(pays.lower().strip(), na=False)
    df_pays = df_actuel[mask_pays]
    match_now = df_pays[df_pays['name_1'].astype(str).str.lower().str.contains(region_final.lower().strip(), na=False)]
    
    mask_pays_f = df_futur['name_0'].astype(str).str.lower().str.contains(pays.lower().strip(), na=False)
    df_f_pays = df_futur[mask_pays_f]
    match_fut = df_f_pays[df_f_pays['name_1'].astype(str).str.lower().str.contains(region_final.lower().strip(), na=False)]

    s25 = match_now['score'].mean() if not match_now.empty else 0
    s30 = match_fut['score'].mean() if not match_fut.empty else 0
    
    return {
        "ent": "N/A", "ville": ville, "pays": pays, "region": region_final,
        "lat": loc.latitude, "lon": loc.longitude,
        "s25": s25, "s30": s30, "found": not match_now.empty
    }

# --- 6. PDF ---
def create_pdf(data):
    def clean(t):
        t = str(t).replace("✅", "[OK]").replace("⚠️", "[!]").replace("🚨", "[ALRT]").replace("ℹ️", "[INFO]").replace("’", "'")
        return t.encode('latin-1', 'replace').decode('latin-1')

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, clean(f"AUDIT AQUARISK: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, clean(f"Site: {data['loc']}"), ln=1)
    pdf.cell(0, 10, clean(f"Capital/CA Expose: {data['var']:,.0f} $"), ln=1)
    if data.get('website_url'):
        pdf.cell(0, 10, clean(f"Source Web: {data['website_url']}"), ln=1)
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"Score Risque 2025: {data['s25_display']:.2f} / 5", ln=1)
    pdf.cell(0, 10, f"Projection 2030: {data['s30_display']:.2f} / 5", ln=1)
    pdf.ln(5)
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 8, clean(f"Analyse IA (Web+News):\n{data['txt_ia']}"))
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 7. INTERFACE ---
st.info("💡 Mode Universel : Fonctionne pour les entreprises cotées (Stock) et non-cotées (PME/ETI).")

c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("🔎 Paramètres Audit")
    ent = st.text_input("Nom de l'Entreprise", "Ferme Bio du Sud")
    website = st.text_input("Site Web (Optionnel)", placeholder="www.ferme-exemple.com")
    v = st.text_input("Ville", "Avignon")
    p = st.text_input("Pays", "France")
    reg = st.text_input("Région (Si connue)", "Provence-Alpes-Côte d'Azur")
    cap = st.number_input("Montant Investissement / CA ($)", 500000)
    
    st.markdown("---")
    notes = st.text_area("Notes manuelles", height=50)
    
    if st.button("🚀 Lancer l'Audit Web"):
        with st.spinner("🌍 Scan GPS + 🕷️ Analyse Site Web + 📰 News..."):
            res = analyser_site(v, p, reg)
            
            if res and res['found']:
                # 1. Sources de texte
                news = get_company_news(ent)
                web_text = scan_website(website) # <--- LE ROBOT SCANNE LE SITE ICI
                
                # 2. Construction du corpus pour l'IA
                full_text = notes + " " + web_text + " " + " ".join([n['title'] + " " + n['summary'] for n in news])
                
                # 3. Analyse Sémantique
                m_pos = ['recyclage', 'goutte-à-goutte', 'économie', 'biologique', 'durable', 'certification', 'reduce', 'recycle']
                m_neg = ['sécheresse', 'restriction', 'arrêté', 'prélèvement', 'conflit', 'pollué', 'drought', 'fine']
                
                bonus = 0.0
                txt_ia = "Neutre (Pas assez d'infos web/presse)."
                
                if len(full_text) > 20:
                    s_pos = sum(1 for w in m_pos if w in full_text.lower())
                    s_neg = sum(1 for w in m_neg if w in full_text.lower())
                    
                    if s_pos > s_neg: 
                        bonus = 0.15
                        txt_ia = f"✅ Stratégie Positive détectée ({s_pos} mentions sur le site/news)."
                    elif s_neg > s_pos: 
                        bonus = -0.10
                        txt_ia = f"⚠️ Risques identifiés dans les textes ({s_neg} mentions négatives)."
                elif website and len(web_text) < 10:
                    txt_ia = "⚠️ Le site web n'a pas pu être lu (protection ou vide)."

                # 4. Finalisation
                res['ent'] = ent
                res['website_url'] = website
                res['s25_brut'] = res['s25']
                res['s25_display'] = res['s25'] * (1 - bonus)
                res['s30_display'] = res['s30'] * (1 - bonus)
                res['var'] = cap * (res['s25_display'] / 5)
                res['txt_ia'] = txt_ia
                res['news'] = news
                res['loc'] = f"{res['ville']}, {res['region']}, {res['pays']}"
                
                st.session_state.audit_unique = res
                st.rerun()
            else:
                st.error("❌ Localisation introuvable.")

with c2:
    if st.session_state.audit_unique:
        r = st.session_state.audit_unique
        st.success(f"Audit : {r['ent']}")
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Risque Ajusté", f"{r['s25_display']:.2f}/5", delta=f"Physique: {r['s25_brut']:.2f}", delta_color="inverse")
        k2.metric("Horizon 2030", f"{r['s30_display']:.2f}/5")
        k3.metric("Capital à Risque", f"{r['var']:,.0f} $")
        
        with st.expander("📝 Analyse Textuelle (Site + News)", expanded=True):
            st.info(f"🤖 **IA :** {r['txt_ia']}")
            if r.get('website_url'):
                st.caption(f"Source Web analysée : {r['website_url']}")
            
            if r['news']:
                st.write("**Dernières Actualités :**")
                for n in r['news']:
                    st.markdown(f"- [{n['title']}]({n['link']})")

        m = folium.Map([r['lat'], r['lon']], zoom_start=9, tiles="cartodbpositron")
        folium.Marker([r['lat'], r['lon']], popup=r['ent'], icon=folium.Icon(color="red" if r['s25_display']>3 else "green")).add_to(m)
        st_folium(m, height=300)
        
        pdf_bytes = create_pdf(r)
        st.download_button("📄 Télécharger Audit PDF", pdf_bytes, file_name=f"Audit_{r['ent']}.pdf", mime="application/pdf")
        
