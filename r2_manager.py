import os
import boto3
from dotenv import load_dotenv

# Charge les variables globales du Cloud (R2)
load_dotenv()

def get_r2_client():
    """Initialise le client S3/R2"""
    return boto3.client(
        's3',
        endpoint_url=os.getenv('R2_ENDPOINT_URL'),
        aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
        region_name='auto'
    )

def upload_stream_to_r2(file_stream, r2_key):
    """
    Envoie un flux binaire (BytesIO) directement vers Cloudflare R2.
    Zéro-Disque : Le fichier ne touche jamais le stockage local.
    """
    client = get_r2_client()
    bucket_name = os.getenv('R2_BUCKET_NAME')
    
    try:
        # On remet le curseur au début au cas où
        file_stream.seek(0)
        client.upload_fileobj(file_stream, bucket_name, r2_key)
        return True
    except Exception as e:
        print(f"Erreur Upload R2 : {e}")
        return False

def get_available_videos_from_r2():
    """Scan le bucket R2 et retourne la liste des vidéos disponibles"""
    # SÉCURITÉ : Chargement silencieux des variables d'environnement (chemin VPS)
    if os.path.exists('/home/datafoot/.env'):
        load_dotenv('/home/datafoot/.env')
    else:
        load_dotenv()
    
    client = get_r2_client()
    bucket_name = os.getenv('R2_BUCKET_NAME')
    
    try:
        # On liste les objets dans le dossier "videos/" du bucket
        response = client.list_objects_v2(Bucket=bucket_name, Prefix='videos/')
        if 'Contents' in response:
            # On extrait uniquement les clés (chemins) des fichiers .mp4, .mkv, .ts
            videos = [item['Key'] for item in response['Contents'] 
                      if item['Key'].lower().endswith(('.mp4', '.mkv', '.ts', '.mov'))]
            # On trie pour l'affichage
            return sorted(videos)
        return []
def get_r2_presigned_url(r2_key, expiration=3600):
    """Génère une URL signée temporaire pour visionner la vidéo dans le navigateur"""
    client = get_r2_client()
    bucket_name = os.getenv('R2_BUCKET_NAME')
    
    try:
        url = client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': r2_key},
            ExpiresIn=expiration
        )
        return url
    except Exception as e:
        print(f"❌ Erreur URL signée R2 : {e}")
        return None
