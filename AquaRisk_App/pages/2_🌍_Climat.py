import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
try:
    from geopy.geocoders import Nominatim
except: pass

st.title("🌍 Climat & Risques Physiques")

if st.session_state['valo_finale'] == 0:
    st.warning("⚠️ Attention : Aucune valorisation financière détectée. Allez d'abord dans l'onglet 'Finance'.")

c1, c2 = st.columns(2)
with c1: st.session_state['ville'] = st.text_input("Ville du Siège", st.session_state['ville'])
with c2: st.session_state['pays'] = st.text_input("Pays", st.session_state['pays'])

st.markdown("### 📊 Analyse")

if st.button("⚡ Calculer Risques & Trajectoire"):
    # 1. GPS
    try:
        geo = Nominatim(user_agent="AR_V31")
        loc = geo.geocode(f"{st.session_state['ville']}, {st.session_state['pays']}")
        if loc: 
            st.session_state['lat'] = loc.latitude
            st.session_state['lon'] = loc.longitude
    except: pass
    
    # 2. Score
    s24 = 2.5
    s30 = s24 * 1.25 # Simulation WRI
    st.session_state['s24'] = s24
    st.session_state['s30'] = s30
    
    # 3. VaR avec Secteur
    vuln = utils.SECTEURS.get(st.session_state['secteur'], 0.5)
    delta = s30 - s24
    st.session_state['var_amount'] = st.session_state['valo_finale'] * (delta/5.0) * vuln
    
    # 4. Intelligence
    wiki, news = utils.get_company_intelligence(st.session_state['ent_name'])
    st.session_state['wiki_summary'] = wiki
    st.session_state['news'] = news
    
    st.success("Calculs terminés.")

# VISUALISATION
k1, k2, k3 = st.columns(3)
k1.metric("Risque Eau 2024", f"{st.session_state['s24']:.2f}/5")
k2.metric("Risque Eau 2030", f"{st.session_state['s30']:.2f}/5", delta="Aggravation", delta_color="inverse")
k3.metric("Impact Financier (VaR)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

c_map, c_chart = st.columns(2)

with c_map:
    st.write("**Localisation du site analysé**")
    m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=10)
    folium.Marker([st.session_state['lat'], st.session_state['lon']], popup=st.session_state['ent_name']).add_to(m)
    st_folium(m, height=300, use_container_width=True)

with c_chart:
    st.write("**Trajectoire de dégradation (2024-2030)**")
    df_chart = pd.DataFrame({"Année": ["2024", "2030"], "Score": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
    st.line_chart(df_chart)
    st.caption(f"Impact calculé selon la vulnérabilité du secteur : {st.session_state['secteur']} ({utils.SECTEURS.get(st.session_state['secteur'])*100}%)")
    
