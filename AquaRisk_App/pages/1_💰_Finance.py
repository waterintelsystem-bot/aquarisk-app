import streamlit as st
import utils

utils.init_session()
st.title("💰 Finance & Identité")

# Identité
c1, c2 = st.columns(2)
with c1: 
    st.session_state['ent_name'] = st.text_input("Nom Entreprise", st.session_state['ent_name'])
with c2: 
    saved_sec = st.session_state.get('secteur')
    idx = utils.SECTEURS_LISTE.index(saved_sec) if saved_sec in utils.SECTEURS_LISTE else 0
    st.session_state['secteur'] = st.selectbox("Secteur (Vulnérabilité)", utils.SECTEURS_LISTE, index=idx)

st.divider()

# Mode Valo
modes = ["PME (Bilan)", "Cotée (Bourse)", "Startup"]
try: idx_m = modes.index(st.session_state.get('mode_valo', modes[0]))
except: idx_m = 0
mode = st.radio("Mode", modes, index=idx_m, horizontal=True)
st.session_state['mode_valo'] = mode

if mode == "PME (Bilan)":
    t1, t2 = st.tabs(["OCR PDF", "Pappers"])
    with t1:
        upl = st.file_uploader("PDF", type=["pdf"])
        if upl and st.button("OCR"):
            s, m = utils.run_ocr_scan(upl)
            if s['found']: 
                st.session_state.update(s)
                st.success(m)
    with t2:
        pk = st.text_input("API Pappers", type="password")
        q = st.text_input("Nom/SIREN")
        if st.button("Chercher"):
            s, n = utils.get_pappers_data(q, pk)
            if s: 
                st.session_state.update(s)
                st.session_state['ent_name'] = n
                st.success(n); st.rerun()

    c_ca, c_res, c_cap = st.columns(3)
    with c_ca: st.session_state['ca'] = st.number_input("CA", value=st.session_state['ca'])
    with c_res: st.session_state['res'] = st.number_input("Res", value=st.session_state['res'])
    with c_cap: st.session_state['cap'] = st.number_input("Cap", value=st.session_state['cap'])
    
    m = st.slider("Multiple CA", 0.1, 5.0, 1.0)
    st.session_state['valo_finale'] = st.session_state['ca'] * m

elif mode == "Cotée (Bourse)":
    # Changement ici : On encourage les tickers US
    tick = st.text_input("Ticker (ex: TSLA, AAPL, AIR.PA)", value=st.session_state.get('ticker_input', ''))
    st.session_state['ticker_input'] = tick
    
    if st.button("Chercher Yahoo"):
        with st.spinner("Recherche Bourse..."):
            # Appel à la fonction corrigée (renvoie 4 valeurs)
            val, nom, sec, full_t = utils.get_yahoo_data(tick)
            
            if val > 0:
                st.session_state['valo_finale'] = val
                st.session_state['ent_name'] = nom
                st.session_state['ca'] = val * 0.4 # Est.
                st.success(f"Trouvé: {nom} (Secteur: {sec}) | Valo: {val:,.0f}€")
                st.rerun()
            else:
                st.error("Introuvable. Essayez le code exact (ex: TSLA pour Tesla).")
            
    st.session_state['valo_finale'] = st.number_input("Valo", value=float(st.session_state['valo_finale']))

else:
    st.session_state['valo_finale'] = st.slider("Valo Startup", 1e6, 100e6, 5e6)

st.info(f"Valo Retenue: {st.session_state['valo_finale']:,.0f} €")
