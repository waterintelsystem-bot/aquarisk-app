import streamlit as st
import utils
import pandas as pd

utils.init_session()
st.set_page_config(page_title="Audit Site", layout="wide")

# Vérification qu'un site est sélectionné
if not st.session_state.get('current_site_id'):
    st.warning("⚠️ Aucun site sélectionné. Veuillez passer par la page d'accueil (Home) pour choisir un site à auditer.")
    if st.button("Retour Home"): st.switch_page("Home.py")
    st.stop()

st.title(f"🎯 Audit : {st.session_state['current_site_name']}")
st.caption(f"Client : {st.session_state['current_client_name']} | Localisation : {st.session_state['ville']}")

# --- SCORING ---
c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("Paramètres")
    p_leg = st.slider("Pression Légale", 0, 100, 50)
    p_img = st.slider("Réputation", 0, 100, 50)
    params = {'pression_legale': p_leg, 'risque_image': p_img}

with c2:
    if st.button("⚡ CALCULER SCORE", type="primary"):
        sg, s1, s2, s3, s4 = utils.calculate_bloomberg_score(st.session_state, params)
        st.session_state['score_global'] = sg
        st.session_state['var_amount'] = utils.calculate_financial_impact(st.session_state, sg)
        st.success("Calcul terminé.")

    st.metric("SCORE GLOBAL", f"{st.session_state['score_global']:.2f} / 5")
    st.metric("IMPACT FINANCIER", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")

st.divider()

# --- SAUVEGARDE & RAPPORT ---
col_save, col_pdf = st.columns(2)

with col_save:
    if st.button("💾 SAUVEGARDER DANS L'HISTORIQUE DU SITE"):
        msg = utils.save_audit_snapshot(st.session_state['current_site_id'], st.session_state)
        st.success(msg)

with col_pdf:
    if st.button("📄 Générer PDF Site"):
        pdf = utils.generate_pdf_report(st.session_state)
        st.download_button("Rapport_Site.pdf", pdf, "Rapport.pdf", "application/pdf")
        
