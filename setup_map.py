import requests
import zipfile
import io
import os

print("🚀 DÉMARRAGE DU TÉLÉCHARGEMENT AUTOMATIQUE...")
print("Source : Serveurs WRI (Amazon S3) - Version Aqueduct 3.0")

# Lien direct vers la version Shapefile (Fiable et Public)
url = "http://wri-projects.s3.amazonaws.com/Aqueduct30/finalData/Y2019M07D12_Aqueduct30_PPS_V01.zip"

try:
    # 1. Téléchargement
    print("⏳ Téléchargement en cours (500 Mo)... Cela peut prendre 2-3 minutes...")
    r = requests.get(url)
    
    if r.status_code == 200:
        print("✅ Téléchargement terminé. Décompression...")
        
        # 2. Décompression en mémoire
        z = zipfile.ZipFile(io.BytesIO(r.content))
        
        # On extrait seulement le fichier Shapefile (.shp) et ses dépendances (.dbf, .shx, .prj)
        # pour ne pas polluer le dossier.
        fichiers_a_garder = [f for f in z.namelist() if "baseline" in f and f.endswith(('.shp', '.shx', '.dbf', '.prj'))]
        
        z.extractall(path="WRI_Data")
        print(f"✅ Fichiers extraits dans le dossier 'WRI_Data'")
        print("🎉 C'est prêt ! Vous avez maintenant la carte précise.")
        
    else:
        print(f"❌ Erreur de téléchargement : Code {r.status_code}")

except Exception as e:
    print(f"❌ Erreur critique : {e}")
