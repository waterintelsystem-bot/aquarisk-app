import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
try:
    from geopy.geocoders import Nominatim
except: pass

st.title("🌍 Module Climat & Risques")

c1, c2 = st.columns(2)
with c1: st.session_state['ville'] = st.text_input("Ville", st.session_state['ville'])
with c2: st.session_state['secteur'] = st.selectbox("Secteur", ["Agroalimentaire (100%)", "Industrie (70%)", "Services (10%)"])

if st.button("🔄 Calculer Trajectoires"):
    # 1. Geo
    try:
        geo = Nominatim(user_agent="AR_V30")
        loc = geo.geocode(f"{st.session_state['ville']}, {st.session_state['pays']}")
        if loc: 
            st.session_state['lat'] = loc.latitude
            st.session_state['lon'] = loc.longitude
    except: pass
    
    # 2. Scores
    s24, s26, s30 = utils.get_climate_projections(2.5)
    st.session_state['s24'] = s24
    st.session_state['s30'] = s30
    
    # 3. VaR
    vuln = float(st.session_state['secteur'].split('(')[1][:-2]) / 100
    delta = s30 - s24
    st.session_state['var_amount'] = st.session_state['valo_finale'] * (delta/5.0) * vuln

# AFFICHAGE
k1, k2, k3 = st.columns(3)
k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta="Aggravation", delta_color="inverse")
k3.metric("Impact (VaR)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

# CARTE
m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=10)
folium.Marker([st.session_state['lat'], st.session_state['lon']], popup=st.session_state['ent_name']).add_to(m)
st_folium(m, height=300)

# GRAPHIQUE
chart_data = pd.DataFrame({"Année": ["2024", "2030"], "Risque": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
st.line_chart(chart_data)
