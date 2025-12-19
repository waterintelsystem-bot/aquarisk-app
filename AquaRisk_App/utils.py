import pandas as pd
import re
import pdfplumber
import yfinance as yf
from fpdf import FPDF
from datetime import datetime
import io
import requests
from thefuzz import process

# --- MOTEUR OCR INTELLIGENT ---
def clean_number(text_num):
    """Nettoie les formats bizarres (ex: '1 000' ou '(500)')"""
    if not isinstance(text_num, str): return 0.0
    try:
        clean = text_num.replace(' ', '').replace(')', '').replace('(', '-').replace("'", "").replace('"', "")
        clean = re.sub(r'[^\d,\.-]', '', clean).replace(',', '.')
        if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except: return 0.0

def run_ocr_scan(file_obj):
    """Lit le PDF et cherche les gros chiffres autour des mots clés"""
    stats = {'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'found': False}
    full_text = ""
    try:
        with pdfplumber.open(file_obj) as pdf:
            # On lit max 20 pages pour aller vite
            for p in pdf.pages[:20]: full_text += (p.extract_text() or "") + "\n"
        
        text_upper = full_text.upper()
        # Mots clés cibles
        patterns = {
            'ca': ["CHIFFRES D'AFFAIRES", "PRODUITS D'EXPLOITATION", "VENTES", "TOTAL DES PRODUITS"],
            'res': ["RESULTAT NET", "BENEFICE OU PERTE", "RESULTAT DE L'EXERCICE"],
            'cap': ["CAPITAUX PROPRES", "SITUATION NETTE", "TOTAL PASSIF"]
        }

        for key, keywords in patterns.items():
            for kw in keywords:
                if kw in text_upper:
                    idx = text_upper.find(kw)
                    # On regarde une fenêtre de 400 caractères autour du mot
                    window = text_upper[idx:idx+400]
                    # Regex pour capturer les nombres
                    nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', window)
                    
                    valid_nums = []
                    for n in nums:
                        val = clean_number(n)
                        # Filtre anti-bruit (on ignore les années et petits chiffres)
                        if abs(val) > 2050 or (abs(val) > 1000 and abs(val) < 1900):
                            valid_nums.append(val)
                    
                    if valid_nums:
                        # Pour le CA on prend le max, pour le reste le premier pertinent
                        if key == 'ca': stats['ca'] = max(valid_nums, key=abs)
                        else: stats[key] = valid_nums[0]
                        stats['found'] = True
                        break
    except Exception as e:
        return stats, f"Erreur : {str(e)}"
    
    return stats, full_text

# --- MOTEUR BOURSE ---
def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker)
        # On essaie plusieurs champs car l'API change souvent
        mcap = t.info.get('marketCap') or t.fast_info.get('market_cap')
        name = t.info.get('shortName') or t.info.get('longName') or ticker
        return (float(mcap), name) if mcap else (0.0, "Non trouvé")
    except: return 0.0, "Erreur API"

# --- MOTEUR CLIMAT ---
def get_climate_projections(base_score):
    # Simulation d'une trajectoire standard
    s24 = base_score
    s30 = min(base_score * 1.25, 5.0) # +25% de risque
    s26 = s24 + (s30 - s24) * 0.33
    return s24, s26, s30

# --- MOTEUR PDF ---
def generate_pdf_report(data):
    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, f"AUDIT STRATEGIQUE: {data.get('ent_name', 'N/A')}", ln=1, align='C')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 10, f"Genere le {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='C')
    pdf.ln(10)
    
    # Finance
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "1. ANALYSE FINANCIERE", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Valorisation Retenue: {data.get('valo_finale', 0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"Methode: {data.get('mode_valo', 'N/A')}", ln=1)
    pdf.cell(0, 8, f"Chiffre d'Affaires: {data.get('ca', 0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"Resultat Net: {data.get('res', 0):,.0f} EUR", ln=1)
    pdf.ln(5)
    
    # Climat
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "2. IMPACT CLIMATIQUE & RISQUE EAU", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Score Risque 2030: {data.get('s30', 0):.2f} / 5.00", ln=1)
    var = data.get('var_amount', 0)
    txt_var = f"Impact Financier (VaR): -{abs(var):,.0f} EUR" if var > 0 else "Impact Financier: Stable"
    pdf.cell(0, 8, txt_var, ln=1)
    pdf.ln(5)
    
    # Note de synthèse
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "3. SYNTHESE", ln=1)
    pdf.set_font("Arial", '', 10)
    # Encodage sécurisé pour éviter le crash sur les accents
    txt = data.get('txt_synthese', 'Pas de résumé disponible.')
    try: txt = txt.encode('latin-1', 'replace').decode('latin-1')
    except: txt = "Erreur encodage."
    pdf.multi_cell(0, 6, txt)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')
  
