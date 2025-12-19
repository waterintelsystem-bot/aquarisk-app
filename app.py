import streamlit as st
import pandas as pd
# Importation sécurisée des librairies
try:
    from geopy.geocoders import Nominatim
except: pass
import time
from random import randint
from fpdf import FPDF
import io
import re
import os
import requests
from bs4 import BeautifulSoup
import pdfplumber
import yfinance as yf
from thefuzz import process
from datetime import datetime, timedelta
from staticmap import StaticMap, CircleMarker
import xlsxwriter

# ==============================================================================
# 1. CONFIGURATION & SESSION (INIT)
# ==============================================================================
st.set_page_config(page_title="AquaRisk V23 : ULTIMATE", page_icon="💎", layout="wide")
st.title("💎 AquaRisk V23 : Audit Complet (Finance, Bourse, Climat)")

# Initialisation SÉCURISÉE des variables de session
# Cela empêche l'écran blanc si on recharge la page
defaults = {
    'finance_ca': 1000000.0, 
    'finance_res': 100000.0, 
    'finance_cap': 200000.0,
    'finance_ebitda': 125000.0,
    'audit_done': False, # Pour savoir si on a lancé un audit
    'audit_data': {},    # Pour stocker les résultats
    'stock_data': {"mcap": 0, "ev": 0},
    'comparables': None,
    'ocr_log': "En attente de fichier..."
}

for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ==============================================================================
# 2. CHARGEMENT DATA (MODE "SANS ÉCHEC")
# ==============================================================================
@st.cache_data
def load_data_safe():
    # Données par défaut pour que l'app ne plante JAMAIS
    df_def = pd.DataFrame({
        'name_0': ['France', 'United States', 'Germany', 'China'],
        'score': [2.5, 3.8, 2.2, 4.1]
    })
    
    # On essaie de lire les fichiers, sinon on prend le défaut
    df_now, df_fut = df_def.copy(), df_def.copy()
    
    try:
        if os.path.exists("risk_actuel.csv"):
            df_now = pd.read_csv("risk_actuel.csv", on_bad_lines='skip')
        if os.path.exists("risk_futur.csv"):
            df_fut = pd.read_csv("risk_futur.csv", on_bad_lines='skip')
            
        # Nettoyage colonnes
        for df in [df_now, df_fut]:
            df.columns = [c.lower().strip() for c in df.columns]
            if 'score' in df.columns:
                df['score'] = pd.to_numeric(df['score'].astype(str).str.replace(',', '.'), errors='coerce')
    except: pass
            
    return df_now, df_fut

df_actuel, df_futur = load_data_safe()

# ==============================================================================
# 3. MOTEUR OCR V7 (SPÉCIAL LIASSE FISCALE)
# ==============================================================================
def clean_number(text_num):
    """Transforme '44 868 910' en 44868910.0"""
    try:
        # On supprime espaces, guillemets, parenthèses
        clean = text_num.replace(' ', '').replace(')', '').replace('(', '-').replace("'", "").replace('"', "")
        # On remplace virgule par point
        clean = clean.replace(',', '.')
        # On garde uniquement chiffres, point, moins
        clean = re.sub(r'[^\d.-]', '', clean)
        return float(clean)
    except: return None

def extract_financials_smart(text):
    """Cherche les données clés dans le texte brut du PDF"""
    data = {"ca": 0, "res": 0, "cap": 0, "found": False}
    
    # 1. On découpe en lignes
    lines = text.split('\n')
    
    # 2. Motifs de recherche (Regex souple)
    # Cherche "Chiffre d'affaires" suivi de n'importe quoi, puis des chiffres
    patterns = {
        "ca": [r"CHIFFRES? D['’\s]?AFFAIRES?", r"TOTAL DES PRODUITS D['’\s]?EXPLOITATION", r"VENTES DE MARCHANDISES"],
        "res": [r"BENEFICE OU PERTE", r"RESULTAT DE L['’\s]?EXERCICE", r"RESULTAT NET"],
        "cap": [r"TOTAL CAPITAUX PROPRES", r"CAPITAUX PROPRES", r"SITUATION NETTE"]
    }
    
    text_upper = text.upper()
    
    # Stratégie : On cherche le mot clé, puis on analyse les nombres sur la même ligne
    for metric, keywords in patterns.items():
        if data[metric] != 0: continue # Déjà trouvé
        
        for line in lines:
            line_up = line.upper()
            # Si un mot clé est présent (ou très proche via Fuzzy)
            found_kw = any(k in line_up for k in keywords)
            if not found_kw:
                # Tentative Fuzzy (si > 90%)
                best, score = process.extractOne(line_up, keywords)
                if score > 90: found_kw = True
            
            if found_kw:
                # Extraction de TOUS les nombres de la ligne
                # Regex : attrape "10 000" ou "- 500.00"
                nums_str = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', line)
                
                valid_nums = []
                for ns in nums_str:
                    val = clean_number(ns)
                    # On ignore les années (2021, 2022) et les petits chiffres (notes)
                    if val and abs(val) > 2030: 
                        valid_nums.append(val)
                
                if valid_nums:
                    # HEURISTIQUE :
                    # CA : Souvent le plus grand chiffre
                    if metric == "ca": data["ca"] = max(valid_nums, key=abs)
                    # Résultat/Capitaux : Souvent le 1er chiffre (colonne N) ou le plus grand
                    else: data[metric] = valid_nums[0]
                    
                    data["found"] = True
                    break # On passe à la métrique suivante
    return data

def read_pdf(file):
    if not file: return ""
    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            # On lit jusqu'à 50 pages pour trouver la liasse
            for p in pdf.pages[:50]:
                extracted = p.extract_text()
                if extracted: text += extracted + "\n"
    except: pass
    return text

# ==============================================================================
# 4. FONCTIONS FINANCIERES & BOURSE
# ==============================================================================
def get_comparables(sector):
    """Récupère les données boursières via Yahoo Finance"""
    # Mapping Secteur -> Tickers
    mapping = {
        "Agro": ["BN.PA", "NESN.SW", "KO"], # Danone, Nestlé, Coca
        "Indus": ["AIR.PA", "SAF.PA", "SIE.DE"],
        "Tech": ["DSY.PA", "CAP.PA", "MSFT"],
        "BTP": ["DG.PA", "EN.PA", "HO.PA"],
        "Comm": ["CA.PA", "WMT", "AMZN"]
    }
    # Fallback Agro par défaut
    key = sector.split()[0][:4]
    tickers = mapping.get(key, ["BN.PA"])
    
    data = []
    for t in tickers:
        try:
            s = yf.Ticker(t)
            i = s.info
            pe = i.get('trailingPE', 'N/A')
            pb = i.get('priceToBook', 'N/A')
            mcap = i.get('marketCap', 0)
            name = i.get('shortName', t)
            
            if mcap > 0:
                data.append({
                    "Société": name,
                    "Ticker": t,
                    "P/E Ratio": pe,
                    "Valo (Mds)": f"{mcap/1e9:.1f} B$"
                })
        except: continue
        
    return pd.DataFrame(data)

def calculate_ratios(ca, res, cap):
    r = {}
    r['Marge Nette'] = (res / ca * 100) if ca else 0
    r['ROE'] = (res / cap * 100) if cap else 0
    return r

# ==============================================================================
# 5. FONCTIONS PDF & EXCEL
# ==============================================================================
def create_pdf(data):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"AUDIT: {data.get('ent', '?')}", ln=1, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "1. SYNTHESE FINANCIERE", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Valorisation Retenue: {data.get('valo',0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"Chiffre d'Affaires: {data.get('ca',0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"Resultat Net: {data.get('res',0):,.0f} EUR", ln=1)
    
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "2. RISQUE CLIMATIQUE (EAU)", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Score Risque 2030: {data.get('s30',0):.2f} / 5", ln=1)
    pdf.cell(0, 8, f"Impact Financier (VaR): {data.get('var',0):,.0f} EUR", ln=1)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

def create_excel(data):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet()
    
    # Headers
    headers = ["Indicateur", "Valeur", "Unité"]
    for col, h in enumerate(headers): worksheet.write(0, col, h)
    
    # Rows
    rows = [
        ("Entreprise", data.get('ent'), "Nom"),
        ("Valorisation", data.get('valo'), "EUR"),
        ("Chiffre d'Affaires", data.get('ca'), "EUR"),
        ("Résultat Net", data.get('res'), "EUR"),
        ("Score Eau 2030", data.get('s30'), "/5"),
        ("Impact VaR", data.get('var'), "EUR")
    ]
    
    for row_idx, row_data in enumerate(rows):
        for col_idx, cell_data in enumerate(row_data):
            worksheet.write(row_idx+1, col_idx, cell_data)
            
    workbook.close()
    return output.getvalue()

# ==============================================================================
# 6. INTERFACE UTILISATEUR (LAYOUT)
# ==============================================================================
# Sidebar
with st.sidebar:
    st.header("Paramètres")
    api_key = st.text_input("Clé Pappers (Optionnel)", type="password")
    st.info("💡 Sans clé, utilisez l'OCR PDF ou la saisie manuelle.")

# Colonnes principales
col_left, col_right = st.columns([1, 1.5])

# --- COLONNE GAUCHE : SAISIE ---
with col_left:
    st.subheader("1. Entreprise & Données")
    
    ent_name = st.text_input("Nom", "Michel et Augustin")
    ville = st.text_input("Ville (Siège)", "Issy-les-Moulineaux")
    pays = st.text_input("Pays", "France")
    
    st.markdown("---")
    st.subheader("2. Finance")
    
    type_ent = st.radio("Type", ["Non Cotée (PME)", "Cotée (Bourse)", "Startup (VC)"])
    
    # SECTEUR (Pour Risque & Comparables)
    secteur = st.selectbox("Secteur d'Activité", 
                           ["Agroalimentaire (100% Vulnérable)", 
                            "Industrie (70% Vulnérable)", 
                            "BTP (40% Vulnérable)", 
                            "Logiciel (5% Vulnérable)"])
    vuln_factor = float(re.findall(r'\d+', secteur)[0]) / 100
    
    # --- LOGIQUE SPECIFIQUE ---
    val_finale = 0.0
    
    if type_ent == "Non Cotée (PME)":
        # ZONE PDF
        st.caption("📄 Glissez votre Liasse Fiscale / Bilan PDF")
        uploaded_pdf = st.file_uploader("Upload PDF", type=["pdf"])
        
        if uploaded_pdf:
            # Lecture OCR Immédiate
            if st.button("🧠 Analyser le PDF"):
                with st.spinner("Lecture intelligente..."):
                    raw_text = read_pdf(uploaded_pdf)
                    fin_data = extract_financials_smart(raw_text)
                    
                    if fin_data['found']:
                        # MISE A JOUR SESSION STATE
                        st.session_state.finance_ca = fin_data['ca']
                        st.session_state.finance_res = fin_data['res']
                        st.session_state.finance_cap = fin_data['cap']
                        # Approx EBITDA
                        st.session_state.finance_ebitda = fin_data['res'] * 1.25
                        st.success("✅ Données extraites !")
                        st.session_state.ocr_log = f"CA: {fin_data['ca']:,.0f} | Res: {fin_data['res']:,.0f}"
                    else:
                        st.warning("⚠️ Pas de chiffres nets trouvés. Saisie manuelle requise.")
                        st.session_state.ocr_log = "Échec OCR"
        
        if st.session_state.ocr_log != "En attente de fichier...":
            st.caption(f"Log OCR: {st.session_state.ocr_log}")

        # CHAMPS DE SAISIE (Pré-remplis par session_state)
        # Note : On utilise key= pour lier au session_state
        methode = st.selectbox("Méthode Valo", ["Multiple CA", "Multiple EBITDA", "DCF"])
        
        if methode == "Multiple CA":
            ca_input = st.number_input("Chiffre d'Affaires (€)", key="finance_ca")
            mult = st.slider("Multiple", 0.5, 5.0, 1.5)
            val_finale = ca_input * mult
            
        elif methode == "Multiple EBITDA":
            ebitda_input = st.number_input("EBITDA (€)", key="finance_ebitda")
            mult = st.slider("Multiple", 2.0, 15.0, 7.0)
            val_finale = ebitda_input * mult
            
        elif methode == "DCF":
            fcf_input = st.number_input("Flux Trésorerie (FCF) (€)", key="finance_res")
            wacc = st.number_input("WACC (%)", 5.0, 15.0, 10.0) / 100
            g = st.number_input("Croissance (%)", 0.0, 5.0, 2.0) / 100
            if wacc > g: val_finale = fcf_input * (1+g)/(wacc-g)
            
    elif type_ent == "Cotée (Bourse)":
        ticker = st.text_input("Ticker Yahoo", "BN.PA")
        if st.button("Charger Cours"):
            try:
                info = yf.Ticker(ticker).info
                mcap = info.get('marketCap', 0)
                st.session_state.stock_data['mcap'] = mcap
                st.success(f"Market Cap: {mcap:,.0f}")
            except: st.error("Ticker inconnu")
        val_finale = st.number_input("Valo Boursière", value=float(st.session_state.stock_data['mcap']))
        
    else: # Startup
        stade = st.selectbox("Stade", ["Seed (2-8M)", "Series A (8-30M)", "Series B (30-80M)"])
        ranges = {"Seed": (2e6, 8e6), "Series A": (8e6, 30e6), "Series B": (30e6, 80e6)}
        mini, maxi = ranges.get(stade.split()[0], (1e6, 5e6))
        val_finale = st.slider("Valo VC (€)", mini, maxi, (mini+maxi)/2)

    # BOUTON PRINCIPAL
    st.markdown("---")
    if st.button("🚀 LANCER L'AUDIT COMPLET", type="primary"):
        # Calculs Climat
        s24 = 2.5 # Simulé (ou via CSV si dispo)
        s30 = s24 * 1.1 # Dégradation par défaut
        
        # VaR
        delta_risk = s30 - s24
        var_amount = val_finale * (delta_risk / 5.0) * vuln_factor
        
        # Stockage
        st.session_state.audit_data = {
            "ent": ent_name, "ville": ville, "valo": val_finale,
            "ca": st.session_state.finance_ca, "res": st.session_state.finance_res,
            "s24": s24, "s30": s30, "var": var_amount, "vuln": vuln_factor
        }
        st.session_state.audit_done = True
        
        # Comparables
        st.session_state.comparables = get_comparables(secteur)

# --- COLONNE DROITE : RÉSULTATS ---
with col_right:
    st.subheader("📊 Tableau de Bord")
    
    if st.session_state.audit_done:
        d = st.session_state.audit_data
        
        # 1. KPIs
        k1, k2, k3 = st.columns(3)
        k1.metric("Valorisation", f"{d['valo']:,.0f} €")
        k2.metric("Risque Eau 2030", f"{d['s30']:.2f}/5", delta=f"{d['s30']-d['s24']:.2f}", delta_color="inverse")
        
        # VaR Couleur
        var_col = "inverse" if d['var'] > 0 else "normal"
        lbl_var = f"-{abs(d['var']):,.0f} €" if d['var'] > 0 else "Stable"
        k3.metric("Impact Financier", lbl_var, delta="VaR 2030", delta_color=var_col)
        
        # 2. Ratios
        if d['ca'] > 0:
            marge = (d['res'] / d['ca']) * 100
            st.progress(min(max(marge+50, 0), 100)/100, text=f"Marge Nette: {marge:.1f}%")
        
        # 3. Onglets
        tab1, tab2, tab3 = st.tabs(["📄 Rapports", "📈 Bourse", "🌍 Climat"])
        
        with tab1:
            st.success("Documents générés")
            col_pdf, col_xls = st.columns(2)
            with col_pdf:
                pdf_data = create_pdf(d)
                st.download_button("Télécharger PDF", pdf_data, file_name="Audit_Complet.pdf", mime="application/pdf")
            with col_xls:
                xls_data = create_excel(d)
                st.download_button("Télécharger Excel", xls_data, file_name="Donnees_Audit.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
        with tab2:
            st.write("#### Comparables Sectoriels")
            if st.session_state.comparables is not None:
                st.dataframe(st.session_state.comparables, use_container_width=True)
            else:
                st.info("Pas de données boursières disponibles.")
                
        with tab3:
            st.write(f"**Vulnérabilité Secteur :** {d['vuln']*100:.0f}%")
            st.write("Localisation :", d['ville'])
            # Carte statique simple (simulée ici pour éviter dépendance complexe)
            st.map(pd.DataFrame({'lat': [48.823], 'lon': [2.269]})) # Issy
            
    else:
        # Message d'accueil si pas encore d'audit
        st.info("👈 Veuillez entrer les données à gauche et cliquer sur 'LANCER L'AUDIT'.")
        st.write("Ce dashboard affichera :")
        st.write("- La valorisation calculée")
        st.write("- L'impact du risque eau sur le bilan")
        st.write("- Les comparables boursiers (Danone, Nestlé...)")
        
