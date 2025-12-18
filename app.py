import streamlit as st
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
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

# --- 1. CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="AquaRisk 4.3 : Stable", page_icon="🛡️", layout="wide")
st.title("🛡️ AquaRisk 4.3 : Version Stable & Blindée")

# --- 2. GESTION DE LA MÉMOIRE (SESSION STATE) ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'audit_masse' not in st.session_state: st.session_state.audit_masse = None

# --- 3. CHARGEMENT DES DONNÉES (EXTRÊMEMENT ROBUSTE) ---
@st.cache_data
def load_data():
    def smart_read(filename):
        # A. Vérifier si le fichier existe physiquement
        if not os.path.exists(filename):
            st.error(f"❌ FICHIER MANQUANT : '{filename}' n'est pas à la racine.")
            st.info(f"Fichiers visibles ici : {os.listdir('.')}")
            return None
        
        # B. Vérifier s'il n'est pas vide (problème Git LFS ou upload raté)
        if os.path.getsize(filename) < 50:
            st.error(f"⚠️ FICHIER VIDE ou CORROMPU : '{filename}' (Taille < 50 octets).")
            return None

        # C. Essayer de lire avec plusieurs séparateurs
        separators = [',', ';', '\t']
        for sep in separators:
            try:
                df = pd.read_csv(filename, sep=sep, engine='python', on_bad_lines='skip')
                # Si on a réussi à créer des colonnes, on nettoie les noms
                if len(df.columns) > 1:
                    df.columns = [c.lower().strip() for c in df.columns]
                    return df
            except:
                continue
        
        st.error(f"⛔ FICHIER ILLISIBLE : Impossible de lire '{filename}' (Format inconnu).")
        return None

    # --- Chargement Actuel ---
    df_now = smart_read("risk_actuel.csv")
    if df_now is not None:
        # Conversion du score (4,5 -> 4.5)
        if 'score' in df_now.columns:
            df_now['score'] = df_now['score'].astype(str).str.replace(',', '.', regex=False)
            df_now['score'] = pd.to_numeric(df_now['score'], errors='coerce')
        # Filtre spécifique WRI (si les colonnes existent)
        if 'indicator_name' in df_now.columns:
            df_now = df_now[df_now['indicator_name'] == 'bws']

    # --- Chargement Futur ---
    df_fut = smart_read("risk_futur.csv")
    if df_fut is not None:
        if 'score' in df_fut.columns:
            df_fut['score'] = df_fut['score'].astype(str).str.replace(',', '.', regex=False)
            df_fut['score'] = pd.to_numeric(df_fut['score'], errors='coerce')
        if 'year' in df_fut.columns and 'scenario' in df_fut.columns:
            mask = (df_fut['year'] == 2030) & (df_fut['scenario'] == 'bau') & (df_fut['indicator_name'] == 'bws')
            df_fut = df_fut[mask]

    return df_now, df_fut

# Exécution du chargement avec arrêt propre si échec
try:
    df_actuel, df_futur = load_data()
except Exception as e:
    st.error(f"Erreur Système : {e}")
    st.stop()

if df_actuel is None or df_futur is None:
    st.warning("⚠️ L'application ne peut pas démarrer sans les fichiers CSV valides.")
    st.stop()

# --- 4. FONCTIONS GÉOGRAPHIQUES (ANTI-BLOCAGE) ---
def get_location_safe(ville, pays):
    agents = ["Aqua_V4", "Student_Project_Fr", "Data_Viz_Tool"]
    for i in range(3):
        try:
            ua = f"{agents[i]}_{randint(100,999)}"
            geolocator = Nominatim(user_agent=ua, timeout=5)
            loc = geolocator.geocode(f"{ville}, {pays}")
            if loc: return loc
        except:
            time.sleep(1)
    return None

def get_region_safe(lat, lon):
    try:
        ua = f"Rev_Geo_{randint(100,999)}"
        geolocator = Nominatim(user_agent=ua, timeout=5)
        return geolocator.reverse(f"{lat}, {lon}", language='en')
    except: return None

# --- 5. MOTEUR NEWS (GOOGLE RSS) ---
def get_company_news(company_name):
    query = urllib.parse.quote(f"{company_name} water environment")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    
    def clean_html(raw_html):
        cleanr = re.compile('<.*?>')
        text = re.sub(cleanr, '', raw_html)
        return text.replace("&nbsp;", " ").replace("&#39;", "'")
    
    try:
        feed = feedparser.parse(rss_url)
        items = []
        for entry in feed.entries[:5]:
            summary = entry.summary if 'summary' in entry else entry.title
            clean_sum = clean_html(summary)
            if len(clean_sum) > 200: clean_sum = clean_sum[:200] + "..."
            
            items.append({
                "title": entry.title,
                "link": entry.link,
                "summary": clean_sum
            })
        return items
    except:
        return []

# --- 6. MOTEUR ANALYSE ---
def analyser_site(ville, pays, region_forcee=None):
    loc = get_location_safe(ville, pays)
    if not loc: return None
    
    # Région
    loc_details = get_region_safe(loc.latitude, loc.longitude)
    reg_auto = ""
    if loc_details:
        addr = loc_details.raw['address']
        reg_auto = addr.get('state', addr.get('region', addr.get('county', ''))).strip()
    
    region_final = region_forcee if region_forcee else reg_auto
    
    # Matching Data
    # On vérifie que les colonnes existent pour éviter le crash
    if 'name_0' not in df_actuel.columns or 'name_1' not in df_actuel.columns:
        return {"ent": "Error", "ville": ville, "lat": loc.latitude, "lon": loc.longitude, "s25": 0, "s30": 0, "found": False, "error": "Colonnes CSV incorrectes"}

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

# --- 7. GÉNÉRATEUR PDF (SANS CRASH) ---
def create_pdf(data):
    def clean(text):
        if not isinstance(text, str): text = str(text)
        # Remplacements de sûreté
        replacements = {"✅": "[OK]", "⚠️": "[!]", "🚨": "[ALERTE]", "ℹ️": "[INFO]", "’": "'", "“": '"', "”": '"', "…": "..."}
        for k, v in replacements.items():
            text = text.replace(k, v)
        # Encodage final pour FPDF
        return text.encode('latin-1', 'replace').decode('latin-1')

    pdf = FPDF()
    pdf.add_page()
    
    # Titre
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, clean(f"RAPPORT AQUARISK: {data['ent'].upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    # Infos
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, clean(f"Localisation: {data['loc']}"), ln=1)
    pdf.cell(0, 10, clean(f"VaR (Risque Financier): {data['var']:,.0f} $"), ln=1)
    pdf.ln(5)
    
    # Scores
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"Risque Residuel 2025: {data['s25_display']:.2f} / 5", ln=1)
    pdf.cell(0, 10, f"Risque Physique (Base): {data['s25_brut']:.2f} / 5", ln=1)
    pdf.cell(0, 10, f"Projection 2030: {data['s30_display']:.2f} / 5", ln=1)
    pdf.ln(5)
    
    # Analyse
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 8, clean(f"Analyse IA:\n{data['txt_ia']}"))
    
    # News
    if 'news' in data and data['news']:
        pdf.ln(10)
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(0, 10, "Presse (Google News):", ln=1)
        for n in data['news']:
            pdf.set_font("Arial", 'B', 9)
            pdf.cell(0, 6, clean(f"- {n['title'][:90]}"), ln=1)
            pdf.set_font("Arial", 'I', 8)
            pdf.set_text_color(100,100,100)
            pdf.multi_cell(0, 4, clean(f"  {n['summary']}"))
            pdf.set_text_color(0,0,0)
            pdf.ln(1)

    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 8. INTERFACE UTILISATEUR ---
tab1, tab2 = st.tabs(["📡 Audit Live", "📂 Excel Masse"])

with tab1:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.info("💡 Paramètres de l'usine à auditer")
        ent = st.text_input("Nom Entreprise", "Tesla")
        v = st.text_input("Ville", "Austin")
        p = st.text_input("Pays", "United States")
        reg = st.text_input("Région (Optionnel)", "Texas")
        cap = st.number_input("Capital ($)", 10000000)
        
        st.write("---")
        notes = st.text_area("Notes manuelles", height=60, placeholder="Ex: Plan de réduction...")
        
        if st.button("🚀 LANCER L'AUDIT"):
            with st.spinner("Analyse en cours (Satellite + News)..."):
                res = analyser_site(v, p, reg)
                
                if res and res['found']:
                    # 1. News
                    news = get_company_news(ent)
                    
                    # 2. Scoring IA
                    txt_combined = notes + " " + " ".join([n['title'] for n in news])
                    bonus = 0.0
                    txt_ia = "Neutre (Pas de signal fort)."
                    
                    m_pos = ['recycle', 'reduce', 'saving', 'stewardship', 'rainwater']
                    m_neg = ['drought', 'shortage', 'conflict', 'pollution', 'violation']
                    
                    if len(txt_combined) > 5:
                        s_pos = sum(1 for w in m_pos if w in txt_combined.lower())
                        s_neg = sum(1 for w in m_neg if w in txt_combined.lower())
                        if s_pos > s_neg: 
                            bonus = 0.15
                            txt_ia = f"✅ Positif (-15% Risque): {s_pos} indices positifs trouvés."
                        elif s_neg > s_pos: 
                            bonus = -0.10
                            txt_ia = f"⚠️ Alerte (+10% Risque): {s_neg} indices négatifs trouvés."
                    
                    # 3. Finalisation
                    res['ent'] = ent
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
                    st.error("❌ Lieu introuvable ou hors base de données.")

    with c2:
        if st.session_state.audit_unique:
            r = st.session_state.audit_unique
            st.success(f"Rapport : {r['ent']}")
            
            # KPIs
            k1, k2, k3 = st.columns(3)
            k1.metric("Risque Résiduel", f"{r['s25_display']:.2f}/5", delta=f"Base: {r['s25_brut']:.2f}", delta_color="inverse")
            k2.metric("Horizon 2030", f"{r['s30_display']:.2f}/5")
            k3.metric("VaR Financière", f"{r['var']:,.0f} $")
            
            # Onglet News
            with st.expander("📰 Revue de Presse", expanded=True):
                st.caption(r['txt_ia'])
                if r['news']:
                    for n in r['news']:
                        st.markdown(f"- [{n['title']}]({n['link']})")
                else:
                    st.write("Aucune news récente.")

            # Carte
            m = folium.Map([r['lat'], r['lon']], zoom_start=9, tiles="cartodbpositron")
            folium.Marker([r['lat'], r['lon']], popup=r['ent'], icon=folium.Icon(color="red" if r['s25_display']>3 else "green")).add_to(m)
            st_folium(m, height=300)
            
            # PDF
            pdf_bytes = create_pdf(r)
            st.download_button("📄 Télécharger PDF", pdf_bytes, file_name=f"Rapport_{r['ent']}.pdf", mime="application/pdf")

with tab2:
    st.header("Mode Excel (Portefeuille)")
    
    df_ex = pd.DataFrame({"Ville": ["Lyon", "Berlin"], "Pays": ["France", "Germany"], "Region_Force": ["", ""]})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        df_ex.to_excel(writer, index=False)
    st.download_button("📥 Modèle Excel", buf.getvalue(), "modele.xlsx", "application/vnd.ms-excel")
    
    up = st.file_uploader("Upload Excel", type=["xlsx", "csv"])
    if up and st.button("Lancer Scan"):
        df_in = pd.read_excel(up) if up.name.endswith('xlsx') else pd.read_csv(up)
        out = []
        bar = st.progress(0)
        
        for i, row in df_in.iterrows():
            rf = row['Region_Force'] if 'Region_Force' in row and pd.notna(row['Region_Force']) else None
            res = analyser_site(row['Ville'], row['Pays'], rf)
            
            if res and res.get('found'):
                out.append({"Ville": row['Ville'], "Score_25": res['s25'], "Score_30": res['s30']})
            else:
                out.append({"Ville": row['Ville'], "Score_25": "Erreur"})
            
            bar.progress((i+1)/len(df_in))
            time.sleep(1)
            
        st.session_state.audit_masse = pd.DataFrame(out)
        st.success("Terminé !")
        
    if st.session_state.audit_masse is not None:
        st.dataframe(st.session_state.audit_masse)
        
