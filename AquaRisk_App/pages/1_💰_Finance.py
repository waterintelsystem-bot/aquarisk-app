import streamlit as st
import utils

utils.init_session()
st.title("💰 Finance & Identité")

# --- IDENTITE ---
c1, c2 = st.columns(2)
with c1: st.session_state['ent_name'] = st.text_input("Entreprise", st.session_state['ent_name'])
with c2: 
    secteur_list = [
        "Agroalimentaire (100%)", "Industrie (80%)", "Énergie (70%)", 
        "BTP (60%)", "Transport (50%)", "Commerce (40%)", "Services (10%)"
    ]
    st.session_state['secteur'] = st.selectbox("Secteur", secteur_list)

st.divider()

# --- TYPE D'AUDIT ---
mode = st.radio("Mode", ["PME (Bilan)", "Cotée (Bourse)", "Startup"], horizontal=True)
st.session_state['mode_valo'] = mode

if mode == "PME (Bilan)":
    t1, t2 = st.tabs(["📄 OCR PDF", "🔍 API Pappers"])
    
    with t1:
        uploaded = st.file_uploader("Bilan PDF", type=["pdf"])
        if uploaded and st.button("Lancer OCR"):
            with st.spinner("Lecture..."):
                stats, msg = utils.run_ocr_scan(uploaded)
                if stats['found']:
                    st.session_state['ca'] = stats['ca']
                    st.session_state['res'] = stats['res']
                    st.session_state['cap'] = stats['cap']
                    st.session_state['source_data'] = "OCR PDF"
                    st.success(f"Trouvé! CA: {stats['ca']:,.0f}")
                else: st.error(f"Echec OCR: {msg}")

    with t2:
        pk = st.text_input("Clé API Pappers", value=st.session_state.get('pappers_token', ''), type="password")
        if st.button("Chercher sur Pappers"):
            if pk:
                st.session_state['pappers_token'] = pk # Save token
                stats, nom = utils.get_pappers_data(st.session_state['ent_name'], pk)
                if stats:
                    st.session_state['ca'] = stats['ca']
                    st.session_state['res'] = stats['res']
                    st.session_state['cap'] = stats['cap']
                    st.session_state['ent_name'] = nom
                    st.session_state['source_data'] = "API Pappers"
                    st.success(f"Données importées pour {nom}")
                else: st.error("Erreur Pappers (Vérifiez la clé ou le nom)")
            else: st.warning("Entrez une clé API.")

    # CHAMPS MANUELS (S'affichent toujours)
    st.markdown("#### Données Financières (Modifiables)")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1: st.session_state['ca'] = st.number_input("CA (€)", value=st.session_state['ca'])
    with col_f2: st.session_state['res'] = st.number_input("Résultat (€)", value=st.session_state['res'])
    with col_f3: st.session_state['cap'] = st.number_input("Capitaux (€)", value=st.session_state['cap'])

    meth = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "Patrimonial"])
    if meth == "Multiple CA":
        m = st.slider("Coeff", 0.1, 5.0, 1.0)
        st.session_state['valo_finale'] = st.session_state['ca'] * m
    elif meth == "Multiple EBITDA":
        ebitda = st.session_state['res'] * 1.3
        m = st.slider("Coeff", 2.0, 15.0, 7.0)
        st.session_state['valo_finale'] = ebitda * m
    else: st.session_state['valo_finale'] = st.session_state['cap']

elif mode == "Cotée (Bourse)":
    tick = st.text_input("Ticker (ex: BN.PA)", "BN.PA")
    if st.button("Chercher Ticker"):
        val, nom, sec, full_t = utils.get_yahoo_data(tick)
        if val > 0:
            st.session_state['valo_finale'] = val
            st.session_state['ent_name'] = nom
            st.session_state['source_data'] = f"Yahoo {full_t}"
            # Est. ratios
            st.session_state['ca'] = val * 0.5
            st.session_state['res'] = val * 0.05
            st.success(f"Trouvé: {nom} ({val:,.0f}€)")
        else: st.error("Ticker introuvable.")
    st.metric("Valo Bourse", f"{st.session_state['valo_finale']:,.0f} €")

else: # Startup
    stade = st.selectbox("Stade", ["Pre-Seed", "Seed", "Series A", "Series B"])
    ranges = {"Pre-Seed": 1.5e6, "Seed": 5e6, "Series A": 15e6, "Series B": 50e6}
    st.session_state['valo_finale'] = st.slider("Valo", 500000.0, 100000000.0, ranges[stade.split()[0]])

st.divider()
st.info(f"Valorisation Retenue : {st.session_state['valo_finale']:,.0f} €")
if st.button("✅ Valider Finance", type="primary"):
    st.success("Données financières figées. Allez dans Climat.")
    
