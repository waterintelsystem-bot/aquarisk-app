import streamlit as st
import utils

st.set_page_config(page_title="AquaRisk V33", page_icon="🏢", layout="wide")
utils.init_session()

st.title("🏢 AquaRisk V33 : Portail d'Audit Stable")
st.success("Système initialisé et prêt.")
st.markdown("""
### Workflow :
1.  **💰 Finance :** Importez le bilan ou connectez Pappers.
2.  **🌍 Climat :** Visualisez la carte et calculez la VaR.
3.  **📑 Rapport :** Exportez le dossier.
""")
