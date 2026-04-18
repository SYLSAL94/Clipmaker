"""
ui_match_utils.py
================
Shared utilities for match configuration management, team detection,
and status filtering across different tabs.
"""

import os
import json
import re
import hashlib
import pandas as pd
import streamlit as st
from worker_utils import get_opta_cache_path

# =============================================================================
# CONSTANTS
# =============================================================================

STATUS_FILTER_OPTS = {
    "🎬 Vidéo OK": "v",
    "🎬 Manque Vidéo": "!v",
    "⚙️ Données OK": "c",
    "⚙️ Manque Données": "!c",
    "⏱️ Timings OK": "t",
    "⏱️ Manque Timings": "!t",
    "✅ Match Prêt": "ready",
}


# =============================================================================
# TEAM & KEYWORD DETECTION
# =============================================================================

def extract_match_keywords_from_filenames(configs):
    """Extraction intelligente des noms d'équipes par regex (fallback)."""
    teams = set()
    for c in configs:
        name = os.path.splitext(c)[0]
        clean_name = name.replace("_", " ")
        parts = re.split(r"\s+vs\s+", clean_name, flags=re.IGNORECASE)
        if len(parts) == 2:
            t1, t2 = parts[0], parts[1]
            t1 = re.sub(r".*J\d+\s+", "", t1)
            t1 = re.sub(r".*J\s+", "", t1)
            t2 = re.sub(r"[\-\s]+\d{4}[\-\s]\d{2}[\-\s]\d{2}.*", "", t2)
            t2 = re.sub(r"[\-\s]+\d{4}.*", "", t2)
            if len(t1.strip()) > 1:
                teams.add(t1.strip())
            if len(t2.strip()) > 1:
                teams.add(t2.strip())
        else:
            to_exclude = {"vs", "match", "config", "suaol", "2024", "2023", "2025", "2022", "2021", "2026", "2020", "highlights"}
            for t in re.sub(r"[^a-zA-ZÀ-ÿ0-9]", " ", name).split():
                if t.lower() not in to_exclude and len(t) > 2:
                    teams.add(t)
    return teams


@st.cache_data(show_spinner="🔍 Détection des équipes dans la base...")
def get_real_teams_from_base(config_dir, configs, team_index_dir="team_index_cache"):
    """Explore les fichiers et le cache pour extraire les VRAIS noms d'équipes."""
    os.makedirs(team_index_dir, exist_ok=True)
    base_id = hashlib.md5(config_dir.encode()).hexdigest()[:10]
    cache_path = os.path.join(team_index_dir, f"index_{base_id}.json")

    index = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        except:
            pass

    updated = False
    all_teams = set()

    import concurrent.futures

    def scan_one_config(c):
        path = os.path.join(config_dir, c)
        try:
            mtime = os.path.getmtime(path)
            cached_data = index.get(c)
            if cached_data and cached_data.get("mtime") == mtime:
                return c, cached_data.get("teams", []), mtime, False

            found_teams = set()
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            csv_p = data.get("csv_path", "")
            if csv_p:
                cache_p = get_opta_cache_path(csv_p)
                if os.path.exists(cache_p):
                    # Using only a subset to be fast
                    df_tmp = pd.read_csv(cache_p, usecols=["teamName"], nrows=2000)
                    found_teams.update(df_tmp["teamName"].unique())

            found_teams.update(extract_match_keywords_from_filenames([c]))
            teams_list = [str(t).strip() for t in found_teams if t and str(t).strip()]
            return c, teams_list, mtime, True
        except:
            return c, [], 0, False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(scan_one_config, configs))

    for c, teams_list, mtime, was_updated in results:
        if teams_list:
            all_teams.update(teams_list)
        if was_updated:
            index[c] = {"mtime": mtime, "teams": teams_list}
            updated = True

    if updated:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=4)
        except:
            pass

    return sorted([str(t).strip() for t in all_teams if t and str(t).strip()])


# =============================================================================
# CONFIG FILTERING LOGIC
# =============================================================================

def filter_match_configs(available_match_configs, MATCH_CONFIG_DIR, selected_team_keywords, selected_status_filters, get_config_status_fn):
    """Applique les filtres de mots-clés et de statut à la liste des configs."""
    filtered_match_configs = []
    for cfg in available_match_configs:
        # 1. Filter by keyword
        if selected_team_keywords:
            cfg_clean = cfg.lower().replace("_", " ")
            if not any(k.lower() in cfg_clean for k in selected_team_keywords):
                continue
        
        # 2. Filter by status
        if not selected_status_filters:
            filtered_match_configs.append(cfg)
            continue
            
        v, c, t = get_config_status_fn(cfg, MATCH_CONFIG_DIR)
        is_ready = v and c and t
        keep = True
        for f_name in selected_status_filters:
            logic = STATUS_FILTER_OPTS.get(f_name)
            if logic == "v" and not v: keep = False; break
            if logic == "!v" and v: keep = False; break
            if logic == "c" and not c: keep = False; break
            if logic == "!c" and c: keep = False; break
            if logic == "t" and not t: keep = False; break
            if logic == "!t" and t: keep = False; break
            if logic == "ready" and not is_ready: keep = False; break
        
        if keep:
            filtered_match_configs.append(cfg)
            
    return filtered_match_configs
