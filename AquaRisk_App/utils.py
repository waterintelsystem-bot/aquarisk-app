import pandas as pd
import re
import pdfplumber
import yfinance as yf
from fpdf import FPDF
from datetime import datetime
import io
import requests
import feedparser
import xlsxwriter
from thefuzz import process

# --- CONSTANTES AVEC % VISIBLES ---
# On utilise ça pour le menu déroulant
SECTEURS_LISTE = [
    "Agroalimentaire (100%)",
    "Industrie Lourde (80%)",
    "Énergie / Pétrole (70%)",
    "BTP / Construction (60%)",
    "Transport / Logistique (50%)",
    "Luxe / Textile (50%)",
    "Commerce / Retail (40%)",
    "Santé / Pharma (30%)",
    "Services / Logiciel (10%)"
]

def get_vuln_from_sector(sector_str):
    """Extrait le pourcentage du string 'Agro (100%)' -> 1.0"""
    try:
        pct = int(re.findall(r'(\d+)%', sector_str)[0])
        return pct / 100.0
    except: return 0.5

# --- OCR AGRESSIF ---
def clean_number(text_num):
    if not isinstance(text_num, str): return 0.0
    try:
        clean = text_num.replace(' ', '').replace(')', '').replace('(', '-').replace("'", "").replace('"', "")
        clean = re.sub(r'[^\d,\.-]', '', clean).replace(',', '.')
        if clean.count('.') > 1: clean = clean.replace('.', '', clean.count('.') - 1)
        return float(clean)
    except: return 0.0

def run_ocr_scan(file_obj):
    stats = {'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'found': False}
    full_text = ""
    try:
        with pdfplumber.open(file_obj) as pdf:
            for p in pdf.pages[:30]: full_text += (p.extract_text() or "") + "\n"
        
        text_upper = full_text.upper()
        patterns = {
            'ca': ["CHIFFRES D'AFFAIRES", "PRODUITS D'EXPLOITATION", "VENTES", "TOTAL PRODUITS"],
            'res': ["RESULTAT NET", "BENEFICE OU PERTE", "RESULTAT DE L'EXERCICE"],
            'cap': ["CAPITAUX PROPRES", "SITUATION NETTE", "TOTAL PASSIF"]
        }

        for key, keywords in patterns.items():
            for kw in keywords:
                if kw in text_upper:
                    idx = text_upper.find(kw)
                    window = text_upper[idx:idx+400]
                    nums = re.findall(r'-?\s*(?:\d{1,3}(?:\s\d{3})*|\d+)(?:[\.,]\d+)?', window)
                    valid_nums = [clean_number(n) for n in nums if abs(clean_number(n)) > 2050 or (abs(clean_number(n)) > 500 and abs(clean_number(n)) < 1900)]
                    if valid_nums:
                        if key == 'ca': stats['ca'] = max(valid_nums, key=abs)
                        else: stats[key] = valid_nums[0]
                        stats['found'] = True
                        break
    except Exception as e: return stats, str(e)
    return stats, full_text

# --- INTELLIGENCE ---
def get_company_intelligence(name):
    wiki_text = "Pas de données Wikipedia."
    try:
        url = f"https://fr.wikipedia.org/api/rest_v1/page/summary/{name}"
        r = requests.get(url, timeout=2)
        if r.status_code == 200: wiki_text = r.json().get('extract', wiki_text)
    except: pass

    news_items = []
    try:
        import urllib.parse
        q = urllib.parse.quote(f'"{name}" (finance OR business OR climat)')
        f = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
        news_items = [{"title": e.title, "link": e.link} for e in f.entries[:5]]
    except: pass
    return wiki_text, news_items

# --- BOURSE ---
def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker)
        mcap = t.info.get('marketCap') or t.fast_info.get('market_cap')
        name = t.info.get('shortName') or t.info.get('longName')
        sector = t.info.get('sector', "Inconnu")
        return (float(mcap), name, sector) if mcap else (0.0, None, None)
    except: return 0.0, None, None

# --- PDF SOLIDE ---
def generate_pdf_report(data):
    pdf = FPDF()
    pdf.add_page()
    
    # 1. Couverture
    pdf.set_font("Arial", 'B', 24)
    pdf.cell(0, 20, f"RAPPORT D'AUDIT", ln=1, align='C')
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(0, 10, f"{str(data.get('ent_name', 'Société Inconnue')).upper()}", ln=1, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 10, f"Secteur: {str(data.get('secteur', 'Non défini'))} | Date: {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='C')
    pdf.ln(20)
    
    # 2. Finance
    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "1. SYNTHESE FINANCIERE", ln=1, fill=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 8, f"Valorisation Retenue: {data.get('valo_finale', 0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"Mode: {str(data.get('mode_valo', 'N/A'))} / {str(data.get('source_data', 'Manuel'))}", ln=1)
    pdf.cell(0, 8, f"Chiffre d'Affaires: {data.get('ca', 0):,.0f} EUR", ln=1)
    pdf.cell(0, 8, f"Resultat Net: {data.get('res', 0):,.0f} EUR", ln=1)
    pdf.ln(10)

    # 3. Climat & VaR
    pdf.set_fill_color(255, 200, 200)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "2. ANALYSE RISQUES & VAR", ln=1, fill=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", '', 12)
    s30 = data.get('s30', 0)
    pdf.cell(0, 8, f"Score Risque Eau 2030: {s30:.2f} / 5.00", ln=1)
    
    var = data.get('var_amount', 0)
    if var > 0:
        pdf.set_text_color(200, 0, 0) # Rouge
        txt_var = f"PERTE POTENTIELLE (VaR): -{abs(var):,.0f} EUR"
    else:
        pdf.set_text_color(0, 100, 0) # Vert
        txt_var = "IMPACT FINANCIER: Stable / Non significatif"
        
    pdf.cell(0, 8, txt_var, ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(10)

    # 4. Intelligence
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "3. CONTEXTE & INTELLIGENCE", ln=1)
    pdf.set_font("Arial", '', 10)
    
    txt = str(data.get('wiki_summary', 'Pas de résumé.'))[:1500]
    try: txt = txt.encode('latin-1', 'replace').decode('latin-1')
    except: txt = "Erreur encodage texte."
    pdf.multi_cell(0, 5, txt)
    
    # Sources
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 10, "Sources Detectees:", ln=1)
    pdf.set_font("Arial", '', 9)
    news = data.get('news', [])
    if news:
        for n in news:
            try:
                t = n['title'].encode('latin-1', 'replace').decode('latin-1')
                pdf.cell(0, 5, f"- {t}", ln=1, link=n['link'])
            except: continue
    else:
        pdf.cell(0, 5, "Aucune source externe trouvee.", ln=1)

    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_excel(data):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet("Audit")
    headers = ["Metric", "Value", "Detail"]
    rows = [
        ["Name", data.get('ent_name'), data.get('secteur')],
        ["Valuation", data.get('valo_finale'), data.get('mode_valo')],
        ["Revenue (CA)", data.get('ca'), data.get('source_data')],
        ["Net Result", data.get('res'), ""],
        ["Risk Score 2030", data.get('s30'), "/ 5.0"],
        ["VaR Amount", data.get('var_amount'), "EUR"]
    ]
    for col, h in enumerate(headers): ws.write(0, col, h)
    for row, record in enumerate(rows):
        for col, val in enumerate(record): ws.write(row+1, col, val)
    workbook.close()
    return output.getvalue()
    
