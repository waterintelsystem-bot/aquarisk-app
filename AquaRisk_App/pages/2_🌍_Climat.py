import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
from random import randint
from geopy.geocoders import Nominatim

utils.init_session()
st.title("🌍 Climat & Risques")

# Sélecteurs
GEO_DATA = {"France": ["Paris", "Lyon", "Marseille", "Bordeaux", "Autre"], "Monde": ["New York", "Shanghai", "Londres", "Autre"]}

if st.session_state.get('valo_finale', 0) == 0:
    st.error("⚠️ Valo = 0. Complétez l'onglet Finance.")

st.markdown("### 📍 Localisation")
with st.container():
    c1, c2 = st.columns(2)
    p_sel = c1.selectbox("Pays", list(GEO_DATA.keys())+["Autre"], key="p_sel")
    v_sel = c2.selectbox("Ville", GEO_DATA.get(p_sel, ["Autre"]), key="v_sel")
    
    p_final = c1.text_input("Nom Pays", value=st.session_state['pays']) if p_sel == "Autre" else p_sel
    v_final = c2.text_input("Nom Ville", value=st.session_state['ville']) if v_sel == "Autre" else v_sel

if st.button("⚡ ACTUALISER LOCALISATION", type="primary"):
    st.session_state['ville'] = v_final
    st.session_state['pays'] = p_final
    st.session_state['climat_calcule'] = True
    st.session_state['map_id'] += 1 # Force refresh
    
    with st.spinner("Recherche GPS..."):
        try:
            ua = f"AR_{randint(10000,99999)}"
            geo = Nominatim(user_agent=ua, timeout=8)
            loc = geo.geocode(f"{v_final}, {p_final}")
            
            if loc:
                st.session_state['lat'] = loc.latitude
                st.session_state['lon'] = loc.longitude
                st.success(f"GPS Trouvé: {loc.address}")
            else:
                st.warning("Ville introuvable, coordonnées par défaut.")
        except Exception as e: st.error(f"Erreur GPS: {e}")
        
        # Calculs
        s24, s30 = utils.calculate_dynamic_score(st.session_state['lat'], st.session_state['lon'])
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        # VaR
        val = st.session_state.get('valo_finale', 0)
        st.session_state['var_amount'] = val * ((s30 - s24)/5.0) * 0.5
        
        # Data Externe
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])
        st.session_state['news'] = utils.get_company_news(st.session_state['ent_name'])
        st.session_state['weather_info'] = utils.get_weather_data(st.session_state['lat'], st.session_state['lon'])

    st.rerun()

if st.session_state.get('climat_calcule'):
    st.divider()
    k1, k2, k3 = st.columns(3)
    k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
    k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta=f"+{st.session_state['s30']-st.session_state['s24']:.2f}")
    k3.metric("VaR", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

    mc, gc = st.columns(2)
    with mc:
        # CLE UNIQUE = LAT + LON + ID => Impossible de rester bloqué
        ukey = f"map_{st.session_state['lat']}_{st.session_state['lon']}_{st.session_state['map_id']}"
        m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=11)
        folium.Marker([st.session_state['lat'], st.session_state['lon']], icon=folium.Icon(color='red')).add_to(m)
        st_folium(m, height=300, use_container_width=True, key=ukey)
        
    with gc:
        st.line_chart(pd.DataFrame({"A": [st.session_state['s24'], st.session_state['s30']]}, index=["2024","2030"]))
        
