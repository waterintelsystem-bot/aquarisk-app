import streamlit as st
import utils
import pandas as pd

utils.init_session()
st.set_page_config(page_title="Risques 360", layout="wide")

st.title("🎯 Diagnostic Risques 360°")

if st.session_state['valo_finale'] == 0:
    st.error("⚠️ Valo = 0. Complétez l'onglet Finance.")
    st.stop()

st.markdown("### 🏭 Données Opérationnelles")
c1, c2, c3 = st.columns(3)
with c1:
    st.session_state['vol_eau'] = st.number_input("Vol. Eau (m3)", value=st.session_state['vol_eau'])
    st.session_state['prix_eau'] = st.number_input("Prix Eau (€)", value=st.session_state['prix_eau'])
with c2:
    st.session_state['part_fournisseur_risk'] = st.slider("% Fourn. Risque", 0, 100, int(st.session_state['part_fournisseur_risk']))
    st.session_state['energie_conso'] = st.number_input("Energie (kWh)", value=st.session_state['energie_conso'])
with c3:
    st.session_state['reut_invest'] = st.checkbox("REUT installé ?", value=st.session_state['reut_invest'])

st.divider()
st.markdown("### 🎛️ Scénarios")

c_sim, c_res = st.columns([1, 2])
with c_sim:
    p_eau = st.slider("📈 Hausse Prix Eau", 0, 200, 20, format="+%d%%")
    p_geo = st.slider("🌍 Impact Supply", 0, 100, 10)
    p_leg = st.slider("⚖️ Pression Légale", 0, 100, 30)
    p_img = st.slider("📢 Image", 0, 20, 2)
    p_nrg = st.slider("⚡ Énergie", 0, 100, 15)
    
    params = {
        'hausse_eau_pct': p_eau, 'impact_geopolitique': p_geo,
        'pression_legale': p_leg, 'risque_image': p_img, 'hausse_energie': p_nrg
    }

with c_res:
    # CALCUL LIVE
    risks, total = utils.calculate_360_risks(st.session_state, params)
    
    # SAUVEGARDE POUR LE PDF
    st.session_state['risks_360_dict'] = risks
    st.session_state['risks_360_total'] = total
    
    m1, m2 = st.columns(2)
    m1.metric("Perte Totale", f"-{total:,.0f} €", delta_color="inverse")
    im_res = (total / st.session_state['res']) * 100 if st.session_state['res'] > 0 else 0
    m2.metric("Impact Résultat", f"-{im_res:.1f} %", delta_color="inverse")
    
    st.bar_chart(pd.DataFrame(list(risks.items()), columns=['R', 'V']).set_index('R'))

st.divider()

# --- ZONE ACTIONS (SAUVEGARDE + PDF) ---
c_pdf, c_db = st.columns(2)

with c_pdf:
    if st.button("📄 Télécharger Rapport (PDF)"):
        pdf = utils.generate_pdf_report(st.session_state)
        st.download_button("Rapport.pdf", pdf, "Rapport.pdf", "application/pdf")

with c_db:
    # BOUTON SAUVEGARDE DB
    if st.button("💾 SAUVEGARDER CET AUDIT (Historique)", type="primary"):
        msg = utils.save_audit_to_db(st.session_state)
        st.success(msg)

st.divider()
# --- AFFICHAGE HISTORIQUE ---
st.markdown("### 📂 Historique des Audits")
try:
    df_history = utils.load_all_audits()
    if not df_history.empty:
        st.dataframe(df_history, hide_index=True, use_container_width=True)
    else:
        st.info("Aucun audit enregistré pour l'instant.")
except: st.warning("Impossible de lire la base de données.")
    
