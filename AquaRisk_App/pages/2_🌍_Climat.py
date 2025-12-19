import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
from random import randint
# IMPORT CRUCIAL CORRIGÉ (Plus de try/except qui cachent les erreurs)
from geopy.geocoders import Nominatim 
from geopy.exc import GeocoderTimedOut

# --- 1. CONFIGURATION ---
utils.init_session()
st.title("🌍 Climat & Risques")

# Base de données simple pour faciliter la saisie
GEO_DATA = {
    "France": ["Paris", "Lyon", "Marseille", "Bordeaux", "Lille", "Toulouse", "Nantes", "Strasbourg", "Autre"],
    "États-Unis": ["New York", "Los Angeles", "Chicago", "Houston", "Miami", "San Francisco", "Autre"],
    "Allemagne": ["Berlin", "Munich", "Hambourg", "Francfort", "Autre"],
    "Royaume-Uni": ["Londres", "Manchester", "Liverpool", "Édimbourg", "Autre"],
    "Chine": ["Shanghai", "Pékin", "Shenzhen", "Hong Kong", "Autre"],
    "Inde": ["Mumbai", "Delhi", "Bangalore", "Autre"],
    "Brésil": ["São Paulo", "Rio de Janeiro", "Brasilia", "Autre"],
    "Autre Pays": ["Autre"]
}

if st.session_state.get('valo_finale', 0) == 0:
    st.warning("⚠️ Valorisation à 0 €. Pensez à compléter l'onglet Finance.")
else:
    st.info(f"Analyse pour : {st.session_state['ent_name']} ({st.session_state['valo_finale']:,.0f} €)")

# --- 2. FORMULAIRE DE LOCALISATION ---
st.markdown("### 📍 Localisation du Site Industriel")

with st.container():
    c1, c2 = st.columns(2)
    with c1:
        pays_select = st.selectbox("Pays", list(GEO_DATA.keys()))
        pays_final = st.text_input("Nom du Pays", value="Italie") if pays_select == "Autre Pays" else pays_select

    with c2:
        villes_dispo = GEO_DATA.get(pays_select, ["Autre"])
        ville_select = st.selectbox("Ville / Région", villes_dispo)
        ville_final = st.text_input("Nom de la Ville", value="") if ville_select == "Autre" else ville_select

# --- 3. BOUTON D'ACTION ---
if st.button("⚡ ACTUALISER LOCALISATION & RISQUE", type="primary"):
    
    # 1. Mise à jour de la mémoire (Nom de la ville)
    st.session_state['ville'] = ville_final
    st.session_state['pays'] = pays_final
    st.session_state['climat_calcule'] = True
    
    # 2. Force le redessin de la carte
    st.session_state['map_id'] = st.session_state.get('map_id', 0) + 1
    
    with st.spinner(f"Recherche GPS pour {ville_final} ({pays_final})..."):
        found = False
        try:
            # User-Agent aléatoire pour éviter le blocage (Erreur 403)
            ua = f"AquaRisk_User_{randint(10000,99999)}"
            geo = Nominatim(user_agent=ua, timeout=10)
            
            # Recherche GPS
            query = f"{ville_final}, {pays_final}"
            loc = geo.geocode(query)
            
            if loc:
                st.session_state['lat'] = loc.latitude
                st.session_state['lon'] = loc.longitude
                found = True
                st.success(f"✅ GPS Trouvé : {loc.address}")
            else:
                st.error(f"❌ Ville introuvable : '{query}'. Coordonnées par défaut (Paris) utilisées.")
                # On ne change PAS lat/lon si on ne trouve pas, pour éviter de tout casser
                
        except Exception as e:
            st.error(f"Erreur Technique GPS : {e}")

        # 3. Calculs des Scores (Doit se faire APRES la mise à jour GPS)
        # C'est ici que les chiffres 2.92 / 3.50 vont enfin changer !
        s24, s30 = utils.calculate_dynamic_score(st.session_state['lat'], st.session_state['lon'])
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        # 4. Calcul VaR
        try:
            s_txt = st.session_state.get('secteur', '')
            import re
            match = re.search(r'\((\d+)%\)', s_txt)
            vuln = int(match.group(1))/100.0 if match else 0.5
        except: vuln = 0.5
        
        val = st.session_state.get('valo_finale', 0)
        st.session_state['var_amount'] = val * ((s30 - s24)/5.0) * vuln
        
        # 5. Wiki
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])

    # Rafraîchissement immédiat de la page
    if found: st.rerun()

# --- 4. AFFICHAGE RESULTATS ---
if st.session_state.get('climat_calcule'):
    st.divider()
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
    # Le delta montre la différence exacte entre le nouveau score et l'ancien
    k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta=f"+{st.session_state['s30']-st.session_state['s24']:.2f}")
    k3.metric("VaR (Impact)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

    map_col, graph_col = st.columns(2)
    
    with map_col:
        # Clé unique pour forcer le nettoyage de la carte
        unique_key = f"map_{st.session_state['ville']}_{st.session_state['map_id']}"
        
        m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=10)
        folium.Marker(
            [st.session_state['lat'], st.session_state['lon']], 
            popup=f"{st.session_state['ent_name']}\n{st.session_state['ville']}",
            icon=folium.Icon(color='red', icon='info-sign')
        ).add_to(m)
        st_folium(m, height=300, use_container_width=True, key=unique_key)
        
    with graph_col:
        df = pd.DataFrame({"Année": ["2024", "2030"], "Risque": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
        st.line_chart(df)
        
