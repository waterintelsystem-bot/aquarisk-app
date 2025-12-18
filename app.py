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
import os  # Pour le diagnostic de fichiers

# --- CONFIGURATION ---
st.set_page_config(page_title="AquaRisk 4.2", page_icon="💧", layout="wide")
st.title("💧 AquaRisk 4.2 : Monitoring & Diagnostic")

# --- INITIALISATION MÉMOIRE ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'audit_masse' not in st.session_state: st.session_state.audit_masse = None

# --- 0. DIAGNOSTIC & CHARGEMENT ROBUSTE ---
@st.cache_data
def load_data():
    # Fonction locale pour tenter de lire un fichier
    def smart_read(filename):
        if not os.path.exists(filename):
            return None
        
        separators = [',', ';', '\t']
        for sep in separators:
            try:
                df = pd.read_csv(filename, sep=sep, engine='python', on_bad_lines='skip')
                # Nettoyage colonnes
                df.columns = [c.lower().strip() for c in df.columns]
                # Vérification basique
                if len(df.columns) > 2:
                    return df
            except:
                continue
        return None

    # 1. Chargement Actuel
    df_now = smart_read("risk_actuel.csv")
    if df_now is not None and 'score' in df_now.columns:
        df_now['score'] = df_now['score'].astype(str).str.replace(',', '.', regex=False)
        df_now['score'] = pd.to_numeric(df_now['score'], errors='coerce')
        # Filtre WRI (optionnel selon structure)
        if 'indicator_name' in df_now.columns:
            df_now = df_now[df_now['indicator_name'] == 'bws']

    # 2. Chargement Futur
    df_fut = smart_read("risk_futur.csv")
    if df_fut is not None and 'score' in df_fut.columns:
        df_fut['score'] = df_fut['score'].astype(str).str.replace(',', '.', regex=False)
        df_fut['score'] = pd.to_numeric(df_fut['score'], errors='coerce')
        if 'year' in df_fut.columns:
            mask = (df_fut['year'] == 2030) & (df_fut['scenario'] == 'bau') & (df_fut['indicator_name'] == 'bws')
            df_fut = df_fut[mask]

    return df_now, df_fut

# Lancement du chargement
try:
    df_actuel, df_futur = load_data()
except Exception as e:
    st.error(f"Erreur technique au chargement : {e}")
    df_actuel, df_futur = None, None

# --- BLOC DE DÉBOGAGE VISUEL (ANTI-CRASH) ---
if df_actuel is None or df_futur is None:
    st.error("🚨 ERREUR CRITIQUE : Fichiers de données introuvables.")
    
    st.warning("Voici ce que je vois dans le dossier du serveur :")
    files_present = os.listdir('.')
    st.code(f"Fichiers trouvés : {files_present}")
    
    st.markdown("""
    **Solutions :**
    1. Vérifiez que `risk_actuel.csv` et `risk_futur.csv` sont bien à la racine du GitHub.
    2. S'ils sont dans un dossier, déplacez-les ou changez le chemin dans le code.
    3. Vérifiez l'orthographe exacte (majuscules/minuscules).
    """)
    st.stop() # Arrête l'app ici proprement au lieu de crasher

# --- 1. FONCTIONS GÉOGRAPHIQUES ---
def get_location_safe(ville, pays):
    agents = ["AquaBot_Pro_v4", "Geo_Student_Project", "Climate_Risk_Tool"]
    for i in range(3):
        try:
            ua = f"{agents[i%3]}_{randint(1000,9999)}"
            geolocator = Nominatim(user_agent=ua, timeout=10)
            return geolocator.geocode(f"{ville}, {pays}")
        except:
            time.sleep(1)
    return None

def get_region_safe(lat, lon):
    try:
        ua = f"Reg_Finder_{randint(1000,9999)}"
        geolocator = Nominatim(user_agent=ua, timeout=10)
        return geolocator.reverse(f"{lat}, {lon}", language='en')
    except:
        return None

# --- 2. MOTEUR RSS (NEWS) ---
def get_company_news(company_name):
    # Encodage propre de l'URL
    query = urllib.parse.quote(f"{company_name} water environment")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    
    def clean_html(raw_html):
        # Enlève les balises HTML
        cleanr = re.compile('<.*?>')
        cleantext = re.sub(cleanr, '', raw_html)
        return cleantext.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    
    try:
        feed = feedparser.parse(rss_url)
        news_items = []
        for entry in feed.entries[:5]: # Top 5 news
            raw_summary = entry.summary if 'summary' in entry else entry.title
            clean_summary = clean_html(raw_summary)
            # Tronquer si trop long
            if len(clean_summary) > 200: clean_summary = clean_summary[:200] + "..."
            
            news_items.append({
                "title": entry.title,
                "link": entry.link,
                "published": entry.published,
                "summary": clean_summary
            })
        return news_items
    except:
        return []

# --- 3. MOTEUR ANALYSE ---
def analyser_site(ville, pays, region_forcee=None):
    loc = get_location_safe(ville, pays)
    if not loc: return None
    
    # Détection région
    loc_details = get_region_safe(loc.latitude, loc.longitude)
    reg_auto = ""
    if loc_details:
        addr = loc_details.raw['address']
        reg_auto = addr.get('state', addr.get('region', addr.get('county', ''))).strip()
    
    region_finale = region_forcee if region_forcee else reg_auto
    
    # Recherche Data
    mask_pays = df_actuel['name_0'].astype(str).str.lower().str.contains(pays.lower().strip(), na=False)
    df_pays = df_actuel[mask_pays]
    match_now = df_pays[df_pays['name_1'].astype(str).str.lower().str.contains(region_finale.lower().strip(), na=False)]
    
    mask_pays_fut = df_futur['name_0'].astype(str).str.lower().str.contains(pays.lower().strip(), na=False)
    df_pays_fut = df_futur[mask_pays_fut]
    match_fut = df_pays_fut[df_pays_fut['name_1'].astype(str).str.lower().str.contains(region_finale.lower().strip(), na=False)]

    return {
        "ent": "N/A", "ville": ville, "pays": pays, "region": region_finale,
        "lat": loc.latitude, "lon": loc.longitude,
        "s25": match_now['score'].mean() if not match_now.empty else 0,
        "s30": match_fut['score'].mean() if not match_fut.empty else 0,
        "found": not match_now.empty
    }

# --- 4. GÉNÉRATEUR PDF ---
def create_pdf(data_dict, analysis_text):
    def clean(t):
        t = str(t).replace("✅", "[OK]").replace("⚠️", "[WARN]").replace("🚨", "[ALERT]").replace("ℹ️", "[INFO]")
        t = t.replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("…", "...")
        return t.encode('latin-1', 'replace').decode('latin-1')

    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, clean(f"RAPPORT AQUARISK: {data_dict['ent'].upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    # Data
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, clean(f"Loc: {data_dict['loc']}"), ln=1)
    pdf.cell(0, 10, f"VaR (Capital a Risque): {data_dict['var']:,.0f} $", ln=1)
    pdf.ln(5)
    
    # Scores
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"Risque Residuel 2025: {data_dict['s25_display']:.2f} / 5", ln=1)
    pdf.cell(0, 10, f"Risque Physique (Base): {data_dict['s25_brut']:.2f} / 5", ln=1)
    pdf.cell(0, 10, f"Projection 2030: {data_dict['s30_display']:.2f} / 5", ln=1)
    pdf.ln(5)
    
    # IA Text
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 8, clean(f"Analyse Stratégique:\n{analysis_text}"))
    
    # News Section
    if 'news' in data_dict and data_dict['news']:
        pdf.ln(10)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Revue de Presse (Dernieres 24h):", ln=1)
        
        for n in data_dict['news']:
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(0, 6, clean(f"- {n['title'][:80]}..."), ln=1)
            
            pdf.set_font("Arial", 'I', 8)
            pdf.set_text_color(100, 100, 100)
            clean_sum = clean(n['summary'])
            pdf.multi_cell(0, 5, f"   {clean_sum}")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)

    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 5. INTERFACE UI ---
tab1, tab2 = st.tabs(["🔍 Audit Live (RSS)", "📂 Import Excel (Masse)"])

# === ONGLET 1 ===
with tab1:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("📡 Paramètres Cible")
        ent = st.text_input("Entreprise", "Tesla")
        v = st.text_input("Ville", "Austin")
        p = st.text_input("Pays", "United States")
        reg = st.text_input("Région (Optionnel)", "Texas")
        cap = st.number_input("Capital Exposé ($)", 10000000)
        
        st.markdown("---")
        notes = st.text_area("Notes manuelles (Optionnel)", height=50)
        
        if st.button("🚀 Lancer l'Audit"):
            with st.spinner("🛰️ Scan Satellite + 📰 Analyse Presse..."):
                res = analyser_site(v, p, reg)
                
                if res and res['found']:
                    # 1. News
                    news = get_company_news(ent)
                    
                    # 2. IA Scoring
                    full_text = notes + " " + " ".join([n['title'] + " " + n['summary'] for n in news])
                    
                    m_pos = ['recycle', 'reduce', 'saving', 'efficient', 'reuse', 'rainwater', 'replenish']
                    m_neg = ['drought', 'shortage', 'conflict', 'pollution', 'fine', 'violation', 'leak']
                    
                    bonus = 0.0
                    txt_ia = "Aucune donnée textuelle pertinente."
                    
                    if len(full_text) > 10:
                        s_pos = sum(1 for w in m_pos if w in full_text.lower())
                        s_neg = sum(1 for w in m_neg if w in full_text.lower())
                        
                        if s_pos > s_neg:
                            bonus = 0.15
                            txt_ia = f"✅ Positif : Stratégie détectée ({s_pos} indices positifs)."
                        elif s_neg > s_pos:
                            bonus = -0.10
                            txt_ia = f"⚠️ Alerte : Presse/Notes négatives ({s_neg} indices négatifs)."
                        else:
                            txt_ia = "ℹ️ Neutre : Pas de signal fort détecté."

                    # 3. Calculs
                    res['ent'] = ent
                    res['s25_brut'] = res['s25']
                    res['s25_display'] = res['s25'] * (1 - bonus)
                    res['s30_display'] = res['s30'] * (1 - bonus)
                    res['var'] = cap * (res['s25_display'] / 5)
                    res['txt_ia'] = txt_ia
                    res['news'] = news
                    
                    st.session_state.audit_unique = res
                    st.rerun()
                else:
                    st.error("❌ Lieu introuvable ou hors couverture WRI.")

    with c2:
        if st.session_state.audit_unique:
            r = st.session_state.audit_unique
            
            st.success(f"Résultats : {r['ent']}")
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Risque Résiduel", f"{r['s25_display']:.2f}/5", delta=f"Base: {r['s25_brut']:.2f}", delta_color="inverse")
            k2.metric("Horizon 2030", f"{r['s30_display']:.2f}/5")
            k3.metric("VaR Financière", f"{r['var']:,.0f} $")
            
            with st.expander("📰 Revue de Presse Automatique", expanded=True):
                st.info(f"🤖 **IA :** {r['txt_ia']}")
                if r['news']:
                    for n in r['news']:
                        st.markdown(f"**[{n['title']}]({n['link']})**")
                        st.caption(f"{n['summary']}")
                        st.divider()
                else:
                    st.write("Aucune news trouvée.")

            # Carte
            m = folium.Map([r['lat'], r['lon']], zoom_start=9, tiles="cartodbpositron")
            folium.Marker([r['lat'], r['lon']], popup=r['ent'], icon=folium.Icon(color="red" if r['s25_display']>3 else "green")).add_to(m)
            st_folium(m, height=300)
            
            # PDF
            pdf_d = {
                'ent': r['ent'], 'loc': f"{r['ville']}, {r['region']}", 'var': r['var'],
                's25_display': r['s25_display'], 's25_brut': r['s25_brut'],
                's30_display': r['s30_display'], 'news': r['news']
            }
            pdf_b = create_pdf(pdf_d, r['txt_ia'])
            st.download_button("📄 Télécharger Rapport PDF", pdf_b, file_name=f"Rapport_{r['ent']}.pdf", mime="application/pdf")

# === ONGLET 2 ===
with tab2:
    st.header("Analyse Excel (Portefeuille)")
    
    df_modele = pd.DataFrame({"Ville": ["Lyon", "Berlin"], "Pays": ["France", "Germany"], "Region_Force": ["", ""]})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df_modele.to_excel(writer, index=False)
    st.download_button("📥 Modèle Excel", data=buffer.getvalue(), file_name="modele.xlsx", mime="application/vnd.ms-excel")
    
    up = st.file_uploader("Upload Excel", type=["xlsx", "csv"])
    
    if up and st.button("Lancer Scan"):
        df_in = pd.read_excel(up) if up.name.endswith('xlsx') else pd.read_csv(up)
        results = []
        bar = st.progress(0)
        
        for i, row in df_in.iterrows():
            rf = row['Region_Force'] if 'Region_Force' in row and pd.notna(row['Region_Force']) else None
            res = analyser_site(row['Ville'], row['Pays'], rf)
            
            if res and res['found']:
                results.append({
                    "Ville": row['Ville'], "Pays": row['Pays'], "Region": res['region'],
                    "Score_2025": res['s25'], "Score_2030": res['s30']
                })
            else:
                results.append({"Ville": row['Ville'], "Score_2025": "Erreur GPS/Data"})
            
            bar.progress((i+1)/len(df_in))
            time.sleep(1)
            
        st.session_state.audit_masse = pd.DataFrame(results)
        st.success("Scan Terminé !")

    if st.session_state.audit_masse is not None:
        df_fin = st.session_state.audit_masse
        st.dataframe(df_fin)
        
        b_out = io.BytesIO()
        with pd.ExcelWriter(b_out, engine='xlsxwriter') as writer:
            df_fin.to_excel(writer, index=False)
        st.download_button("📥 Résultats Excel", b_out, file_name="Resultats.xlsx", mime="application/vnd.ms-excel")
        
