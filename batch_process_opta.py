import os
import pandas as pd
from process_opta_data import OptaProcessor
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

def process_single_file(file_path):
    """Fonction isolée pour traiter UN fichier (pour le multi-processing)"""
    processor = OptaProcessor()
    filename = os.path.basename(file_path)
    base_name, _ = os.path.splitext(file_path)
    dir_name = os.path.dirname(file_path)
    final_cache_path = base_name + "_PROCESSED_OPTA.csv"
    
    try:
        # --- PHASE DE NETTOYAGE ---
        match_prefix = os.path.basename(base_name)
        for f in os.listdir(dir_name):
            if f.startswith(match_prefix) and "_PROCESSED_OPTA" in f:
                try:
                    os.remove(os.path.join(dir_name, f))
                except: pass

        # --- PHASE DE TRAITEMENT ---
        processed_data = processor.process_file(file_path)
        df = pd.DataFrame(processed_data)
        df.to_csv(final_cache_path, index=False, encoding='utf-8')
        return f"✅ OK : {filename}"
        
    except Exception as e:
        return f"❌ Erreur sur {filename} : {e}"

def batch_process_parallel(directory_path):
    # Extensions sources (brutes)
    supported_extensions = ('.xlsx', '.xls', '.csv')
    
    print(f"--- Démarrage du mode PARALLÈLE dans : {directory_path} ---")
    
    files_to_process = []
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            if "_PROCESSED_OPTA" in file:
                continue
            if file.lower().endswith(supported_extensions):
                files_to_process.append(os.path.join(root, file))

    total = len(files_to_process)
    if total == 0:
        print("Aucun fichier brut trouvé.")
        return

    # On utilise tous les coeurs moins un pour laisser l'ordi respirer
    num_workers = max(1, multiprocessing.cpu_count() - 1)
    print(f"Lancement de {num_workers} cœurs en simultané pour {total} fichiers...\n")

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(process_single_file, fp): fp for fp in files_to_process}
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            print(f"[{completed}/{total}] {result}")

    print("\n--- Traitement parallèle terminé ---")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Traitement par lot PARALLÈLE des fichiers Opta")
    parser.add_argument("--dir", default=".", help="Dossier à traiter")
    
    args = parser.parse_args()
    target_dir = os.path.abspath(args.dir)
    
    # Indispensable sur Windows pour le multi-processing
    multiprocessing.freeze_support()
    batch_process_parallel(target_dir)
