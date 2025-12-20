import streamlit as st
import utils

utils.init_session()
st.title(f"🎯 Audit : {st.session_state['current_site_name']}")

# Check Valo
if st.session_state['valo_finale'] == 0:
    st.warning("⚠️ Valorisation nulle. Allez dans l'onglet Finance.")

# --- INPUTS ---
c1, c2 = st.columns([1, 2])
with c1:
    st.subheader("Paramètres")
    # On lie directement les sliders au session_state
    pleg = st.slider("Pression Légale", 0, 100, 50)
    pimg = st.slider("Réputation", 0, 100, 50)
    psup = st.slider("Fournisseurs", 0, 100, 30)
    
    # Bouton de Calcul
    if st.button("⚡ CALCULER IMPACT", type="primary"):
        params = {'pression_legale': pleg, 'risque_image': pimg}
        st.session_state['part_fournisseur_risk'] = psup
        
        # Calcul
        sg, s1, s2, s3, s4 = utils.calculate_bloomberg_score(st.session_state, params)
        st.session_state['score_global'] = sg
        st.session_state['score_physique'] = s1
        st.session_state['score_reglementaire'] = s2
        st.session_state['score_reputation'] = s3
        st.session_state['score_resilience'] = s4
        
        # VaR
        st.session_state['var_amount'] = utils.calculate_financial_impact(st.session_state, sg)
        st.rerun()

with c2:
    st.metric("SCORE GLOBAL", f"{st.session_state['score_global']:.2f} / 5")
    st.metric("IMPACT FINANCIER (VaR)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")
    
    # Graphique Légendé
    if st.session_state['score_global'] > 0:
        data_graph = {
            "Physique": st.session_state['score_physique'],
            "Réglementaire": st.session_state['score_reglementaire'],
            "Réputation": st.session_state['score_reputation'],
            "Résilience": st.session_state['score_resilience']
        }
        st.bar_chart(data_graph)
        st.caption("Détail des risques pondérés")

st.divider()
c_s, c_p = st.columns(2)
if c_s.button("💾 SAUVEGARDER VERSION"):
    msg = utils.save_audit_snapshot(st.session_state['current_site_id'], st.session_state)
    st.success(msg)

if c_p.button("📄 TELECHARGER PDF"):
    pdf = utils.generate_pdf_report(st.session_state)
    st.download_button("Rapport.pdf", pdf, "application/pdf")
    
