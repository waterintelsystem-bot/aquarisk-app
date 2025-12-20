import streamlit as st
import utils

utils.init_session()
st.title("💰 Finance & Valorisation Avancée")

# Contexte Client
st.info(f"Analyse pour : **{st.session_state['ent_name']}** (Site: {st.session_state['current_site_name']})")

# Choix de la méthode
type_ent = st.radio("Type d'Entreprise", ["PME / ETI", "Start-up", "Grande Entreprise (Bourse)"], horizontal=True)

if type_ent == "PME / ETI":
    tab1, tab2, tab3 = st.tabs(["📊 Saisie / Pappers", "📐 Multiples", "🏛️ Patrimonial / DCF"])
    
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### Connexion Pappers (SIREN)")
            api_key = st.text_input("Clé API Pappers", type="password")
            siren = st.text_input("SIREN ou Nom")
            if st.button("Importer Données"):
                stats, nom = utils.get_pappers_data(siren, api_key)
                if stats:
                    st.session_state.update(stats)
                    st.session_state['ent_name'] = nom
                    st.success(f"Données importées pour {nom}")
                    st.rerun()
                else: st.error(nom)
        
        with c2:
            st.markdown("##### Saisie Manuelle")
            st.session_state['ca'] = st.number_input("Chiffre d'Affaires (€)", value=float(st.session_state['ca']))
            st.session_state['ebitda'] = st.number_input("EBITDA (€)", value=float(st.session_state['ebitda']))
            st.session_state['res'] = st.number_input("Résultat Net (€)", value=float(st.session_state['res']))
            st.session_state['cap'] = st.number_input("Capitaux Propres (€)", value=float(st.session_state['cap']))

    with tab2:
        st.subheader("Valorisation par Multiples")
        m_ca = st.slider("Multiple CA", 0.5, 3.0, 1.0)
        m_ebitda = st.slider("Multiple EBITDA", 3.0, 15.0, 7.0)
        
        val_ca = st.session_state['ca'] * m_ca
        val_ebitda = st.session_state['ebitda'] * m_ebitda
        
        st.write(f"Valo (CA) : **{val_ca:,.0f} €**")
        st.write(f"Valo (EBITDA) : **{val_ebitda:,.0f} €**")
        
        if st.button("Appliquer Valo EBITDA"): st.session_state['valo_finale'] = val_ebitda

    with tab3:
        st.subheader("Méthodes Patrimoniale & DCF")
        c_a, c_b = st.columns(2)
        with c_a:
            st.write(f"**Actif Net (Patrimonial)** : {st.session_state['cap']:,.0f} €")
            if st.button("Appliquer Patrimonial"): st.session_state['valo_finale'] = st.session_state['cap']
        with c_b:
            st.caption("DCF Simplifié (5 ans)")
            croissance = st.number_input("Croissance %", 0, 50, 5)
            wacc = st.number_input("Taux Actualisation %", 5, 20, 10)
            # Calcul simple
            fcf = st.session_state['ebitda'] * 0.7 # Est. FCF
            dcf_val = sum([fcf * ((1+croissance/100)**i) / ((1+wacc/100)**i) for i in range(1,6)])
            st.write(f"**Valo DCF** : {dcf_val:,.0f} €")
            if st.button("Appliquer DCF"): st.session_state['valo_finale'] = dcf_val

elif type_ent == "Start-up":
    st.subheader("Valorisation Start-up")
    arr = st.number_input("ARR (Revenu Récurrent Annuel)", value=1000000.0)
    mult = st.slider("Multiple ARR", 5, 30, 10)
    st.metric("Valorisation", f"{arr*mult:,.0f} €")
    if st.button("Valider"): st.session_state['valo_finale'] = arr*mult

elif type_ent == "Grande Entreprise (Bourse)":
    tick = st.text_input("Ticker Yahoo (ex: AI.PA)", "AI.PA")
    if st.button("Chercher"):
        v, n, s = utils.get_yahoo_data(tick)
        st.session_state['valo_finale'] = v
        st.session_state['ent_name'] = n
        st.session_state['secteur'] = s
        st.rerun()

st.divider()
st.metric("VALORISATION RETENUE POUR L'AUDIT", f"{st.session_state['valo_finale']:,.0f} €")
