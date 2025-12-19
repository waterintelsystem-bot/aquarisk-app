import streamlit as st
import utils
import pandas as pd
import folium
from streamlit_folium import st_folium
try: from geopy.geocoders import Nominatim
except: pass

utils.init_session()
st.title("🌍 Climat & VaR")

if st.session_state['valo_finale'] == 0:
    st.warning("⚠️ Valo = 0 €. Allez dans Finance d'abord.")

c1, c2 = st.columns(2)
with c1: st.session_state['ville'] = st.text_input("Ville", st.session_state['ville'])
with c2: st.session_state['pays'] = st.text_input("Pays", st.session_state['pays'])

# BOUTON PRINCIPAL
if st.button("⚡ Lancer l'Analyse Climatique", type="primary"):
    with st.spinner("Calculs..."):
        # 1. GPS
        try:
            geo = Nominatim(user_agent="AR_V34")
            loc = geo.geocode(f"{st.session_state['ville']}, {st.session_state['pays']}")
            if loc:
                st.session_state['lat'] = loc.latitude
                st.session_state['lon'] = loc.longitude
        except: pass
        
        # 2. Scores
        s24 = 2.5
        s30 = 3.2 # Simulation aggravation
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        # 3. VaR
        # Extraction pourcentage "Agro (100%)" -> 1.0
        import re
        try:
            vuln_pct = int(re.findall(r'(\d+)%', st.session_state['secteur'])[0]) / 100
        except: vuln_pct = 0.5
        
        delta = s30 - s24
        st.session_state['var_amount'] = st.session_state['valo_finale'] * (delta/5.0) * vuln_pct
        
        # 4. Wiki
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])
        
        st.success("Analyse terminée !")

# DASHBOARD
k1, k2, k3 = st.columns(3)
k1.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5")
k2.metric("Aggravation", f"+{st.session_state['s30']-st.session_state['s24']:.2f}")
k3.metric("Impact Financier (VaR)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

map_col, chart_col = st.columns(2)
with map_col:
    m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=10)
    folium.Marker([st.session_state['lat'], st.session_state['lon']], popup=st.session_state['ent_name']).add_to(m)
    st_folium(m, height=300, use_container_width=True)

with chart_col:
    df = pd.DataFrame({"Année": ["2024", "2030"], "Risque": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
    st.line_chart(df)
    
