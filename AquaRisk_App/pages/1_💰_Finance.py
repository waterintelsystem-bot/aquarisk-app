import streamlit as st
import utils # On appelle le cerveau

st.title("💰 Module Financier")

# 1. Identité (Liée à la mémoire)
c1, c2 = st.columns(2)
with c1: st.session_state['ent_name'] = st.text_input("Nom de l'entreprise", st.session_state['ent_name'])
with c2: st.session_state['mode_valo'] = st.radio("Type", ["PME", "Bourse", "Startup"])

st.markdown("---")

# 2. Logique selon le mode
if st.session_state['mode_valo'] == "PME":
    st.subheader("Import Bilan & OCR")
    uploaded = st.file_uploader("Liasse Fiscale (PDF)", type=["pdf"])
    
    if uploaded:
        if st.button("🧠 Lancer l'analyse du document"):
            with st.spinner("Lecture intelligente..."):
                stats, txt = utils.run_ocr_scan(uploaded)
                if stats['found']:
                    st.session_state['ca'] = stats['ca']
                    st.session_state['res'] = stats['res']
                    st.session_state['cap'] = stats['cap']
                    st.success(f"Données trouvées ! CA: {stats['ca']:,.0f} €")
                else:
                    st.warning("OCR : Pas de chiffres nets détectés. Saisie manuelle requise.")

    # Champs éditables (connectés mémoire)
    c_ca, c_res, c_cap = st.columns(3)
    with c_ca: st.session_state['ca'] = st.number_input("Chiffre d'Affaires", value=st.session_state['ca'])
    with c_res: st.session_state['res'] = st.number_input("Résultat Net", value=st.session_state['res'])
    with c_cap: st.session_state['cap'] = st.number_input("Capitaux Propres", value=st.session_state['cap'])
    
    # Calcul Valo
    methode = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "Patrimonial"])
    if methode == "Multiple CA":
        mult = st.slider("Multiple", 0.1, 5.0, 1.0)
        st.session_state['valo_finale'] = st.session_state['ca'] * mult
    elif methode == "Multiple EBITDA":
        ebitda = st.session_state['res'] * 1.25
        mult = st.slider("Multiple", 1.0, 15.0, 7.0)
        st.session_state['valo_finale'] = ebitda * mult
    else:
        st.session_state['valo_finale'] = st.session_state['cap']

elif st.session_state['mode_valo'] == "Bourse":
    ticker = st.text_input("Ticker Yahoo", "BN.PA")
    if st.button("Charger"):
        val, name = utils.get_yahoo_data(ticker)
        if val > 0:
            st.session_state['valo_finale'] = val
            st.session_state['ent_name'] = name
            st.success(f"Trouvé: {name}")
        else: st.error("Ticker introuvable")

else: # Startup
    stade = st.selectbox("Stade", ["Pre-Seed", "Seed", "Series A"])
    ranges = {"Pre-Seed": 1000000.0, "Seed": 5000000.0, "Series A": 15000000.0}
    st.session_state['valo_finale'] = ranges[stade]

st.metric("Valorisation Retenue", f"{st.session_state['valo_finale']:,.0f} €")
