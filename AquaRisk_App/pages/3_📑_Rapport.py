import streamlit as st
import utils

utils.init_session()
st.title("📑 Rapport Final")

st.info(f"Résumé IA : {st.session_state['wiki_summary'][:200]}...")

col1, col2 = st.columns(2)
with col1:
    if st.button("Générer PDF"):
        data_pdf = utils.generate_pdf_report(st.session_state)
        st.download_button("📥 Télécharger PDF", data=data_pdf, file_name="Rapport.pdf", mime="application/pdf")

with col2:
    if st.button("Générer Excel"):
        data_xls = utils.generate_excel(st.session_state)
        st.download_button("📊 Télécharger Excel", data=data_xls, file_name="Data.xlsx")
        
