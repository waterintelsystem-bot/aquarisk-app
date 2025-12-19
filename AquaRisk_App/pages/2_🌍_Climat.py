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

# Vérification Finance
if st.session_state.get('valo_finale', 0) == 0:
    st.error("⚠️ Valo = 0 €. Allez dans l'onglet Finance.")
else:
    st.info(f"Analyse : {st.session_state['ent_name']} ({st.session_state['valo_finale']:,.0f} €)")

# Saisie Ville
c1, c2 = st.columns(2)
# On utilise des clés uniques pour que le champ soit indépendant
new_ville = c1.text_input("Ville", value=st.session_state['ville'], key="input_ville")
new_pays = c2.text_input("Pays", value=st.session_state['pays'], key="input_pays")

# BOUTON QUI DECLENCHE TOUT
if st.button("⚡ ACTUALISER DONNEES & CARTE", type="primary"):
    
    # 1. Incrémenter l'ID pour forcer la nouvelle carte
    st.session_state['map_id'] = st.session_state.get('map_id', 0) + 1
    
    # 2. Sauvegarde des inputs
    st.session_state['ville'] = new_ville
    st.session_state['pays'] = new_pays
    st.session_state['climat_calcule'] = True
    
    with st.spinner("Mise à jour GPS & Scores..."):
        # A. GPS
        found = False
        lat, lon = 48.85, 2.35 # Paris défaut
        try:
            ua = f"AR_{randint(1000,9999)}"
            geo = Nominatim(user_agent=ua)
            loc = geo.geocode(f"{new_ville}, {new_pays}", timeout=8)
            if loc:
                lat, lon = loc.latitude, loc.longitude
                st.session_state['lat'] = lat
                st.session_state['lon'] = lon
                found = True
                st.success(f"📍 GPS OK : {lat:.4f}, {lon:.4f}")
            else:
                st.warning("GPS Introuvable (Carte centrée sur Paris)")
        except: pass
        
        # B. SCORES DYNAMIQUES
        # On appelle la fonction de utils qui était manquante avant
        s24, s30 = utils.calculate_dynamic_score(lat, lon)
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        # C. VAR (Impact Financier)
        try:
            secteur_txt = st.session_state.get('secteur', '')
            import re
            match = re.search(r'\((\d+)%\)', secteur_txt)
            vuln = int(match.group(1))/100.0 if match else 0.5
        except: vuln = 0.5
        
        val = st.session_state.get('valo_finale', 0)
        st.session_state['var_amount'] = val * ((s30 - s24)/5.0) * vuln
        
        # D. WIKI
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])

    # 3. RECHARGEMENT FORCE DE LA PAGE
    if found:
        st.rerun()

# AFFICHAGE RESULTATS
if st.session_state.get('climat_calcule'):
    st.divider()
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
    k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta=f"+{st.session_state['s30']-st.session_state['s24']:.2f}")
    k3.metric("VaR (Impact)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

    map_col, graph_col = st.columns(2)
    
    with map_col:
        # L'ASTUCE EST ICI : key=...map_id
        # Si map_id change, Streamlit jette la vieille carte et en fait une neuve
        unique_key = f"map_render_{st.session_state['map_id']}"
        
        m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=11)
        folium.Marker(
            [st.session_state['lat'], st.session_state['lon']], 
            popup=st.session_state['ent_name'],
            icon=folium.Icon(color='red', icon='warning')
        ).add_to(m)
        st_folium(m, height=300, use_container_width=True, key=unique_key)
        
    with graph_col:
        df = pd.DataFrame({"Année": ["2024", "2030"], "Risque": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
        st.line_chart(df)
        
