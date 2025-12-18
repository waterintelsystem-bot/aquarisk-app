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
import feedparser  # Pour lire le flux RSS
import urllib.parse # Pour encoder l'URL
import re # Pour nettoyer le HTML des news

# --- CONFIGURATION ---
st.set_page_config(page_title="AquaRisk 4.1 : Live Monitor", page_icon="📡", layout="wide")
st.title("📡 AquaRisk 4.1 : Monitoring Temps Réel")

# --- INITIALISATION MÉMOIRE ---
if 'audit_unique' not in st.session_state: st.session_state.audit_unique = None
if 'audit_masse' not in st.session_state: st.session_state.audit_masse = None

# --- 1. CHARGEMENT DATA (ROBUSTE) ---
@st.cache_data
def load_data():
    def smart_load(filepath):
        # Tente plusieurs séparateurs pour éviter les erreurs CSV
        for sep in [',', ';', '\t']:
            try:
                df = pd.read_csv(filepath, sep=sep, engine='python', on_bad_lines='skip')
                df.columns = [c.lower().strip() for c in df.columns]
                # Vérifie si la lecture semble correcte (plus de 5 colonnes)
                if len(df.columns) > 5 and 'score' in df.columns:
                    # Nettoyage des virgules en points (4,5 -> 4.5)
                    df['score'] = df['score'].astype(str).str.replace(',', '.', regex=False)
                    df['score'] = pd.to_numeric(df['score'], errors='coerce')
                    return df
            except: continue
        return None

    # Chargement Actuel
    df_n = smart_load("risk_actuel.csv")
    if df_n is not None and 'indicator_name' in df_n.columns:
        df_n = df_n[df_n['indicator_name'] == 'bws'].dropna(subset=['score'])

    # Chargement Futur
    df_f = smart_load("risk_futur.csv")
    if df_f is not None and 'year' in df_f.columns:
        mask = (df_f['year'] == 2030) & (df_f['scenario'] == 'bau') & (df_f['indicator_name'] == 'bws')
        df_f = df_f[mask].dropna(subset=['score'])
    
    return df_n, df_f

df_actuel, df_futur = load_data()
if df_actuel is None: st.stop()

# --- 2. FONCTIONS TECH (GPS + NEWS) ---
def get_location_safe(ville, pays):
    # Rotation d'agents pour éviter l'erreur 403
    agents = ["AquaBot_v2", "Student_Project_2025", "Climate_Monitor_Pro"]
    for i in range(3):
        try:
            ua = f"{agents[i%3]}_{randint(100,999)}"
            geolocator = Nominatim(user_agent=ua, timeout=10)
            return geolocator.geocode(f"{ville}, {pays}")
        except: time.sleep(1)
    return None

def get_region_safe(lat, lon):
    try:
        ua = f"Reg_Finder_{randint(100,999)}"
        geolocator = Nominatim(user_agent=ua, timeout=10)
        return geolocator.reverse(f"{lat}, {lon}", language='en')
    except: return None

# --- LE MOTEUR RSS AVEC RÉSUMÉS ---
def get_company_news(company_name):
    # Recherche Google News : Entreprise + Water + Environment
    query = urllib.parse.quote(f"{company_name} water environment")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    
    # Fonction locale pour nettoyer le HTML crado de Google
    def clean_html(raw_html):
        cleanr = re.compile('<.*?>') # Enlève tout ce qui est entre < >
        cleantext = re.sub(cleanr, '', raw_html)
        # Remplace les codes HTML courants
        return cleantext.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    
    try:
        feed = feedparser.parse(rss_url)
        news_items = []
        # On prend les 5 premiers articles
        for entry in feed.entries[:5]:
            # On cherche le résumé, sinon on prend le titre
            raw_summary = entry.summary if 'summary' in entry else entry.title
            clean_summary = clean_html(raw_summary)
            
            # On tronque si c'est trop long pour le PDF
            if len(clean_summary) > 250:
                clean_summary = clean_summary[:250] + "..."
                
            news_items.append({
                "title": entry.title, 
                "link": entry.link, 
                "published": entry.published,
                "summary": clean_summary 
            })
        return news_items
    except:
        return []

# --- 3. MOTEUR ANALYSE DONNÉES ---
def analyser_site(ville, pays, region_forcee=None):
    loc = get_location_safe(ville, pays)
    if not loc: return None
    
    loc_details = get_region_safe(loc.latitude, loc.longitude)
    reg_auto = ""
    if loc_details:
        addr = loc_details.raw['address']
        reg_auto = addr.get('state', addr.get('region', addr.get('county', ''))).strip()
    
    region_finale = region_forcee if region_forcee else reg_auto
    
    # Recherche Data Actuelle
    mask_pays = df_actuel['name_0'].astype(str).str.lower().str.contains(pays.lower().strip(), na=False)
    df_pays = df_actuel[mask_pays]
    match_now = df_pays[df_pays['name_1'].astype(str).str.lower().str.contains(region_finale.lower().strip(), na=False)]
    
    # Recherche Data Future
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

# --- 4. GÉNÉRATEUR PDF (AVEC RÉSUMÉS & CLEANING) ---
def create_pdf(data_dict, analysis_text):
    def clean(t): 
        # Remplace les émojis et caractères spéciaux qui font planter le PDF
        t = str(t).replace("✅", "[OK]").replace("⚠️", "[WARN]").replace("🚨", "[ALERT]").replace("ℹ️", "[INFO]")
        t = t.replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("…", "...")
        return t.encode('latin-1', 'replace').decode('latin-1')

    pdf = FPDF()
    pdf.add_page()
    
    # En-tête
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, clean(f"RAPPORT AQUARISK: {data_dict['ent'].upper()}"), ln=1, align='C')
    pdf.ln(10)
    
    # Infos Clés
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, clean(f"Loc: {data_dict['loc']}"), ln=1)
    pdf.cell(0, 10, f"VaR (Capital a Risque): {data_dict['var']:,.0f} $", ln=1)
    pdf.ln(5)
    
    # Scores
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"Risque Residuel 2025: {data_dict['s25_display']:.2f} / 5", ln=1)
    pdf.cell(0, 10, f"Risque Physique (Brut): {data_dict['s25_brut']:.2f} / 5", ln=1)
    pdf.cell(0, 10, f"Projection 2030: {data_dict['s30_display']:.2f} / 5", ln=1)
    pdf.ln(5)
    
    # Analyse IA
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 8, clean(f"Analyse IA:\n{analysis_text}"))
    
    # SECTION NEWS (Avec Résumés)
    if 'news' in data_dict and data_dict['news']:
        pdf.ln(10)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Revue de Presse (Dernieres 24h):", ln=1)
        
        for n in data_dict['news']:
            # Titre en Gras
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(0, 6, clean(f"- {n['title'][:75]}..."), ln=1)
            
            # Résumé en Italique et Gris
            pdf.set_font("Arial", 'I', 9)
            pdf.set_text_color(100, 100, 100) # Gris
            # On nettoie bien le résumé avant de l'écrire
            summary_clean = clean(n['summary'])
            pdf.multi_cell(0, 5, f"   {summary_clean}")
            
            pdf.set_text_color(0, 0, 0) # Retour au noir pour la suite
            pdf.ln(2)

    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 5. INTERFACE UTILISATEUR ---
tab1, tab2 = st.tabs(["🔍 Audit Live (RSS)", "📂 Import Excel (Masse)"])

# === ONGLET 1 : AUDIT LIVE ===
with tab1:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("📡 Cible")
        ent = st.text_input("Entreprise", "Tesla")
        v = st.text_input("Ville", "Austin")
        p = st.text_input("Pays", "United States")
        reg = st.text_input("Région (Optionnel)", "Texas")
        cap = st.number_input("Capital ($)", 10000000)
        
        st.markdown("---")
        st.caption("Le robot va scanner Google News pour ajuster le score.")
        notes_manuelles = st.text_area("Notes manuelles (Optionnel)", height=50, placeholder="Ex: Plan de réduction annoncé...")
        
        if st.button("🚀 Lancer l'Audit Live"):
            with st.spinner("🛰️ Connexion Satellite + 📰 Analyse Presse..."):
                res = analyser_site(v, p, reg)
                
                if res and res['found']:
                    # 1. RÉCUPÉRATION NEWS + RÉSUMÉS
                    news = get_company_news(ent)
                    
                    # On construit un grand texte avec les titres et les résumés pour l'analyse IA
                    full_text = notes_manuelles + " "
                    for n in news:
                        full_text += f"{n['title']} {n['summary']} "
                    
                    # 2. ANALYSE SÉMANTIQUE (BONUS/MALUS)
                    m_pos = ['recycle', 'reduce', 'saving', 'efficient', 'stewardship', 'reuse', 'rainwater', 'replenish']
                    m_neg = ['drought', 'shortage', 'conflict', 'pollution', 'fine', 'violation', 'protest', 'risk', 'crisis']
                    
                    bonus = 0.0
                    txt_ia = "Aucune news pertinente trouvée."
                    
                    if len(news) > 0 or len(notes_manuelles) > 5:
                        s_pos = sum(1 for w in m_pos if w in full_text.lower())
                        s_neg = sum(1 for w in m_neg if w in full_text.lower())
                        
                        if s_pos > s_neg:
                            bonus = 0.15 # Bonus 15%
                            txt_ia = f"✅ Positif : La presse évoque des solutions ({s_pos} termes positifs détectés)."
                        elif s_neg > s_pos:
                            bonus = -0.10 # Malus 10%
                            txt_ia = f"⚠️ Alerte : Contexte médiatique tendu ({s_neg} termes négatifs détectés)."
                        else:
                            txt_ia = "ℹ️ Neutre : Signaux faibles dans la presse."
                    
                    # 3. CALCULS FINAUX & SAUVEGARDE
                    res['ent'] = ent
                    res['s25_brut'] = res['s25']
                    res['s25_display'] = res['s25'] * (1 - bonus)
                    res['s30_display'] = res['s30'] * (1 - bonus)
                    res['var'] = cap * (res['s25_display'] / 5)
                    res['txt_ia'] = txt_ia
                    res['news'] = news # On garde tout (titre + résumé)
                    
                    st.session_state.audit_unique = res
                    st.rerun()
                else:
                    st.error("Lieu introuvable ou Données WRI manquantes.")

    with c2:
        if st.session_state.audit_unique:
            r = st.session_state.audit_unique
            
            st.success(f"Rapport Live : {r['ent']}")
            
            # KPIs
            k1, k2, k3 = st.columns(3)
            k1.metric("Risque Résiduel", f"{r['s25_display']:.2f}/5", delta=f"Base Physique: {r['s25_brut']:.2f}", delta_color="inverse")
            k2.metric("Projection 2030", f"{r['s30_display']:.2f}/5")
            k3.metric("VaR Financière", f"{r['var']:,.0f} $")
            
            # REVUE DE PRESSE DÉTAILLÉE
            with st.expander("📰 Revue de Presse (Google News & Résumés)", expanded=True):
                st.info(f"🤖 **Analyse Auto :** {r['txt_ia']}")
                if r['news']:
                    for n in r['news']:
                        st.markdown(f"**[{n['title']}]({n['link']})**")
                        st.caption(f"{n['summary']}") # Affiche le résumé en petit
                        st.divider()
                else:
                    st.write("Aucune news récente trouvée.")

            # Carte
            m = folium.Map([r['lat'], r['lon']], zoom_start=9, tiles="cartodbpositron")
            folium.Marker([r['lat'], r['lon']], popup=r['ent'], icon=folium.Icon(color="red" if r['s25_display']>3 else "green")).add_to(m)
            st_folium(m, height=300)
            
            # PDF (Avec la nouvelle fonction qui gère les résumés)
            pdf_d = {
                'ent': r['ent'], 'loc': f"{r['ville']}, {r['region']}", 'var': r['var'], 
                's25_display': r['s25_display'], 's25_brut': r['s25_brut'], 
                's30_display': r['s30_display'], 'news': r['news']
            }
            pdf_b = create_pdf(pdf_d, r['txt_ia'])
            st.download_button("📄 Télécharger PDF (Complet)", pdf_b, file_name=f"Report_{r['ent']}.pdf", mime="application/pdf")

# === ONGLET 2 : IMPORT EXCEL ===
with tab2:
    st.header("Analyse de Masse (Excel)")
    
    # Modèle
    df_modele = pd.DataFrame({"Ville": ["Lyon", "Berlin"], "Pays": ["France", "Germany"], "Region_Force": ["", ""]})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df_modele.to_excel(writer, index=False)
    st.download_button("📥 Télécharger le modèle Excel", data=buffer.getvalue(), file_name="modele.xlsx", mime="application/vnd.ms-excel")
    
    uploaded_file = st.file_uploader("Uploadez votre Excel", type=["xlsx", "csv"])
    
    if uploaded_file and st.button("Lancer le Scan de Masse"):
        df_input = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('xlsx') else pd.read_csv(uploaded_file)
        resultats = []
        barre = st.progress(0)
        
        for i, row in df_input.iterrows():
            reg_f = row['Region_Force'] if 'Region_Force' in row and pd.notna(row['Region_Force']) else None
            res = analyser_site(row['Ville'], row['Pays'], reg_f)
            
            if res and res['found']:
                resultats.append({
                    "Ville": row['Ville'], "Pays": row['Pays'], "Region": res['region'],
                    "Score_2025": res['s25'], "Score_2030": res['s30']
                })
            else:
                resultats.append({"Ville": row['Ville'], "Score_2025": "Erreur GPS/Data"})
            
            barre.progress((i + 1) / len(df_input))
            time.sleep(1)
            
        st.session_state.audit_masse = pd.DataFrame(resultats)
        st.success("Terminé !")

    if st.session_state.audit_masse is not None:
        df_final = st.session_state.audit_masse
        st.dataframe(df_final)
        buffer_out = io.BytesIO()
        with pd.ExcelWriter(buffer_out, engine='xlsxwriter') as writer:
            df_final.to_excel(writer, index=False)
        st.download_button("📥 Télécharger les Résultats (Excel)", data=buffer_out.getvalue(), file_name="Resultats_AquaRisk.xlsx", mime="application/vnd.ms-excel")
        
