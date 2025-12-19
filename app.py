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
try:
    from geopy.geocoders import Nominatim
except: pass

# ==============================================================================
# 1. INITIALISATION & CONFIG
# ==============================================================================
st.set_page_config(page_title="AquaRisk V27.1 : Stable", page_icon="🛡️", layout="wide")
st.title("🛡️ AquaRisk V27.1 : Audit Intégral & Sécurisé")

# Variables de Session (Mémoire)
defaults = {
    'finance_ca': 1000000.0, 'finance_res': 100000.0, 'finance_cap': 200000.0,
    'audit_done': False, 'audit_data': {}, 
    'ocr_log': "", 'lat': 48.8566, 'lon': 2.3522 # Paris par défaut
}
for k, v in defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# ==============================================================================
# 2. MOTEUR OCR "AGGRESSIF"
# ==============================================================================
def clean_number(text_num):
    try:
        clean = text_num.replace(' ', '').replace(')', '').replace('(', '-').replace("'", "").replace('"', "")
        clean = re.sub(r'[^\d,\.-]', '', clean).replace(',', '.')
        if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except: return None

def extract_financials_aggressive(text):
    data = {"ca": 0, "res": 0, "cap": 0, "found": False}
    text_upper = text.upper()
    keywords_map = {
        "ca": ["CHIFFRES D'AFFAIRES", "PRODUITS D'EXPLOITATION", "VENTES"],
        "res": ["RESULTAT NET", "BENEFICE OU PERTE", "RESULTAT DE L'EXERCICE"],
        "cap": ["CAPITAUX PROPRES", "SITUATION NETTE"]
    }
    for metric, keys in keywords_map.items():
        if data[metric] != 0: continue
        for k in keys:
            if k in text_upper:
                idx = text_upper.find(k)
                window = text_upper[idx:idx+400]
                nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', window)
                valid_nums = []
                for n in nums:
                    val = clean_number(n)
                    if val and (abs(val) > 2050 or abs(val) < 1900) and abs(val) > 1000:
                        valid_nums.append(val)
                if valid_nums:
                    if metric == "ca": data["ca"] = max(valid_nums, key=abs)
                    else: data[metric] = valid_nums[0]
                    data["found"] = True
                    break
    return data

def read_pdf(file):
    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for p in pdf.pages[:30]: text += (p.extract_text() or "") + "\n"
    except: pass
    return text

# ==============================================================================
# 3. DONNEES & CALCULS
# ==============================================================================
def get_location(ville, pays):
    try:
        geolocator = Nominatim(user_agent=f"AR_{randint(1,9999)}")
        loc = geolocator.geocode(f"{ville}, {pays}", timeout=3)
        if loc: return loc.latitude, loc.longitude
    except: pass
    return 48.8566, 2.3522 # Fallback Paris

def get_projections_climat(score_actuel):
    s2024 = score_actuel
    s2030 = min(score_actuel * 1.25, 5.0)
    s2026 = s2024 + (s2030 - s2024) * (2/6)
    return s2024, s2026, s2030

# ==============================================================================
# 4. INTERFACE
# ==============================================================================
with st.sidebar:
    st.header("⚙️ Config")
    if st.button("🔄 Nettoyer Mémoire (Reset)"):
        st.session_state.clear()
        st.rerun()

col_settings, col_main = st.columns([1, 2])

with col_settings:
    st.header("1. Saisie & Documents")
    
    ent = st.text_input("Entreprise", "Michel et Augustin")
    ville = st.text_input("Ville", "Issy-les-Moulineaux")
    pays = st.text_input("Pays", "France")
    
    st.markdown("---")
    st.subheader("Import Bilan (Auto)")
    
    uploaded_pdf = st.file_uploader("Glissez le Bilan PDF ici", type=["pdf"])
    
    if uploaded_pdf:
        if st.session_state.ocr_log == "":
            with st.spinner("Lecture des chiffres..."):
                txt = read_pdf(uploaded_pdf)
                fin = extract_financials_aggressive(txt)
                if fin['found']:
                    st.session_state.finance_ca = fin['ca']
                    st.session_state.finance_res = fin['res']
                    st.session_state.finance_cap = fin['cap']
                    st.session_state.ocr_log = "Succès"
                    st.success("✅ Chiffres détectés et remplis !")
                else:
                    st.warning("⚠️ Lecture difficile, remplissez manuellement.")
                    st.session_state.ocr_log = "Echec"

    # CHAMPS MANUELS (MAIS REMPLIS PAR OCR)
    ca = st.number_input("Chiffre d'Affaires (€)", value=st.session_state.finance_ca, key="finance_ca")
    res = st.number_input("Résultat Net (€)", value=st.session_state.finance_res, key="finance_res")
    cap = st.number_input("Capitaux Propres (€)", value=st.session_state.finance_cap, key="finance_cap")
    
    methode = st.selectbox("Méthode Valo", ["Multiple CA", "Multiple EBITDA", "Patrimonial"])
    
    # Calcul Valo en temps réel
    if methode == "Multiple CA":
        mult = st.slider("Multiple", 0.5, 5.0, 1.5)
        valo = ca * mult
    elif methode == "Multiple EBITDA":
        ebitda = res * 1.25 # Approx
        mult = st.slider("Multiple", 3.0, 15.0, 7.0)
        valo = ebitda * mult
    else:
        valo = cap

    st.metric("Valorisation Estimée", f"{valo:,.0f} €")
    
    st.markdown("---")
    if st.button("🚀 LANCER L'ANALYSE COMPLETE", type="primary"):
        with st.spinner("Génération carte et trajectoires..."):
            lat, lon = get_location(ville, pays)
            s24, s26, s30 = get_projections_climat(2.5) # Score de base moyen
            
            delta_score = s30 - s24
            var_value = valo * (delta_score / 5.0) * 0.5
            
            st.session_state.audit_data = {
                "ent": ent, "ville": ville, "valo": valo,
                "s24": s24, "s26": s26, "s30": s30,
                "lat": lat, "lon": lon, "var": var_value,
                "ca": ca, "res": res
            }
            st.session_state.audit_done = True
            st.rerun()

with col_main:
    if st.session_state.audit_done:
        d = st.session_state.audit_data
        
        st.header(f"Rapport d'Audit : {d.get('ent', 'N/A')}")
        
        # 1. KPIs (Sécurisés avec .get)
        k1, k2, k3 = st.columns(3)
        k1.metric("Valorisation Actuelle", f"{d.get('valo',0):,.0f} €")
        
        s30 = d.get('s30', 2.5)
        s24 = d.get('s24', 2.5)
        k2.metric("Risque Eau 2030", f"{s30:.2f}/5", delta=f"+{(s30-s24):.2f}", delta_color="inverse")
        
        var = d.get('var', 0)
        k3.metric("Impact Financier (VaR)", f"-{var:,.0f} €", delta="Perte potentielle", delta_color="inverse")
        
        # 2. ONGLETS
        tab_clim, tab_fin, tab_doc = st.tabs(["🌍 Climat & Carte", "💰 Finance & Détails", "📄 Sources & PDF"])
        
        with tab_clim:
            c_map, c_graph = st.columns([1, 1])
            
            with c_map:
                st.subheader("Localisation")
                lat = d.get('lat', 48.8566)
                lon = d.get('lon', 2.3522)
                m = folium.Map(location=[lat, lon], zoom_start=10)
                folium.Marker([lat, lon], popup=d.get('ent'), icon=folium.Icon(color="red", icon="warning")).add_to(m)
                st_folium(m, height=300, width=400)
            
            with c_graph:
                st.subheader("Trajectoire Risque")
                chart_data = pd.DataFrame({
                    "Année": [2024, 2026, 2030],
                    "Score Risque": [d.get('s24',0), d.get('s26',0), d.get('s30',0)]
                }).set_index("Année")
                st.line_chart(chart_data)

        with tab_fin:
            st.subheader("Analyse Financière")
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                st.write(f"**Chiffre d'Affaires :** {d.get('ca',0):,.0f} €")
                st.write(f"**Résultat Net :** {d.get('res',0):,.0f} €")
            with col_f2:
                if d.get('ca',0) > 0:
                    marge = (d.get('res',0) / d['ca']) * 100
                    st.metric("Marge Nette", f"{marge:.1f} %")

        with tab_doc:
            st.subheader("Export")
            # Génération PDF Simple et Robuste
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", "B", 16)
            pdf.cell(40, 10, f"Audit: {d.get('ent')}")
            pdf.ln(20)
            pdf.set_font("Arial", "", 12)
            pdf.cell(40, 10, f"Valorisation: {d.get('valo',0):,.0f} EUR")
            pdf.ln(10)
            pdf.cell(40, 10, f"Score Risque 2030: {d.get('s30',0):.2f} / 5")
            
            html = pdf.output(dest='S').encode('latin-1', 'replace')
            st.download_button("Télécharger le Rapport PDF", html, file_name="Rapport.pdf")

    else:
        st.info("👈 Importez un PDF à gauche pour voir la magie opérer.")
        st.write("En attente de données...")
        
