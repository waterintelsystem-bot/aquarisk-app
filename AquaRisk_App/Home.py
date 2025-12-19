import streamlit as st
import utils

st.set_page_config(page_title="AquaRisk V34", page_icon="🏢", layout="wide")

# --- INITIALISATION OBLIGATOIRE ---
utils.init_session()

st.title("🏢 AquaRisk V34 : Portail Audit")
st.success("Système Stable Chargé.")

st.markdown("""
### Guide de Démarrage :
1.  **Finance :** Si Pappers échoue, utilisez l'OCR. Si l'OCR échoue, saisissez à la main.
2.  **Climat :** Cliquez sur "Calculer" pour voir les courbes de risque.
3.  **Rapport :** Générez le PDF à la fin.
""")
