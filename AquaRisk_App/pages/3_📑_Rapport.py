import streamlit as st
import utils

st.title("📑 Rapport & Sources")

st.markdown("### 1. Intelligence Artificielle (Contexte)")
st.info(f"Source : Wikipedia & Web")
st.write(st.session_state.get('wiki_summary', 'Pas de données.'))

st.markdown("### 2. Sources Détectées")
if st.session_state['news']:
    for n in st.session_state['news']:
        st.write(f"🔗 [{n['title']}]({n['link']})")
else:
    st.warning("Aucune actualité récente trouvée.")

st.markdown("---")
st.markdown("### 3. Exports")

c1, c2 = st.columns(2)

with c1:
    if st.button("Générer PDF Complet"):
        pdf_data = utils.generate_pdf_report(st.session_state)
        st.download_button("📥 Télécharger PDF", pdf_data, file_name="Rapport_Audit.pdf", mime="application/pdf")

with c2:
    if st.button("Générer Excel Data"):
        xls_data = utils.generate_excel(st.session_state)
        st.download_button("📊 Télécharger Excel", xls_data, file_name="Data_Audit.xlsx")
        
