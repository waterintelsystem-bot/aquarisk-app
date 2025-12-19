import streamlit as st
import utils
import pandas as pd

utils.init_session()
st.set_page_config(page_title="Risques 360", layout="wide")

st.title("🎯 Diagnostic Risques 360° & Scénarios")

if st.session_state['valo_finale'] == 0:
    st.error("⚠️ Valo = 0. Complétez l'onglet Finance.")
    st.stop()

# --- INPUTS ---
st.markdown("### 🏭 Données Exploitation")
with st.expander("Saisie des paramètres", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.session_state['vol_eau'] = st.number_input("Vol. Eau (m3/an)", value=50000.0)
        st.session_state['prix_eau'] = st.number_input("Prix Eau (€/m3)", value=4.5)
    with c2:
        st.session_state['part_fournisseur_risk'] = st.slider("% Fournisseurs à risque", 0, 100, 30)
        st.session_state['energie_conso'] = st.number_input("Energie (kWh)", value=100000.0)
    with c3:
        st.session_state['reut_invest'] = st.checkbox("REUT installé ?", value=False)

st.divider()

# --- SCENARIOS ---
st.markdown("### 🎛️ Simulateur de Crise")
c_sim, c_res = st.columns([1, 2])

with c_sim:
    p_eau = st.slider("📈 Hausse Prix Eau", 0, 200, 20, format="+%d%%")
    p_geo = st.slider("🌍 Impact Supply Chain", 0, 100, 10)
    p_leg = st.slider("⚖️ Pression Légale", 0, 100, 30)
    p_img = st.slider("📢 Risque Image (Valo)", 0, 20, 2)
    p_nrg = st.slider("⚡ Hausse Énergie", 0, 100, 15)

    params = {
        'hausse_eau_pct': p_eau, 'impact_geopolitique': p_geo,
        'pression_legale': p_leg, 'risque_image': p_img, 'hausse_energie': p_nrg
    }

with c_res:
    # CALCUL
    risks, total = utils.calculate_360_risks(st.session_state, params)
    
    m1, m2 = st.columns(2)
    m1.metric("Perte Totale Estimée", f"-{total:,.0f} €", delta="Risque Cumulé", delta_color="inverse")
    impact_res = (total / st.session_state['res']) * 100 if st.session_state['res'] > 0 else 0
    m2.metric("Impact Résultat Net", f"-{impact_resultat:.1f} %" if 'impact_resultat' in locals() else "N/A", delta_color="inverse")

    df = pd.DataFrame(list(risks.items()), columns=['Risque', 'Coût'])
    st.bar_chart(df.set_index('Risque'))

st.divider()
wf = utils.calculate_water_footprint(st.session_state)
st.metric("💧 Empreinte Eau Totale", f"{wf:,.0f} m3/an")
