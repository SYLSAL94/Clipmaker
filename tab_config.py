"""
tab_config.py
=============
Onglet "Config Match" de ClipMaker SUAOL.
Gestion des bases de configurations, chargement/sauvegarde/suppression
des matchs, sélection des fichiers vidéo/CSV, kick-off timestamps,
rognage (crop), et traitement Opta.
"""

import json
import os
import platform
import pandas as pd
import streamlit as st
import re
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from r2_manager import upload_stream_to_r2, get_available_videos_from_r2

from ui_match_utils import (
    extract_match_keywords_from_filenames,
    get_real_teams_from_base,
    STATUS_FILTER_OPTS,
    filter_match_configs
)
from ui_helpers import (
    browse_file, browse_folder, get_initial_dir,
    open_file_location, safe_rerun, get_ffmpeg_path,
)
from ui_theme import step_header
from clip_processing import to_seconds
from worker_utils import get_opta_cache_path, delete_opta_cache


# =============================================================================
# RENDER
# =============================================================================

def render_tab_config(
    MATCH_CONFIG_DIR: str,
    current_base_name: str,
    available_match_configs: list,
    save_bases_fn,
    get_config_status_fn,
    BASKET_DIR: str,
    TEAM_INDEX_DIR: str,
) -> dict:
    """
    Affiche l'onglet Config Match.
    Retourne un dict avec video_path, video2_path, csv_path, split_video,
    half1..half4, use_crop, crop_params, half_filter.
    """
    # STATUS_FILTER_OPTS imported from ui_match_utils

    def format_config_label(config_name):
        if not config_name:
            return "--- Sélectionner une configuration ---"
        has_video, has_cache, has_time = get_config_status_fn(config_name, MATCH_CONFIG_DIR)
        v_icon = "🎬" if has_video else "🌑"
        p_icon = "⚙️" if has_cache else "⏳"
        t_icon = "⏱️" if has_time else "⚪"
        ready_icon = "✅" if (has_video and has_cache and has_time) else "  "
        return f"{v_icon} {p_icon} {t_icon} {ready_icon} | {config_name}"

    def get_current_matching_config():
        return {
            "video_path": st.session_state.get("video_path", ""),
            "video2_path": st.session_state.get("video2_path", ""),
            "csv_path": st.session_state.get("csv_path", ""),
            "ui_split_video": st.session_state.get("ui_split_video", False),
            "ui_half1": st.session_state.get("ui_half1", ""),
            "ui_half2": st.session_state.get("ui_half2", ""),
            "ui_half3": st.session_state.get("ui_half3", ""),
            "ui_half4": st.session_state.get("ui_half4", ""),
            "ui_use_crop": st.session_state.get("ui_use_crop", False),
            "ui_crop_params": st.session_state.get("ui_crop_params", None),
            "ui_half_filter": st.session_state.get("ui_half_filter", "Both halves"),
        }

    def save_match_config():
        """Sauvegarde via le nouveau système SQL (Redirection)"""
        st.warning("Utilisez le bouton '🚀 Uploader et Sauvegarder' en bas pour le Zero-Disk.")

    def update_match_config():
        """Mise à jour via le nouveau système SQL (Redirection)"""
        # On pourrait ici implémenter une logique de mise à jour SQL simplifiée
        st.info("La mise à jour se fait désormais par l'interface Cloud en bas.")

    def save_match_config_to_db(match_name, video_key, data_key, ui_config):
        """Enregistre la configuration du match directement dans PostgreSQL"""
        # SÉCURITÉ : Chargement silencieux des variables d'environnement
        load_dotenv('/home/datafoot/.env')
        DB_PWD = os.getenv('POSTGRES_PWD')
        
        # Connexion à ton conteneur Docker
        DB_URL = f"postgresql://analyst_admin:{DB_PWD}@127.0.0.1:5432/datafoot_db"
        engine = create_engine(DB_URL)
        
        try:
            with engine.connect() as conn:
                # Upsert : Met à jour si le match existe, sinon l'insère
                query = text("""
                    INSERT INTO match_configs (match_name, r2_video_key, r2_data_key, ui_config)
                    VALUES (:n, :v, :d, :c)
                    ON CONFLICT (match_name) DO UPDATE SET
                    r2_video_key = EXCLUDED.r2_video_key,
                    r2_data_key = EXCLUDED.r2_data_key,
                    ui_config = EXCLUDED.ui_config
                """)
                conn.execute(query, {"n": match_name, "v": video_key, "d": data_key, "c": json.dumps(ui_config)})
                conn.commit()
            return True
        except Exception as e:
            st.error(f"❌ Erreur SQL lors de l'enregistrement : {e}")
            return False

    def load_match_config():
        name = st.session_state.get("ui_sel_match_config", "")
        if name:
            path = os.path.join(MATCH_CONFIG_DIR, name)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                for k, v in config.items():
                    st.session_state[k] = v
                st.session_state["ui_match_config_name"] = name.replace(".json", "")
                st.session_state.opta_processed = False
                st.session_state.opta_df = None

    def delete_match_config():
        name = st.session_state.get("ui_sel_match_config", "")
        if name:
            path = os.path.join(MATCH_CONFIG_DIR, name)
            if os.path.exists(path):
                os.remove(path)
                st.session_state.ui_sel_match_config = ""
                st.success(f"Configuration '{name}' supprimée.")

    def reset_match_config():
        for k in ["ui_match_config_name", "ui_sel_match_config", "video_path", "video2_path", "csv_path"]:
            st.session_state[k] = "" if k != "ui_split_video" else False
        st.session_state["ui_split_video"] = False
        for k in ["ui_half1", "ui_half2", "ui_half3", "ui_half4"]:
            st.session_state[k] = ""
        st.session_state["ui_use_crop"] = False
        st.session_state["ui_crop_params"] = None
        st.session_state["ui_half_filter"] = "Both halves"
        st.session_state.opta_processed = False
        st.session_state.opta_df = None
        st.session_state.df_preview = None

    # =========================================================================
    # RENDER
    # =========================================================================
    st.markdown(step_header(1, "Bases de Configurations"), unsafe_allow_html=True)

    b1, b2 = st.columns([2, 1])
    with b1:
        def on_base_change():
            st.session_state.opta_processed = False
            st.session_state.opta_df = None
            st.session_state.df_preview = None
            st.session_state.ui_sel_match_config = ""
            st.cache_data.clear()

        base_names = list(st.session_state.ui_match_bases.keys())
        idx = base_names.index(st.session_state.ui_active_base) if st.session_state.ui_active_base in base_names else 0
        sel_base = st.selectbox(
            "Base active",
            options=base_names,
            index=idx,
            help="Choisissez le dossier qui contient vos configurations de match.",
        )
        if sel_base != st.session_state.ui_active_base:
            st.session_state.ui_active_base = sel_base
            on_base_change()
            st.rerun()

        cp1, cp2 = st.columns([0.9, 0.1])
        cp1.caption(f"📍 Chemin actuel : `{MATCH_CONFIG_DIR}`")
        if cp2.button("📂", key="open_active_base_dir", help="Ouvrir l'emplacement du dossier de base"):
            open_file_location(MATCH_CONFIG_DIR)

    with b2:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh Status", use_container_width=True, help="Force la mise à jour des icônes de statut (🎬⚙️⏱️)"):
            st.cache_data.clear()
            st.toast("✅ Toutes les icônes de statut ont été rafraîchies.", icon="🔄")
            st.rerun()
        if st.button("➕ Ajouter / Modifier une Base", use_container_width=True):
            st.session_state.show_base_editor = not st.session_state.get("show_base_editor", False)

    if st.session_state.get("show_base_editor"):
        with st.expander("🛠️ Éditeur de Bases", expanded=True):
            new_base_name = st.text_input("Nom de la base (Ex: Pro Liga 2024)", placeholder="Nom unique")
            c_b1, c_b2 = st.columns([4, 1])
            with c_b1:
                new_base_path = st.text_input("Chemin du dossier match_configs", value=st.session_state.get("new_base_path", ""))
                st.session_state.new_base_path = new_base_path
            with c_b2:
                st.write("")
                st.write("")
                if platform.system() == "Windows":
                    if st.button("Browse", key="browse_new_base"):
                        picked = browse_folder()
                        if picked:
                            st.session_state.new_base_path = picked
                            st.rerun()
                else:
                    st.button("Browse", key="browse_new_base", disabled=True, help="Désactivé sur VPS (Linux)")

            if st.button("✅ Enregistrer la Base", type="primary"):
                if new_base_name and st.session_state.get("new_base_path"):
                    path_to_save = st.session_state.new_base_path
                    st.session_state.ui_match_bases[new_base_name] = path_to_save
                    save_bases_fn()
                    st.session_state.ui_active_base = new_base_name
                    st.session_state.show_base_editor = False
                    st.success(f"Base '{new_base_name}' ajoutée.")
                    st.rerun()
                else:
                    st.error("Veuillez remplir le nom et le chemin.")

            if len(st.session_state.ui_match_bases) > 1:
                st.divider()
                base_to_del = st.selectbox("Supprimer une base", options=[""] + [b for b in base_names if b != "Default"])
                if base_to_del and st.button(f"🗑️ Supprimer {base_to_del}"):
                    del st.session_state.ui_match_bases[base_to_del]
                    save_bases_fn()
                    st.session_state.ui_active_base = "Default"
                    st.success(f"Base '{base_to_del}' supprimée.")
                    st.rerun()

    st.divider()
    st.subheader(f"💾 Configurations dans '{current_base_name}' ({len(available_match_configs)})")

    mc_col1, mc_col2 = st.columns(2)
    with mc_col1:
        st.text_input("Nom de Match", placeholder="Ex: PSG_vs_OM", key="ui_match_config_name")
        st.button("💾 Sauvegarder (Nouveau)", on_click=save_match_config, use_container_width=True, key="save_match_config_btn")
        st.button("🔄 Refresh (Vider)", on_click=reset_match_config, use_container_width=True, key="reset_match_config_btn")

    with mc_col2:
        st.markdown("<label style='font-size: 14px; font-weight: 500;'>Charger Config</label>", unsafe_allow_html=True)

        sf_col1, sf_col2 = st.columns([1, 1])
        with sf_col1:
            match_keywords_all = get_real_teams_from_base(MATCH_CONFIG_DIR, available_match_configs, TEAM_INDEX_DIR)
            selected_team_keywords = st.multiselect(
                "Filtrer par Équipe / Mot-clé",
                options=match_keywords_all,
                key="ui_team_search_cfg_multi",
                placeholder="🔍 Équipes...",
                label_visibility="collapsed",
            )
        with sf_col2:
            selected_status_filters = st.multiselect(
                "Filtres rapides",
                options=list(STATUS_FILTER_OPTS.keys()),
                key="ui_status_filter",
                placeholder="🔍 Statut...",
                label_visibility="collapsed",
            )

        # Filter configs
        filtered_match_configs = filter_match_configs(
            available_match_configs,
            MATCH_CONFIG_DIR,
            selected_team_keywords,
            selected_status_filters,
            get_config_status_fn
        )

        def navigate_filtered(delta):
            if not filtered_match_configs:
                return
            curr = st.session_state.get("ui_sel_match_config", "")
            try:
                idx = filtered_match_configs.index(curr) if curr in filtered_match_configs else -1
            except ValueError:
                idx = -1
            new_idx = (idx + delta) % len(filtered_match_configs)
            st.session_state.ui_sel_match_config = filtered_match_configs[new_idx]
            load_match_config()

        nav_c1, nav_c2, nav_c3 = st.columns([1, 5, 1])
        with nav_c1:
            st.button("⬅️", on_click=navigate_filtered, args=(-1,), key="mc_prev", use_container_width=True)
        with nav_c2:
            st.selectbox(
                "Charger Config",
                [""] + filtered_match_configs,
                key="ui_sel_match_config",
                label_visibility="collapsed",
                on_change=load_match_config,
                format_func=format_config_label,
            )
        with nav_c3:
            st.button("➡️", on_click=navigate_filtered, args=(1,), key="mc_next", use_container_width=True)

        if selected_status_filters:
            st.caption(f"💡 {len(filtered_match_configs)} match(s) correspondent aux filtres.")

        btn_c1, btn_c2 = st.columns(2)
        with btn_c1:
            st.button("📂 Charger", on_click=load_match_config, use_container_width=True, key="load_match_config_btn")
        with btn_c2:
            st.button("🔄 Mettre à jour", on_click=update_match_config, use_container_width=True, type="primary", key="update_match_config_btn")

        def add_to_basket_cli():
            name = st.session_state.get("ui_sel_match_config", "")
            if name:
                is_in = any(item["name"] == name and item["base_dir"] == MATCH_CONFIG_DIR for item in st.session_state.ui_basket)
                if not is_in:
                    st.session_state.ui_basket.append({"name": name, "base_dir": MATCH_CONFIG_DIR, "base_name": current_base_name})
                    st.toast(f"✅ '{name}' ajouté au panier.", icon="🛒")
                else:
                    st.toast(f"ℹ️ '{name}' est déjà dans le panier.", icon="🛒")

        st.button("🛒 Ajouter au Panier Multi-Match", on_click=add_to_basket_cli, use_container_width=True, key="add_to_basket_from_cfg")
        st.button("🗑️ Supprimer", on_click=delete_match_config, type="secondary", use_container_width=True, key="del_match_config_btn")

        with st.expander("🔍 Analyse des Status (Debug)", expanded=False):
            name = st.session_state.get("ui_sel_match_config", "")
            if name:
                full_json_path = os.path.join(MATCH_CONFIG_DIR, name)
                st.write(f"**Fichier Config :** `{name}`")
                st.write(f"**Chemin complet :** `{full_json_path}`")
                exists_json = os.path.exists(full_json_path)
                st.write(f"Détecté sur disque : {'✅' if exists_json else '❌'}")
                if exists_json:
                    try:
                        with open(full_json_path, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        v = d.get("video_path", "")
                        c = d.get("csv_path", "")
                        st.divider()
                        st.write(f"**Vidéo configurée :** `{v}`")
                        st.write(f"Détecté sur disque : {'✅' if (v and os.path.exists(v)) else '❌'}")
                        cache_p = get_opta_cache_path(c)
                        st.write(f"**Cache attendu :** `{os.path.basename(cache_p)}`")
                        st.write(f"Détecté sur disque : {'✅' if (cache_p and os.path.exists(cache_p)) else '❌'}")
                    except Exception as e:
                        st.error(f"Erreur lecture JSON: {e}")
            else:
                st.info("Sélectionnez un match pour voir le diagnostic.")

    # =========================================================================
    # SOURCE FILES (HYBRIDE R2 + SQL)
    # =========================================================================
    st.subheader("☁️ Association Cloud (Vidéo R2 + Data Opta)")
    
    # Initialisation des variables locales pour éviter les NameError
    video_path = st.session_state.get("video_path", "")
    video2_path = st.session_state.get("video2_path", "")
    csv_path = st.session_state.get("csv_path", "")
    split_video = st.session_state.get("ui_split_video", False)

    # 1. Le Menu Déroulant (Scan en direct de R2)
    # On met en cache la liste pour éviter de spammer R2 à chaque frappe au clavier
    if "r2_available_videos" not in st.session_state:
        st.session_state.r2_available_videos = get_available_videos_from_r2()
    
    if st.button("🔄 Actualiser les vidéos Cloud (R2)", key="refresh_r2_btn"):
        st.session_state.r2_available_videos = get_available_videos_from_r2()
        st.rerun()

    available_v = st.session_state.r2_available_videos
    
    selected_video_key = ""
    selected_video_key_h2 = ""
    
    if not available_v:
        st.warning("⚠️ Aucune vidéo trouvée sur Cloudflare R2. Uploadez vos fichiers dans le dossier 'videos/' via Cyberduck ou R2 Web UI.")
    else:
        split_video = st.checkbox("Le match est fractionné en 2 vidéos (Mi-temps 1 & 2)", key="ui_split_video_h")
        
        c_v1, c_v2 = st.columns(2)
        with c_v1:
            selected_video_key = st.selectbox("🎬 Vidéo 1 (ou Match complet)", [""] + available_v, key="sel_r2_v1")
        with c_v2:
            if split_video:
                selected_video_key_h2 = st.selectbox("🎬 Vidéo 2 (2ème mi-temps)", [""] + available_v, key="sel_r2_v2")

        # 2. L'upload du fichier Excel (Très léger pour la RAM)
        st.divider()
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            match_name = st.text_input("Nom du Match (ex: LALIGA_Alaves_Levante)", key="new_match_name_h")
        with col_d2:
            opta_file = st.file_uploader("📊 Données Opta (.xlsx)", type=["xlsx"], key="d_up_h")

        can_associate = selected_video_key and opta_file and match_name
        if split_video:
            can_associate = can_associate and selected_video_key_h2

        if st.button("🚀 Associer et Sauvegarder", type="primary", disabled=not can_associate):
            with st.spinner("Lien Vidéo 🔗 Données Opta..."):
                data_key = f"data/{match_name}.xlsx"
                
                # Envoi uniquement de l'Excel vers R2 (la vidéo y est déjà !)
                if upload_stream_to_r2(opta_file, data_key):
                    opta_file.seek(0)
                    
                    # Injection SQL avec les clés R2
                    ui_config_dict = {
                        "split_video": split_video,
                        "r2_video_key_h2": selected_video_key_h2,
                        "use_crop": st.session_state.get("ui_use_crop", False),
                        "crop_params": st.session_state.get("ui_crop_params", {}),
                        "periods": {
                            "half1": st.session_state.get("ui_half1", ""),
                            "half2": st.session_state.get("ui_half2", ""),
                            "half3": st.session_state.get("ui_half3", ""),
                            "half4": st.session_state.get("ui_half4", "")
                        }
                    }
                    
                    if save_match_config_to_db(match_name, selected_video_key, data_key, ui_config_dict):
                        st.success(f"✅ Match '{match_name}' synchronisé ! Vidéo et Excel liés dans PostgreSQL.")
                        st.balloons()
                else:
                    st.error("Erreur lors de l'upload des données Opta vers R2.")

    # Opta Processing
    clean_csv_path = csv_path.strip().strip("\"'")
    file_ext = clean_csv_path.lower()
    is_supported = file_ext.endswith((".xlsx", ".xls", ".csv"))
    cache_path_opta = get_opta_cache_path(clean_csv_path)
    is_already_processed_file = "_PROCESSED_OPTA.csv" in clean_csv_path
    cache_exists = os.path.exists(cache_path_opta) if cache_path_opta else False

    if clean_csv_path and os.path.exists(clean_csv_path) and is_supported and not is_already_processed_file:
        if not st.session_state.opta_processed:
            if cache_exists:
                try:
                    temp_df = pd.read_csv(cache_path_opta)
                    # Check for mandatory columns that trigger a re-process if missing
                    mandatory_cols = ["one_two_score"]
                    if any(c not in temp_df.columns for c in mandatory_cols):
                        st.session_state.opta_processed = False
                    else:
                        st.session_state.opta_df = temp_df
                        st.session_state.opta_processed = True
                        st.session_state.is_aggregate_mode = False
                        safe_rerun()
                except Exception as e:
                    st.error(f"Erreur chargement auto cache: {e}")

            st.info("💡 Nouveau fichier ou besoin de recalculer ? Cliquez ci-dessous.")
            if st.button("✨ Process Opta Data (Nouveau)", use_container_width=True, type="secondary"):
                st.session_state.show_opta_logs = True
                st.session_state.opta_process_logs = []
                try:
                    delete_opta_cache(clean_csv_path)
                    final_cache_path = get_opta_cache_path(clean_csv_path)
                    from process_opta_data import OptaProcessor
                    processor = OptaProcessor()
                    log_container = st.empty()

                    def update_logs(msg):
                        st.session_state.opta_process_logs.append(msg)
                        log_container.markdown(
                            f'<div class="log-box">{"<br>".join(st.session_state.opta_process_logs[-15:])}</div>',
                            unsafe_allow_html=True,
                        )

                    with st.spinner("🚀 Traitement Opta en cours..."):
                        processed_events = processor.process_file(clean_csv_path, log_callback=update_logs)
                        df = pd.DataFrame(processed_events)
                        df.to_csv(final_cache_path, index=False)
                        st.session_state.opta_df = df
                        st.session_state.opta_processed = True
                        st.session_state.is_aggregate_mode = False
                        st.session_state.df_preview = None
                        update_logs("<span style='color:#00ff88;'>🏁 TRAITEMENT TERMINÉ AVEC SUCCÈS !</span>")
                        st.toast("✅ Données Opta traitées.", icon="🚀")
                except Exception as e:
                    err_msg = f"<span style='color:#ff4b4b;'>❌ ERREUR : {str(e)}</span>"
                    st.session_state.opta_process_logs = st.session_state.get("opta_process_logs", []) + [err_msg]
                    st.error(f"Le process a échoué : {e}")

            if st.session_state.get("show_opta_logs") and st.session_state.get("opta_process_logs"):
                st.markdown(
                    f'<div class="log-box">{"<br>".join(st.session_state.opta_process_logs)}</div>',
                    unsafe_allow_html=True,
                )
                if st.button("🗑️ Fermer les logs", key="close_opta_logs_btn"):
                    st.session_state.show_opta_logs = False
                    st.session_state.opta_process_logs = []
                    st.rerun()
        else:
            st.success("✅ Données Opta prêtes (chargées en mémoire).")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔄 Re-process (Forcer)", use_container_width=True):
                    st.session_state.opta_processed = False
                    safe_rerun()
            with col_b:
                if st.button("🗑️ Supprimer Cache", use_container_width=True):
                    delete_opta_cache(clean_csv_path)
                    st.session_state.opta_processed = False
                    st.warning("Tous les caches associés ont été supprimés.")
                    safe_rerun()
    elif is_already_processed_file and os.path.exists(clean_csv_path):
        if not st.session_state.opta_processed:
            try:
                st.session_state.opta_df = pd.read_csv(clean_csv_path)
                st.session_state.opta_processed = True
                st.session_state.is_aggregate_mode = False
                safe_rerun()
            except Exception as e:
                st.error(f"Erreur lecture fichier pré-traité: {e}")
        else:
            st.success("✅ Données Opta prêtes (Fichier traité).")
            if st.button("🔄 Recharger Fichier", use_container_width=True):
                st.session_state.opta_processed = False
                safe_rerun()

    # =========================================================================
    # KICK-OFF TIMESTAMPS
    # =========================================================================
    st.subheader("Kick-off Timestamps")
    if split_video:
        st.caption("Enter timestamps relative to the START of each video file")
    else:
        st.caption("Type exactly what your video player shows — MM:SS or HH:MM:SS")

    test_video1 = st.session_state.video_path or video_path
    test_video2 = st.session_state.video2_path or video2_path

    tc1, tc2 = st.columns(2)
    with tc1:
        half1 = st.text_input("1st Half kick-off", placeholder="e.g. 4:16", key="ui_half1", on_change=update_match_config)
        if half1 and test_video1:
            col_h1_btn1, col_h1_btn2, col_h1_btn3 = st.columns([1, 1, 1])
            with col_h1_btn1:
                if st.button("👁️ Vidéo", key="test_h1", use_container_width=True):
                    st.session_state.ui_show_test_h1 = True
                    st.session_state.ui_show_img_h1 = False
            with col_h1_btn2:
                if st.button("📸 Photo", key="img_h1", use_container_width=True):
                    import subprocess
                    try:
                        t_sec = to_seconds(half1)
                        ffmpeg_bin = get_ffmpeg_path()
                        h1_frame = "h1_capture.jpg"
                        subprocess.run([ffmpeg_bin, "-y", "-ss", str(t_sec), "-i", test_video1, "-frames:v", "1", "-update", "1", h1_frame], capture_output=True)
                        st.session_state.ui_show_img_h1 = True
                        st.session_state.ui_show_test_h1 = False
                    except:
                        st.error("Erreur capture")
            with col_h1_btn3:
                if st.session_state.ui_show_test_h1 or st.session_state.ui_show_img_h1:
                    if st.button("❌ Retirer", key="hide_h1", use_container_width=True):
                        st.session_state.ui_show_test_h1 = False
                        st.session_state.ui_show_img_h1 = False

            if st.session_state.ui_show_test_h1:
                try:
                    st.video(test_video1, start_time=to_seconds(half1))
                except Exception:
                    st.error("Vidéo illisible")

            if st.session_state.ui_show_img_h1 and os.path.exists("h1_capture.jpg"):
                st.image("h1_capture.jpg", caption=f"Capture 1ère MT à {half1}")

        half3 = st.text_input("ET 1st Half (optional)", placeholder="leave blank", key="ui_half3", on_change=update_match_config)

    with tc2:
        half2 = st.text_input(
            "2nd Half kick-off",
            placeholder="e.g. 0:45" if split_video else "e.g. 1:00:32",
            key="ui_half2",
            on_change=update_match_config,
        )
        if half2:
            vid_to_test = test_video2 if split_video and test_video2 else test_video1
            if vid_to_test:
                col_h2_btn1, col_h2_btn2, col_h2_btn3 = st.columns([1, 1, 1])
                with col_h2_btn1:
                    if st.button("👁️ Vidéo", key="test_h2", use_container_width=True):
                        st.session_state.ui_show_test_h2 = True
                        st.session_state.ui_show_img_h2 = False
                with col_h2_btn2:
                    if st.button("📸 Photo", key="img_h2", use_container_width=True):
                        import subprocess
                        try:
                            t_sec = to_seconds(half2)
                            ffmpeg_bin = get_ffmpeg_path()
                            h2_frame = "h2_capture.jpg"
                            subprocess.run([ffmpeg_bin, "-y", "-ss", str(t_sec), "-i", vid_to_test, "-frames:v", "1", "-update", "1", h2_frame], capture_output=True)
                            st.session_state.ui_show_img_h2 = True
                            st.session_state.ui_show_test_h2 = False
                        except:
                            st.error("Erreur capture")
                with col_h2_btn3:
                    if st.session_state.ui_show_test_h2 or st.session_state.ui_show_img_h2:
                        if st.button("❌ Retirer", key="hide_h2", use_container_width=True):
                            st.session_state.ui_show_test_h2 = False
                            st.session_state.ui_show_img_h2 = False

                if st.session_state.ui_show_test_h2:
                    try:
                        st.video(vid_to_test, start_time=to_seconds(half2))
                    except Exception:
                        st.error("Vidéo illisible")

                if st.session_state.ui_show_img_h2 and os.path.exists("h2_capture.jpg"):
                    st.image("h2_capture.jpg", caption=f"Capture 2ème MT à {half2}")
            else:
                st.info("Vidéo 2 manquante")

        half4 = st.text_input("ET 2nd Half (optional)", placeholder="leave blank", key="ui_half4", on_change=update_match_config)

    # =========================================================================
    # CROP
    # =========================================================================
    st.subheader("✂️ Rognage (Crop)")
    use_crop = st.checkbox("Activer le rognage global", key="ui_use_crop", help="Permet de zoomer ou recadrer la vidéo pour tous les clips.")

    if use_crop:
        import subprocess
        from PIL import Image
        from streamlit_cropper import st_cropper

        crop_video = st.session_state.video_path or video_path
        if crop_video and os.path.exists(crop_video):
            c1, c2 = st.columns([1, 2])
            with c1:
                crop_time = st.text_input("Minute pour aperçu", value="10:00", help="MM:SS")

            try:
                t_sec = to_seconds(crop_time)
                ffmpeg_bin = get_ffmpeg_path()
                tmp_frame = "tmp_crop_frame.jpg"

                if st.button("🔄 Actualiser l'aperçu"):
                    subprocess.run([ffmpeg_bin, "-y", "-ss", str(t_sec), "-i", crop_video, "-frames:v", "1", "-update", "1", tmp_frame], capture_output=True)

                if os.path.exists(tmp_frame):
                    img = Image.open(tmp_frame)
                    st.write("Dessinez la zone à conserver (cliquez sur 'Valider le rognage' ensuite) :")
                    cropped_box = st_cropper(img, realtime_update=True, box_color="#00FF88", aspect_ratio=None, return_type="box")
                    if cropped_box:
                        c_left = int(cropped_box.get("left", 0))
                        c_top = int(cropped_box.get("top", 0))
                        c_width = int(cropped_box.get("width", 0))
                        c_height = int(cropped_box.get("height", 0))
                        st.session_state.ui_crop_params = {"left": c_left, "top": c_top, "width": c_width, "height": c_height}
                        st.success(f"Zone sélectionnée : {c_width}x{c_height} à ({c_left}, {c_top})")
                else:
                    st.warning("Cliquez sur 'Actualiser l'aperçu' pour charger une image.")
            except Exception as e:
                st.error(f"Erreur d'aperçu : {e}")
        else:
            st.warning("Veuillez d'abord sélectionner un fichier vidéo.")

    return {
        "video_path": video_path,
        "video2_path": video2_path,
        "csv_path": csv_path,
        "split_video": split_video,
        "half1": half1,
        "half2": half2,
        "half3": half3,
        "half4": half4,
        "half_filter": st.session_state.get("ui_half_filter", "Both halves"),
        "use_crop": use_crop,
    }

