import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
from random import randint
try: from geopy.geocoders import Nominatim
except: pass

utils.init_session()
st.title("🌍 Climat & Risques")

# Vérification Valo
if st.session_state.get('valo_finale', 0) == 0:
    st.error("⚠️ ERREUR : La Valorisation est à 0 €.")
    st.info("Retournez à l'onglet Finance, vérifiez le montant et validez.")
else:
    st.success(f"Dossier en cours : {st.session_state['ent_name']} (Valo: {st.session_state['valo_finale']:,.0f} €)")

# Zone Saisie
c1, c2 = st.columns(2)
new_ville = c1.text_input("Ville", value=st.session_state['ville'])
new_pays = c2.text_input("Pays", value=st.session_state['pays'])

# Bouton Calcul
if st.button("⚡ ACTUALISER LOCALISATION & RISQUE", type="primary"):
    
    st.session_state['ville'] = new_ville
    st.session_state['pays'] = new_pays
    st.session_state['climat_calcule'] = True
    
    with st.spinner("Analyse Géographique & Web..."):
        found = False
        lat, lon = 48.85, 2.35 # Default
        
        # 1. GPS
        try:
            ua = f"AquaRisk_{randint(100,999)}"
            geo = Nominatim(user_agent=ua)
            loc = geo.geocode(f"{new_ville}, {new_pays}", timeout=8)
            if loc:
                lat, lon = loc.latitude, loc.longitude
                st.session_state['lat'] = lat
                st.session_state['lon'] = lon
                st.success(f"📍 GPS Trouvé : {lat:.3f}, {lon:.3f}")
                found = True
            else:
                st.warning("⚠️ Ville introuvable, utilisation des coordonnées par défaut.")
        except: pass
        
        # 2. SCORE DYNAMIQUE (LE FIX EST ICI)
        # On appelle la nouvelle fonction qui utilise Lat/Lon
        s24, s30 = utils.calculate_dynamic_score(lat, lon)
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        # 3. VaR
        vuln = utils.SECTEURS.get(st.session_state.get('secteur'), 0.5)
        delta = s30 - s24
        val = st.session_state.get('valo_finale', 0)
        st.session_state['var_amount'] = val * (delta/5.0) * vuln
        
        # 4. Wiki (Avec User-Agent)
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])

    if found: st.rerun()

# Résultats
if st.session_state.get('climat_calcule'):
    st.divider()
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
    # Affichage dynamique de l'aggravation
    diff = st.session_state['s30'] - st.session_state['s24']
    k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta=f"+{diff:.2f}")
    
    var = st.session_state['var_amount']
    k3.metric("Impact (VaR)", f"-{var:,.0f} €", delta_color="inverse")

    c_map, c_graph = st.columns(2)
    with c_map:
        # Clé dynamique pour forcer le rafraichissement
        map_key = f"map_{st.session_state['lat']}_{st.session_state['lon']}"
        m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=10)
        folium.Marker(
            [st.session_state['lat'], st.session_state['lon']], 
            popup=st.session_state['ent_name'],
            icon=folium.Icon(color="red", icon="warning")
        ).add_to(m)
        st_folium(m, height=300, use_container_width=True, key=map_key)

    with c_graph:
        df = pd.DataFrame({"Année": ["2024", "2030"], "Risque": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
        st.line_chart(df)
        
