import streamlit as st
import utils

st.title("📑 Rapport Final & Exports")

# Vérification que l'audit est lancé
if st.session_state.get('valo_finale', 0) == 0:
    st.warning("⚠️ Attention : Aucune valorisation n'a été faite. Le rapport sera incomplet.")

st.markdown("### 1. Aperçu de l'Intelligence")
st.info("Résumé généré via Wikipedia & Web")
st.write(st.session_state.get('wiki_summary', 'Pas de données.'))

st.markdown("### 2. Sources Détectées")
if st.session_state['news']:
    for n in st.session_state['news']:
        st.write(f"🔗 [{n['title']}]({n['link']})")
else:
    st.warning("Aucune actualité récente trouvée.")

st.markdown("---")
st.markdown("### 3. Zone de Téléchargement")

c1, c2 = st.columns(2)

with c1:
    # BOUTON PDF ROBUSTE
    if st.button("📄 Générer le PDF Complet"):
        with st.spinner("Génération du document..."):
            pdf_data = utils.generate_pdf_report(st.session_state)
            st.download_button(
                "📥 Télécharger le PDF", 
                data=pdf_data, 
                file_name=f"Audit_{st.session_state['ent_name']}.pdf", 
                mime="application/pdf"
            )

with c2:
    if st.button("📊 Générer les Données Excel"):
        xls_data = utils.generate_excel(st.session_state)
        st.download_button(
            "📥 Télécharger Excel", 
            data=xls_data, 
            file_name="Data_Audit.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
