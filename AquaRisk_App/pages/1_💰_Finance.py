import streamlit as st
import utils

utils.init_session()
st.title("💰 Finance & Identité")

# --- 1. IDENTITE ---
c1, c2 = st.columns(2)
with c1: st.session_state['ent_name'] = st.text_input("Nom Entreprise", st.session_state['ent_name'])
with c2: 
    st.session_state['secteur'] = st.selectbox(
        "Secteur (Impact Vulnérabilité)", 
        utils.SECTEURS_LISTE,
        index=0
    )

st.divider()

# --- 2. VALORISATION ---
mode = st.radio("Mode", ["PME (Bilan)", "Cotée (Bourse)", "Startup"], horizontal=True)
st.session_state['mode_valo'] = mode

if mode == "PME (Bilan)":
    t1, t2 = st.tabs(["📄 OCR PDF", "🔍 Pappers (Nom ou SIREN)"])
    
    with t1:
        uploaded = st.file_uploader("Bilan PDF", type=["pdf"])
        if uploaded and st.button("Lancer OCR"):
            stats, msg = utils.run_ocr_scan(uploaded)
            if stats['found']:
                st.session_state['ca'] = stats['ca']
                st.session_state['res'] = stats['res']
                st.session_state['cap'] = stats['cap']
                st.success(f"✅ OCR : {msg}")
            else: st.error(f"❌ OCR : {msg}")

    with t2:
        pk = st.text_input("Clé API Pappers", type="password")
        search_query = st.text_input("Recherche (Nom ou SIREN)")
        if st.button("Chercher Pappers"):
            if pk and search_query:
                stats, nom = utils.get_pappers_data(search_query, pk)
                if stats:
                    st.session_state['ca'] = stats['ca']
                    st.session_state['res'] = stats['res']
                    st.session_state['cap'] = stats['cap']
                    st.session_state['ent_name'] = nom
                    st.session_state['source_data'] = "Pappers"
                    st.success(f"Données importées pour {nom}")
                else: st.error(nom) # Affiche le message d'erreur

    st.markdown("#### Données Financières")
    c_ca, c_res, c_cap = st.columns(3)
    with c_ca: st.session_state['ca'] = st.number_input("CA (€)", value=st.session_state['ca'])
    with c_res: st.session_state['res'] = st.number_input("Résultat (€)", value=st.session_state['res'])
    with c_cap: st.session_state['cap'] = st.number_input("Capitaux (€)", value=st.session_state['cap'])
    
    # --- METHODES VALO ---
    meth = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "Patrimonial", "DCF (Cash Flow)"])
    
    val_calc = 0.0
    if meth == "Multiple CA":
        m = st.slider("Coeff", 0.1, 6.0, 1.0)
        val_calc = st.session_state['ca'] * m
    elif meth == "Multiple EBITDA":
        ebitda = st.session_state['res'] * 1.3
        m = st.slider("Coeff", 2.0, 15.0, 7.0)
        val_calc = ebitda * m
    elif meth == "Patrimonial":
        val_calc = st.session_state['cap']
    elif meth == "DCF (Cash Flow)":
        st.info("Méthode DCF simplifiée")
        k1, k2 = st.columns(2)
        with k1: wacc = st.number_input("WACC (%)", 5.0, 15.0, 10.0) / 100
        with k2: g = st.number_input("Croissance g (%)", 0.0, 5.0, 1.5) / 100
        # FCF estimé à partir du Résultat Net
        fcf = st.number_input("Free Cash Flow (est.)", value=st.session_state['res'])
        if wacc > g:
            val_calc = fcf / (wacc - g)
        else:
            st.error("WACC doit être > g")
            val_calc = 0

    st.session_state['valo_finale'] = val_calc

elif mode == "Cotée (Bourse)":
    tick = st.text_input("Ticker ou Nom (ex: Airbus, BN.PA)", "BN.PA")
    if st.button("Chercher Yahoo"):
        val, nom, sec, full_t = utils.get_yahoo_data(tick)
        if val > 0:
            st.session_state['valo_finale'] = val
            st.session_state['ent_name'] = nom
            st.session_state['source_data'] = f"Yahoo {full_t}"
            st.session_state['ca'] = val * 0.5 
            st.success(f"Trouvé : {nom} ({sec}) | Valo : {val:,.0f}€")
        else: st.error("Introuvable (Essayez le symbole exact ex: AAPL)")
    st.number_input("Valo Bourse (€)", key="valo_finale")

else: # Startup
    stade = st.selectbox("Stade", ["Pre-Seed", "Seed", "Series A", "Series B"])
    ranges = {"Pre-Seed": 1.5e6, "Seed": 5e6, "Series A": 15e6, "Series B": 50e6}
    st.session_state['valo_finale'] = st.slider("Valo", 500000.0, 100000000.0, ranges[stade.split()[0]])

st.divider()
st.info(f"Valorisation Retenue : {st.session_state['valo_finale']:,.0f} €")
if st.button("✅ VALIDER FINANCE", type="primary"):
    st.success("Validé ! Passez à l'onglet Climat.")
    
