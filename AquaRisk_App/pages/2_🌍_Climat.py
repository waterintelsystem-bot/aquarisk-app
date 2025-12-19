import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
from random import randint
# IMPORT SÉCURISÉ GEOPY
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

utils.init_session()
st.title("🌍 Climat & Risques")

# Vérification Finance
if st.session_state.get('valo_finale', 0) == 0:
    st.error("⚠️ Valorisation = 0. Allez dans l'onglet Finance mettre un montant.")
else:
    st.info(f"Analyse en cours : {st.session_state['ent_name']} ({st.session_state['valo_finale']:,.0f} €)")

# --- INTERFACE DE SAISIE LIBRE ---
st.markdown("### 📍 Localisation")
st.caption("Utilisez les suggestions ou saisissez manuellement n'importe quelle ville.")

# 1. SUGGESTIONS (Juste pour aider, n'écrase pas si vide)
suggestions = {
    "France": ["Paris", "Lyon", "Marseille", "Bordeaux"],
    "Monde": ["New York", "Shanghai", "Londres", "Dubai", "Sao Paulo", "Tokyo"]
}
col_sugg, col_vide = st.columns(2)
with col_sugg:
    choix_rapide = st.selectbox("Suggestions Rapides (Optionnel)", ["-"] + suggestions["France"] + suggestions["Monde"])

# 2. CHAMPS DE SAISIE LIBRE (Ce sont eux les maitres)
# Si l'utilisateur choisit une suggestion, on pré-remplit, sinon on garde ce qu'il y avait
valeur_ville = choix_rapide if choix_rapide != "-" else st.session_state['ville']
valeur_pays = "France" if choix_rapide in suggestions["France"] else st.session_state['pays']

c1, c2 = st.columns(2)
# Key unique pour éviter les conflits
ville_final = c1.text_input("Ville (Saisie Libre)", value=valeur_ville)
pays_final = c2.text_input("Pays (Saisie Libre)", value=valeur_pays)

# --- BOUTON DE CALCUL (Cerveau Central) ---
if st.button("⚡ ACTUALISER TOUS LES CALCULS", type="primary"):
    
    # A. Mise à jour Mémoire
    st.session_state['ville'] = ville_final
    st.session_state['pays'] = pays_final
    st.session_state['climat_calcule'] = True
    st.session_state['map_id'] += 1 # Force le redessin de la carte
    
    # B. Géocodage (GPS)
    with st.spinner(f"Géolocalisation de {ville_final}..."):
        found = False
        lat, lon = 48.85, 2.35 # Valeur défaut (Paris)
        
        try:
            ua = f"AR_User_{randint(10000,99999)}"
            geo = Nominatim(user_agent=ua, timeout=8)
            # On tente la recherche Ville + Pays
            loc = geo.geocode(f"{ville_final}, {pays_final}")
            
            # Si échec, on tente Ville seule
            if not loc:
                loc = geo.geocode(ville_final)
                
            if loc:
                lat, lon = loc.latitude, loc.longitude
                st.session_state['lat'] = lat
                st.session_state['lon'] = lon
                found = True
                st.success(f"📍 GPS Trouvé : {loc.address}")
            else:
                st.error("❌ Ville introuvable. Vérifiez l'orthographe.")
        except Exception as e:
            st.error(f"Erreur technique GPS : {e}")

        # C. RE-CALCUL OBLIGATOIRE DES SCORES (Avec les nouvelles Lat/Lon)
        # C'est ici que les chiffres vont changer !
        s24, s30 = utils.calculate_dynamic_score(lat, lon)
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        # D. RE-CALCUL VaR
        try:
            s_txt = st.session_state.get('secteur', '')
            import re
            vuln_match = re.search(r'\((\d+)%\)', s_txt)
            vuln = int(vuln_match.group(1))/100.0 if vuln_match else 0.5
        except: vuln = 0.5
        
        val = st.session_state.get('valo_finale', 0)
        # Formule : Valo * (Delta Score / 5) * Vulnérabilité
        st.session_state['var_amount'] = val * ((s30 - s24)/5.0) * vuln
        
        # E. DATA EXTERNE
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])
        st.session_state['news'] = utils.get_company_news(st.session_state['ent_name'])
        st.session_state['weather_info'] = utils.get_weather_data(lat, lon)

    # F. Refresh Page
    if found: st.rerun()

# --- AFFICHAGE ---
if st.session_state.get('climat_calcule'):
    st.divider()
    
    # Onglets
    t1, t2, t3 = st.tabs(["📊 Analyse Risques", "📰 Presse & Wiki", "🌦️ Météo"])
    
    with t1:
        k1, k2, k3 = st.columns(3)
        k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
        k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta=f"+{st.session_state['s30']-st.session_state['s24']:.2f}")
        k3.metric("Impact Financier (VaR)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

        mc, gc = st.columns(2)
        with mc:
            # Clé dynamique unique pour la carte
            ukey = f"map_{st.session_state['lat']}_{st.session_state['lon']}_{st.session_state['map_id']}"
            m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=10)
            folium.Marker([st.session_state['lat'], st.session_state['lon']], icon=folium.Icon(color='red')).add_to(m)
            st_folium(m, height=300, use_container_width=True, key=ukey)
        with gc:
            st.line_chart(pd.DataFrame({"Risque": [st.session_state['s24'], st.session_state['s30']]}, index=["2024", "2030"]))

    with t2:
        st.subheader("Contexte")
        st.write(st.session_state['wiki_summary'])
        st.divider()
        st.subheader("Presse Récente")
        for n in st.session_state['news']:
            st.markdown(f"🔗 [{n['title']}]({n['link']})")

    with t3:
        w = st.session_state['weather_info']
        if w:
            st.metric("Température Actuelle", f"{w.get('temperature')} °C")
            st.metric("Vent", f"{w.get('windspeed')} km/h")
        else: st.warning("Météo indisponible")
            
