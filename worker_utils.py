import os
import json
import pandas as pd
import datetime
from process_opta_data import OptaProcessor

# Removed hardcoded MATCH_CONFIG_DIR - now passed as argument to tasks

def get_opta_cache_path(path):
    """
    Returns the standard cache path for a given CSV/Excel file.
    Always points to 'filename_PROCESSED_OPTA.csv' even if given a processed file.
    """
    if not path: return ""
    clean_path = path.strip().strip("\"'")
    dir_name = os.path.dirname(clean_path)
    base_name = os.path.splitext(os.path.basename(clean_path))[0]
    if "_PROCESSED_OPTA" in base_name:
        base_name = base_name.split("_PROCESSED_OPTA")[0]
    return os.path.join(dir_name, base_name + "_PROCESSED_OPTA.csv")

def delete_opta_cache(path):
    """
    Aggressively deletes all cache files associated with a source file.
    Useful for cleaning up files like '_PROCESSED_OPTA_PROCESSED_OPTA.csv'.
    """
    if not path: return
    clean_path = path.strip().strip("\"'")
    if not os.path.exists(os.path.dirname(clean_path)): return
    
    dir_name = os.path.dirname(clean_path)
    base_name = os.path.splitext(os.path.basename(clean_path))[0]
    if "_PROCESSED_OPTA" in base_name:
        base_name = base_name.split("_PROCESSED_OPTA")[0]
    
    for f in os.listdir(dir_name):
        if f.startswith(base_name) and "_PROCESSED_OPTA" in f:
            try:
                os.remove(os.path.join(dir_name, f))
            except:
                pass

def process_task(args):
    """
    args = (config_name, match_config_dir)
    """
    config_name, match_config_dir = args
    # This MUST stay at the top level of its module for ProcessPoolExecutor on Windows.
    # We put it in a separate file to ensure it's imported cleanly by child processes.
    try:
        path = os.path.join(match_config_dir, config_name)
        with open(path, "r", encoding="utf-8") as f:
            c_data = json.load(f)
        
        raw_csv = c_data.get("csv_path", "").strip().strip("\"'")
        if not raw_csv or not os.path.exists(raw_csv): 
            return False, f"Fichier CSV introuvable pour {config_name}"
        
        # --- PHASE DE NETTOYAGE AGGRESSIVE ---
        delete_opta_cache(raw_csv)
        final_cache_path = get_opta_cache_path(raw_csv)
        
        processor = OptaProcessor()
        processed_events = processor.process_file(raw_csv)
        pd.DataFrame(processed_events).to_csv(final_cache_path, index=False)
        return True, config_name
    except Exception as e:
        return False, f"Échec sur {config_name}: {e}"

def load_match_data_task(args):
    """
    Worker function to load (or process if needed) a single match's data.
    Must be top-level for ProcessPoolExecutor.
    args = (config_name, match_config_dir)
    """
    config_name, match_config_dir = args
    try:
        import os
        import json
        import pandas as pd
        from process_opta_data import OptaProcessor
        
        path = os.path.join(match_config_dir, config_name)
        with open(path, "r", encoding="utf-8") as f:
            c_data = json.load(f)
        
        source_path = c_data.get("csv_path", "").strip().strip("\"'")
        if not source_path or not os.path.exists(source_path):
            return None
        
        clean_cache_path = get_opta_cache_path(source_path)
        
        m_df = None
        if os.path.exists(clean_cache_path):
            m_df = pd.read_csv(clean_cache_path)
            # Check validity (need one_two_score marker)
            if 'one_two_score' not in m_df.columns:
                m_df = None
        
        if m_df is None:
            processor = OptaProcessor()
            processed_events = processor.process_file(source_path)
            m_df = pd.DataFrame(processed_events)
            m_df.to_csv(clean_cache_path, index=False)
        
        m_df["_source_config_file"] = config_name
        m_df["_source_config_dir"] = match_config_dir
        return m_df
    except Exception as e:
        print(f"Erreur fusion sur {config_name}: {e}")
        return None
