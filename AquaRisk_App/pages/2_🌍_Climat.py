import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
from random import randint
from geopy.geocoders import Nominatim 

utils.init_session()
st.title("🌍 Climat & Risques")

GEO_DATA = {
    "France": ["Paris", "Lyon", "Marseille", "Bordeaux", "Lille", "Toulouse", "Nantes", "Strasbourg", "Autre"],
    "États-Unis": ["New York", "Los Angeles", "Chicago", "Houston", "Miami", "San Francisco", "Autre"],
    "Allemagne": ["Berlin", "Munich", "Hambourg", "Francfort", "Autre"],
    "Royaume-Uni": ["Londres", "Manchester", "Liverpool", "Édimbourg", "Autre"],
    "Chine": ["Shanghai", "Pékin", "Shenzhen", "Hong Kong", "Autre"],
    "Inde": ["Mumbai", "Delhi", "Bangalore", "Autre"],
    "Autre Pays": ["Autre"]
}

if st.session_state.get('valo_finale', 0) == 0:
    st.warning("⚠️ Valorisation à 0 €. Pensez à compléter l'onglet Finance.")
else:
    st.info(f"Analyse pour : {st.session_state['ent_name']} ({st.session_state['valo_finale']:,.0f} €)")

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

if st.button("⚡ ACTUALISER LOCALISATION & RISQUE", type="primary"):
    
    st.session_state['ville'] = ville_final
    st.session_state['pays'] = pays_final
    st.session_state['climat_calcule'] = True
    st.session_state['map_id'] = st.session_state.get('map_id', 0) + 1
    
    with st.spinner(f"Recherche GPS & Données pour {ville_final}..."):
        found = False
        try:
            ua = f"AquaRisk_User_{randint(10000,99999)}"
            geo = Nominatim(user_agent=ua, timeout=10)
            loc = geo.geocode(f"{ville_final}, {pays_final}")
            
            if loc:
                st.session_state['lat'] = loc.latitude
                st.session_state['lon'] = loc.longitude
                found = True
                st.success(f"✅ GPS Trouvé : {loc.address}")
            else:
                st.error("Ville introuvable. Coordonnées par défaut utilisées.")
        except Exception as e: st.error(f"Erreur GPS : {e}")

        # SCORES
        s24, s30 = utils.calculate_dynamic_score(st.session_state['lat'], st.session_state['lon'])
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        # VAR
        try:
            s_txt = st.session_state.get('secteur', '')
            import re
            vuln = int(re.search(r'\((\d+)%\)', s_txt).group(1))/100.0 if re.search(r'\((\d+)%\)', s_txt) else 0.5
        except: vuln = 0.5
        val = st.session_state.get('valo_finale', 0)
        st.session_state['var_amount'] = val * ((s30 - s24)/5.0) * vuln
        
        # DATA EXTERNES (NOUVEAU)
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])
        st.session_state['news'] = utils.get_company_news(st.session_state['ent_name'])
        st.session_state['weather_info'] = utils.get_weather_data(st.session_state['lat'], st.session_state['lon'])

    if found: st.rerun()

if st.session_state.get('climat_calcule'):
    st.divider()
    
    # 1. ONGLETS POUR ORGANISER L'INFO
    tab1, tab2, tab3 = st.tabs(["📊 Risques & Carte", "📰 Sources & Presse", "🌦️ Météo Site"])
    
    with tab1:
        k1, k2, k3 = st.columns(3)
        k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
        k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta=f"+{st.session_state['s30']-st.session_state['s24']:.2f}")
        k3.metric("VaR (Impact)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

        map_col, graph_col = st.columns(2)
        with map_col:
            unique_key = f"map_{st.session_state['ville']}_{st.session_state['map_id']}"
            m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=10)
            folium.Marker([st.session_state['lat'], st.session_state['lon']], icon=folium.Icon(color='red')).add_to(m)
            st_folium(m, height=300, use_container_width=True, key=unique_key)
        with graph_col:
            df = pd.DataFrame({"Année": ["2024", "2030"], "Risque": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
            st.line_chart(df)

    with tab2:
        st.subheader(f"Actualités : {st.session_state['ent_name']}")
        news = st.session_state.get('news', [])
        if news:
            for n in news:
                st.markdown(f"🔗 **[{n['title']}]({n['link']})**")
                st.caption(f"Publié : {n['published']}")
        else:
            st.warning("Aucune actualité trouvée ou erreur de connexion.")
        
        st.divider()
        st.subheader("Contexte Wikipedia")
        st.write(st.session_state.get('wiki_summary'))

    with tab3:
        w = st.session_state.get('weather_info')
        if w:
            c_now, c_forecast = st.columns(2)
            with c_now:
                st.metric("Température Actuelle", f"{w['temp']} °C")
                st.metric("Vitesse Vent", f"{w['wind']} km/h")
            with c_forecast:
                st.write("**Prévisions (3 jours)**")
                for day in w.get('forecast', []):
                    st.write(f"📅 **{day['day']}** : Max {day['temp_max']}°C | 🌧️ {day['rain']}mm")
        else:
            st.error("Données météo indisponibles.")
            
