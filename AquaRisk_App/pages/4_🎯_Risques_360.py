import streamlit as st
import utils
import pandas as pd

utils.init_session()
st.title(f"🎯 Audit 360 : {st.session_state.get('current_site_name')}")

if st.session_state['valo_finale'] == 0:
    st.warning("⚠️ Valorisation financière nulle. Impact financier sera de 0€.")

# --- SCORING PONDÉRÉ (Bloomberg) ---
st.subheader("⚙️ Paramètres d'Audit")
c1, c2 = st.columns([1, 2])
with c1:
    p_leg = st.slider("Pression Légale", 0, 100, 50)
    p_img = st.slider("Réputation / Image", 0, 100, 50)
    p_sup = st.slider("Dépendance Fournisseurs", 0, 100, 30)
    params = {'pression_legale': p_leg, 'risque_image': p_img}
    st.session_state['part_fournisseur_risk'] = p_sup

with c2:
    if st.button("⚡ CALCULER SCORE FINAL", type="primary"):
        sg, s1, s2, s3, s4 = utils.calculate_bloomberg_score(st.session_state, params)
        st.session_state['score_global'] = sg
        st.session_state['score_physique'] = s1
        st.session_state['score_reglementaire'] = s2
        st.session_state['score_reputation'] = s3
        st.session_state['score_resilience'] = s4
        
        st.session_state['var_amount'] = utils.calculate_financial_impact(st.session_state, sg)
        st.success("Scoring terminé.")

# --- RESULTATS ---
st.divider()
col_res1, col_res2 = st.columns(2)
with col_res1:
    st.metric("SCORE GLOBAL EAU", f"{st.session_state['score_global']:.2f} / 5")
    st.write(f"- Physique : {st.session_state.get('score_physique',0):.2f}")
    st.write(f"- Réglementaire : {st.session_state.get('score_reglementaire',0):.2f}")
with col_res2:
    st.metric("IMPACT FINANCIER (VaR)", f"-{st.session_state['var_amount']:,.0f} €", delta="Risque", delta_color="inverse")

# --- VEILLE SPECIFIQUE AU SITE ---
st.divider()
st.subheader("📰 Veille & Actualités")
if st.button("🔄 Lancer recherche actus"):
    news = utils.fetch_automated_news(f"{st.session_state['ent_name']} water")
    st.session_state['news'] = news

for n in st.session_state.get('news', []):
    st.caption(f"{n['date']} - [{n['title']}]({n['link']})")

# --- ACTIONS ---
st.divider()
c_save, c_pdf = st.columns(2)
with c_save:
    if st.button("💾 SAUVEGARDER L'AUDIT"):
        # Appel à la fonction corrigée dans utils
        if st.session_state.get('current_site_id'):
            msg = utils.save_audit_snapshot(st.session_state['current_site_id'], st.session_state)
            st.success(msg)
        else:
            st.error("Sélectionnez d'abord un site dans Home.")

with c_pdf:
    if st.button("📄 Télécharger PDF"):
        pdf = utils.generate_pdf_report(st.session_state)
        st.download_button("Rapport.pdf", pdf, "Rapport.pdf", "application/pdf")
        
