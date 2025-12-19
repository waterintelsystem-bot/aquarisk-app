import streamlit as st
import utils

st.title("📑 Rapport & Synthèse")

st.markdown("### Synthèse Automatique")
st.session_state['txt_synthese'] = st.text_area(
    "Editez le résumé avant export :",
    f"L'entreprise {st.session_state['ent_name']} présente une valorisation de {st.session_state['valo_finale']:,.0f} EUR.\n"
    f"Son exposition au risque climatique (Secteur {st.session_state['secteur']}) pourrait engendrer une perte de valeur estimée à {st.session_state['var_amount']:,.0f} EUR d'ici 2030.",
    height=150
)

st.write("### Export")
if st.button("Générer le PDF Officiel"):
    pdf_bytes = utils.generate_pdf_report(st.session_state)
    st.download_button(
        label="📥 Télécharger le Rapport PDF",
        data=pdf_bytes,
        file_name=f"Audit_{st.session_state['ent_name']}.pdf",
        mime="application/pdf"
    )

st.success("Données prêtes pour l'export.")
