import streamlit as st
import utils

# --- OBLIGATOIRE ---
utils.init_session()

st.title("📑 Rapport & Sources")

st.markdown("### 1. Intelligence Artificielle")
st.info(f"Source : Wikipedia & Web")
st.write(st.session_state.get('wiki_summary', 'Pas de données.'))

st.markdown("### 2. Sources Détectées")
# Utilisation de .get() pour éviter le KeyError si 'news' n'existe pas
news = st.session_state.get('news', [])
if news:
    for n in news:
        st.write(f"🔗 [{n['title']}]({n['link']})")
else:
    st.warning("Aucune actualité récente trouvée.")

st.markdown("---")
st.markdown("### 3. Exports")

c1, c2 = st.columns(2)
with c1:
    if st.button("Générer PDF Complet"):
        pdf_data = utils.generate_pdf_report(st.session_state)
        st.download_button("📥 Télécharger PDF", data=pdf_data, file_name="Rapport.pdf", mime="application/pdf")

with c2:
    if st.button("Générer Excel Data"):
        xls_data = utils.generate_excel(st.session_state)
        st.download_button("📊 Télécharger Excel", data=xls_data, file_name="Data.xlsx")
        
