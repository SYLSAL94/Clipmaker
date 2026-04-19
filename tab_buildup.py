"""
tab_buildup.py
==============
Onglet "Build-Up & Séquences" de ClipMaker SUAOL.
Analyse des séquences de possession pré-taguées (sub_sequence_id),
filtrage en temps-réel, visualisation tactique et génération vidéo.
"""

import json
import os
import queue
import subprocess
import threading

import pandas as pd
import streamlit as st

from clip_processing import (
    to_seconds, assign_periods, match_clock_to_video_time, get_ffmpeg_binary,
    cut_clip_ffmpeg, cut_and_concat_ffmpeg,
)
from interactive_visualizations import plot_tactical_sequence
from ui_theme import step_header
from r2_manager import get_r2_presigned_url



def _parse_period(val):
    """Parse une valeur de période (string ou int/float) vers 1 ou 2."""
    if val is None or pd.isna(val):
        return 1
    v = str(val).lower()
    if v in ["firsthalf", "1sthalf", "h1", "1", "1.0"]:
        return 1
    if v in ["secondhalf", "2ndhalf", "h2", "2", "2.0"]:
        return 2
    try:
        return int(float(val))
    except:
        return 1


def _get_bu_summary_df(df_seq):
    """
    Crée un résumé condensé des séquences (1 ligne par séquence) de manière vectorisée.
    Optimisé pour la vitesse en évitant les apply() coûteux sur de gros groupes.
    """
    # 1. Pré-calcul des indicateurs au niveau de la ligne (Vectorisé)
    df_seq["_is_success_pass"] = (df_seq["type"] == "Pass") & (df_seq["outcomeType"] == "Successful")
    
    if "prog_pass" in df_seq.columns and "prog_carry" in df_seq.columns:
        df_seq["_is_prog"] = (df_seq["prog_pass"].fillna(0) > 0) | (df_seq["prog_carry"].fillna(0) > 0)
    else:
        # Fallback si les colonnes enrichment ne sont pas là
        try:
            df_seq["_is_prog"] = (df_seq["endX"].fillna(0).astype(float) - df_seq["x"].fillna(0).astype(float)) >= 10
        except:
            df_seq["_is_prog"] = False

    group_cols = ["sub_sequence_id"]
    if "_source_config_file" in df_seq.columns:
        group_cols.insert(0, "_source_config_file")

    # 2. Agrégation principale
    agg_map = {
        "teamName": "first",
        "minute": ["min", "max"],
        "second": ["first", "last"],
        "period": ["first", "last"],
        "seq_team": "first",
        "possession_team": "first",
        "possession_id": "first",
        "seq_pass_count": "first",
        "seq_action_count": "first",
        "seq_prog_action_count": "first",
        "seq_score": "first",
        "seq_has_shot": "first",
        "seq_has_goal": "first",
        "seq_is_fast_break": "first",
        "seq_tempo_s": "first",
        "seq_starts_own_half": "first",
        "seq_reaches_opp_half": "first",
    }
    # Filtrer l'agg_map pour ne garder que les colonnes présentes
    agg_map = {k: v for k, v in agg_map.items() if k in df_seq.columns}
    
    # On ajoute les listes d'indices
    df_seq["_temp_idx"] = df_seq.index
    agg_map["_temp_idx"] = lambda x: x.tolist()
    agg_map["playerName"] = lambda x: list(set(x.dropna().unique()))

    summary = df_seq.groupby(group_cols).agg(agg_map)
    
    # Nettoyage des colonnes multi-index
    summary.columns = [
        f"{col}_{func}" if isinstance(func, str) and func in ["min", "max", "first", "last"] else col 
        for col, func in summary.columns
    ]

    # 3. Calcul des stats par joueur (Optimisé : un seul groupby sur le sous-ensemble)
    player_counts = df_seq[df_seq["playerName"].notna()].groupby(group_cols + ["playerName"]).agg(
        passes=("_is_success_pass", "sum"),
        prog=("_is_prog", "sum")
    ).reset_index()

    # On transforme en dictionnaire {joueur: {stats}} pour chaque séquence
    def build_player_dict(grp):
        return {r.playerName: {"passes": int(r.passes), "prog": int(r.prog)} for r in grp.itertuples()}

    stats_series = player_counts.groupby(group_cols).apply(build_player_dict, include_groups=False)
    summary["player_stats"] = stats_series
    
    # Renommage final
    rename_rules = {
        "teamName_first": "team_raw",
        "seq_team_first": "team",
        "minute_min": "start_minute",
        "minute_max": "end_minute",
        "second_first": "start_second",
        "second_last": "end_second",
        "period_first": "start_period",
        "period_last": "end_period",
        "playerName": "players",
        "_temp_idx": "indices",
        "possession_id_first": "possession_id",
        "seq_pass_count_first": "seq_pass_count",
        "seq_action_count_first": "seq_action_count",
        "seq_prog_action_count_first": "seq_prog_action_count",
        "seq_score_first": "seq_score",
        "seq_has_shot_first": "has_shot",
        "seq_has_goal_first": "has_goal",
        "seq_is_fast_break_first": "is_fast_break"
    }
    summary = summary.rename(columns=rename_rules)
    
    if "team" not in summary.columns:
        summary["team"] = summary["team_raw"] if "team_raw" in summary.columns else "?"
    
    return summary.reset_index()



def render_tab_buildup(MATCH_CONFIG_DIR: str, TEMP_DIR: str):
    """Affiche l'onglet Build-Up & Séquences."""
    st.markdown(step_header(5, "Analyse des Séquences de Construction (Build-Up)"), unsafe_allow_html=True)
    st.subheader("📊 Analyse des Séquences (Build-Up)")
    st.markdown(
        """
        Les séquences de possession sont **pré-analysées** lors du chargement des données.
        Utilisez les filtres ci-dessous pour explorer les phases de construction et transitions offensives.
        """
    )

    if st.session_state.opta_df is None or st.session_state.opta_df.empty:
        st.info("💡 Chargez des données Opta pour activer l'analyse du Build-Up.")
        return

    _df_bu = st.session_state.opta_df

    if "sub_sequence_id" not in _df_bu.columns:
        st.warning("⚠️ Les données n'ont pas été traitées avec le processeur enrichi. Rechargez les données pour activer le Build-Up optimisé.")
        return

    # ---- Extraction du résumé en cache (Corrigé : On vérifie aussi la présence de player_stats) ----
    need_refresh = "bu_summary_df" not in st.session_state or \
                   st.session_state.get("bu_last_df_len") != len(_df_bu) or \
                   (not st.session_state.bu_summary_df.empty and "player_stats" not in st.session_state.bu_summary_df.columns)

    if need_refresh:
        with st.spinner("Pré-agrégation des séquences..."):
            df_seq_raw = _df_bu[_df_bu["sub_sequence_id"].notna()].copy()
            if not df_seq_raw.empty:
                st.session_state.bu_summary_df = _get_bu_summary_df(df_seq_raw)
                st.session_state.bu_last_df_len = len(_df_bu)
            else:
                st.session_state.bu_summary_df = pd.DataFrame()

    summary_df = st.session_state.bu_summary_df
    if summary_df.empty:
        st.warning("⚠️ Aucune possession détectée dans les données.")
        return

    # ---- Filters ----
    bu_c1, bu_c1b, bu_c2, bu_c3, bu_c4, bu_c5 = st.columns([2, 1, 1.3, 1.3, 1.5, 1.5])
    with bu_c1:
        teams_avail = ["Toutes"] + sorted(summary_df["team"].dropna().unique().tolist())
        st.selectbox("Équipe à analyser", options=teams_avail, key="ui_bu_team")
    with bu_c1b:
        st.write("")
        st.write("")
        st.checkbox("Contre", key="ui_bu_contre", help="Inverser : afficher les séquences de l'adversaire")
    with bu_c2:
        st.number_input("Min. passes", min_value=0, max_value=30, step=1, key="ui_bu_min_passes")
    with bu_c3:
        st.number_input("Min. actions", min_value=1, max_value=30, step=1, key="ui_bu_min_actions")
    with bu_c4:
        st.number_input("Min. progressives (seq)", min_value=0, max_value=20, step=1, key="ui_bu_min_prog")
    with bu_c5:
        st.number_input("Score Min", min_value=0.0, max_value=50.0, step=0.5, format="%.1f", key="ui_bu_min_score")

    const_c1, const_c2, const_c3, const_c4, const_c5 = st.columns(5)
    with const_c1:
        st.checkbox("Départ zone déf.", key="ui_bu_starts_own")
    with const_c2:
        st.checkbox("Atteint zone off.", key="ui_bu_reaches_opp")
    with const_c3:
        st.checkbox("Avec Tir/But", key="ui_bu_shots")
    with const_c4:
        st.checkbox("Contre-attaques", key="ui_bu_fast_break")

    pl_c1, pl_c1b, pl_c2, pl_c3 = st.columns([2, 1.5, 1, 1])
    # Extraction de la liste des joueurs depuis le résumé au lieu du dataframe complet
    all_bu_players = sorted(list(set([p for players in summary_df["players"] for p in players])))
    
    with pl_c1:
        st.multiselect("Joueurs impliqués", options=all_bu_players, key="ui_bu_players")
    with pl_c1b:
        st.multiselect("Joueurs exclus", options=all_bu_players, key="ui_bu_exclude_players")
    with pl_c2:
        st.number_input("Min passes", min_value=0, max_value=20, step=1, key="ui_bu_player_min_passes", help="Min par joueur sélectionné")
    with pl_c3:
        st.number_input("Min progressives", min_value=0, max_value=10, step=1, key="ui_bu_player_min_prog", help="Actions progressives par joueur sélectionné")

    st.write("")
    c_btn, _ = st.columns([1, 4])
    with c_btn:
        if st.button("🔍 Afficher les Séquences", use_container_width=True, type="primary"):
            # Filtrage vectorisé sur le résumé
            mask = pd.Series([True] * len(summary_df), index=summary_df.index)
            
            # Équipe
            sel_team = st.session_state.ui_bu_team
            is_contre = st.session_state.get("ui_bu_contre", False)
            if sel_team != "Toutes":
                if is_contre:
                    mask &= summary_df["team"].str.lower() != sel_team.lower()
                else:
                    mask &= summary_df["team"].str.lower() == sel_team.lower()

            # Métriques
            if st.session_state.ui_bu_min_passes > 0:
                mask &= summary_df["seq_pass_count"] >= st.session_state.ui_bu_min_passes
            if st.session_state.ui_bu_min_actions > 1:
                mask &= summary_df["seq_action_count"] >= st.session_state.ui_bu_min_actions
            if st.session_state.ui_bu_min_prog > 0:
                mask &= summary_df["seq_prog_action_count"] >= st.session_state.ui_bu_min_prog
            if st.session_state.ui_bu_min_score > 0:
                mask &= summary_df["seq_score"] >= st.session_state.ui_bu_min_score
                
            # Zones & Types
            if st.session_state.ui_bu_starts_own:
                mask &= summary_df["seq_starts_own_half_first"] == True
            if st.session_state.ui_bu_reaches_opp:
                mask &= summary_df["seq_reaches_opp_half_first"] == True
            if st.session_state.ui_bu_shots:
                mask &= (summary_df["has_shot"] == True) | (summary_df["has_goal"] == True)
            if st.session_state.ui_bu_fast_break:
                mask &= summary_df["is_fast_break"] == True

            # Filtrage Joueurs
            sel_players = st.session_state.get("ui_bu_players", [])
            min_p = st.session_state.get("ui_bu_player_min_passes", 0)
            min_prog_p = st.session_state.get("ui_bu_player_min_prog", 0)

            if sel_players:
                def check_players(row_stats):
                    if not isinstance(row_stats, dict): return False
                    for p in sel_players:
                        if p in row_stats:
                            s = row_stats[p]
                            if s.get("passes", 0) >= min_p and s.get("prog", 0) >= min_prog_p:
                                return True
                    return False
                mask &= summary_df["player_stats"].apply(check_players)
            
            exclude_players = st.session_state.get("ui_bu_exclude_players", [])
            if exclude_players:
                mask &= summary_df["players"].apply(lambda pl: not any(p in pl for p in exclude_players))

            filtered_df = summary_df[mask].copy()
            
            # Tri
            sort_cols = []
            if "_source_config_file" in filtered_df.columns:
                sort_cols.append("_source_config_file")
            sort_cols.extend(["start_period", "start_minute", "start_second"])
            filtered_df = filtered_df.sort_values(sort_cols)

            # Transformation optimisée en liste de dicts
            if not filtered_df.empty:
                if "_source_config_file" in filtered_df.columns:
                    filtered_df["match_name"] = filtered_df["_source_config_file"].str.replace(".json", "", case=False).str.replace(".JSON", "", case=False)
                else:
                    filtered_df["match_name"] = None
                
                filtered_df["start_period"] = filtered_df["start_period"].apply(_parse_period)
                filtered_df["end_period"] = filtered_df["end_period"].apply(_parse_period)
                
                # Conversion explicite en int pour éviter ValueError avec :02d
                for col in ["start_minute", "start_second", "end_minute", "end_second", "action_count", "seq_pass_count"]:
                    if col in filtered_df.columns:
                        filtered_df[col] = filtered_df[col].fillna(0).astype(int)

                display_chains = filtered_df.to_dict("records")
            else:
                display_chains = []

            st.session_state.ui_bu_chains = display_chains
            st.session_state.ui_bu_active_idx = 0
            st.session_state.ui_bu_active_clip = None
            st.session_state.ui_bu_page = 0
            st.rerun()

    # ---- Display from session state ----
    display_chains = st.session_state.get("ui_bu_chains", [])
    if not display_chains:
        return

    # Stats banner
    st.markdown(
        f"""
        <div class="cm-stats-bar">
            <div class="cm-stats-cell"><div class="cm-stats-label">SÉQUENCES</div><div class="cm-stats-value">{len(display_chains)}</div></div>
            <div class="cm-stats-cell"><div class="cm-stats-label">AVEC TIR</div><div class="cm-stats-value">{sum(1 for c in display_chains if c.get('has_shot'))}</div></div>
            <div class="cm-stats-cell"><div class="cm-stats-label">AVEC BUT</div><div class="cm-stats-value">{sum(1 for c in display_chains if c.get('has_goal'))}</div></div>
            <div class="cm-stats-cell"><div class="cm-stats-label">CONTRE-ATT.</div><div class="cm-stats-value">{sum(1 for c in display_chains if c.get('is_fast_break'))}</div></div>
            <div class="cm-stats-cell"><div class="cm-stats-label">MOY. PASSES</div><div class="cm-stats-value">{sum(c.get('seq_pass_count', 0) for c in display_chains) / max(len(display_chains), 1):.1f}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()
    bu_list_col, bu_map_col = st.columns([1.5, 2.5])

    if "ui_bu_active_idx" not in st.session_state:
        st.session_state.ui_bu_active_idx = 0
    if "ui_bu_active_clip" not in st.session_state:
        st.session_state.ui_bu_active_clip = None

    chain_data = display_chains[min(st.session_state.ui_bu_active_idx, len(display_chains) - 1)]

    with bu_list_col:
        # --- PAGINATION LOGIC ---
        PAGE_SIZE = 40
        all_chains = display_chains
        total_p = (len(all_chains) - 1) // PAGE_SIZE + 1
        curr_p = min(st.session_state.get("ui_bu_page", 0), total_p - 1)
        if curr_p < 0: curr_p = 0
        
        if total_p > 1:
            pag_c1, pag_c2, pag_c3 = st.columns([1, 2, 1])
            with pag_c1:
                if st.button("⬅️", disabled=(curr_p == 0), use_container_width=True, key="bu_prev_page"):
                    st.session_state.ui_bu_page = curr_p - 1
                    st.rerun()
            with pag_c2:
                st.markdown(f"<center><small>Page {curr_p + 1} / {total_p}</small></center>", unsafe_allow_html=True)
            with pag_c3:
                if st.button("➡️", disabled=(curr_p >= total_p - 1), use_container_width=True, key="bu_next_page"):
                    st.session_state.ui_bu_page = curr_p + 1
                    st.rerun()
        
        start_idx = curr_p * PAGE_SIZE
        end_idx = min(start_idx + PAGE_SIZE, len(all_chains))
        curr_chains = all_chains[start_idx:end_idx]

        st.markdown(
            """
            <style>
            div.st-key-bu_list_container div.stButton > button[kind="secondary"] {
                text-align: left !important;
                justify-content: flex-start !important;
                background: rgba(255, 255, 255, 0.02) !important;
                border-left: 3px solid transparent !important;
                color: #ffffff !important;
                font-family: 'JetBrains Mono', monospace !important;
                font-size: 11px !important;
                height: auto !important;
                padding: 10px 14px !important;
                line-height: 1.4 !important;
                border-radius: 6px !important;
            }
            div.st-key-bu_list_container div.stButton > button[kind="secondary"]:hover {
                border-left-color: var(--accent) !important;
                background: rgba(255, 255, 255, 0.05) !important;
            }
            .bu-active-card-btn div.stButton > button[kind="secondary"] {
                background: linear-gradient(90deg, rgba(223, 255, 0, 0.1), transparent) !important;
                border-left: 4px solid var(--accent) !important;
                color: var(--accent) !important;
                font-weight: 700 !important;
            }
            </style>
            """,
            unsafe_allow_html=True
        )
        with st.container(height=650, key="bu_list_container"):
            for i_local, c in enumerate(curr_chains):
                i_global = start_idx + i_local
                is_active = (i_global == st.session_state.ui_bu_active_idx)
                
                if is_active:
                    st.markdown('<div class="bu-active-card-btn">', unsafe_allow_html=True)

                col_card, col_play = st.columns([5.2, 0.8], gap="small")
                with col_card:
                    icons = ""
                    if c.get("has_goal"): icons += " 🔥"
                    elif c.get("has_shot"): icons += " 🚩"
                    if c.get("is_fast_break"): icons += " ⚡"

                    score_val = c.get('seq_score', 0)
                    score_lbl = f" ★{score_val:.1f}" if score_val > 0 else ""
                    p_id_str = f"P{int(c['possession_id'])} · " if c.get("possession_id") else ""
                    match_prefix = f"[{c['match_name']}] " if c.get("match_name") else ""
                    period_lbl = f"{c['start_period']}H" if c["start_period"] < 3 else "ET"
                    lbl = f"{match_prefix}{p_id_str}{c['start_minute']}'{c['start_second']:02d}\" → {c['end_minute']}'{c['end_second']:02d}\" ({period_lbl})  ·  {c.get('action_count', 0)} ACTS · {c.get('seq_pass_count', 0)}P{icons}{score_lbl}"

                    if st.button(lbl, key=f"bu_card_{i_global}", use_container_width=True):
                        st.session_state.ui_bu_active_idx = i_global
                        st.session_state.ui_bu_trigger_play = True
                        st.session_state.ui_bu_active_clip = None 
                        st.rerun()

                with col_play:
                    if st.button("▶", key=f"bu_play_{i_global}", use_container_width=True):
                        st.session_state.ui_bu_active_idx = i_global
                        st.session_state.ui_bu_trigger_play = True
                        st.rerun()

                if is_active:
                    st.markdown("</div>", unsafe_allow_html=True)

        st.divider()
        st.markdown("##### 📦 Actions sur la Sélection")
        export_name = st.text_input(
            "Nom de l'export",
            value=f"BuildUp_{st.session_state.ui_bu_team.replace(' ', '_')}_{len(display_chains)}",
            key="ui_bu_export_name",
        )

        ex_c1, ex_c2 = st.columns(2)
        with ex_c1:
            if st.button("🎥 Export Fusionné", use_container_width=True, type="primary"):
                st.session_state.ui_bu_batch_mode = "merge"
                st.session_state.ui_bu_trigger_batch = True
                st.rerun()
        with ex_c2:
            if st.button("📂 Export Individuel", use_container_width=True):
                st.session_state.ui_bu_batch_mode = "split"
                st.session_state.ui_bu_trigger_batch = True
                st.rerun()

        st.divider()
        st.markdown("##### ⚙️ Réglages Séquence")
        before_bu = st.number_input("Buffer avant (s)", 0, 15, 5)
        after_bu = st.number_input("Buffer après (s)", 0, 15, 3)

    with bu_map_col:
        if chain_data:
            st.markdown(f"#### SEQUENCE DETAIL · {chain_data['start_minute']}'{chain_data['start_second']:02d} - {chain_data['end_minute']}'{chain_data['end_second']:02d}")

            # --- RÉCUPÉRATION ROBUSTE DES DONNÉES DE LA SÉQUENCE ---
            # Au lieu de se fier aux index (qui peuvent changer lors d'un rechargement), 
            # on utilise sub_sequence_id et le nom du fichier source si disponible.
            seq_id = chain_data["sub_sequence_id"]
            m_name = chain_data.get("match_name")
            
            mask_seq = (_df_bu["sub_sequence_id"] == seq_id)
            if m_name and "_source_config_file" in _df_bu.columns:
                # On recrée le nom du fichier pour matcher la colonne brute
                mask_seq &= (_df_bu["_source_config_file"].str.replace(".json", "", case=False).str.replace(".JSON", "", case=False) == m_name)

            chain_df = _df_bu[mask_seq].copy()
            
            # Fallback sur les indices si la méthode filtrée ne donne rien (sécurité)
            if chain_df.empty and "indices" in chain_data:
                valid_idx = [i for i in chain_data["indices"] if i in _df_bu.index]
                if valid_idx:
                    chain_df = _df_bu.loc[valid_idx].copy()

            if chain_df.empty:
                st.warning("⚠️ Les données de cette séquence sont introuvables dans le dataset actuel. Essayez de re-cliquer sur 'Afficher les Séquences'.")
            else:
                # Affichage de la carte tactique
                fig_bu = plot_tactical_sequence(chain_df, team_name=chain_data["team"])
                st.plotly_chart(fig_bu, use_container_width=True)

            # ---- BATCH DIALOG ----
            if st.session_state.get("ui_bu_trigger_batch"):
                @st.dialog("🎬 Batch Render Build-Up", width="large")
                def bu_batch_render_dialog():
                    st.write(f"Séquences à traiter : **{len(display_chains)}**")
                    st.write(f"Mode : **{st.session_state.ui_bu_batch_mode}**")
                    log_container = st.empty()
                    prog_bar = st.progress(0)

                    if st.session_state.get("bu_batch_done"):
                        st.success("✅ Batch Export terminé !")
                        if st.button("Fermer", use_container_width=True):
                            st.session_state.bu_batch_done = False
                            st.session_state.ui_bu_trigger_batch = False
                            st.rerun()
                        return

                    all_specs = []
                    for c_item in display_chains:
                        c_idx = c_item.get("indices", [])
                        if not c_idx:
                            continue
                        c_df = _df_bu.loc[c_idx].copy()
                        p_col = st.session_state.get("period_column", "period") if not st.session_state.get("use_fallback") else None
                        f_row = st.session_state.get("fallback_row", 0)
                        c_df = assign_periods(c_df, p_col, f_row)

                        src_conf = c_df.iloc[0].get("_source_config_file")
                        src_dir = c_df.iloc[0].get("_source_config_dir") or MATCH_CONFIG_DIR

                        if not src_conf and not st.session_state.get("is_aggregate_mode"):
                            h_cfg = {
                                "video_path": st.session_state.video_path, "video2_path": st.session_state.video2_path,
                                "ui_half1": st.session_state.get("ui_half1", "0:00"), "ui_half2": st.session_state.get("ui_half2", "0:00"),
                                "ui_split_video": st.session_state.get("ui_split_video", False),
                            }
                        else:
                            conf_path = os.path.join(src_dir, src_conf) if src_conf else None
                            if conf_path and os.path.exists(conf_path):
                                with open(conf_path, "r", encoding="utf-8") as f:
                                    h_cfg = json.load(f)
                            else:
                                continue

                        ps = {1: to_seconds(h_cfg.get("ui_half1") or "0:00"), 2: to_seconds(h_cfg.get("ui_half2") or "0:00")}
                        po = {1: (0, 0), 2: (45, 0)}
                        p_val = _parse_period(c_df.iloc[0].get("period", 1))
                        p_val_end = _parse_period(c_df.iloc[-1].get("period", 1))

                        ts = match_clock_to_video_time(int(c_df.iloc[0]["minute"]), int(c_df.iloc[0]["second"]), p_val, ps, po) - before_bu
                        te = match_clock_to_video_time(int(c_df.iloc[-1]["minute"]), int(c_df.iloc[-1]["second"]), p_val_end, ps, po) + after_bu

                        video_url1 = h_cfg.get("video_path", "").strip().strip("\"'")
                        video_url2 = h_cfg.get("video2_path", "").strip().strip("\"'")

                        # --- 🌐 CLOUD-NATIVE DECODING (R2 Keys -> URLs) ---
                        if video_url1 and not video_url1.startswith(('http', '/')) and not os.path.exists(video_url1):
                            video_url1 = get_r2_presigned_url(video_url1)
                        if video_url2 and not video_url2.startswith(('http', '/')) and not os.path.exists(video_url2):
                            video_url2 = get_r2_presigned_url(video_url2)

                        vs = video_url1
                        if h_cfg.get("ui_split_video") and p_val >= 2:
                            vs = video_url2


                        all_specs.append({
                            "src": vs, "start": max(0, ts), "end": te,
                            "label": f"{c_item['team']} {c_item['start_minute']}'{c_item['start_second']:02d}",
                            "team_name": c_item["team"], "match_name": c_item.get("match_name", "Match"),
                        })

                    if not all_specs:
                        st.error("Aucune spec valide.")
                        return

                    f_out_dir = st.session_state.output_dir or "exports"
                    os.makedirs(f_out_dir, exist_ok=True)
                    ff_bin = get_ffmpeg_binary()

                    if st.session_state.ui_bu_batch_mode == "merge":
                        out_p = os.path.join(f_out_dir, f"{st.session_state.ui_bu_export_name}.mp4")
                        q_rend = queue.Queue()
                        import time
                        t_rend = threading.Thread(target=cut_and_concat_ffmpeg, args=(ff_bin, all_specs, out_p, q_rend, time.time()))
                        t_rend.start()
                        while t_rend.is_alive() or not q_rend.empty():
                            try:
                                msg = q_rend.get(timeout=0.2)
                                if msg.get("phase") == "clips":
                                    cur, tot = msg.get("current", 0), msg.get("total", 0)
                                    prog_bar.progress(cur / tot)
                                    log_container.info(f"Rendu clip {cur}/{tot}...")
                            except:
                                pass
                        t_rend.join()
                    else:
                        for i, spc in enumerate(all_specs):
                            prog_bar.progress((i + 1) / len(all_specs))
                            o_single = os.path.join(f_out_dir, f"{st.session_state.ui_bu_export_name}_{i+1:02d}.mp4")
                            log_container.info(f"Export {i+1}/{len(all_specs)} : {o_single}")
                            
                            cut_clip_ffmpeg(
                                ffmpeg_bin=ff_bin,
                                src_path=spc["src"],
                                start=spc["start"],
                                end=spc["end"],
                                out_path=o_single
                            )

                    st.session_state.bu_batch_done = True
                    st.rerun()

                bu_batch_render_dialog()

            # ---- SINGLE PREVIEW ----
            if st.session_state.get("ui_bu_trigger_play"):
                st.session_state.ui_bu_trigger_play = False
                with st.spinner("Génération du clip en cours..."):
                    try:
                        p_col = st.session_state.get("period_column", "period") if not st.session_state.get("use_fallback") else None
                        f_row = st.session_state.get("fallback_row", 0)
                        chain_df = assign_periods(chain_df, p_col, f_row)

                        if chain_df.empty:
                            raise ValueError("Séquence vide.")

                        src_config = chain_df.iloc[0].get("_source_config_file")
                        src_dir = chain_df.iloc[0].get("_source_config_dir") or MATCH_CONFIG_DIR

                        if not src_config and not st.session_state.get("is_aggregate_mode"):
                            h_config = {
                                "video_path": st.session_state.video_path, "video2_path": st.session_state.video2_path,
                                "ui_half1": st.session_state.get("ui_half1", "0:00"), "ui_half2": st.session_state.get("ui_half2", "0:00"),
                                "ui_split_video": st.session_state.get("ui_split_video", False),
                            }
                        else:
                            conf_path = os.path.join(src_dir, src_config) if src_config else None
                            if conf_path and os.path.exists(conf_path):
                                with open(conf_path, "r", encoding="utf-8") as f:
                                    h_config = json.load(f)
                            else:
                                raise ValueError(f"Source introuvable : {src_config} dans {src_dir}")

                        p_start = {1: to_seconds(h_config.get("ui_half1") or "0:00"), 2: to_seconds(h_config.get("ui_half2") or "0:00")}
                        p_offset = {1: (0, 0), 2: (45, 0)}

                        def _match_t(row):
                            return match_clock_to_video_time(int(row["minute"]), int(row["second"]), int(row.get("resolved_period", 1)), p_start, p_offset)

                        t_start = _match_t(chain_df.iloc[0]) - before_bu
                        t_end = _match_t(chain_df.iloc[-1]) + after_bu

                        video_url1 = h_config.get("video_path", "").strip().strip("\"'")
                        video_url2 = h_config.get("video2_path", "").strip().strip("\"'")

                        # --- 🌐 CLOUD-NATIVE DECODING (R2 Keys -> URLs) ---
                        if video_url1 and not video_url1.startswith(('http', '/')) and not os.path.exists(video_url1):
                            video_url1 = get_r2_presigned_url(video_url1)
                        if video_url2 and not video_url2.startswith(('http', '/')) and not os.path.exists(video_url2):
                            video_url2 = get_r2_presigned_url(video_url2)

                        v_src = video_url1
                        if h_config.get("ui_split_video") and chain_df.iloc[0]["resolved_period"] >= 2:
                            v_src = video_url2

                        if not v_src:
                            raise FileNotFoundError("Source vidéo manquante.")
                        if not v_src.startswith('http') and not os.path.exists(v_src):
                            raise FileNotFoundError(f"Fichier vidéo introuvable localement : {v_src}")

                        out_name = f"BU_Preview_{chain_data['team'].replace(' ', '_')}_{chain_data['start_minute']}_{chain_data['start_second']}.mp4"
                        out_p = os.path.join(TEMP_DIR, out_name)
                        os.makedirs(TEMP_DIR, exist_ok=True)

                        # Utilisation de la fonction standardisée pour plus de robustesse
                        cut_clip_ffmpeg(
                            ffmpeg_bin=get_ffmpeg_binary(),
                            src_path=v_src,
                            start=max(0, t_start),
                            end=t_end,
                            out_path=out_p
                        )

                        if os.path.exists(out_p):
                            st.session_state.ui_bu_active_clip = out_p
                        else:
                            st.error("Le clip n'a pas pu être généré (FFmpeg).")

                    except Exception as e:
                        st.error(f"❌ Erreur lors de la génération du clip : {e}")

            if st.session_state.ui_bu_active_clip and os.path.exists(st.session_state.ui_bu_active_clip):
                st.video(st.session_state.ui_bu_active_clip)
                if st.button("💾 Enregistrer ce clip dans Exports", use_container_width=True):
                    import shutil
                    final_name = os.path.basename(st.session_state.ui_bu_active_clip).replace("BU_Preview_", "BuildUp_")
                    final_out = os.path.join(st.session_state.output_dir or "exports", final_name)
                    os.makedirs(os.path.dirname(final_out), exist_ok=True)
                    shutil.copy(st.session_state.ui_bu_active_clip, final_out)
                    st.toast(f"✅ Sauvegardé : {final_out}")
            else:
                st.info("ℹ️ Cliquez sur ▶ pour lire la séquence vidéo.")
