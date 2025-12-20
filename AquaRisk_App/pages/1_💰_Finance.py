import streamlit as st
import utils

utils.init_session()
st.title("💰 Finance & Valorisation")

# Identité
c1, c2 = st.columns(2)
with c1: 
    # Synchronisation avec le client actif si possible
    def_name = st.session_state.get('current_client_name', 'Nouvelle Entreprise')
    st.session_state['ent_name'] = st.text_input("Nom Entreprise", def_name)
with c2: 
    saved_sec = st.session_state.get('secteur')
    idx = utils.SECTEURS_LISTE.index(saved_sec) if saved_sec in utils.SECTEURS_LISTE else 0
    st.session_state['secteur'] = st.selectbox("Secteur (Vulnérabilité)", utils.SECTEURS_LISTE, index=idx)

st.divider()

# CHOIX DU MODELE (RESTAURÉ)
modes = ["PME (Bilan)", "Cotée (Bourse)", "Startup (Estimation)"]
st.subheader("Méthode de Valorisation")
mode = st.radio("Type d'entreprise", modes, horizontal=True)
st.session_state['mode_valo'] = mode

if "PME" in mode:
    st.info("💡 Mode PME : Saisissez les données du bilan ou utilisez un multiple du CA.")
    c_ca, c_res, c_cap = st.columns(3)
    with c_ca: st.session_state['ca'] = st.number_input("Chiffre d'Affaires (€)", value=float(st.session_state['ca']))
    with c_res: st.session_state['res'] = st.number_input("Résultat Net (€)", value=float(st.session_state['res']))
    with c_cap: st.session_state['cap'] = st.number_input("Capitaux Propres (€)", value=float(st.session_state['cap']))
    
    m = st.slider("Multiple de Valorisation (x CA)", 0.1, 5.0, 1.0)
    st.session_state['valo_finale'] = st.session_state['ca'] * m

elif "Cotée" in mode:
    st.info("💡 Mode Bourse : Récupération automatique via Yahoo Finance.")
    tick = st.text_input("Ticker (ex: AI.PA, BN.PA, TSLA)", value="")
    if st.button("Chercher Ticker"):
        val, nom, sec, full_t = utils.get_yahoo_data(tick)
        if val > 0:
            st.session_state['valo_finale'] = val
            st.session_state['ent_name'] = nom
            st.success(f"Trouvé : {nom} | Valo : {val:,.0f} €")
            st.rerun()
        else:
            st.error("Ticker introuvable.")
    st.metric("Valorisation Boursière", f"{st.session_state['valo_finale']:,.0f} €")

elif "Startup" in mode:
    st.info("💡 Mode Startup : Estimation manuelle.")
    st.session_state['valo_finale'] = st.slider("Valorisation Estimée (€)", 1_000_000, 100_000_000, 5_000_000, step=1_000_000)

st.success(f"💰 Valorisation retenue pour l'audit : **{st.session_state['valo_finale']:,.0f} €**")
