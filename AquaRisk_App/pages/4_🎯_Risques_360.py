import streamlit as st
import utils
import pandas as pd
from geopy.geocoders import Nominatim

# Init
utils.init_session()
st.set_page_config(page_title="Terminal Bloomberg Eau", layout="wide")
st.title("💧 Terminal d'Analyse & Veille")

# --- BARRE LATÉRALE : INPUTS STRATÉGIQUES ---
with st.sidebar:
    st.header("1. Cible")
    st.session_state['ent_name'] = st.text_input("Entreprise", st.session_state['ent_name'])
    st.session_state['valo_finale'] = st.number_input("Valo (€)", value=float(st.session_state['valo_finale']))
    
    st.header("2. Localisation")
    ville = st.text_input("Ville", st.session_state['ville'])
    if st.button("📍 Localiser"):
        try:
            geolocator = Nominatim(user_agent="AquaTerminal_v60")
            loc = geolocator.geocode(ville)
            if loc:
                st.session_state['lat'] = loc.latitude
                st.session_state['lon'] = loc.longitude
                st.session_state['ville'] = ville
                st.success("GPS OK")
        except: st.error("Erreur GPS")

# --- CORPS PRINCIPAL ---
t_audit, t_veille, t_db = st.tabs(["📊 Audit & Scoring", "🌍 Veille Automatisée", "💾 Base de Données"])

with t_audit:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("Paramètres de Risque")
        # Inputs liés à votre méthodologie
        p_leg = st.slider("Pression Légale (Réglementaire)", 0, 100, 50)
        p_img = st.slider("Sensibilité Image (Réputation)", 0, 100, 50)
        p_sup = st.slider("Risque Fournisseur (Résilience)", 0, 100, 30)
        
        params = {'pression_legale': p_leg, 'risque_image': p_img}
        st.session_state['part_fournisseur_risk'] = p_sup
        
    with c2:
        if st.button("⚡ LANCER L'ANALYSE (SCORING)", type="primary"):
            # Calcul Pondéré
            sg, s_phy, s_reg, s_rep, s_res = utils.calculate_bloomberg_score(st.session_state, params)
            
            # Stockage en session
            st.session_state['score_global'] = sg
            st.session_state['score_physique'] = s_phy
            st.session_state['score_reglementaire'] = s_reg
            st.session_state['score_reputation'] = s_rep
            st.session_state['score_resilience'] = s_res
            
            # Impact Financier
            st.session_state['var_amount'] = utils.calculate_financial_impact(st.session_state, sg)
            
            st.success("Scoring effectué selon méthodologie pondérée.")

        # Affichage Résultats
        st.metric("SCORE GLOBAL EAU", f"{st.session_state['score_global']:.2f} / 5")
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Physique (40%)", f"{st.session_state.get('score_physique',0):.2f}")
        m2.metric("Réglementaire (30%)", f"{st.session_state.get('score_reglementaire',0):.2f}")
        m3.metric("Réputation (10%)", f"{st.session_state.get('score_reputation',0):.2f}")
        m4.metric("Résilience (20%)", f"{st.session_state.get('score_resilience',0):.2f}")
        
        st.metric("IMPACT FINANCIER ESTIMÉ", f"-{st.session_state['var_amount']:,.0f} €", delta="Risque", delta_color="inverse")
        
        if st.button("💾 ENREGISTRER DANS LE TERMINAL"):
            msg = utils.save_audit_to_db(st.session_state)
            st.toast(msg)

with t_veille:
    st.header("📡 Veille Sectorielle Automatisée")
    st.caption("Agrégation RSS automatique (Google News)")
    
    topic = st.text_input("Sujet de veille", f"{st.session_state['ent_name']} water risk")
    if st.button("🔄 Actualiser le Flux"):
        with st.spinner("Collecte des données..."):
            news = utils.fetch_automated_news(topic)
            st.session_state['news'] = news
            
    for n in st.session_state.get('news', []):
        st.info(f"[{n['date']}] **{n['title']}**\n\n[Lire l'article]({n['link']})")

with t_db:
    st.header("🗄️ Base de Données du Fonds")
    df = utils.load_history()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.caption("Données stockées localement dans aquarisk.db")
    else:
        st.warning("Aucune donnée historique.")

st.divider()
if st.button("📄 Générer Rapport PDF"):
    pdf_bytes = utils.generate_pdf_report(st.session_state)
    st.download_button("Télécharger Audit.pdf", pdf_bytes, "Audit.pdf", "application/pdf")

