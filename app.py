import streamlit as st
import pandas as pd
import numpy as np
import pdfplumber
import re
import os
import requests
import io
import yfinance as yf
from fpdf import FPDF
from datetime import datetime
import folium
from streamlit_folium import st_folium
import xlsxwriter
import feedparser
from random import randint
from thefuzz import process

# On gère l'absence de geopy pour éviter le crash immédiat
try:
    from geopy.geocoders import Nominatim
except ImportError:
    Nominatim = None

# ==============================================================================
# 1. ARCHITECTURE & CONFIGURATION
# ==============================================================================
st.set_page_config(page_title="AquaRisk V30 : Architecture Stable", page_icon="🏢", layout="wide")

# --- CSS POUR STABILISER L'INTERFACE ---
st.markdown("""
    <style>
    .stMetric {background-color: #f0f2f6; padding: 10px; border-radius: 5px;}
    .stAlert {padding: 10px;}
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. LE "COFFRE-FORT" (SESSION STATE MANAGER)
# ==============================================================================
def init_session_state():
    # Définition de toutes les variables nécessaires au fonctionnement
    defaults = {
        # Données Entreprise
        'ent_name': "Michel et Augustin",
        'ville': "Issy-les-Moulineaux",
        'pays': "France",
        'lat': 48.823, 'lon': 2.269,
        'secteur': "Agroalimentaire (100%)",
        
        # Données Financières (Brutes)
        'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'ebitda': 0.0,
        'source_data': "Manuel", # ou "OCR PDF", "Pappers", "Yahoo"
        
        # Données Valo
        'mode_valo': "PME (Non Cotée)",
        'methode_pme': "Multiple CA",
        'multiple': 1.5,
        'valo_finale': 0.0,
        
        # Données Climat
        's24': 2.5, 's26': 2.7, 's30': 3.1,
        'var_amount': 0.0,
        'pluie_90j': "N/A",
        
        # Intelligence & Docs
        'news': [],
        'wiki_summary': "",
        'ocr_log': "",
        'doc_content': "",
        
        # Flags
        'audit_launched': False
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ==============================================================================
# 3. LES MOTEURS LOGIQUES (BACKEND)
# ==============================================================================

class FinancialEngine:
    @staticmethod
    def clean_number(text_num):
        """Nettoie n'importe quel format de nombre (ex: (10 000) -> -10000.0)"""
        if not isinstance(text_num, str): return 0.0
        try:
            clean = text_num.replace(' ', '').replace(')', '').replace('(', '-').replace("'", "").replace('"', "")
            clean = re.sub(r'[^\d,\.-]', '', clean).replace(',', '.')
            if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
            return float(clean)
        except: return 0.0

    @staticmethod
    def run_ocr(file_obj):
        """OCR Robuste : Lit tout et cherche les patterns"""
        stats = {'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'found': False}
        full_text = ""
        
        try:
            with pdfplumber.open(file_obj) as pdf:
                for p in pdf.pages[:30]: 
                    full_text += (p.extract_text() or "") + "\n"
            
            text_upper = full_text.upper()
            patterns = {
                'ca': ["CHIFFRES D'AFFAIRES", "PRODUITS D'EXPLOITATION", "VENTES"],
                'res': ["RESULTAT NET", "BENEFICE OU PERTE", "RESULTAT DE L'EXERCICE"],
                'cap': ["CAPITAUX PROPRES", "SITUATION NETTE"]
            }

            for key, keywords in patterns.items():
                for kw in keywords:
                    if kw in text_upper:
                        idx = text_upper.find(kw)
                        # Fenêtre de recherche large (400 chars après le mot clé)
                        window = text_upper[idx:idx+400] 
                        # Regex pour trouver des nombres isolés
                        nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', window)
                        
                        valid_nums = []
                        for n in nums:
                            val = FinancialEngine.clean_number(n)
                            # Filtre intelligent : on ignore les années (1990-2030) et numéros de page
                            if abs(val) > 2050 or (abs(val) > 500 and abs(val) < 1900):
                                valid_nums.append(val)
                        
                        if valid_nums:
                            # Pour le CA on prend le max, pour le reste le premier pertinent
                            if key == 'ca': stats['ca'] = max(valid_nums, key=abs)
                            else: stats[key] = valid_nums[0]
                            stats['found'] = True
                            break # On passe au pattern suivant
        except Exception as e:
            return stats, f"Erreur OCR: {str(e)}", ""

        return stats, "Succès", full_text

    @staticmethod
    def get_yahoo_data(ticker):
        try:
            tick = yf.Ticker(ticker)
            info = tick.info
            # Fallback fast_info si info est vide
            mcap = info.get('marketCap') or tick.fast_info.get('market_cap')
            return mcap if mcap else 0.0, info.get('shortName', ticker)
        except: return 0.0, "Inconnu"

class ClimateEngine:
    @staticmethod
    def get_coords(ville, pays):
        if Nominatim:
            try:
                geolocator = Nominatim(user_agent=f"AR_V30_{randint(1,10000)}")
                loc = geolocator.geocode(f"{ville}, {pays}", timeout=3)
                if loc: return loc.latitude, loc.longitude
            except: pass
        return 48.8566, 2.3522 # Paris défaut

    @staticmethod
    def get_risk_curve(base_score=2.5):
        # Simulation d'une courbe de risque standard
        s24 = base_score
        s30 = min(s24 * 1.2, 5.0) # +20% en 2030
        s26 = s24 + (s30 - s24) * 0.33
        return s24, s26, s30

class ReportEngine:
    @staticmethod
    def generate_pdf(data):
        pdf = FPDF()
        pdf.add_page()
        
        # En-tête
        pdf.set_font("Arial", 'B', 20)
        pdf.cell(0, 15, f"AUDIT: {data['ent_name']}", ln=1, align='C')
        pdf.ln(10)
        
        # Section 1: Finance
        pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "1. FINANCE & VALORISATION", ln=1)
        pdf.set_font("Arial", '', 11)
        pdf.cell(0, 8, f"Valorisation Retenue: {data['valo_finale']:,.0f} EUR", ln=1)
        pdf.cell(0, 8, f"Methode: {data['mode_valo']} / {data['methode_pme']}", ln=1)
        pdf.cell(0, 8, f"CA: {data['ca']:,.0f} EUR | Res. Net: {data['res']:,.0f} EUR", ln=1)
        pdf.ln(5)
        
        # Section 2: Climat
        pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "2. RISQUE CLIMATIQUE", ln=1)
        pdf.set_font("Arial", '', 11)
        pdf.cell(0, 8, f"Score Risque Eau 2030: {data['s30']:.2f} / 5.00", ln=1)
        pdf.cell(0, 8, f"Evolution 2024-2030: +{data['s30']-data['s24']:.2f} pts", ln=1)
        
        # Section 3: VaR
        pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "3. IMPACT FINANCIER (VAR)", ln=1)
        pdf.set_font("Arial", '', 11)
        txt_var = f"PERTE ESTIMEE 2030: -{abs(data['var_amount']):,.0f} EUR" if data['var_amount'] > 0 else "Pas d'impact significatif"
        pdf.cell(0, 8, txt_var, ln=1)
        
        # Section 4: Sources
        pdf.ln(10)
        pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "4. SOURCES INTELLIGENCE", ln=1)
        pdf.set_font("Arial", '', 10)
        for n in data['news']:
            try:
                title = n['title'].encode('latin-1', 'replace').decode('latin-1')
                pdf.cell(0, 6, f"- {title}", ln=1, link=n['link'])
            except: continue
            
        return pdf.output(dest='S').encode('latin-1', 'replace')

# ==============================================================================
# 4. INTERFACE UTILISATEUR (FRONTEND)
# ==============================================================================

# --- SIDEBAR (PARAMÈTRES GLOBAUX) ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    if st.button("♻️ Réinitialiser l'Audit"):
        st.session_state.clear()
        st.rerun()
    st.info("Version 30.0 Stable\nMode : Expert")

# --- CORPS PRINCIPAL ---
st.subheader(f"Dossier : {st.session_state['ent_name']}")

# TABS POUR ORGANISER L'INFORMATION
tab_input, tab_dashboard, tab_docs = st.tabs(["📝 Saisie & Données", "📊 Dashboard & Climat", "📄 Rapports & Sources"])

# ----------------- TAB 1 : SAISIE -----------------
with tab_input:
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.markdown("### 1. Identité")
        # On met à jour le session_state directement via les clés 'key'
        st.text_input("Nom Entreprise", key="ent_name")
        col_v, col_p = st.columns(2)
        with col_v: st.text_input("Ville", key="ville")
        with col_p: st.text_input("Pays", key="pays")
        
        st.markdown("### 2. Secteur & Vulnérabilité")
        secteurs = ["Agroalimentaire (100%)", "Industrie (70%)", "Energie (60%)", "BTP (40%)", "Services (5%)"]
        st.selectbox("Secteur", options=secteurs, key="secteur")

    with c2:
        st.markdown("### 3. Données Financières")
        mode = st.radio("Mode de saisie", ["PME (Non Cotée)", "Cotée (Bourse)", "Startup"], key="mode_valo", horizontal=True)
        
        if mode == "PME (Non Cotée)":
            # --- ZONE OCR ---
            uploaded = st.file_uploader("Importer Liasse Fiscale (PDF)", type=['pdf'])
            if uploaded:
                if st.button("🧠 Analyser le Bilan"):
                    stats, msg, txt = FinancialEngine.run_ocr(uploaded)
                    if stats['found']:
                        st.session_state['ca'] = stats['ca']
                        st.session_state['res'] = stats['res']
                        st.session_state['cap'] = stats['cap']
                        st.session_state['source_data'] = "OCR PDF"
                        st.session_state['doc_content'] = txt
                        st.success(f"Données extraites : CA {stats['ca']:,.0f}")
                    else:
                        st.error("Lecture difficile. Veuillez saisir manuellement.")
            
            # --- CHAMPS MANUELS (Connectés au State) ---
            st.number_input("Chiffre d'Affaires (€)", key="ca")
            st.number_input("Résultat Net (€)", key="res")
            st.number_input("Capitaux Propres (€)", key="cap")
            
            st.markdown("#### Méthode de Valorisation")
            meth = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "Patrimonial", "DCF Simplifié"], key="methode_pme")
            
            val_calc = 0.0
            if meth == "Multiple CA":
                mult = st.slider("Multiple CA", 0.5, 5.0, 1.5, 0.1)
                val_calc = st.session_state['ca'] * mult
            elif meth == "Multiple EBITDA":
                # Approx Ebitda
                ebitda = st.session_state['res'] * 1.25
                mult = st.slider("Multiple EBITDA", 3.0, 15.0, 7.0, 0.5)
                val_calc = ebitda * mult
            elif meth == "Patrimonial":
                val_calc = st.session_state['cap']
            else: # DCF
                val_calc = st.session_state['res'] * 10 # Simple proxy
            
            st.session_state['valo_finale'] = val_calc
            st.metric("Valorisation Calculée", f"{val_calc:,.0f} €")

        elif mode == "Cotée (Bourse)":
            ticker = st.text_input("Ticker Yahoo (ex: BN.PA)", "BN.PA")
            if st.button("Charger Données Bourse"):
                mcap, name = FinancialEngine.get_yahoo_data(ticker)
                if mcap > 0:
                    st.session_state['valo_finale'] = mcap
                    st.session_state['source_data'] = f"Yahoo ({ticker})"
                    # Estimation CA/Res pour ratios
                    st.session_state['ca'] = mcap * 0.5
                    st.session_state['res'] = mcap * 0.05
                    st.success(f"Société : {name} | Valo : {mcap:,.0f} €")
                else:
                    st.error("Ticker introuvable.")
            st.number_input("Capitalisation (€)", key="valo_finale")

        else: # Startup
            stade = st.selectbox("Stade", ["Pre-Seed", "Seed", "Series A", "Series B"])
            ranges = {"Pre-Seed": 1.5e6, "Seed": 5e6, "Series A": 15e6, "Series B": 50e6}
            val_calc = st.slider("Valorisation (€)", 500000.0, 100000000.0, ranges[stade.split()[0]])
            st.session_state['valo_finale'] = val_calc

# ----------------- TAB 2 : DASHBOARD -----------------
with tab_dashboard:
    if st.button("🚀 ACTUALISER L'AUDIT", type="primary"):
        with st.spinner("Calculs géographiques et risques..."):
            # 1. Geo
            lat, lon = ClimateEngine.get_coords(st.session_state['ville'], st.session_state['pays'])
            st.session_state['lat'] = lat
            st.session_state['lon'] = lon
            
            # 2. Risque
            s24, s26, s30 = ClimateEngine.get_risk_curve()
            st.session_state['s24'] = s24
            st.session_state['s26'] = s26
            st.session_state['s30'] = s30
            
            # 3. VaR
            # Facteur vulnérabilité (Regex pour extraire le %)
            vuln_str = st.session_state['secteur']
            vuln_pct = float(re.findall(r'\d+', vuln_str)[0]) / 100
            
            delta_risk = s30 - s24
            var = st.session_state['valo_finale'] * (delta_risk / 5.0) * vuln_pct
            st.session_state['var_amount'] = var
            
            # 4. News
            try:
                q = urllib.parse.quote(st.session_state['ent_name'])
                f = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
                st.session_state['news'] = [{"title": e.title, "link": e.link} for e in f.entries[:5]]
            except: pass
            
            st.session_state['audit_launched'] = True

    if st.session_state['audit_launched']:
        # KPIs
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Valorisation", f"{st.session_state['valo_finale']:,.0f} €")
        k2.metric("Chiffre d'Affaires", f"{st.session_state['ca']:,.0f} €")
        k3.metric("Risque Eau 2030", f"{st.session_state['s30']:.2f}/5", delta=f"+{st.session_state['s30']-st.session_state['s24']:.2f}", delta_color="inverse")
        k4.metric("Impact (VaR)", f"-{abs(st.session_state['var_amount']):,.0f} €", delta="Perte Potentielle", delta_color="inverse")
        
        st.markdown("---")
        
        # CARTE ET GRAPHIQUE
        col_visu1, col_visu2 = st.columns([1, 1])
        
        with col_visu1:
            st.subheader("📍 Localisation")
            m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=11)
            folium.Marker(
                [st.session_state['lat'], st.session_state['lon']], 
                popup=st.session_state['ent_name'], 
                icon=folium.Icon(color="red", icon="info-sign")
            ).add_to(m)
            st_folium(m, height=350, use_container_width=True)
            
        with col_visu2:
            st.subheader("📈 Évolution du Risque")
            chart_data = pd.DataFrame({
                "Année": ["2024", "2026", "2030"],
                "Risque": [st.session_state['s24'], st.session_state['s26'], st.session_state['s30']]
            }).set_index("Année")
            st.line_chart(chart_data)
            
            st.info(f"Vulnérabilité sectorielle appliquée : {st.session_state['secteur']}")

# ----------------- TAB 3 : RAPPORTS -----------------
with tab_docs:
    if st.session_state['audit_launched']:
        c_pdf, c_xls = st.columns(2)
        
        with c_pdf:
            st.markdown("### Rapport PDF")
            pdf_data = ReportEngine.generate_pdf(st.session_state)
            st.download_button("📄 Télécharger le PDF", pdf_data, file_name="Rapport_Audit.pdf", mime="application/pdf")
            
        with c_xls:
            st.markdown("### Export Excel")
            # Création Excel en mémoire
            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            ws = workbook.add_worksheet()
            data_rows = [
                ["Indicateur", "Valeur"],
                ["Entreprise", st.session_state['ent_name']],
                ["Valorisation", st.session_state['valo_finale']],
                ["CA", st.session_state['ca']],
                ["Score 2030", st.session_state['s30']],
                ["VaR", st.session_state['var_amount']]
            ]
            for i, r in enumerate(data_rows):
                ws.write_row(i, 0, r)
            workbook.close()
            st.download_button("📊 Télécharger Excel", output.getvalue(), file_name="Data.xlsx")
            
        st.markdown("### 📰 Sources Détectées")
        if st.session_state['news']:
            for n in st.session_state['news']:
                st.write(f"- [{n['title']}]({n['link']})")
        else:
            st.write("Pas d'actualités récentes.")
    else:
        st.warning("Veuillez lancer l'audit dans l'onglet 'Dashboard' pour générer les rapports.")

