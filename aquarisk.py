# ==============================================================================
# PROJET AQUARISK V2 - VERSION LOCALE ROBUSTE
# ==============================================================================

import pandas as pd
import folium
from geopy.geocoders import Nominatim
import time

print("🚀 DÉMARRAGE DU SYSTÈME AQUARISK (V2)...")

# --- 1. BASE DE DONNÉES ---
def initialiser_base_donnees():
    csv_content = """region,pays,score_wri,label_wri
brandenburg,germany,3.82,High (40-80%)
central java,indonesia,3.45,High (40-80%)
ömnögovi,mongolia,4.85,Extremely High (>80%)
california,usa,4.10,Extremely High (>80%)
texas,usa,3.95,High (40-80%)
rhône-alpes,france,2.15,Medium-High (20-40%)
"""
    with open("wri_reference_data.csv", "w") as f:
        f.write(csv_content)
    return pd.read_csv("wri_reference_data.csv")

DB_WRI = initialiser_base_donnees()
print("✅ Base de données chargée.")

# --- 2. LE MOTEUR D'ANALYSE (MODIFIÉ) ---
# J'ai changé le timeout à 30 secondes et changé le user_agent
geolocator = Nominatim(user_agent="aquarisk_mac_sweegy_v2", timeout=30)

def auditer_site(nom_site, lat, lon, ca_expose):
    print(f"   🔎 Analyse de : {nom_site}...")
    try:
        # On demande l'adresse
        location = geolocator.reverse(f"{lat}, {lon}", language='en')
        
        if location is None:
            region_detectee = "Inconnue"
            score = 1.0; label = "Low (Défaut)"
        else:
            address = location.raw['address']
            region_detectee = address.get('state', address.get('county', 'Inconnue')).lower()
            
            match = DB_WRI[DB_WRI['region'] == region_detectee]
            if not match.empty:
                data = match.iloc[0]
                score = data['score_wri']
                label = data['label_wri']
            else:
                score = 2.0; label = "Medium (Hors Base)"

        return {
            "nom": nom_site, "lat": lat, "lon": lon,
            "region": region_detectee.title(),
            "score": score, "label": label, "capital": ca_expose
        }
    except Exception as e:
        print(f"   ⚠️ Erreur connexion : {e}")
        return None

# --- 3. EXÉCUTION ---
portefeuille = [
    {"nom": "Rio Tinto (Mine Oyu Tolgoi)", "lat": 43.011, "lon": 106.873, "ca": "12 Mrd $"},
    {"nom": "Tesla (Giga Berlin)", "lat": 52.397, "lon": 13.794, "ca": "20 Mrd $"},
    {"nom": "Danone (Klaten Factory)", "lat": -7.673, "lon": 110.628, "ca": "500 M $"},
{"nom": "Apple (Data Center)", "lat": 39.54, "lon": -119.81, "ca": "Unknown"}
]

resultats = []
print("\n🔄 SCAN EN COURS (Patience, le serveur peut être lent)...")

for site in portefeuille:
    res = auditer_site(site['nom'], site['lat'], site['lon'], site['ca'])
    if res: 
        resultats.append(res)
        print(f"      -> Succès : Région {res['region']} détectée.")
    time.sleep(2) # Pause de 2 secondes entre chaque requête

# --- 4. CARTE ---
print("\n🗺️ GÉNÉRATION DE LA CARTE...")
carte = folium.Map(location=[25, 0], zoom_start=2, tiles='cartodbpositron')

def get_color(score):
    if score >= 4: return 'darkred'
    if score >= 3: return 'red'
    if score >= 2: return 'orange'
    return 'green'

for res in resultats:
    couleur = get_color(res['score'])
    html = f"""
    <div style="font-family:sans-serif; width:200px">
        <h4>{res['nom']}</h4>
        📍 {res['region']}<br>
        <hr>
        🌊 Risque: <b style="color:{couleur}">{res['score']}/5</b><br>
        <i>{res['label']}</i><br>
        💰 En jeu: {res['capital']}
    </div>
    """
    folium.Marker(
        [res['lat'], res['lon']],
        popup=folium.Popup(html, max_width=260),
        icon=folium.Icon(color=couleur, icon="tint", prefix='fa')
    ).add_to(carte)

# SAUVEGARDE
nom_fichier = "Rapport_AquaRisk_Final.html"
carte.save(nom_fichier)
print(f"\n✅ TERMINÉ ! Va ouvrir le fichier '{nom_fichier}' dans ton dossier.")
