import streamlit as st
import utils

# 1. INITIALISATION
utils.init_session()
st.title("💰 Finance & Identité")

# --- IDENTITE (Mémoire persistante) ---
c1, c2 = st.columns(2)
with c1: 
    # Le champ lit la valeur en mémoire 'ent_name'
    st.session_state['ent_name'] = st.text_input("Nom Entreprise", value=st.session_state['ent_name'])
with c2: 
    # On trouve l'index du secteur sauvegardé pour le pré-selectionner
    try:
        idx_secteur = utils.SECTEURS_LISTE.index(st.session_state.get('secteur', utils.SECTEURS_LISTE[0]))
    except: idx_secteur = 0
    
    st.session_state['secteur'] = st.selectbox(
        "Secteur (Impact Vulnérabilité)", 
        utils.SECTEURS_LISTE,
        index=idx_secteur
    )

st.divider()

# --- VALORISATION (CORRECTION BUG MEMOIRE) ---
# On définit les modes
modes = ["PME (Bilan)", "Cotée (Bourse)", "Startup"]

# On récupère le mode sauvegardé en mémoire, sinon on prend le premier
saved_mode = st.session_state.get('mode_valo', modes[0])
try:
    idx_mode = modes.index(saved_mode)
except: idx_mode = 0

# On force le widget à utiliser l'index sauvegardé
mode = st.radio("Mode", modes, index=idx_mode, horizontal=True)
st.session_state['mode_valo'] = mode # On met à jour la mémoire

# --- LOGIQUE PME ---
if mode == "PME (Bilan)":
    t1, t2 = st.tabs(["📄 OCR PDF", "🔍 Pappers"])
    
    with t1:
        uploaded = st.file_uploader("Bilan PDF", type=["pdf"])
        if uploaded and st.button("Lancer OCR"):
            stats, msg = utils.run_ocr_scan(uploaded)
            if stats['found']:
                st.session_state['ca'] = stats['ca']
                st.session_state['res'] = stats['res']
                st.session_state['cap'] = stats['cap']
                st.session_state['source_data'] = "OCR PDF"
                st.success(f"✅ OCR : {msg}")
            else: st.error(f"❌ OCR : {msg}")

    with t2:
        # On garde la clé Pappers en mémoire si elle existe
        pk = st.text_input("Clé API Pappers", type="password", value=st.session_state.get('pappers_key_input', ''))
        query = st.text_input("Nom ou SIREN")
        
        if st.button("Chercher Pappers"):
            if pk:
                st.session_state['pappers_key_input'] = pk # Sauvegarde technique
                stats, nom = utils.get_pappers_data(query, pk)
                if stats:
                    st.session_state['ca'] = stats['ca']
                    st.session_state['res'] = stats['res']
                    st.session_state['cap'] = stats['cap']
                    st.session_state['ent_name'] = nom
                    st.session_state['source_data'] = "Pappers"
                    st.success(f"Trouvé: {nom}")
                    st.rerun() # Force le rafraichissement des champs
                else: st.error(nom)

    st.markdown("#### Données Financières")
    c_ca, c_res, c_cap = st.columns(3)
    # Les champs lisent la mémoire (value=...)
    with c_ca: st.session_state['ca'] = st.number_input("CA (€)", value=st.session_state['ca'])
    with c_res: st.session_state['res'] = st.number_input("Résultat (€)", value=st.session_state['res'])
    with c_cap: st.session_state['cap'] = st.number_input("Capitaux (€)", value=st.session_state['cap'])
    
    meth = st.selectbox("Méthode", ["Multiple CA", "Multiple EBITDA", "Patrimonial", "DCF"])
    
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
    elif meth == "DCF":
        wacc = st.number_input("WACC (%)", 5.0, 15.0, 10.0)/100
        g = st.number_input("Croissance (%)", 0.0, 5.0, 1.5)/100
        fcf = st.session_state['res'] # Proxy
        if wacc > g: val_calc = fcf / (wacc - g)
    
    st.session_state['valo_finale'] = val_calc

# --- LOGIQUE BOURSE ---
elif mode == "Cotée (Bourse)":
    # On mémorise le ticker
    current_ticker = st.session_state.get('ticker_input', 'BN.PA')
    tick = st.text_input("Ticker ou Nom (ex: Danone, BN.PA)", value=current_ticker)
    st.session_state['ticker_input'] = tick # Sauvegarde
    
    if st.button("Chercher Yahoo"):
        val, nom, sec, full_t = utils.get_yahoo_data(tick)
        if val > 0:
            st.session_state['valo_finale'] = val
            st.session_state['ent_name'] = nom
            st.session_state['source_data'] = f"Yahoo {full_t}"
            # Ratios estimés pour l'affichage
            st.session_state['ca'] = val * 0.5 
            st.session_state['res'] = val * 0.05
            st.success(f"Trouvé : {nom} ({sec})")
            st.rerun() # IMPORTANT : Recharge la page pour afficher la valo mise à jour
        else: st.error("Introuvable.")
    
    # Champ modifiable mais pré-rempli avec la mémoire
    new_valo = st.number_input("Valo Bourse (€)", value=float(st.session_state['valo_finale']))
    st.session_state['valo_finale'] = new_valo

# --- LOGIQUE STARTUP ---
else: 
    stade = st.selectbox("Stade", ["Pre-Seed", "Seed", "Series A", "Series B"])
    ranges = {"Pre-Seed": 1.5e6, "Seed": 5e6, "Series A": 15e6, "Series B": 50e6}
    # On utilise une clé session state pour le slider pour qu'il garde sa position
    if 'startup_valo' not in st.session_state:
        st.session_state['startup_valo'] = ranges[stade.split()[0]]
        
    val_manual = st.slider("Valo", 500000.0, 100000000.0, st.session_state.get('startup_valo', ranges[stade.split()[0]]), key="slider_startup")
    st.session_state['valo_finale'] = val_manual

# --- VALIDATION ---
st.divider()
st.info(f"Valorisation Retenue : {st.session_state['valo_finale']:,.0f} €")

# Pas besoin de bouton "Valider" si on utilise st.session_state directement, 
# mais on peut en garder un pour confirmer visuellement
if st.button("✅ SAUVEGARDER & CONTINUER", type="primary"):
    st.success("Données sauvegardées en mémoire. Vous pouvez aller sur l'onglet Climat.")
    
