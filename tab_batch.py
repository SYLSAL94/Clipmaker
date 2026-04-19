"""
tab_batch.py
============
Onglet "Multi-Match / Turbo" de ClipMaker SUAOL.
Gestion du panier multi-match, sélection des configs à traiter en batch,
et boutons Turbo (déclenchement du run_logic).
"""

import json
import os
import platform

import pandas as pd
import streamlit as st

from clip_processing import assign_periods, apply_filters
from worker_utils import get_opta_cache_path
from process_opta_data import OptaProcessor
from ui_theme import step_header
from ui_helpers import safe_rerun
from ui_session_state import build_global_filter_config
from ui_match_utils import (
    get_real_teams_from_base,
    filter_match_configs,
    STATUS_FILTER_OPTS
)


def render_tab_batch(
    MATCH_CONFIG_DIR: str,
    current_base_name: str,
    available_match_configs: list,
    get_config_status_fn,
    BASKET_DIR: str,
    TEAM_INDEX_DIR: str = "team_index_cache",
) -> dict:
    """
    Rendu de l'onglet Multi-Match / Turbo.
    Retourne un dict avec :
      turbo_run_btn, turbo_xml_btn, batch_configs, batch_profile_sel
    """
    result = {
        "turbo_run_btn": False,
        "turbo_xml_btn": False,
        "batch_configs": [],
        "batch_profile_sel": "(UI Actuelle)",
    }

    st.markdown(step_header(2, "Multi-Match / Turbo Batch"), unsafe_allow_html=True)

    PROFILE_DIR = "profiles"
    os.makedirs(PROFILE_DIR, exist_ok=True)
    available_profiles = sorted([f for f in os.listdir(PROFILE_DIR) if f.endswith(".json")])

    # =========================================================================
    # BASKET MANAGEMENT
    # =========================================================================
    st.subheader("🧺 Panier Multi-Match")
    basket = st.session_state.get("ui_basket", [])

    # --- MANUAL MATCH SELECTION (RESTORED) ---
    with st.expander("🔍 Sélection manuelle (Filtres)", expanded=not bool(basket)):
        sm_c1, sm_c2 = st.columns(2)
        with sm_c1:
            match_keywords_all = get_real_teams_from_base(MATCH_CONFIG_DIR, available_match_configs, TEAM_INDEX_DIR)
            sel_keywords = st.multiselect(
                "Filtrer par Équipe / Mot-clé",
                options=match_keywords_all,
                key="ui_batch_team_search",
                placeholder="🔍 Équipes...",
            )
        with sm_c2:
            sel_status = st.multiselect(
                "Filtrer par Statut",
                options=list(STATUS_FILTER_OPTS.keys()),
                key="ui_batch_status_filter",
                placeholder="🔍 Statut...",
            )

        filtered_batch_configs = filter_match_configs(
            available_match_configs,
            MATCH_CONFIG_DIR,
            sel_keywords,
            sel_status,
            get_config_status_fn
        )

        def format_cfg_label(cname):
            has_v, has_c, has_t = get_config_status_fn(cname, MATCH_CONFIG_DIR)
            v_ico = "🎬" if has_v else "🌑"
            c_ico = "⚙️" if has_c else "⏳"
            t_ico = "⏱️" if has_t else "⚪"
            ready_ico = "✅" if (has_v and has_c and has_t) else "  "
            return f"{v_ico} {c_ico} {t_ico} {ready_ico} | {cname}"

        sel_match = st.selectbox(
            "Match à ajouter",
            [""] + filtered_batch_configs,
            format_func=format_cfg_label,
            key="ui_batch_sel_match"
        )

        # Action buttons
        ac1, ac2 = st.columns(2)
        with ac1:
            if sel_match:
                if st.button("🛒 Ajouter ce match au panier", use_container_width=True, type="primary"):
                    item = {"name": sel_match, "base_dir": MATCH_CONFIG_DIR, "base_name": current_base_name}
                    if item not in st.session_state.ui_basket:
                        st.session_state.ui_basket.append(item)
                        st.toast(f"✅ '{sel_match}' ajouté au panier.")
                        st.rerun()
                    else:
                        st.toast(f"ℹ️ '{sel_match}' est déjà dans le panier.")
            else:
                st.write("")

        with ac2:
            if filtered_batch_configs:
                if st.button(f"🧺 Tout Ajouter ({len(filtered_batch_configs)} filtrés)", use_container_width=True):
                    added_count = 0
                    for cfg in filtered_batch_configs:
                        item = {"name": cfg, "base_dir": MATCH_CONFIG_DIR, "base_name": current_base_name}
                        if item not in st.session_state.ui_basket:
                            st.session_state.ui_basket.append(item)
                            added_count += 1
                    st.toast(f"✅ {added_count} match(s) ajouté(s) au panier.", icon="🛒")
                    st.rerun()

    basket_actions = st.columns([1, 1, 1, 1])
    with basket_actions[0]:
        if st.button("➕ Tout Ajouter (Base Actuelle)", use_container_width=True):
            for cfg in available_match_configs:
                item = {"name": cfg, "base_dir": MATCH_CONFIG_DIR, "base_name": current_base_name}
                if item not in st.session_state.ui_basket:
                    st.session_state.ui_basket.append(item)
            st.toast(f"✅ {len(available_match_configs)} configs ajoutées au panier.", icon="🛒")
            st.rerun()
    with basket_actions[1]:
        if st.button("🗑️ Vider le Panier", use_container_width=True):
            st.session_state.ui_basket = []
            st.rerun()

    saved_baskets = sorted([f for f in os.listdir(BASKET_DIR) if f.endswith(".json")]) if os.path.exists(BASKET_DIR) else []

    with basket_actions[2]:
        basket_save_name = st.text_input("Nom de sauvegarde", placeholder="Sauvegarde 1...", label_visibility="collapsed", key="ui_basket_save_name")

        def save_basket():
            bname = st.session_state.get("ui_basket_save_name", "").strip()
            if bname:
                if not bname.endswith(".json"):
                    bname += ".json"
                os.makedirs(BASKET_DIR, exist_ok=True)
                with open(os.path.join(BASKET_DIR, bname), "w", encoding="utf-8") as f:
                    json.dump(st.session_state.ui_basket, f, indent=4)
                st.toast(f"✅ Panier '{bname}' sauvegardé!")

        if st.button("💾 Sauvegarder", use_container_width=True, on_click=save_basket):
            pass

    with basket_actions[3]:
        sel_saved = st.selectbox("Charger", [""] + saved_baskets, key="ui_sel_saved_basket", label_visibility="collapsed")
        if sel_saved:
            if st.button("📂 Charger ce Panier", use_container_width=True):
                basket_path = os.path.join(BASKET_DIR, sel_saved)
                try:
                    with open(basket_path, "r", encoding="utf-8") as f:
                        loaded_basket = json.load(f)
                    
                    # --- AUTO-CLEAN LEGACY PATHS ---
                    cleaned_basket = []
                    for item in loaded_basket:
                        # If base_dir contains D:, we clean it for Linux
                        if platform.system() == "Linux" and ":" in item.get("base_dir", ""):
                            item["base_dir"] = item["base_dir"].split(":")[-1]
                        cleaned_basket.append(item)
                    
                    st.session_state.ui_basket = cleaned_basket
                    st.toast(f"✅ Panier '{sel_saved}' chargé et nettoyé !", icon="📂")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur lecture panier: {e}")

    # Display basket items
    if basket:
        with st.expander(f"🛒 Panier ({len(basket)} configs)", expanded=True):
            items_to_remove = []
            for i, item in enumerate(basket):
                ic1, ic2, ic3, ic4 = st.columns([3, 1, 1, 0.5])
                with ic1:
                    has_v, has_c, has_t = get_config_status_fn(item["name"], item["base_dir"])
                    v_ico, c_ico, t_ico = ("🎬" if has_v else "🌑"), ("⚙️" if has_c else "⏳"), ("⏱️" if has_t else "⚪")
                    ready_ico = "✅" if (has_v and has_c and has_t) else "  "
                    st.text(f"{v_ico}{c_ico}{t_ico}{ready_ico} {item['name']}")
                with ic2:
                    if st.button("📂 Charger", key=f"bsk_load_{i}", use_container_width=True):
                        path = os.path.join(item["base_dir"], item["name"])
                        if os.path.exists(path):
                            with open(path, "r", encoding="utf-8") as f:
                                cfg_data = json.load(f)
                            for k, v in cfg_data.items():
                                st.session_state[k] = v
                            st.session_state["ui_match_config_name"] = item["name"].replace(".json", "")
                            st.session_state.opta_processed = False
                            st.session_state.opta_df = None
                            st.toast(f"✅ '{item['name']}' chargé.", icon="📂")
                            st.rerun()
                with ic3:
                    if st.button("⬆️ Cache", key=f"bsk_proc_{i}", use_container_width=True):
                        path = os.path.join(item["base_dir"], item["name"])
                        if os.path.exists(path):
                            with open(path, "r", encoding="utf-8") as f:
                                cfg_data = json.load(f)
                            csv_p = cfg_data.get("csv_path", "").strip().strip("\"'")
                            if csv_p and os.path.exists(csv_p):
                                cache_p = get_opta_cache_path(csv_p)
                                if not os.path.exists(cache_p):
                                    with st.spinner(f"Traitement {item['name']}..."):
                                        processor = OptaProcessor()
                                        events = processor.process_file(csv_p, forced_match_name=item["name"].replace(".json", ""))
                                        df = pd.DataFrame(events)
                                        df.to_csv(cache_p, index=False)
                                    st.toast(f"✅ Cache créé pour '{item['name']}'.")
                                else:
                                    st.toast(f"⚠️ Cache déjà existant pour '{item['name']}'.", icon="⚠️")
                            else:
                                st.toast(f"❌ CSV introuvable pour '{item['name']}'.", icon="❌")
                with ic4:
                    if st.button("🗑️", key=f"bsk_del_{i}", help="Retirer du panier"):
                        items_to_remove.append(i)

            if items_to_remove:
                for idx in sorted(items_to_remove, reverse=True):
                    st.session_state.ui_basket.pop(idx)
                st.rerun()

        # Process ALL caches in basket button
        if st.button("⚡ Télécharger Tous les Caches du Panier", use_container_width=True, type="secondary"):
            total = len(basket)
            progress_bar = st.progress(0)
            import concurrent.futures

            def fix_path_for_vps(p):
                if not p: return p
                if platform.system() == "Linux":
                    # Remove drive letter if present (D:/...)
                    if ":" in p and not p.startswith("/"):
                        p = p.split(":")[-1]
                    # Ensure it's absolute from project root if it was a Windows path
                    if p.startswith("/Montage video football/"):
                        p = os.path.join("/home/datafoot", p.lstrip("/"))
                return p

            def process_one_cache(item):
                m_name = item['name']
                base_dir = fix_path_for_vps(item.get("base_dir", ""))
                path = os.path.join(base_dir, m_name)
                if not os.path.exists(path):
                    return f"❓ {m_name} : Config introuvable ({path})."
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        cfg_data = json.load(f)
                    csv_p = fix_path_for_vps(cfg_data.get("csv_path", "").strip().strip("\"'"))
                    if not csv_p or not os.path.exists(csv_p):
                        return f"❌ {m_name} : CSV source introuvable ({csv_p})."
                    
                    cache_p = get_opta_cache_path(csv_p)
                    if not os.path.exists(cache_p):
                        processor = OptaProcessor()
                        events = processor.process_file(csv_p, forced_match_name=m_name.replace(".json", ""))
                        df = pd.DataFrame(events)
                        df.to_csv(cache_p, index=False)
                        return f"✅ {m_name} : Cache créé."
                    return None # Already exists
                except Exception as e:
                    return f"⚠️ {m_name} : Erreur - {str(e)}"

            status = st.empty()
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                future_to_item = {executor.submit(process_one_cache, item): item for item in basket}
                completed = 0
                for future in concurrent.futures.as_completed(future_to_item):
                    completed += 1
                    res = future.result()
                    progress_bar.progress(completed / total)
                    status.markdown(f"Traitement en cours... **{completed}/{total}**")
            
            status.empty()
            progress_bar.empty()
            st.success("✅ Tous les caches ont été créés !")
            st.rerun()

        # NEW: Global Re-Process button to apply new scoring logic to all matches
        if st.button("⚙️ RE-TRAITER TOUTES LES DONNÉES (FULL PROCESS)", use_container_width=True, type="secondary", help="Force le re-calcul complet des scores pour tous les matchs du panier en PARALLÈLE."):
            total = len(basket)
            progress_bar = st.progress(0)
            status = st.empty()
            
            import concurrent.futures
            
            def fix_path_for_vps(p):
                if not p: return p
                if platform.system() == "Linux":
                    if ":" in p and not p.startswith("/"):
                        p = p.split(":")[-1]
                    if p.startswith("/Montage video football/"):
                        p = os.path.join("/home/datafoot", p.lstrip("/"))
                return p

            def process_single_match(item):
                m_name = item['name']
                base_dir = fix_path_for_vps(item.get("base_dir", ""))
                path = os.path.join(base_dir, m_name)
                if not os.path.exists(path):
                    return f"❓ {m_name} : Config JSON introuvable ({path})."
                
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        cfg_data = json.load(f)
                    csv_p = fix_path_for_vps(cfg_data.get("csv_path", "").strip().strip("\"'"))
                    if not csv_p or not os.path.exists(csv_p):
                        return f"❌ {m_name} : CSV d'origine introuvable ({csv_p})."
                    
                    cache_p = get_opta_cache_path(csv_p)
                    
                    # Core processing call
                    processor = OptaProcessor()
                    events = processor.process_file(csv_p, forced_match_name=m_name.replace(".json", ""))
                    df = pd.DataFrame(events)
                    df.to_csv(cache_p, index=False)
                    
                    return f"✅ {m_name} : Terminé."
                except Exception as e:
                    return f"⚠️ {m_name} : Erreur - {str(e)}"

            # Use a container to show logs
            with st.expander("📝 Détails du re-calcul (Parallèle)", expanded=True):
                logs_area = st.empty()
                logs = []
                
                # Use ThreadPoolExecutor for parallel processing
                max_workers = 8 # Process 8 matches at a time
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all tasks
                    future_to_match = {executor.submit(process_single_match, item): item for item in basket}
                    
                    completed = 0
                    for future in concurrent.futures.as_completed(future_to_match):
                        result_msg = future.result()
                        logs.append(result_msg)
                        completed += 1
                        
                        # Update status
                        progress_bar.progress(completed / total)
                        status.markdown(f"Traitement en cours... **{completed}/{total}**")
                        logs_area.markdown("\n".join(logs))
            
            status.empty()
            progress_bar.empty()
            st.success(f"✅ Re-traitement parallèle de {total} matchs terminé !")
            if st.button("🔄 Rafraîchir l'interface"):
                st.rerun()
    else:
        st.info("Le panier est vide. Ajoutez des configurations depuis l'onglet 'Config Match'.")

    # =========================================================================
    # MULTI-MATCH AGGREGATE
    # =========================================================================
    st.divider()
    st.subheader("🌐 Multi-Match / Agrégat")
    st.markdown(
        """
        Chargez **tous les matchs du panier** en mémoire pour appliquer vos filtres sur l'ensemble des matchs.
        Les onglets **Filtrage**, **Aperçu** et **Visualisations** afficheront les événements combinés.
        """
    )

    if basket:
        if st.button("📥 Charger le Panier en Mode Agrégat", use_container_width=True, type="primary"):
            all_dfs = []
            errors_agg = []
            agg_bar = st.progress(0)
            agg_status = st.empty()
            total_agg = len(basket)

            import concurrent.futures

            def load_one_match(item):
                path = os.path.join(item["base_dir"], item["name"])
                if not os.path.exists(path):
                    return None, f"Config introuvable : {item['name']}"
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        cfg_data = json.load(f)
                    csv_p = cfg_data.get("csv_path", "").strip().strip("\"'")
                    if not csv_p:
                        return None, f"Pas de CSV dans : {item['name']}"
                    cache_p = get_opta_cache_path(csv_p)
                    if os.path.exists(cache_p):
                        df_tmp = pd.read_csv(cache_p)
                        df_tmp["_source_config_file"] = item["name"]
                        df_tmp["_source_config_dir"] = item["base_dir"]
                        df_tmp["_source_config_base"] = item.get("base_name", "Default")
                        return df_tmp, None
                    else:
                        return None, f"Cache manquant pour : {item['name']}"
                except Exception as ex:
                    return None, f"Erreur '{item['name']}': {str(ex)}"

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                # Submit all tasks
                future_to_item = {executor.submit(load_one_match, item): item for item in basket}
                
                completed = 0
                for future in concurrent.futures.as_completed(future_to_item):
                    item = future_to_item[future]
                    d, err = future.result()
                    if d is not None:
                        all_dfs.append(d)
                    if err:
                        errors_agg.append(err)
                    
                    completed += 1
                    agg_bar.progress(completed / total_agg)
                    agg_status.markdown(f"Chargement : **{item['name']}** ({completed}/{total_agg})")

            agg_status.empty()
            agg_bar.empty()
            if all_dfs:
                merged_df = pd.concat(all_dfs, ignore_index=True)
                st.session_state.opta_df = merged_df
                st.session_state.opta_processed = True
                st.session_state.is_aggregate_mode = True
                st.session_state.df_preview = None

                total_cfg = len(basket)
                loaded_cfg = len(all_dfs)
                total_events = len(merged_df)
                st.success(f"✅ Agrégat chargé ! {loaded_cfg}/{total_cfg} matchs. {total_events:,} événements en mémoire.")

                if errors_agg:
                    with st.expander("⚠️ Avertissements"):
                        for err in errors_agg:
                            st.warning(err)
            else:
                st.error("Aucune donnée valide trouvée dans le panier. Traitez d'abord les caches.")

        if st.session_state.get("is_aggregate_mode") and st.session_state.opta_df is not None:
            if st.button("🗑️ Sortir du mode Agrégat", use_container_width=True):
                st.session_state.is_aggregate_mode = False
                st.session_state.opta_df = None
                st.session_state.opta_processed = False
                st.session_state.df_preview = None
                st.rerun()
    else:
        st.info("Ajoutez des configurations dans le panier ci-dessus pour activer le mode Agrégat.")

    # =========================================================================
    # TURBO BATCH
    # =========================================================================
    st.divider()
    st.subheader("🚀 Turbo Batch (Extraction Parallèle)")
    st.markdown(
        """
        Traite **tous les matchs séquentiellement ou en parallèle** en appliquant les filtres actuels.
        Idéal pour générer des highlights depuis plusieurs matchs d'un coup.
        """
    )

    if not basket:
        st.info("Ajoutez des configurations dans le panier pour activer le Turbo Batch.")
    else:
        batch_cfgs_options = [item["name"] for item in basket]

        sf1, sf2 = st.columns([2, 1])
        with sf1:
            batch_configs = st.multiselect(
                "Sélectionner les matchs pour ce run (défaut: tous)",
                options=batch_cfgs_options,
                default=batch_cfgs_options,
                key="ui_turbo_batch_configs",
            )
        with sf2:
            PROFILE_DIR_b = "profiles"
            if os.path.exists(PROFILE_DIR_b):
                avail_p = sorted([f for f in os.listdir(PROFILE_DIR_b) if f.endswith(".json")])
            else:
                avail_p = []
            batch_profile_sel = st.selectbox(
                "Filtres à appliquer",
                ["(UI Actuelle)"] + avail_p,
                key="ui_turbo_profile",
                help="Sélectionnez le profil de filtres à utiliser pour ce Turbo Batch. '(UI Actuelle)' utilise les filtres actifs.",
            )

        result["batch_configs"] = batch_configs
        result["batch_profile_sel"] = batch_profile_sel

        # Lecture seule — le widget canonique est dans la colonne de droite (ui_sidebar.py).
        # On ne recrée pas de widget ici pour éviter la clé dupliquée.
        mixed_assembly_batch = st.session_state.get("ui_mixed_assembly", False)
        st.caption(
            f"🚀 Montage Mixte (Interleaved) : **{'Activé ✅' if mixed_assembly_batch else 'Désactivé'}** "
            "— modifiable depuis « Organisation du rendu > Vidéo unique globale » (colonne de droite)."
        )

        tc_b1, tc_b2 = st.columns(2)
        with tc_b1:
            result["turbo_run_btn"] = st.button(
                "🚀 LANCER TURBO BATCH",
                use_container_width=True,
                type="primary",
                disabled=not batch_configs,
            )
        with tc_b2:
            result["turbo_xml_btn"] = st.button(
                "📽️ XML Premiere (Turbo)",
                use_container_width=True,
                disabled=not batch_configs,
            )

    return result
