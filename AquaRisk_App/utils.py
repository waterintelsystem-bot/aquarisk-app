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

# --- CONSTANTES ---
SECTEURS = {
    "Agroalimentaire": 1.0,
    "Industrie Lourde": 0.8,
    "Énergie / Pétrole": 0.7,
    "BTP / Construction": 0.6,
    "Transport / Logistique": 0.5,
    "Luxe / Textile": 0.5,
    "Commerce / Retail": 0.4,
    "Santé / Pharma": 0.3,
    "Services / Logiciel": 0.1
}

# --- OCR AGRESSIF (V27 RESTAURE) ---
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

# --- INTELLIGENCE (WIKI & NEWS) ---
def get_company_intelligence(name):
    # 1. Wikipedia
    wiki_text = "Pas de données Wikipedia."
    try:
        url = f"https://fr.wikipedia.org/api/rest_v1/page/summary/{name}"
        r = requests.get(url, timeout=2)
        if r.status_code == 200: wiki_text = r.json().get('extract', wiki_text)
    except: pass

    # 2. News (Google RSS)
    news_items = []
    try:
        import urllib.parse
        q = urllib.parse.quote(f'"{name}" (finance OR business OR climat)')
        f = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=fr-FR&gl=FR&ceid=FR:fr")
        news_items = [{"title": e.title, "link": e.link} for e in f.entries[:5]]
    except: pass

    return wiki_text, news_items

# --- BOURSE SECURISEE ---
def get_yahoo_data(ticker):
    try:
        t = yf.Ticker(ticker)
        # On tente plusieurs accès car l'API change souvent
        mcap = t.info.get('marketCap') or t.fast_info.get('market_cap')
        name = t.info.get('shortName') or t.info.get('longName')
        sector = t.info.get('sector', "Inconnu")
        return (float(mcap), name, sector) if mcap else (0.0, None, None)
    except: return 0.0, None, None

# --- EXCEL EXPORT ---
def generate_excel(data):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet("Audit")
    
    headers = ["Métrique", "Valeur", "Détail"]
    rows = [
        ["Entreprise", data['ent_name'], data['secteur']],
        ["Valorisation", data['valo_finale'], data['mode_valo']],
        ["CA", data['ca'], data['source_data']],
        ["Résultat", data['res'], ""],
        ["Score Climat 2030", data['s30'], "/ 5.0"],
        ["Impact VaR", data['var_amount'], "Perte potentielle"]
    ]
    
    for col, h in enumerate(headers): ws.write(0, col, h)
    for row, record in enumerate(rows):
        for col, val in enumerate(record):
            ws.write(row+1, col, val)
            
    workbook.close()
    return output.getvalue()

# --- PDF EXPORT ---
def generate_pdf_report(data):
    pdf = FPDF()
    pdf.add_page()
    
    # En-tête
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, f"AUDIT: {data.get('ent_name', 'N/A')}", ln=1, align='C')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 10, f"Secteur: {data.get('secteur', '?')} | Date: {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='C')
    pdf.ln(10)
    
    # Résumé IA
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "1. CONTEXTE & SYNTHESE", ln=1)
    pdf.set_font("Arial", '', 10)
    txt = data.get('wiki_summary', '')[:1000]
    try: txt = txt.encode('latin-1', 'replace').decode('latin-1')
    except: txt = "Erreur encodage."
    pdf.multi_cell(0, 5, txt)
    pdf.ln(5)

    # Finance
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "2. FINANCE", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Valorisation: {data.get('valo_finale', 0):,.0f} EUR ({data.get('mode_valo')})", ln=1)
    pdf.cell(0, 8, f"CA: {data.get('ca', 0):,.0f} EUR | Res. Net: {data.get('res', 0):,.0f} EUR", ln=1)
    
    # Climat
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "3. CLIMAT & RISQUES", ln=1)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Score Risque 2030: {data.get('s30', 0):.2f} / 5.00", ln=1)
    var = data.get('var_amount', 0)
    pdf.cell(0, 8, f"Impact Financier (VaR): -{abs(var):,.0f} EUR", ln=1)
    
    # Sources
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "4. SOURCES", ln=1)
    pdf.set_font("Arial", '', 9)
    for n in data.get('news', []):
        try:
            title = n['title'].encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 5, f"- {title}", ln=1, link=n['link'])
        except: continue
            
    return pdf.output(dest='S').encode('latin-1', 'replace')
    
