"""
app_streamlit.py  (REFACTORED ORCHESTRATOR)
============================================
Point d'entrée de ClipMaker SUAOL.
Ce fichier est volontairement réduit à son rôle d'orchestrateur :
il initialise l'application, configure la page, injecte le CSS, et
délègue chaque responsabilité aux modules dédiés.

Architecture des modules :
  ui_theme.py          → Constantes CSS, logo_header, step_header, inject_global_css
  ui_helpers.py        → browse_file/folder, open_file_location, play_video,
                         open_premiere, interleave_specs, safe_rerun
  ui_session_state.py  → init_session_state, build_global_filter_config
  ui_sidebar.py        → render_sidebar, render_right_column, reset_action_filters
  tab_config.py        → render_tab_config
  tab_batch.py         → render_tab_batch
  tab_filter.py        → render_tab_filter
  tab_preview.py       → render_tab_preview
  tab_buildup.py       → render_tab_buildup
  tab_shots.py         → render_tab_shots
  tab_export.py        → render_tab_export
  run_logic.py         → run_single_match_dialog,
                         run_turbo_batch_dialog,
                         run_aggregate_dialog
"""

import sys
import os
import json
import threading
import queue
import time
import concurrent.futures
import platform

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
import psycopg2
import boto3
from dotenv import load_dotenv

load_dotenv()  # Charge ton fichier .env

# Core processing imports
from interactive_visualizations import plot_interactive_pitch, plot_tactical_sequence
from smp_component import shot_map
from clip_processing import (
    to_seconds, get_merged_specs_from_df, get_ffmpeg_binary,
    assign_periods, match_clock_to_video_time, FLAT_ZONES,
    apply_filters, run_clip_maker, export_to_premiere_xml,
    cut_and_concat_ffmpeg,
)
from worker_utils import get_opta_cache_path, delete_opta_cache, process_task, load_match_data_task
from dashboard_analytics import compute_pass_connections, compute_duel_connections, compute_player_leaderboard, extract_ui_filters_options

# --- UI modules ---
from ui_theme import ACCENT, BG_BASE, BG_SURFACE, BG_BORDER, TEXT_MUTED, logo_header, step_header, inject_global_css
from ui_helpers import (
    browse_file, browse_folder, get_initial_dir,
    open_file_location, play_video, open_premiere,
    interleave_specs, safe_rerun, get_ffmpeg_path,
)
from ui_session_state import init_session_state, build_global_filter_config
from ui_sidebar import render_sidebar, render_right_column

# --- Tab modules ---
from tab_config import render_tab_config
from tab_batch import render_tab_batch
from tab_filter import render_tab_filter
from tab_preview import render_tab_preview
from tab_buildup import render_tab_buildup
from tab_shots import render_tab_shots
from tab_export import render_tab_export

# --- Run logic ---
from run_logic import (
    process_single_match_dialog,
    process_turbo_batch_dialog,
    process_aggregate_dialog,
    process_batch_item,
)

# =============================================================================
# DIRECTORIES & CONSTANTS
# =============================================================================
# =============================================================================
# DIRECTORIES & CONSTANTS (Normalized for VPS/Windows)
# =============================================================================
PROJECT_ROOT = "/home/datafoot" if platform.system() == "Linux" else os.getcwd()

def get_abs_path(rel_path):
    # Removes Windows drive letter if we are on Linux
    if platform.system() == "Linux" and ":" in rel_path and not rel_path.startswith("/"):
        rel_path = rel_path.split(":")[-1]
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.abspath(os.path.join(PROJECT_ROOT, rel_path))

BASKET_DIR = get_abs_path("saved_baskets")
TEAM_INDEX_DIR = get_abs_path("team_index_cache")
TEMP_DIR = get_abs_path("temp_previews")
PROFILE_DIR = get_abs_path("profiles")

os.makedirs(BASKET_DIR, exist_ok=True)
os.makedirs(TEAM_INDEX_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)

# =============================================================================
# PAGE CONFIG  (must be first Streamlit call)
# =============================================================================
st.set_page_config(page_title="ClipMaker 1.1 by B4L1", page_icon="⚽", layout="wide")
inject_global_css()


# =============================================================================
# AUTHENTICATION & DATABASE
# =============================================================================

def get_user_data(username):
    """
    Récupère les informations d'un utilisateur spécifique depuis PostgreSQL.
    """
    try:
        conn = psycopg2.connect(
            host="127.0.0.1",
            port="5432",
            database="datafoot_db",
            user="analyst_admin",
            password=os.getenv("POSTGRES_PWD", "SUAOLPostgres1994!")
        )
        cur = conn.cursor()
        cur.execute("SELECT username, email, password_hash FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        return user
    except Exception:
        return None

def get_all_users():
    """
    Récupère tous les utilisateurs pour initialiser Streamlit Authenticator.
    """
    credentials = {"usernames": {}}
    try:
        conn = psycopg2.connect(
            host="127.0.0.1",
            port="5432",
            database="datafoot_db",
            user="analyst_admin",
            password=os.getenv("POSTGRES_PWD", "SUAOLPostgres1994!")
        )
        cur = conn.cursor()
        cur.execute("SELECT username, email, password_hash FROM users")
        rows = cur.fetchall()
        
        for row in rows:
            username, email, password_hash = row
            credentials["usernames"][username] = {
                "email": email,
                "name": username,  # Optionnel mais recommandé par stauth
                "password": password_hash
            }
        cur.close()
        conn.close()
    except Exception as e:
        st.error(f"⚠️ Erreur de connexion PostgreSQL : {e}")
    return credentials



# =============================================================================
# CONFIG STATUS HELPER
# =============================================================================

def get_config_status_realtime(config_name, match_config_dir):
    """
    Checks if video, cache and timings exist for a given config.
    No cache used here to ensure 100% accuracy with disk state.
    """
    if not config_name:
        return False, False, False

    path = os.path.join(match_config_dir, config_name)
    if not os.path.exists(path):
        return False, False, False

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        v_path = data.get("video_path", "").strip().strip("\"'")
        c_path = data.get("csv_path", "").strip().strip("\"'")

        has_video = os.path.exists(v_path) if v_path else False
        if data.get("ui_split_video"):
            v2_path = data.get("video2_path", "").strip().strip("\"'")
            if not v2_path or not os.path.exists(v2_path):
                has_video = False

        cache_path = get_opta_cache_path(c_path)
        has_cache = os.path.exists(cache_path) if cache_path else False

        h1 = data.get("ui_half1", "").strip()
        h2 = data.get("ui_half2", "").strip()
        has_time = bool(h1 and h2)

        return has_video, has_cache, has_time
    except Exception:
        return False, False, False


# =============================================================================
# CLOUDFLARE R2 INITIALIZATION
# =============================================================================
s3_client = boto3.client(
    's3',
    endpoint_url=os.getenv('R2_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
    region_name='auto'
)
BUCKET_NAME = os.getenv('R2_BUCKET_NAME')


# =============================================================================
# MAIN
# =============================================================================

def main():
    # 1. Configuration de l'authentification via PostgreSQL
    credentials = get_all_users()
    
    # Initialisation de l'authentificateur
    authenticator = stauth.Authenticate(
        credentials,
        'the_analyst_cookie',
        'signature_key_12345',
        cookie_expiry_days=30
    )

    # Affichage du formulaire de connexion
    authenticator.login(location='main')

    if st.session_state["authentication_status"] is False:
        st.error("Identifiants incorrects")
        return
    elif st.session_state["authentication_status"] is None:
        st.warning("Veuillez vous connecter")
        return

    # --- UTILISATEUR AUTHENTIFIÉ ---
    # Affichage du statut dans la sidebar
    st.sidebar.write(f"### 👤 Connecté : {st.session_state['username']}")
    authenticator.logout('Déconnexion', 'sidebar')
    st.sidebar.divider()

    st.success("Accès autorisé !")

    # Initialisation de l'état de la session (si authentifié)
    init_session_state()

    # ---- 1b. Keep-Alive (Crucial for Conditional Rendering) ----
    # explicitly writing back to the key forces Streamlit to retain it
    from ui_session_state import FILTER_KEYS
    for k in FILTER_KEYS:
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]
    
    # Handle dynamic advanced group keys
    adv_count = st.session_state.get("ui_adv_group_count", 1)
    for i in range(adv_count):
        for suffix in ["filters", "and", "start", "end"]:
            k = f"ui_adv_group_{suffix}_{i}"
            if k in st.session_state:
                st.session_state[k] = st.session_state[k]

    # ---- 2. Pre-calculate filters (INTELLIGENT HASHING) ----
    _df_global = st.session_state.opta_df
    if _df_global is not None and not _df_global.empty:
        current_pre_config = build_global_filter_config(None)
        
        # Performance: Only run apply_filters if config changed or forced
        from ui_session_state import get_filter_hash
        current_hash = get_filter_hash(current_pre_config)
        force_apply = st.session_state.ui_filters_applied
        auto_apply = st.session_state.ui_auto_apply_filters
        
        should_recalc = (
            force_apply or 
            (auto_apply and current_hash != st.session_state.ui_last_filter_hash) or
            st.session_state.df_preview is None
        )

        if should_recalc:
            st.session_state.df_preview, _ = apply_filters(_df_global.copy(), current_pre_config)
            st.session_state.ui_last_filter_hash = current_hash
            st.session_state.ui_filters_applied = False

    # ---- 3. Bases management ----
    BASES_FILE = "match_config_bases.json"

    def load_bases():
        if os.path.exists(BASES_FILE):
            try:
                with open(BASES_FILE, "r", encoding="utf-8") as f:
                    st.session_state.ui_match_bases = json.load(f)
            except:
                pass

    def save_bases():
        with open(BASES_FILE, "w", encoding="utf-8") as f:
            json.dump(st.session_state.ui_match_bases, f, indent=4)

    load_bases()

    current_base_name = st.session_state.get("ui_active_base", "Default")
    if current_base_name not in st.session_state.ui_match_bases:
        current_base_name = (
            list(st.session_state.ui_match_bases.keys())[0]
            if st.session_state.ui_match_bases
            else "Default"
        )
        st.session_state.ui_active_base = current_base_name

    MATCH_CONFIG_DIR_RAW = st.session_state.ui_match_bases.get(current_base_name, "match_configs")
    MATCH_CONFIG_DIR = get_abs_path(MATCH_CONFIG_DIR_RAW)
    st.session_state["match_config_dir"] = MATCH_CONFIG_DIR
    os.makedirs(MATCH_CONFIG_DIR, exist_ok=True)

    available_match_configs = []
    if os.path.exists(MATCH_CONFIG_DIR):
        for root, dirs, files in os.walk(MATCH_CONFIG_DIR):
            for f in files:
                if f.endswith(".json"):
                    rel_path = os.path.relpath(os.path.join(root, f), MATCH_CONFIG_DIR)
                    available_match_configs.append(rel_path.replace("\\", "/"))
    available_match_configs = sorted(available_match_configs)

    # Initialise les profils disponibles
    available_profiles = sorted([f for f in os.listdir(PROFILE_DIR) if f.endswith(".json")])


    # ---- 4. Navigation (SIDEBAR based for performance) ----
    with st.sidebar:
        st.markdown("### 🧭 Navigation")
        nav_options = [
            "⚙️ Config Match",
            "🚀 Multi-Match / Turbo",
            "🔬 Filtrage Actions",
            "👁️ Aperçu & Visualisations",
            "📊 Build-Up & Séquences",
            "🎯 Shot Map",
            "🎬 Export & Logs",
        ]
        # Use session state to persist tab even if sidebar is recalculated
        active_tab = st.radio(
            "Choisir un onglet",
            options=nav_options,
            label_visibility="collapsed",
            index=nav_options.index(st.session_state.ui_active_tab) if st.session_state.ui_active_tab in nav_options else 0,
            key="ui_sidebar_nav"
        )
        st.session_state.ui_active_tab = active_tab
        st.divider()

    # ---- 5. Global Branding Header ----
    st.markdown(
        f"""
        <div style="text-align: center; padding: 40px 0;">
            <div class="neon-title" style="letter-spacing: -2px;">⚽ CLIPMAKER PRO</div>
            <div style="font-family: 'Inter', sans-serif; font-size: 11px; color: {TEXT_MUTED}; letter-spacing: 4px; text-transform: uppercase; margin-top: -5px; opacity: 0.8;">
                High-End Football Highlight Reel Generator
            </div>
        </div>
    """,
        unsafe_allow_html=True,
    )

    # ---- 6. Sidebar (Main content) ----
    render_sidebar(MATCH_CONFIG_DIR)

    # ---- 7. Layout: main column ----
    with st.sidebar:
        right_params = render_right_column()

    main_col = st.container()

    export_mode = right_params["export_mode"]
    individual = right_params["individual"]
    group_by_player = right_params["group_by_player"]
    out_filename = right_params["out_filename"]
    sidebar_run_btn = right_params["sidebar_run_btn"]
    sidebar_xml_btn = right_params["sidebar_xml_btn"]

    # ---- 8. Active Content Rendering (Conditional) ----
    cfg_ctx = {}  # collected data from tab_cfg for use in run_logic
    _df = None    # filtered/loaded dataframe for filter/preview tabs

    with main_col:
        st.markdown(
            logo_header("CLIPMAKER SUAOL", f"{active_tab} · Kinetic Theme"),
            unsafe_allow_html=True,
        )

        # -- Core data dependencies --
        video_path = st.session_state.get("video_path", "")
        video2_path = st.session_state.get("video2_path", "")
        csv_path = st.session_state.get("csv_path", "")
        
        final_csv_for_filter = st.session_state.csv_path or csv_path
        if st.session_state.opta_processed and st.session_state.opta_df is not None:
            _df = st.session_state.opta_df
        elif final_csv_for_filter and os.path.exists(final_csv_for_filter) and final_csv_for_filter.endswith(".csv"):
            try:
                _df = pd.read_csv(final_csv_for_filter)
            except Exception:
                pass

        # Conditional rendering of the active tab ONLY
        if active_tab == "⚙️ Config Match":
            cfg_ctx = render_tab_config(
                MATCH_CONFIG_DIR=MATCH_CONFIG_DIR,
                current_base_name=current_base_name,
                available_match_configs=available_match_configs,
                save_bases_fn=save_bases,
                get_config_status_fn=get_config_status_realtime,
                BASKET_DIR=BASKET_DIR,
                TEAM_INDEX_DIR=TEAM_INDEX_DIR,
            )
        
        elif active_tab == "🚀 Multi-Match / Turbo":
            batch_ctx = render_tab_batch(
                MATCH_CONFIG_DIR=MATCH_CONFIG_DIR,
                current_base_name=current_base_name,
                available_match_configs=available_match_configs,
                get_config_status_fn=get_config_status_realtime,
                BASKET_DIR=BASKET_DIR,
                TEAM_INDEX_DIR=TEAM_INDEX_DIR,
            )
            
        elif active_tab == "🔬 Filtrage Actions":
            render_tab_filter(
                _df=_df,
                available_profiles=available_profiles,
                PROFILE_DIR=PROFILE_DIR,
                FLAT_ZONES=FLAT_ZONES,
            )
            
        elif active_tab == "👁️ Aperçu & Visualisations":
            render_tab_preview(
                _df=_df,
                FLAT_ZONES=FLAT_ZONES,
            )
            
        elif active_tab == "📊 Build-Up & Séquences":
            render_tab_buildup(
                MATCH_CONFIG_DIR=MATCH_CONFIG_DIR,
                TEMP_DIR=TEMP_DIR,
            )
            
        elif active_tab == "🎯 Shot Map":
            render_tab_shots(FLAT_ZONES=FLAT_ZONES)
            
        elif active_tab == "🎬 Export & Logs":
            export_params = render_tab_export()

    # Fallback for hidden tabs data if we are NOT on that tab
    # (Extracting some essential defaults from session state when tab is hidden)
    if active_tab != "🚀 Multi-Match / Turbo":
        batch_ctx = {"batch_configs": [], "batch_profile_sel": "(UI Actuelle)"}
    
    # Fallback timing variables if not on Config tab
    if active_tab != "⚙️ Config Match":
        split_video = st.session_state.get("ui_split_video", False)
        half1 = st.session_state.get("ui_half1", "")
        half2 = st.session_state.get("ui_half2", "")
        half3 = st.session_state.get("ui_half3", "")
        half4 = st.session_state.get("ui_half4", "")
    else:
        split_video = cfg_ctx.get("split_video", False)
        half1 = cfg_ctx.get("half1", "")
        half2 = cfg_ctx.get("half2", "")
        half3 = cfg_ctx.get("half3", "")
        half4 = cfg_ctx.get("half4", "")

    if active_tab != "🎬 Export & Logs":
        # Need some defaults for run logic if Export tab is hidden
        from ui_session_state import SESSION_DEFAULTS
        export_params = {
            "period_col": "period", "fallback_row": 0, "use_fallback": False,
            "before_buf": 4, "after_buf": 6, "min_gap": 6, "out_dir_input": "output",
            "custom_text_overlay": "", "custom_text_size": 30, "custom_text_font": "Arial",
            "custom_text_color": "#ffffff", "custom_text_opacity": 1.0, "custom_text_bg": "black",
            "custom_text_bg_opacity": 0.0, "dry_run": False
        }

    # ---- 8. Run Logic ----
    period_col = export_params["period_col"]
    fallback_row = export_params["fallback_row"]
    use_fallback = export_params["use_fallback"]
    before_buf = export_params["before_buf"]
    after_buf = export_params["after_buf"]
    min_gap = export_params["min_gap"]
    final_out_dir = st.session_state.output_dir or export_params["out_dir_input"] or "output"
    custom_text_overlay = export_params["custom_text_overlay"]
    custom_text_size = export_params["custom_text_size"]
    custom_text_font = export_params["custom_text_font"]
    custom_text_color = export_params["custom_text_color"]
    custom_text_opacity = export_params["custom_text_opacity"]
    custom_text_bg = export_params["custom_text_bg"]
    custom_text_bg_opacity = export_params["custom_text_bg_opacity"]
    dry_run = export_params["dry_run"]

    custom_text_options = {
        "text": custom_text_overlay,
        "size": custom_text_size,
        "font": custom_text_font,
        "color": custom_text_color.lstrip("#"),
        "opacity": custom_text_opacity,
        "bg": custom_text_bg,
        "bg_opacity": custom_text_bg_opacity,
    }

    final_video = video_path
    final_video2 = video2_path
    final_csv = csv_path

    turbo_run_btn = batch_ctx.get("turbo_run_btn", False)
    turbo_xml_btn = batch_ctx.get("turbo_xml_btn", False)
    batch_configs = batch_ctx.get("batch_configs", [])
    batch_profile_sel = batch_ctx.get("batch_profile_sel", "(UI Actuelle)")

    run_actually_requested = sidebar_run_btn
    xml_actually_requested = sidebar_xml_btn or turbo_xml_btn
    is_xml_only = xml_actually_requested

    # --- Turbo Batch ---
    if turbo_run_btn or turbo_xml_btn:
        is_xml_only_turbo = turbo_xml_btn
        if not batch_configs:
            st.error("Veuillez sélectionner au moins une configuration de match.")
        else:
            if batch_profile_sel != "(UI Actuelle)":
                prof_path = os.path.join(PROFILE_DIR, batch_profile_sel)
                with open(prof_path, "r", encoding="utf-8") as f:
                    p_data = json.load(f)
                base_filters = build_global_filter_config(p_data)
            else:
                base_filters = build_global_filter_config(None)

            is_global_reel = "Vidéo unique globale" in export_mode
            global_batch_params = {
                "MATCH_CONFIG_DIR": MATCH_CONFIG_DIR,
                "period_col": period_col,
                "use_fallback": use_fallback,
                "fallback_row": fallback_row,
                "before_buf": before_buf,
                "after_buf": after_buf,
                "min_gap": min_gap,
                "final_out_dir": final_out_dir,
                "out_filename": out_filename,
                "individual": individual,
                "group_by_player": group_by_player,
                "is_global_reel": is_global_reel,
                "dry_run": dry_run,
                "xml_only": is_xml_only_turbo,
                "custom_text_options": custom_text_options,
            }
            process_turbo_batch_dialog(
                batch_configs=batch_configs,
                base_filters=base_filters,
                global_batch_params=global_batch_params,
                interleave_specs_fn=interleave_specs,
                out_filename=out_filename,
                final_out_dir=final_out_dir,
                is_global_reel=is_global_reel,
                custom_text_options=custom_text_options,
                open_file_location_fn=open_file_location,
                play_video_fn=play_video,
            )

    # --- Aggregate or Single match run ---
    if run_actually_requested or (xml_actually_requested and not turbo_xml_btn):
        if st.session_state.get("is_aggregate_mode") and st.session_state.opta_df is not None:
            # Aggregate run
            from clip_processing import apply_filters as local_apply

            dummy_config = build_global_filter_config(None)
            df_filtered = local_apply(st.session_state.opta_df.copy(), dummy_config)[0]

            if df_filtered.empty:
                st.warning("Aucun événement ne correspond à vos filtres dans les données fusionnées.")
            else:
                if "_source_config_file" in df_filtered.columns:
                    configs_to_process = sorted(df_filtered["_source_config_file"].unique().tolist())
                else:
                    st.session_state.is_aggregate_mode = False
                    st.warning("Mode agrégé détecté par erreur. Redémarrage en mode simple...")
                    st.stop()

                batch_params_agg = {
                    "final_out_dir": final_out_dir,
                    "out_filename": out_filename,
                    "individual": individual,
                    "group_by_player": group_by_player,
                    "custom_text_options": custom_text_options,
                    "dry_run": dry_run,
                    "is_global_reel": "Vidéo unique globale" in export_mode,
                    "period_col": period_col,
                    "use_fallback": use_fallback,
                    "fallback_row": fallback_row,
                    "before_buf": before_buf,
                    "after_buf": after_buf,
                    "min_gap": min_gap,
                    "MATCH_CONFIG_DIR": MATCH_CONFIG_DIR,
                }
                process_aggregate_dialog(
                    configs_to_process=configs_to_process,
                    df_filtered=df_filtered,
                    dummy_config=dummy_config,
                    batch_params=batch_params_agg,
                    out_filename=out_filename,
                    final_out_dir=final_out_dir,
                    xml_actually_requested=xml_actually_requested,
                    interleave_specs_fn=interleave_specs,
                    open_file_location_fn=open_file_location,
                    open_premiere_fn=open_premiere,
                    play_video_fn=play_video,
                )
        else:
            # Single match run
            errors = []
            if not final_video and not dry_run:
                errors.append("Video file is required.")
            if not final_csv:
                errors.append("CSV file is required.")
            if not half1:
                errors.append("1st half kick-off time is required.")
            if not half2:
                errors.append("2nd half kick-off time is required.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                config = {
                    "video_file": final_video,
                    "video2_file": (st.session_state.video2_path or video2_path).strip().strip("\"'"),
                    "split_video": split_video,
                    "data_file": final_csv,
                    "half1_time": half1,
                    "half2_time": half2,
                    "half3_time": half3 or "",
                    "half4_time": half4 or "",
                    "period_column": "" if use_fallback else period_col,
                    "fallback_row": int(fallback_row) if use_fallback else None,
                    "before_buffer": before_buf,
                    "after_buffer": after_buf,
                    "min_gap": min_gap,
                    "output_dir": final_out_dir,
                    "output_filename": out_filename,
                    "individual_clips": individual,
                    "group_by_player": group_by_player,
                    "custom_text_options": custom_text_options,
                    "dry_run": dry_run,
                    "ui_mixed_assembly": st.session_state.ui_mixed_assembly,
                    "use_crop": st.session_state.ui_use_crop,
                    "crop_params": st.session_state.ui_crop_params,
                    "opta_df": st.session_state.opta_df if st.session_state.opta_processed else None,
                    "xml_only": xml_actually_requested,
                }
                config.update(build_global_filter_config(None))

                process_single_match_dialog(
                    config=config,
                    open_file_location_fn=open_file_location,
                    open_premiere_fn=open_premiere,
                    play_video_fn=play_video,
                )

    # ---- 9. Footer ----
    st.markdown('<div class="footer">@B03GHB4L1 · Kinetic Analyst Theme</div>', unsafe_allow_html=True)



if __name__ == "__main__":
    main()
