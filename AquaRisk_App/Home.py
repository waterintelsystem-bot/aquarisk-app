import streamlit as st
import utils
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim

st.set_page_config(page_title="AquaRisk Portfolio", page_icon="💧", layout="wide")
utils.init_session()
utils.init_db() # Initialise la DB relationnelle

st.title("💧 AquaRisk Portfolio Manager")

# --- MENU LATERAL : GESTION CLIENTS ---
with st.sidebar:
    st.header("🏢 Clients")
    
    # 1. Création Nouveau Client
    with st.expander("Nouveau Client +"):
        new_cl_name = st.text_input("Nom Client")
        new_cl_sec = st.selectbox("Secteur Principal", utils.SECTEURS_LISTE)
        if st.button("Créer Client"):
            cid, msg = utils.create_client(new_cl_name, new_cl_sec)
            if cid: st.success(msg); st.rerun()
            else: st.error(msg)
            
    # 2. Sélection Client
    df_clients = utils.get_clients()
    if not df_clients.empty:
        cl_names = df_clients['name'].tolist()
        selected_client_name = st.selectbox("Sélectionner Client", cl_names, 
                                            index=cl_names.index(st.session_state['current_client_name']) if st.session_state['current_client_name'] in cl_names else 0)
        
        # Mise en mémoire du client actif
        row = df_clients[df_clients['name'] == selected_client_name].iloc[0]
        st.session_state['current_client_id'] = int(row['id'])
        st.session_state['current_client_name'] = row['name']
        st.session_state['ent_name'] = row['name'] # Pour compatibilité autres pages
        st.session_state['secteur'] = row['secteur_activite']
        
        st.info(f"Client Actif : **{row['name']}**")
    else:
        st.warning("Créez votre premier client.")
        st.stop()

# --- CORPS PRINCIPAL : GESTION DES SITES (MULTI-SITES) ---

# Onglets de gestion
tab_sites, tab_global, tab_reports = st.tabs(["🏭 Gestion Sites & Audits", "🌍 Vue Consolidée (Carte)", "📄 Rapports Consolidés"])

with tab_sites:
    c1, c2 = st.columns([1, 2])
    
    with c1:
        st.subheader(f"Ajouter un Site pour {st.session_state['current_client_name']}")
        site_name = st.text_input("Nom du Site (ex: Usine Nord)")
        site_pays = st.text_input("Pays", "France")
        site_ville = st.text_input("Ville", "Lyon")
        site_act = st.selectbox("Activité Spécifique", utils.SECTEURS_LISTE)
        
        if st.button("Ajouter ce Site"):
            # Géocodage auto à la création
            try:
                geolocator = Nominatim(user_agent="AquaRisk_Manager")
                loc = geolocator.geocode(f"{site_ville}, {site_pays}")
                lat, lon = (loc.latitude, loc.longitude) if loc else (0.0, 0.0)
            except: lat, lon = 0.0, 0.0
            
            utils.create_site(st.session_state['current_client_id'], site_name, site_pays, site_ville, lat, lon, site_act)
            st.success(f"Site {site_name} ajouté !")
            st.rerun()

    with c2:
        st.subheader("Sites Existants")
        df_sites = utils.get_sites(st.session_state['current_client_id'])
        
        if not df_sites.empty:
            for index, row in df_sites.iterrows():
                with st.expander(f"🏭 {row['name']} ({row['ville']}, {row['pays']})"):
                    col_info, col_action = st.columns([3, 1])
                    with col_info:
                        st.write(f"**Activité:** {row['activite_specifique']}")
                        st.write(f"**GPS:** {row['lat']}, {row['lon']}")
                    with col_action:
                        if st.button("👉 AUDITER", key=f"btn_{row['id']}"):
                            # CHARGEMENT DU CONTEXTE SITE
                            st.session_state['current_site_id'] = row['id']
                            st.session_state['current_site_name'] = row['name']
                            st.session_state['ville'] = row['ville']
                            st.session_state['pays'] = row['pays']
                            st.session_state['lat'] = row['lat']
                            st.session_state['lon'] = row['lon']
                            st.session_state['secteur'] = row['activite_specifique']
                            st.switch_page("pages/2_🌍_Climat.py") # Redirection directe vers l'analyse
        else:
            st.info("Aucun site enregistré pour ce client.")

with tab_global:
    st.subheader("Vision Portefeuille Global")
    df_all = utils.get_all_sites_consolidated()
    
    if not df_all.empty:
        # Carte Folium avec tous les sites
        m = folium.Map(location=[20, 0], zoom_start=2)
        for i, r in df_all.iterrows():
            if r['lat'] != 0:
                folium.Marker(
                    [r['lat'], r['lon']], 
                    popup=f"{r['Client']} - {r['Site']}",
                    tooltip=r['activite_specifique'],
                    icon=folium.Icon(color="blue", icon="industry", prefix="fa")
                ).add_to(m)
        st_folium(m, width=1000, height=500)
        
        st.dataframe(df_all, use_container_width=True)
    else:
        st.write("Pas encore de sites dans la base.")

with tab_reports:
    st.subheader("Génération de Rapports")
    st.write("Sélectionnez les sites à inclure dans un rapport PDF consolidé.")
    # (Logique de rapport multi-sites à venir dans une prochaine étape)
    st.info("Fonctionnalité en cours de développement (V71).")
  
