import streamlit as st
import pandas as pd
import sqlite3
import json
from datetime import datetime
from fpdf import FPDF
import os
import time

# --- CONFIGURATION ---
st.set_page_config(page_title="AquaRisk AI Terminal", page_icon="💧", layout="wide")

# --- 1. LE CERVEAU (GEMINI + CATALOGUE) ---
class SmartAnalyst:
    def __init__(self, api_key=None):
        self.api_key = api_key
        # Chargement du catalogue de données
        try:
            self.catalog = pd.read_csv("risk_data_sources_catalog.csv")
        except:
            # Fallback si le fichier n'est pas là
            self.catalog = pd.DataFrame([
                {"dataset": "WRI Aqueduct", "provider": "WRI", "typical_use": "Stress Hydrique"},
                {"dataset": "IMF Climate Data", "provider": "IMF", "typical_use": "Risque Macro"}
            ])

    def analyze(self, context_data, prompt_user):
        """Décide entre Simulation et IA Réelle"""
        
        # CAS 1 : PAS DE CLÉ (Mode Simulation)
        if not self.api_key:
            time.sleep(1.5)
            return f"""
            ⚠️ **MODE SIMULATION (Clé API manquante)**
            
            Analyse pour **{context_data.get('ent_name')}** ({context_data.get('ville')}) :
            Le système a identifié des risques potentiels basés sur le secteur **{context_data.get('secteur')}**.
            
            *Pour activer l'intelligence réelle, entrez votre clé API Gemini dans la barre latérale.*
            """
        
        # CAS 2 : CLÉ PRÉSENTE (Mode Réel)
        else:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                model = genai.GenerativeModel('gemini-1.5-pro')
                
                # On prépare les données pour l'IA
                sources_text = self.catalog.to_string() if not self.catalog.empty else "Catalogue vide."
                
                full_prompt = f"""
                Tu es un Analyste Senior en Risques Hydriques pour un fonds d'investissement.
                
                CONTEXTE CLIENT :
                {json.dumps(context_data, indent=2)}
                
                CATALOGUE DE DONNÉES DISPONIBLES (Ne pas inventer, utiliser ces sources) :
                {sources_text}
                
                DEMANDE UTILISATEUR :
                {prompt_user}
                
                INSTRUCTIONS :
                1. Analyse la situation spécifique de l'entreprise.
                2. Cite quelles sources du catalogue (CSV) seraient utiles pour approfondir.
                3. Donne une estimation du risque financier (Low/Medium/High) avec justification.
                4. Sois professionnel, style Bloomberg Terminal.
                """
                
                with st.spinner("🤖 Gemini analyse vos données et le catalogue..."):
                    response = model.generate_content(full_prompt)
                    return response.text
                    
            except Exception as e:
                return f"❌ Erreur de connexion Google Gemini : {str(e)}"

# --- 2. LA MÉMOIRE (BASE DE DONNÉES) ---
class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect("aquarisk_pro.db", check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, secteur TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, name TEXT, pays TEXT, ville TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY AUTOINCREMENT, site_id INTEGER, date TEXT, content TEXT)''')
        self.conn.commit()

    def add_client(self, name, secteur):
        try:
            self.conn.execute("INSERT INTO clients (name, secteur) VALUES (?, ?)", (name, secteur))
            self.conn.commit(); return True
        except: return False

    def get_clients(self): return pd.read_sql("SELECT * FROM clients", self.conn)
    
    def add_site(self, cid, name, pays, ville):
        self.conn.execute("INSERT INTO sites (client_id, name, pays, ville) VALUES (?, ?, ?, ?)", (cid, name, pays, ville))
        self.conn.commit()
        
    def get_sites(self, cid): return pd.read_sql("SELECT * FROM sites WHERE client_id = ?", self.conn, params=(cid,))
    
    def save_audit(self, sid, text):
        self.conn.execute("INSERT INTO audits (site_id, date, content) VALUES (?, ?, ?)", (sid, datetime.now().strftime("%Y-%m-%d %H:%M"), text))
        self.conn.commit()
        
    def get_audits(self, sid): return pd.read_sql("SELECT * FROM audits WHERE site_id = ? ORDER BY date DESC", self.conn, params=(sid,))

# --- 3. L'INTERFACE ---
def main():
    db = DatabaseManager()
    
    # SIDEBAR
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3105/3105807.png", width=50)
        st.title("AquaRisk AI")
        
        # ZONE CLÉ API
        api_input = st.text_input("🔑 Clé API Google Gemini", type="password", placeholder="Collez votre clé AIza...")
        if api_input:
            st.success("Module IA Activé")
            brain = SmartAnalyst(api_key=api_input)
        else:
            st.warning("Mode Simulation (Pas de clé)")
            brain = SmartAnalyst(api_key=None)
            
        st.divider()
        
        # SÉLECTEUR CLIENT
        df_cl = db.get_clients()
        cl_names = df_cl['name'].tolist() if not df_cl.empty else []
        sel_client = st.selectbox("Client", ["+ Nouveau Client"] + cl_names)

    # PAGE PRINCIPALE
    if sel_client == "+ Nouveau Client":
        st.header("Nouveau Dossier Client")
        with st.form("new_cl"):
            n = st.text_input("Nom Entreprise"); s = st.selectbox("Secteur", ["Agroalimentaire", "Industrie", "Tech", "Mines"])
            if st.form_submit_button("Créer"):
                if db.add_client(n, s): st.success("Client créé !"); st.rerun()
                else: st.error("Existe déjà.")

    else:
        # CONTEXTE CLIENT
        client_row = df_cl[df_cl['name'] == sel_client].iloc[0]
        st.title(f"Dossier : {client_row['name']}")
        st.caption(f"Secteur : {client_row['secteur']}")
        
        t1, t2 = st.tabs(["🏭 Sites & Actifs", "🧠 Analyse IA (Bloomberg)"])
        
        with t1:
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Ajouter Site")
                sn = st.text_input("Nom Site"); sv = st.text_input("Ville"); sp = st.text_input("Pays")
                if st.button("Ajouter"): db.add_site(client_row['id'], sn, sp, sv); st.rerun()
            with c2:
                sites = db.get_sites(client_row['id'])
                if not sites.empty: st.dataframe(sites[['name', 'ville', 'pays']], hide_index=True)
                else: st.info("Aucun site.")

        with t2:
            sites = db.get_sites(client_row['id'])
            if sites.empty:
                st.warning("Veuillez créer un site dans l'onglet précédent pour l'analyser.")
            else:
                sel_site_name = st.selectbox("Choisir le site à analyser", sites['name'])
                site_data = sites[sites['name'] == sel_site_name].iloc[0]
                
                st.markdown(f"### 🤖 Analyste Virtuel - {sel_site_name}")
                
                # PROMPT UTILISATEUR
                user_q = st.text_area("Question à l'IA", value=f"Quels sont les risques physiques et réglementaires pour ce site à {site_data['ville']} ? Estime l'impact financier.")
                
                if st.button("Lancer l'Analyse"):
                    context = {"ent_name": client_row['name'], "secteur": client_row['secteur'], "site": site_data['name'], "ville": site_data['ville'], "pays": site_data['pays']}
                    
                    # APPEL IA
                    result = brain.analyze(context, user_q)
                    
                    # AFFICHAGE
                    st.markdown("---")
                    st.markdown(result)
                    
                    # SAUVEGARDE
                    db.save_audit(site_data['id'], result)
                
                # HISTORIQUE
                st.divider()
                st.caption("Historique des analyses")
                h = db.get_audits(site_data['id'])
                for i, r in h.iterrows():
                    with st.expander(f"Analyse du {r['date']}"):
                        st.write(r['content'])

if __name__ == "__main__":
    main()
  
