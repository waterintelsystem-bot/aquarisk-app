import streamlit as st
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
import matplotlib.pyplot as plt
import matplotlib
import tempfile
import os
import random

matplotlib.use('Agg')

# --- INIT MEMOIRE ---
def init_session():
    defaults = {
        'ent_name': "Nouvelle Entreprise",
        'ville': "Paris", 'pays': "France",
        'secteur': "Agroalimentaire (100%)",
        # Finance
        'ca': 0.0, 'res': 0.0, 'cap': 0.0, 'valo_finale': 0.0,
        'mode_valo': "PME", 'source_data': "Manuel",
        # Inputs Risques 360
        'vol_eau': 50000.0, # m3/an
        'prix_eau': 4.5, # €/m3
        'part_fournisseur_risk': 30.0, # %
        'energie_conso': 100000.0, # kWh
        'reut_invest': False,
        # Resultats Risques
        'risk_total_amount': 0.0,
        'water_footprint': 0.0,
        # Docs
        'news': [], 'wiki_summary': "Pas de données.",
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

SECTEURS = {
    "Agroalimentaire (100%)": 1.0, "Chimie (85%)": 0.85, "Industrie (80%)": 0.8,
    "Énergie (70%)": 0.7, "Textile (65%)": 0.65, "BTP (60%)": 0.6,
    "Services (10%)": 0.1
}
SECTEURS_LISTE = list(SECTEURS.keys())
HEADERS = {'User-Agent': 'AquaRisk/1.0'}

# --- MOTEUR DE RISQUES 360 ---
def calculate_360_risks(data, params):
    """
    Calcule l'impact financier (€) selon différents scénarios.
    params: dictionnaire des curseurs (hausse prix eau, taxe carbone, etc)
    """
    risks = {}
    
    # 1. RISQUE OPERATIONNEL (Prix de l'eau)
    # Impact = Volume * (Nouveau Prix - Ancien Prix)
    delta_prix = data['prix_eau'] * (params['hausse_eau_pct'] / 100.0)
    risks['Opérationnel (Coût Eau)'] = data['vol_eau'] * delta_prix

    # 2. RISQUE FOURNISSEUR (Matières Premières)
    # Impact = % CA dépendant fournisseurs * % Risque Geopolitique * Impact Rupture
    # On estime que la part "Achats" est env. 40% du CA
    achats = data['ca'] * 0.40 
    part_exposee = achats * (data['part_fournisseur_risk'] / 100.0)
    risks['Supply Chain (Rupture)'] = part_exposee * (params['impact_geopolitique'] / 100.0)

    # 3. RISQUE REGULATOIRE & NORMES (REUT / Taxes)
    # Si pas de REUT, risque de taxes ou obligation d'investissement forcé
    if not data['reut_invest']:
        # Estimation Coût Station : 1000€ par m3/jour de capacité + OPEX
        vol_jour = data['vol_eau'] / 300
        capex_reut = vol_jour * 1500 # Investissement forcé
        risks['Réglementaire (Mise aux normes)'] = capex_reut * (params['pression_legale'] / 100.0)
    else:
        risks['Réglementaire (Mise aux normes)'] = 0.0

    # 4. RISQUE IMAGE & REPUTATION
    # Impact sur la Valo (pas le CA) : Perte de multiple
    # Ex: Danone accusé d'assécher une nappe => -5% de valo
    risks['Réputation (Boycott/Image)'] = data['valo_finale'] * (params['risque_image'] / 100.0)

    # 5. RISQUE ENERGIE (Water-Energy Nexus)
    # Si le prix de l'eau monte, souvent l'énergie aussi (pompage/traitement)
    risks['Corrélation Énergie'] = (data['energie_conso'] * 0.15) * (params['hausse_energie'] / 100.0)

    total_risk = sum(risks.values())
    return risks, total_risk

def calculate_water_footprint(data):
    # Calcul simplifié Empreinte Eau (Blue + Grey Water)
    # Industrie: Moyenne 50L / € de CA (très variable, c'est une heuristique)
    direct = data['vol_eau'] # Scope 1
    indirect = data['ca'] * 0.02 # Scope 3 (Estimation: 20L par euro de CA généré)
    return direct + indirect

# --- FONCTIONS STANDARDS (GARDÉES) ---
# (Je garde les fonctions PDF, Excel, Yahoo, Pappers de la V36 qui marchaient)
def get_pappers_data(query, api_key):
    # ... (Code identique V36)
    pass 
# ... (J'abrège ici pour la lisibilité, mais il faut garder le contenu de utils.py V36 pour le reste)
# Je remets juste generate_pdf_report modifié pour inclure les risques 360

def generate_pdf_360(data, risks_detail):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, "AUDIT RISQUES 360", ln=1, align='C')
    
    # Tableau Risques
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "DETAIL DES IMPACTS FINANCIERS", ln=1)
    pdf.set_font("Arial", '', 10)
    
    for k, v in risks_detail.items():
        pdf.cell(100, 8, f"{k}", 1)
        pdf.cell(50, 8, f"-{v:,.0f} EUR", 1, ln=1)
        
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"TOTAL RISQUE ESTIME: -{sum(risks_detail.values()):,.0f} EUR", ln=1)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')
    
