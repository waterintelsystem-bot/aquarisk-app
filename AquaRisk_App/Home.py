import streamlit as st
import utils
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim

st.set_page_config(page_title="AquaRisk Portfolio", page_icon="💧", layout="wide")
utils.init_session()
utils.init_db()

st.title("💧 AquaRisk Portfolio Manager")

# --- BARRE LATERALE : CLIENTS ---
with st.sidebar:
    st.header("1. Clients")
    with st.expander("Nouveau Client +"):
        new_name = st.text_input("Nom Client")
        new_sec = st.selectbox("Secteur", utils.SECTEURS_LISTE)
        if st.button("Créer"):
            cid, msg = utils.create_client(new_name, new_sec)
            if cid: st.success(msg); st.rerun()
            else: st.error(msg)
    
    df_cl = utils.get_clients()
    if not df_cl.empty:
        cl_list = df_cl['name'].tolist()
        # On essaie de garder la sélection
        idx = 0
        if st.session_state['current_client_name'] in cl_list:
            idx = cl_list.index(st.session_state['current_client_name'])
            
        sel_cl = st.selectbox("Sélectionner Client", cl_list, index=idx)
        
        # Mise en mémoire
        row = df_cl[df_cl['name'] == sel_cl].iloc[0]
        st.session_state['current_client_id'] = int(row['id'])
        st.session_state['current_client_name'] = row['name']
        st.session_state['ent_name'] = row['name'] # Synchro
        
        st.info(f"Client Actif : **{sel_cl}**")
    else:
        st.warning("Commencez par créer un client.")
        st.stop()

# --- GESTION DES SITES ---
t1, t2 = st.tabs(["🏭 Gestion Sites", "🌍 Carte Consolidée"])

with t1:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("Ajouter un Site")
        s_name = st.text_input("Nom Site (ex: Usine Nord)")
        s_ville = st.text_input("Ville", "Lyon")
        s_pays = st.text_input("Pays", "France")
        
        if st.button("Ajouter Site"):
            try:
                geo = Nominatim(user_agent="AR_Manager")
                loc = geo.geocode(f"{s_ville}, {s_pays}")
                lat, lon = (loc.latitude, loc.longitude) if loc else (0.0, 0.0)
            except: lat, lon = 0.0, 0.0
            
            utils.create_site(st.session_state['current_client_id'], s_name, s_pays, s_ville, lat, lon, st.session_state['secteur'])
            st.success("Site ajouté !"); st.rerun()

    with c2:
        st.subheader(f"Sites de {st.session_state['current_client_name']}")
        df_s = utils.get_sites(st.session_state['current_client_id'])
        
        if not df_s.empty:
            for i, r in df_s.iterrows():
                with st.expander(f"🏭 {r['name']} - {r['ville']}"):
                    col_a, col_b = st.columns([3, 1])
                    col_a.write(f"GPS: {r['lat']:.3f}, {r['lon']:.3f}")
                    if col_b.button("AUDITER ➡️", key=f"btn_{r['id']}"):
                        st.session_state['current_site_id'] = r['id']
                        st.session_state['current_site_name'] = r['name']
                        st.session_state['ville'] = r['ville']
                        st.session_state['pays'] = r['pays']
                        st.session_state['lat'] = r['lat']
                        st.session_state['lon'] = r['lon']
                        st.switch_page("pages/4_🎯_Risques_360.py")
        else:
            st.info("Aucun site.")

with t2:
    df_all = utils.get_all_sites_consolidated()
    if not df_all.empty:
        st.dataframe(df_all)
        # Carte simple
        m = folium.Map(location=[20, 0], zoom_start=2)
        for i, r in df_all.iterrows():
            if r['lat'] != 0:
                folium.Marker([r['lat'], r['lon']], popup=f"{r['Client']} - {r['Site']}").add_to(m)
        st_folium(m, width=800, height=400)
        
