import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from random import randint

utils.init_session()
st.title(f"🌍 Climat : {st.session_state.get('current_site_name', 'Site')}")

# --- GPS ---
st.subheader("📍 Localisation Site")
c1, c2 = st.columns(2)
ville = c1.text_input("Ville", st.session_state['ville'])
pays = c2.text_input("Pays", st.session_state['pays'])

if st.button("🔍 Actualiser GPS & Météo"):
    try:
        # User-Agent unique pour éviter l'erreur 403
        ua = f"AquaRisk_App_{randint(1000,9999)}"
        geolocator = Nominatim(user_agent=ua)
        loc = geolocator.geocode(f"{ville}, {pays}")
        if loc:
            st.session_state['lat'] = loc.latitude
            st.session_state['lon'] = loc.longitude
            st.session_state['ville'] = ville
            st.session_state['pays'] = pays
            st.success(f"GPS Trouvé: {loc.address}")
            
            # Recalcul scores climatiques
            s24, s30 = utils.calculate_dynamic_score(loc.latitude, loc.longitude)
            st.session_state['s24'] = s24
            st.session_state['s30'] = s30
        else:
            st.warning("Ville introuvable. Coordonnées par défaut.")
    except Exception as e:
        st.error(f"Erreur GPS : {e}")

# --- CARTE ---
m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=10)
folium.Marker([st.session_state['lat'], st.session_state['lon']], popup=st.session_state['current_site_name'], icon=folium.Icon(color="red")).add_to(m)
st_folium(m, height=300, use_container_width=True, key=f"map_{st.session_state['lat']}")

# --- SCORES CLIMATIQUES ---
c_score, c_graph = st.columns(2)
with c_score:
    st.metric("Score Physique 2024", f"{st.session_state.get('s24', 0):.2f}/5")
    st.metric("Projection 2030", f"{st.session_state.get('s30', 0):.2f}/5", delta="Aggravation")
with c_graph:
    st.line_chart({"2024": st.session_state.get('s24'), "2030": st.session_state.get('s30')})
    
