import streamlit as st
import utils
import folium
from streamlit_folium import st_folium

utils.init_session()
st.title(f"🌍 Climat : {st.session_state.get('current_site_name', 'Site')}")

# --- 1. LOCALISATION & METEO ---
st.subheader("📍 Coordonnées & Météo")
c1, c2, c3 = st.columns([2, 1, 1])

with c1:
    v = st.text_input("Ville", st.session_state['ville'])
    p = st.text_input("Pays", st.session_state['pays'])
    
    if st.button("🔍 Actualiser GPS"):
        with st.spinner("Recherche satellite..."):
            lat, lon, address = utils.get_gps_coordinates(v, p)
            if lat:
                st.session_state.update({'lat': lat, 'lon': lon, 'ville': v, 'pays': p})
                st.success(f"Trouvé: {address}")
                # Récupération Météo immédiate
                w = utils.get_weather_data(lat, lon)
                st.session_state['weather_info'] = w
            else:
                st.error("Ville introuvable. Essayez une grande ville proche.")

with c2:
    if st.session_state.get('weather_info'):
        w = st.session_state['weather_info']
        st.metric("Température", f"{w['temp']} °C")
        st.caption(f"Vent: {w['wind']} km/h")
    else:
        st.info("Météo indisponible")

with c3:
    if st.session_state.get('weather_info'):
        w = st.session_state['weather_info']
        st.metric("Pluie (24h)", f"{w['rain_today']} mm")

st.divider()

# --- 2. CARTE ---
m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=10)
folium.Marker([st.session_state['lat'], st.session_state['lon']], 
              popup=f"{st.session_state['current_site_name']}\n{st.session_state['ville']}", 
              icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)
st_folium(m, height=350, use_container_width=True, key=f"map_{st.session_state['lat']}")
