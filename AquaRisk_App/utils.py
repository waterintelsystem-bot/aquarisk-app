import sqlite3
import json

# --- GESTION BASE DE DONNEES (SQLITE) ---

def init_db():
    """Crée la table si elle n'existe pas encore"""
    conn = sqlite3.connect('aquarisk.db')
    c = conn.cursor()
    # On crée une table simple qui stocke les infos clés + tout le reste en JSON
    c.execute('''
        CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            entreprise TEXT,
            ville TEXT,
            pays TEXT,
            score_climat REAL,
            valo_financiere REAL,
            data_complete TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_audit_to_db(data):
    """Sauvegarde l'état actuel (session_state) dans la base"""
    init_db() # Sécurité
    conn = sqlite3.connect('aquarisk.db')
    c = conn.cursor()
    
    # On convertit le dictionnaire complet en texte JSON pour ne rien perdre
    # On exclut les objets non sérialisables comme les images
    clean_data = {k: v for k, v in data.items() if k not in ['news', 'weather_info']}
    json_data = json.dumps(clean_data, default=str)
    
    c.execute('''
        INSERT INTO audits (date, entreprise, ville, pays, score_climat, valo_financiere, data_complete)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        data.get('ent_name', 'Inconnu'),
        data.get('ville', ''),
        data.get('pays', ''),
        data.get('s30', 0.0),
        data.get('valo_finale', 0.0),
        json_data
    ))
    conn.commit()
    conn.close()
    return "Audit sauvegardé avec succès !"

def load_all_audits():
    """Récupère la liste de tous les audits passés"""
    init_db()
    conn = sqlite3.connect('aquarisk.db')
    df = pd.read_sql_query("SELECT id, date, entreprise, ville, pays, score_climat, valo_financiere FROM audits ORDER BY date DESC", conn)
    conn.close()
    return df
    
