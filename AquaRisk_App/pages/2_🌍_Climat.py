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
    st.warning("⚠️ Valorisation à 0 €. Pensez à compléter l'onglet Finance.")

# --- SAISIE (Variables locales temporaires) ---
c1, c2 = st.columns(2)
# On pré-remplit avec la mémoire, mais on laisse l'utilisateur modifier 'new_ville'
new_ville = c1.text_input("Ville du Siège", value=st.session_state['ville'])
new_pays = c2.text_input("Pays", value=st.session_state['pays'])

st.markdown("### 📊 Analyse")

# --- BOUTON CALCUL (Met à jour la mémoire) ---
if st.button("⚡ CALCULER & ACTUALISER CARTE", type="primary"):
    
    # 1. MISE A JOUR MEMOIRE FORCEE
    st.session_state['ville'] = new_ville
    st.session_state['pays'] = new_pays
    st.session_state['climat_calcule'] = True
    
    with st.spinner(f"Analyse pour {new_ville}..."):
        # 2. GPS
        try:
            geo = Nominatim(user_agent=f"AR_Final_{utils.datetime.now().second}")
            loc = geo.geocode(f"{new_ville}, {new_pays}", timeout=5)
            if loc:
                st.session_state['lat'] = loc.latitude
                st.session_state['lon'] = loc.longitude
            else:
                st.error("Ville introuvable. Coordonnées par défaut utilisées.")
        except: pass
        
        # 3. Scores & VaR
        s24 = 2.5
        s30 = 3.5 # Aggravation simulée
        st.session_state['s24'] = s24
        st.session_state['s30'] = s30
        
        vuln = utils.SECTEURS.get(st.session_state['secteur'], 0.5)
        delta = s30 - s24
        st.session_state['var_amount'] = st.session_state['valo_finale'] * (delta/5.0) * vuln
        
        # 4. Wiki
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])
        
    st.rerun() # RECHARGEMENT OBLIGATOIRE POUR AFFICHER LES NOUVELLES VALEURS

# --- AFFICHAGE ---
if st.session_state.get('climat_calcule'):
    
    # Messages
    var = st.session_state['var_amount']
    if var > 0: st.error(f"🔴 ALERTE : Perte potentielle de {var:,.0f} €")
    else: st.success("🟢 Risque financier limité.")

    k1, k2, k3 = st.columns(3)
    k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
    k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta="Aggravation")
    k3.metric("VaR (Impact)", f"-{var:,.0f} €", delta_color="inverse")

    map_col, chart_col = st.columns(2)
    
    with map_col:
        st.write(f"**📍 Localisation : {st.session_state['ville']}**")
        m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=12)
        folium.Marker(
            [st.session_state['lat'], st.session_state['lon']], 
            popup=st.session_state['ent_name'],
            icon=folium.Icon(color='red', icon='info-sign')
        ).add_to(m)
        st_folium(m, height=300, use_container_width=True)

    with chart_col:
        st.write("**📈 Trajectoire**")
        df = pd.DataFrame({"Année": ["2024", "2030"], "Score": [st.session_state['s24'], st.session_state['s30']]}).set_index("Année")
        st.line_chart(df)
        
