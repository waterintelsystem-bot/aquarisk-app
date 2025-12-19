import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
from random import randint
try: from geopy.geocoders import Nominatim
except: pass

# --- 1. CONFIGURATION ---
utils.init_session()
st.title("🌍 Climat & Risques")

# Base de données simplifiée pour les menus déroulants
# Vous pourrez l'enrichir plus tard ou la mettre dans utils.py
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

# On utilise un conteneur pour que l'interface soit propre
with st.container():
    c1, c2 = st.columns(2)
    
    with c1:
        # Choix du PAYS
        pays_select = st.selectbox(
            "Pays", 
            options=list(GEO_DATA.keys()),
            index=0 if "France" in GEO_DATA else 0
        )
        # Si "Autre Pays", on affiche un champ texte
        if pays_select == "Autre Pays":
            pays_final = st.text_input("Saisir le Pays", value="Italie")
        else:
            pays_final = pays_select

    with c2:
        # Choix de la VILLE (dépend du pays)
        villes_dispo = GEO_DATA.get(pays_select, ["Autre"])
        ville_select = st.selectbox("Ville / Région", options=villes_dispo)
        
        # Si "Autre", on affiche un champ texte
        if ville_select == "Autre":
            ville_final = st.text_input("Saisir la Ville précise", value="")
        else:
            ville_final = ville_select

# --- 3. BOUTON D'ACTION ---
if st.button("⚡ ACTUALISER LOCALISATION & RISQUE", type="primary"):
    
    # Vérification saisie
    if not ville_final or not pays_final:
        st.error("Veuillez renseigner une ville et un pays.")
    else:
        # 1. Update Mémoire
        st.session_state['ville'] = ville_final
        st.session_state['pays'] = pays_final
        st.session_state['climat_calcule'] = True
        
        # 2. Incrémenter ID pour forcer le redraw carte
        st.session_state['map_id'] = st.session_state.get('map_id', 0) + 1
        
        with st.spinner(f"Recherche GPS pour {ville_final} ({pays_final})..."):
            found = False
            try:
                # User-Agent aléatoire pour éviter blocage
                ua = f"AquaRisk_Geo_{randint(1000,9999)}"
                geo = Nominatim(user_agent=ua)
                
                # Recherche précise : "Ville, Pays"
                query = f"{ville_final}, {pays_final}"
                loc = geo.geocode(query, timeout=10)
                
                if loc:
                    st.session_state['lat'] = loc.latitude
                    st.session_state['lon'] = loc.longitude
                    found = True
                    st.success(f"✅ GPS Trouvé : {loc.address}")
                else:
                    st.error(f"❌ Ville introuvable : '{query}'. Essayez une grande ville proche.")
                    # Fallback Paris pour ne pas crasher
                    st.session_state['lat'] = 48.8566
                    st.session_state['lon'] = 2.3522
            except Exception as e:
                st.error(f"Erreur Connexion GPS : {e}")

            # 3. Calculs Financiers (Même si GPS échoue, on calcule les risques)
            # Scores dynamiques basés sur la latitude trouvée (ou défaut)
            s24, s30 = utils.calculate_dynamic_score(st.session_state['lat'], st.session_state['lon'])
            st.session_state['s24'] = s24
            st.session_state['s30'] = s30
            
            # VaR
            try:
                s_txt = st.session_state.get('secteur', '')
                import re
                match = re.search(r'\((\d+)%\)', s_txt)
                vuln = int(match.group(1))/100.0 if match else 0.5
            except: vuln = 0.5
            
            val = st.session_state.get('valo_finale', 0)
            st.session_state['var_amount'] = val * ((s30 - s24)/5.0) * vuln
            
            # Wiki
            st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])

        # 4. Rerun immédiat pour afficher la nouvelle carte
        if found: st.rerun()

# --- 4. AFFICHAGE RESULTATS ---
if st.session_state.get('climat_calcule'):
    st.divider()
    
    # KPIs
    k1, k2, k3 = st.columns(3)
    k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
    k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta=f"+{st.session_state['s30']-st.session_state['s24']:.2f}")
    k3.metric("VaR (Impact)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

    map_col, graph_col = st.columns(2)
    
    with map_col:
        # L'ASTUCE ULTIME : La clé dépend du NOM DE LA VILLE + ID
        # Dès que le nom change, la carte est neuve.
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
        
