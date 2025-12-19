import streamlit as st
import utils

st.title("💰 Module Financier")

# --- 1. IDENTITÉ & SECTEUR (CRITIQUE POUR CLIMAT) ---
c1, c2 = st.columns(2)
with c1: 
    st.session_state['ent_name'] = st.text_input("Nom de l'entreprise", st.session_state['ent_name'])
with c2: 
    # Liste complète des secteurs avec vulnérabilité cachée
    secteur_choix = st.selectbox(
        "Secteur d'Activité (Impact Vulnérabilité)", 
        list(utils.SECTEURS.keys()),
        index=0
    )
    st.session_state['secteur'] = secteur_choix

st.markdown("---")

# --- 2. MODE DE VALORISATION ---
mode = st.radio("Type d'Entreprise", ["PME (Bilan)", "Cotée (Bourse)", "Startup (Levée)"], horizontal=True)
st.session_state['mode_valo'] = mode

if mode == "PME (Bilan)":
    # OCR
    uploaded = st.file_uploader("Importer Liasse Fiscale (PDF)", type=["pdf"])
    if uploaded:
        if st.button("🧠 Analyser le document"):
            with st.spinner("Lecture OCR Agressive..."):
                stats, txt = utils.run_ocr_scan(uploaded)
                if stats['found']:
                    st.session_state['ca'] = stats['ca']
                    st.session_state['res'] = stats['res']
                    st.session_state['cap'] = stats['cap']
                    st.session_state['source_data'] = "OCR PDF"
                    st.success(f"✅ Bilan Lu ! CA: {stats['ca']:,.0f}€")
                else:
                    st.warning("⚠️ OCR : Chiffres non détectés. Saisie manuelle nécessaire.")

    # Champs
    c_ca, c_res, c_cap = st.columns(3)
    with c_ca: st.session_state['ca'] = st.number_input("Chiffre d'Affaires (€)", value=st.session_state['ca'])
    with c_res: st.session_state['res'] = st.number_input("Résultat Net (€)", value=st.session_state['res'])
    with c_cap: st.session_state['cap'] = st.number_input("Capitaux Propres (€)", value=st.session_state['cap'])
    
    # Méthodes Valo
    methode = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "Patrimonial", "DCF Simplifié"])
    
    val_calc = 0.0
    if methode == "Multiple CA":
        mult = st.slider("Multiple CA (x)", 0.5, 6.0, 1.5, 0.1)
        val_calc = st.session_state['ca'] * mult
    elif methode == "Multiple EBITDA":
        ebitda = st.session_state['res'] * 1.3 # Approx standard
        mult = st.slider("Multiple EBITDA (x)", 3.0, 20.0, 7.0, 0.5)
        val_calc = ebitda * mult
    elif methode == "Patrimonial":
        val_calc = st.session_state['cap']
    else: # DCF
        val_calc = st.session_state['res'] * 10 

    st.session_state['valo_finale'] = val_calc

elif mode == "Cotée (Bourse)":
    ticker = st.text_input("Ticker Yahoo (ex: BN.PA, MC.PA)", "BN.PA")
    if st.button("🔍 Rechercher Ticker"):
        mcap, name, sec = utils.get_yahoo_data(ticker)
        if mcap > 0:
            st.session_state['valo_finale'] = mcap
            st.session_state['ent_name'] = name if name else st.session_state['ent_name']
            st.session_state['source_data'] = f"Yahoo ({ticker})"
            # Estimation ratios pour affichage
            st.session_state['ca'] = mcap * 0.5
            st.session_state['res'] = mcap * 0.08
            st.success(f"Trouvé : {name} ({sec}) | Valo : {mcap:,.0f}€")
        else:
            st.error("Ticker introuvable. Vérifiez sur Yahoo Finance (ex: ajoutez .PA pour Paris).")
            
    st.number_input("Capitalisation Boursière (€)", key="valo_finale")

else: # Startup
    stade = st.selectbox("Stade de Maturité", ["Pre-Seed", "Seed", "Series A", "Series B", "Series C"])
    ranges = {
        "Pre-Seed": (1e6, 2e6), "Seed": (3e6, 8e6), 
        "Series A": (10e6, 30e6), "Series B": (40e6, 80e6), "Series C": (100e6, 300e6)
    }
    mini, maxi = ranges[stade]
    st.info(f"Fourchette Marché : {mini/1e6}M€ - {maxi/1e6}M€")
    val_calc = st.slider("Valorisation (€)", mini, maxi, (mini+maxi)/2)
    st.session_state['valo_finale'] = val_calc
    # Fake metrics for report
    st.session_state['ca'] = val_calc * 0.1
    st.session_state['res'] = -val_calc * 0.1

st.metric("VALORISATION RETENUE", f"{st.session_state['valo_finale']:,.0f} €")
