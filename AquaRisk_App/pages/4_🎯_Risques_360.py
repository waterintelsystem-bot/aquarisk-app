import streamlit as st
import utils
import pandas as pd

utils.init_session()
st.title(f"🎯 Audit 360 : {st.session_state.get('current_site_name')}")

if st.session_state['valo_finale'] == 0:
    st.warning("⚠️ Attention : Valorisation à 0€. L'impact financier sera nul.")

# --- 1. PARAMETRES & SCORING ---
t_score, t_veille = st.tabs(["📊 Scoring & Impact", "📰 Veille & Actus"])

with t_score:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("Paramètres")
        p_leg = st.slider("Pression Légale", 0, 100, 50)
        p_img = st.slider("Réputation", 0, 100, 50)
        p_sup = st.slider("Dépendance Fournisseurs", 0, 100, 30)
        
        # Sauvegarde inputs
        st.session_state['part_fournisseur_risk'] = p_sup
        params = {'pression_legale': p_leg, 'risque_image': p_img}

    with c2:
        if st.button("⚡ CALCULER LE RISQUE", type="primary"):
            sg, s1, s2, s3, s4 = utils.calculate_bloomberg_score(st.session_state, params)
            st.session_state.update({
                'score_global': sg, 'score_physique': s1, 
                'score_reglementaire': s2, 'score_reputation': s3, 'score_resilience': s4
            })
            st.session_state['var_amount'] = utils.calculate_financial_impact(st.session_state, sg)
            st.rerun()

        # Résultats
        k1, k2 = st.columns(2)
        k1.metric("SCORE GLOBAL", f"{st.session_state['score_global']:.2f} / 5")
        k2.metric("IMPACT (VaR)", f"-{st.session_state['var_amount']:,.0f} €", delta_color="inverse")
        
        # Graphique Détail
        if st.session_state['score_global'] > 0:
            df_chart = pd.DataFrame({
                "Score": [st.session_state['score_physique'], st.session_state['score_reglementaire'], 
                          st.session_state['score_reputation'], st.session_state['score_resilience']]
            }, index=["Physique", "Réglementaire", "Réputation", "Résilience"])
            st.bar_chart(df_chart)

with t_veille:
    st.subheader(f"Actualités : {st.session_state['ent_name']}")
    
    col_search, col_res = st.columns([1, 3])
    with col_search:
        # Mot clé de recherche modifiable
        sujet = st.text_input("Mot-clé", f"{st.session_state['ent_name']} water")
        if st.button("🔄 Lancer la Veille"):
            with st.spinner("Recherche Google News..."):
                news = utils.fetch_automated_news(sujet)
                st.session_state['news'] = news
                st.success(f"{len(news)} articles trouvés.")
    
    with col_res:
        if st.session_state.get('news'):
            for n in st.session_state['news']:
                st.info(f"**{n['title']}**\n\n📅 {n['date']} | [Lire l'article]({n['link']})")
        else:
            st.caption("Lancez la recherche pour voir les articles.")

st.divider()

# --- 3. EXPORT & SAUVEGARDE ---
c_save, c_pdf = st.columns(2)
with c_save:
    if st.button("💾 SAUVEGARDER L'AUDIT"):
        if st.session_state.get('current_site_id'):
            msg = utils.save_audit_snapshot(st.session_state['current_site_id'], st.session_state)
            st.success(msg)
        else: st.error("Sélectionnez un site dans Home d'abord.")

with c_pdf:
    if st.button("📄 TÉLÉCHARGER LE RAPPORT PDF"):
        # On passe les données actuelles au générateur
        pdf = utils.generate_pdf_report(st.session_state)
        st.download_button("Rapport_Audit.pdf", pdf, "application/pdf")
        
