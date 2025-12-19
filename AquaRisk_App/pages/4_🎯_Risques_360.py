import streamlit as st
import utils
import pandas as pd
import matplotlib.pyplot as plt

utils.init_session()
st.set_page_config(page_title="Risques 360", layout="wide")

st.title("🎯 Diagnostic Risques 360° & Scénarios")

if st.session_state['valo_finale'] == 0:
    st.error("⚠️ Données financières manquantes. Veuillez compléter l'onglet Finance.")
    st.stop()

# --- 1. CONFIGURATION DES INPUTS (DATA) ---
st.markdown("### 🏭 Données Opérationnelles")
with st.expander("Saisir les données d'exploitation", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.session_state['vol_eau'] = st.number_input("Volume Eau annuel (m3)", value=50000.0, step=1000.0)
        st.session_state['prix_eau'] = st.number_input("Prix moyen (€/m3)", value=4.5, step=0.1)
    with c2:
        st.session_state['part_fournisseur_risk'] = st.slider("% Fournisseurs en zone hydrique tendue", 0, 100, 30)
        st.session_state['energie_conso'] = st.number_input("Conso Energie (kWh)", value=100000.0)
    with c3:
        st.session_state['reut_invest'] = st.checkbox("Système REUT (Recyclage) déjà installé ?", value=False)
        st.info("Le REUT réduit le risque réglementaire.")

st.divider()

# --- 2. GENERATEUR DE SCENARIOS (SIMULATION) ---
st.markdown("### 🎛️ Simulateur de Crise")
st.caption("Ajustez les curseurs pour voir l'impact financier immédiat.")

col_s1, col_s2 = st.columns([1, 2])

with col_s1:
    st.subheader("Paramètres Scénario")
    
    # Paramètres de simulation
    p_eau = st.slider("📈 Hausse Prix Eau", 0, 200, 20, format="+%d%%")
    p_geo = st.slider("🌍 Impact Rupture Supply Chain", 0, 100, 10, help="% de perte de CA due aux fournisseurs")
    p_leg = st.slider("⚖️ Pression Légale / Taxes", 0, 100, 30, help="Probabilité de nouvelles taxes ou amendes")
    p_img = st.slider("📢 Risque Image (Valo)", 0, 20, 2, help="% de baisse de la valorisation boursière")
    p_nrg = st.slider("⚡ Hausse Coût Énergie", 0, 100, 15, format="+%d%%")

    params = {
        'hausse_eau_pct': p_eau,
        'impact_geopolitique': p_geo,
        'pression_legale': p_leg,
        'risque_image': p_img,
        'hausse_energie': p_nrg
    }

with col_s2:
    st.subheader("Impact Financier Projeté")
    
    # CALCUL LIVE
    risks, total = utils.calculate_360_risks(st.session_state, params)
    
    # Affichage Métriques
    m1, m2 = st.columns(2)
    m1.metric("Perte Totale Estimée", f"-{total:,.0f} €", delta="Risque Cumulé", delta_color="inverse")
    
    impact_resultat = (total / st.session_state['res']) * 100 if st.session_state['res'] > 0 else 0
    m2.metric("Impact sur Résultat Net", f"-{impact_resultat:.1f} %", delta="Rentabilité", delta_color="inverse")

    # Graphique Waterfall (ou Barres)
    df_risk = pd.DataFrame(list(risks.items()), columns=['Catégorie', 'Coût (€)'])
    st.bar_chart(df_risk.set_index('Catégorie'))

# --- 3. WATER FOOTPRINT ---
st.divider()
st.markdown("### 💧 Water Footprint (Empreinte Eau)")
wf = utils.calculate_water_footprint(st.session_state)
st.metric("Empreinte Eau Totale (Scope 1 + 3 estimé)", f"{wf:,.0f} m3/an")
st.progress(min(1.0, wf / 1000000), text="Intensité Hydrique (échelle relative)")

# --- 4. EXPORT ---
st.divider()
if st.button("📄 Générer Rapport Risques 360 (PDF)"):
    # On utilise une fonction simplifiée pour cet exemple
    # Assurez-vous d'avoir ajouté generate_pdf_360 dans utils.py
    try:
        pdf_data = utils.generate_pdf_360(st.session_state, risks)
        st.download_button("Télécharger Audit 360.pdf", pdf_data, "Audit_360.pdf", "application/pdf")
    except Exception as e:
        st.error(f"Erreur PDF : {e}")
      
