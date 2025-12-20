import streamlit as st
import utils
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim

st.set_page_config(page_title="AquaRisk Manager", page_icon="💧", layout="wide")
utils.init_session()
utils.init_db()

st.title("💧 AquaRisk Portfolio Manager")

# 1. CLIENTS
with st.sidebar:
    st.header("Gestion Clients")
    with st.expander("Nouveau Client +"):
        nc = st.text_input("Nom"); ns = st.selectbox("Secteur", utils.SECTEURS_LISTE)
        if st.button("Créer"): utils.create_client(nc, ns); st.rerun()
    
    df_c = utils.get_clients()
    if not df_c.empty:
        sel = st.selectbox("Client Actif", df_c['name'].tolist())
        row = df_c[df_c['name'] == sel].iloc[0]
        st.session_state['current_client_id'] = int(row['id'])
        st.session_state['current_client_name'] = row['name']
        st.session_state['ent_name'] = row['name']
    else: st.warning("Créez un client.")

# 2. SITES & HISTORIQUE
if st.session_state['current_client_id']:
    t1, t2 = st.tabs(["🏭 Sites & Audits", "🌍 Carte Globale"])
    
    with t1:
        c1, c2 = st.columns([1, 2])
        with c1:
            st.subheader("Ajouter Site")
            sn = st.text_input("Nom Site"); sv = st.text_input("Ville"); sp = st.text_input("Pays")
            if st.button("Ajouter"):
                try: 
                    geo = Nominatim(user_agent="AR_75").geocode(f"{sv}, {sp}")
                    lat, lon = (geo.latitude, geo.longitude) if geo else (0,0)
                except: lat, lon = 0,0
                utils.create_site(st.session_state['current_client_id'], sn, sp, sv, lat, lon, "Usine")
                st.rerun()
        
        with c2:
            st.subheader(f"Sites de {st.session_state['current_client_name']}")
            df_s = utils.get_sites(st.session_state['current_client_id'])
            for i, r in df_s.iterrows():
                with st.expander(f"📍 {r['name']} ({r['ville']})"):
                    # Bouton Auditer
                    if st.button("NOUVEL AUDIT ➡️", key=f"new_{r['id']}"):
                        st.session_state.update({'current_site_id': r['id'], 'current_site_name': r['name'], 'ville': r['ville'], 'pays': r['pays'], 'lat': r['lat'], 'lon': r['lon']})
                        st.switch_page("pages/4_🎯_Risques_360.py")
                    
                    # Historique & Chargement
                    st.caption("Historique des versions :")
                    hist = utils.get_site_history(r['id'])
                    if not hist.empty:
                        for ih, rh in hist.iterrows():
                            c_date, c_score, c_load = st.columns([2, 1, 1])
                            c_date.write(f"📅 {rh['date']}")
                            c_score.write(f"Score: {rh['score_global']:.2f}")
                            if c_load.button("♻️ Charger", key=f"load_{rh['id']}"):
                                if utils.load_audit_to_session(rh['id']):
                                    st.success("Données chargées !")
                                    st.switch_page("pages/4_🎯_Risques_360.py")
                    else: st.write("Aucun audit passé.")

    with t2:
        # Carte simplifiée
        st.write("Carte des sites (Fonctionnelle)")
        
