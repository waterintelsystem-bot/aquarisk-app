import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
try: from geopy.geocoders import Nominatim
except: pass

utils.init_session()
st.title("🌍 Climat & Risques")

if st.session_state['valo_finale'] == 0:
    st.warning("⚠️ Valo = 0 €. Allez dans Finance d'abord.")

c1, c2 = st.columns(2)
# Utilisation de clé unique pour forcer le rafraichissement si besoin
with c1: new_ville = st.text_input("Ville du Siège", st.session_state['ville'])
with c2: new_pays = st.text_input("Pays", st.session_state['pays'])

# --- BOUTON DE CALCUL ---
if st.button("⚡ CALCULER RISQUES & CARTE", type="primary"):
    st.session_state['ville'] = new_ville
    st.session_state['pays'] = new_pays
    st.session_state['climat_calcule'] = True
    
    with st.spinner("Analyse en cours..."):
        # 1. GPS
        try:
            geo = Nominatim(user_agent="AR_V35")
            loc = geo.geocode(f"{new_ville}, {new_pays}")
            if loc:
                st.session_state['lat'] = loc.latitude
                st.session_state['lon'] = loc.longitude
        except: pass
        
        # 2. Scores
        s24 = 2.5
        s30 = 3.5 # Simulation
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        # 3. VaR
        vuln = utils.SECTEURS.get(st.session_state['secteur'], 0.5)
        delta = s30 - s24
        st.session_state['var_amount'] = st.session_state['valo_finale'] * (delta/5.0) * vuln
        
        # 4. Wiki
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])

# --- AFFICHAGE RESULTATS ---
if st.session_state.get('climat_calcule'):
    st.markdown("### 📊 Résultats")
    
    # Explication VaR
    var = st.session_state['var_amount']
    if var > 0:
        msg_var = "🔴 IMPACT FORT : Perte de valeur significative à prévoir."
    else:
        msg_var = "🟢 IMPACT FAIBLE : Risque maîtrisé."
    st.caption(msg_var)

    k1, k2, k3 = st.columns(3)
    k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
    k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta="Aggravation", delta_color="inverse")
    k3.metric("VaR (Impact Financier)", f"-{var:,.0f} €", delta_color="inverse")

    map_col, chart_col = st.columns(2)
    with map_col:
        st.write(f"**Localisation : {st.session_state['ville']}**")
        # Astuce : Re-créer la map à chaque fois pour forcer le centrage
        m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=12)
        folium.Marker(
            [st.session_state['lat'], st.session_state['lon']], 
            popup=st.session_state['ent_name'],
            icon=folium.Icon(color='red', icon='info-sign')
        ).add_to(m)
        st_folium(m, height=300, use_container_width=True)

    with chart_col:
        st.write("**Courbe de Risque**")
        df = pd.DataFrame({"Année": ["2024", "2030"], "Score": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
        st.line_chart(df)
        
