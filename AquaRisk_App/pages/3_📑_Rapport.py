import streamlit as st
import utils

utils.init_session()
st.title("📑 Rapport Final")

st.info(f"Résumé Automatique : {st.session_state['wiki_summary'][:300]}...")

c1, c2 = st.columns(2)
with c1:
    if st.button("Générer PDF avec Graphique"):
        pdf_data = utils.generate_pdf_report(st.session_state)
        st.download_button("📥 Télécharger PDF", data=pdf_data, file_name="Rapport_Complet.pdf", mime="application/pdf")

with c2:
    if st.button("Exporter Excel"):
        xls = utils.generate_excel(st.session_state)
        st.download_button("📊 Télécharger Excel", data=xls, file_name="Data.xlsx")

st.markdown("### Sources")
for n in st.session_state.get('news', []):
    st.write(f"- [{n['title']}]({n['link']})")
    
