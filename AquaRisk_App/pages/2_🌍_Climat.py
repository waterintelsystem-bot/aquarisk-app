import streamlit as st
import utils
import folium
from streamlit_folium import st_folium
import pandas as pd
from random import randint # Pour forcer le rafraichissement
try: from geopy.geocoders import Nominatim
except: pass

# 1. Init Mémoire
utils.init_session()
st.title("🌍 Climat & Risques")

# Vérification Valo
if st.session_state.get('valo_finale', 0) == 0:
    st.warning("⚠️ Aucune valorisation financière. Allez d'abord dans l'onglet Finance.")

# 2. Zone de Saisie
st.markdown("### 📍 Localisation du Site")
c1, c2 = st.columns(2)

# On utilise des clés uniques pour les champs de texte pour éviter les conflits
ville_input = c1.text_input("Ville", value=st.session_state['ville'])
pays_input = c2.text_input("Pays", value=st.session_state['pays'])

# 3. Bouton de Calcul
if st.button("⚡ METTRE À JOUR L'ANALYSE", type="primary"):
    
    # A. Mise à jour des variables
    st.session_state['ville'] = ville_input
    st.session_state['pays'] = pays_input
    st.session_state['climat_calcule'] = True
    
    # B. Géocodage (GPS) avec feedback
    with st.spinner(f"Recherche GPS pour {ville_input}..."):
        found = False
        try:
            # User Agent aléatoire pour éviter le blocage
            ua = f"AquaRisk_User_{randint(1000, 9999)}"
            geo = Nominatim(user_agent=ua)
            loc = geo.geocode(f"{ville_input}, {pays_input}", timeout=10)
            
            if loc:
                st.session_state['lat'] = loc.latitude
                st.session_state['lon'] = loc.longitude
                st.success(f"✅ Position trouvée : {loc.address[:50]}...")
                found = True
            else:
                st.error("❌ Ville introuvable. Vérifiez l'orthographe.")
        except Exception as e:
            st.error(f"Erreur de connexion GPS : {e}")

        # C. Calculs Financiers (Uniquement si GPS trouvé ou pour forcer l'update)
        # Simulation Scores
        st.session_state['s24'] = 2.5
        st.session_state['s30'] = 3.8 # Aggravation forte simulée
        
        # Recalcul VaR
        secteur_str = st.session_state.get('secteur', 'Autre')
        vuln = utils.SECTEURS.get(secteur_str, 0.5)
        
        delta = st.session_state['s30'] - st.session_state['s24']
        val = st.session_state.get('valo_finale', 0)
        st.session_state['var_amount'] = val * (delta/5.0) * vuln
        
        # D. Wiki
        st.session_state['wiki_summary'] = utils.get_wiki_summary(st.session_state['ent_name'])

    # E. RERUN OBLIGATOIRE (Pour rafraîchir la carte tout de suite)
    if found:
        st.rerun()

# 4. Affichage des Résultats
if st.session_state.get('climat_calcule'):
    st.divider()
    
    # KPIs
    k1, k2, k3 = st.columns(3)
    k1.metric("Risque 2024", f"{st.session_state['s24']:.2f}/5")
    k2.metric("Risque 2030", f"{st.session_state['s30']:.2f}/5", delta="+1.3 pts (Aggravation)", delta_color="inverse")
    
    var = st.session_state['var_amount']
    k3.metric("Impact Financier (VaR)", f"-{var:,.0f} €", delta="Perte Potentielle", delta_color="inverse")

    # Carte & Graphique
    c_map, c_graph = st.columns(2)
    
    with c_map:
        st.write(f"**🗺️ Vue Satellite : {st.session_state['ville']}**")
        
        # ASTUCE : La clé 'key' force Streamlit à redessiner la carte si lat/lon change
        map_key = f"map_{st.session_state['lat']}_{st.session_state['lon']}"
        
        m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=12)
        folium.Marker(
            [st.session_state['lat'], st.session_state['lon']], 
            popup=st.session_state['ent_name'],
            tooltip="Siège Social",
            icon=folium.Icon(color="red", icon="info-sign")
        ).add_to(m)
        
        st_folium(m, height=300, use_container_width=True, key=map_key)

    with c_graph:
        st.write("**📉 Trajectoire du Risque**")
        df = pd.DataFrame({
            "Année": ["2024", "2030"],
            "Score Risque": [st.session_state['s24'], st.session_state['s30']]
        }).set_index("Année")
        st.line_chart(df)
        
        if var > 0:
            st.caption("🔴 L'augmentation du risque hydrique menace la valorisation de l'actif.")
        else:
            st.caption("🟢 Risque faible pour le moment.")
            
