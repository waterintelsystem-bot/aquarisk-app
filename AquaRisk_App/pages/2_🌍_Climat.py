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

if st.session_state.get('valo_finale', 0) == 0:
    st.error("⚠️ Valorisation à 0 €. Veuillez compléter l'onglet Finance.")
else:
    st.info(f"Dossier : {st.session_state['ent_name']} ({st.session_state['valo_finale']:,.0f} €)")

# --- FORMULAIRE DE SAISIE (C'EST LE SECRET POUR QUE ÇA MARCHE) ---
# Le formulaire empêche le rechargement intempestif
with st.form("gps_form"):
    c1, c2 = st.columns(2)
    # On initialise avec la valeur mémoire, mais on laisse l'utilisateur changer
    in_ville = c1.text_input("Ville", value=st.session_state['ville'])
    in_pays = c2.text_input("Pays", value=st.session_state['pays'])
    
    submitted = st.form_submit_button("⚡ ACTUALISER LOCALISATION & RISQUES")

if submitted:
    # 1. Mise à jour Mémoire
    st.session_state['ville'] = in_ville
    st.session_state['pays'] = in_pays
    st.session_state['climat_calcule'] = True
    
    # 2. GPS
    found = False
    with st.spinner(f"Recherche GPS pour {in_ville}..."):
        try:
            ua = f"AquaRisk_Agent_{randint(100,99999)}"
            geo = Nominatim(user_agent=ua)
            loc = geo.geocode(f"{in_ville}, {in_pays}", timeout=10)
            if loc:
                st.session_state['lat'] = loc.latitude
                st.session_state['lon'] = loc.longitude
                found = True
                st.success(f"Trouvé: {loc.address}")
            else:
                st.error("Ville introuvable. Essai par défaut (Paris).")
        except Exception as e:
            st.error(f"Erreur GPS : {e}")

        # 3. Calculs
        s24, s30 = utils.calculate_dynamic_score(st.session_state['lat'], st.session_state['lon'])
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        # VaR
        try:
            s_txt = st.session_state.get('secteur', '')
            import re
            vuln = int(re.search(r'\((\d+)%\)', s_txt).group(1))/100.0
        except: vuln = 0.5
        
        val = st.session_state.get('valo_finale', 0)
        st.session_state['var_amount'] = val * ((s30 - s24)/5.0) * vuln
        
        # Wiki
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])

    # 4. Force Redraw Carte
    st.session_state['map_id'] = st.session_state.get('map_id', 0) + 1
    if found: st.rerun()

# --- AFFICHAGE RESULTATS ---
if st.session_state.get('climat_calcule'):
    st.divider()
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
    k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta=f"+{st.session_state['s30']-st.session_state['s24']:.2f}")
    k3.metric("VaR (Impact)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

    map_col, graph_col = st.columns(2)
    with map_col:
        # Clé unique pour forcer le rafraichissement
        unique_key = f"map_{st.session_state['map_id']}"
        m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=11)
        folium.Marker(
            [st.session_state['lat'], st.session_state['lon']], 
            popup=st.session_state['ent_name'],
            icon=folium.Icon(color='red', icon='info-sign')
        ).add_to(m)
        st_folium(m, height=300, use_container_width=True, key=unique_key)
        
    with graph_col:
        df = pd.DataFrame({"Année": ["2024", "2030"], "Risque": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
        st.line_chart(df)
        
