import streamlit as st

st.set_page_config(page_title="AquaRisk V30", page_icon="🏢", layout="wide")

st.title("🏢 AquaRisk V30 : Architecture Modulaire")

# --- INITIALISATION DE LA MEMOIRE (SESSION STATE) ---
# C'est LE secret pour que rien ne disparaisse
defaults = {
    # Identité
    'ent_name': "Nouvelle Entreprise",
    'ville': "Paris", 'pays': "France",
    'secteur': "Agroalimentaire (100%)",
    
    # Finance
    'ca': 0.0, 'res': 0.0, 'cap': 0.0,
    'valo_finale': 0.0, 'mode_valo': "PME",
    
    # Climat
    's24': 2.5, 's26': 2.7, 's30': 3.0,
    'var_amount': 0.0,
    'lat': 48.85, 'lon': 2.35,
    
    # Docs
    'txt_synthese': "",
    'audit_launched': False
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

st.success("✅ Système initialisé. Mémoire sécurisée active.")

st.markdown("""
### Bienvenue dans votre outil d'audit.
Veuillez procéder étape par étape via le menu à gauche :

1.  **💰 Finance :** Importez le bilan (OCR) et calculez la valorisation.
2.  **🌍 Climat :** Visualisez la carte et la trajectoire de risque.
3.  **📑 Rapport :** Téléchargez le dossier final complet.
""")
