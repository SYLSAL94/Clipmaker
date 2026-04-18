"""
tab_preview.py
==============
Onglet "Aperçu & Visualisations" de ClipMaker SUAOL.
Contient : résumé du match, carte interactive Plotly (click-to-watch),
lecteur vidéo (single & batch), cartes matplotlib, et tableau détaillé.
"""

import os
import subprocess

import pandas as pd
import streamlit as st

from clip_processing import (
    to_seconds, get_merged_specs_from_df, get_ffmpeg_binary,
    assign_periods, match_clock_to_video_time,
)
from interactive_visualizations import plot_interactive_pitch
from dashboard_analytics import compute_pass_connections, compute_duel_connections, compute_player_leaderboard
from ui_theme import step_header


def render_tab_preview(_df, FLAT_ZONES: dict):
    """
    Affiche l'onglet Aperçu & Visualisations.
    _df : le dataframe Opta courant (non filtré, pour les métriques globales).
    """
    st.markdown(step_header(4, "Visualisation Tactique & Aperçu Vidéo"), unsafe_allow_html=True)

    # --- Dashboard summary ---
    # --- Dashboard summary ---
    if _df is not None and not _df.empty:
        st.subheader("📊 Résumé du Match")
        
        # ---- CACHE DU DASHBOARD (Optimisation Majeure) ----
        # On stocke tout le résumé lourd en session pour ne pas le recalculer au moindre clic sur la carte.
        if "ui_dash_data" not in st.session_state or st.session_state.get("ui_dash_last_len") != len(_df):
            with st.spinner("Analyse statistique du match..."):
                name_col = "playerName" if "playerName" in _df.columns else "name"
                
                # Métriques rapides
                st_types = _df["type"].astype(str)
                total_events = len(_df)
                total_shots = st_types.str.contains("Shot|Goal", case=False, na=False).sum()
                
                top_p_idx = _df[st_types == "Pass"][name_col].value_counts().head(1)
                top_passer_name = top_p_idx.index[0] if not top_p_idx.empty else "N/A"
                top_passer_val = top_p_idx.values[0] if not top_p_idx.empty else 0
                
                total_xt = pd.to_numeric(_df["xT"], errors="coerce").sum() if "xT" in _df.columns else 0
                
                # Tableaux lourds
                st.session_state.ui_dash_data = {
                    "total_events": total_events,
                    "total_shots": total_shots,
                    "top_passer": (top_passer_name, top_passer_val),
                    "total_xt": total_xt,
                    "pass_conn": compute_pass_connections(_df, name_col),
                    "duel_conn": compute_duel_connections(_df, name_col),
                    "leaderboard": compute_player_leaderboard(_df, name_col),
                    "match_name": _df.iloc[0].get("matchName", "Match") if "matchName" in _df.columns else "Match",
                    "score_val": _df.iloc[0].get("score", "") if "score" in _df.columns else ""
                }
                st.session_state.ui_dash_last_len = len(_df)

        d = st.session_state.ui_dash_data
        st.info(f"🏟️ **{d['match_name']}** | Score Opta: **{d['score_val']}**")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Événements", f"{d['total_events']:,}")
        m2.metric("Meilleur Passeur", d['top_passer'][0], f"{d['top_passer'][1]} passes")
        m3.metric("Total Tirs", d['total_shots'])
        m4.metric("xT Total", f"{d['total_xt']:.2f}")
        
        # Top xT action (seul calcul restant en live car très léger)
        m5.metric("Analyse", "Statistiques", "Détaillées")

        with st.expander("🔗 Connexions & Duels les plus fréquents"):
            c_conn1, c_conn2 = st.columns(2)
            with c_conn1:
                st.markdown("**⚽ Toutes les Connexions (Passes réussies)**")
                if d['pass_conn'] is not None:
                    st.dataframe(d['pass_conn'], hide_index=True, use_container_width=True)
                else:
                    st.write("Aucune donnée de connexion.")
            with c_conn2:
                st.markdown("**⚔️ Tous les Duels (Joueur vs Adversaire)**")
                if d['duel_conn'] is not None:
                    st.dataframe(d['duel_conn'], hide_index=True, use_container_width=True)
                else:
                    st.write("Aucun adversaire direct.")

        with st.expander("🏆 Classement des Joueurs (Top Performances)", expanded=True):
            if d['leaderboard'] is not None:
                st.dataframe(d['leaderboard'], hide_index=True, use_container_width=True)
            else:
                st.write("Données insuffisantes.")

    # --- Preview display ---
    if st.session_state.df_preview is None:
        st.info("💡 Sélectionnez des filtres dans l'onglet précédent puis revenez ici pour voir l'aperçu.")
        return

    df_preview = st.session_state.df_preview.copy()

    # Map zone filter logic
    if "ui_map_zone_filters" not in st.session_state:
        st.session_state.ui_map_zone_filters = []
    if "clip_basket" not in st.session_state:
        st.session_state.clip_basket = []

    if st.session_state.get("ui_map_zone_filters"):
        filters = st.session_state.ui_map_zone_filters
        for zf in filters:
            axis = zf["axis"]
            if axis == "both":
                df_preview = df_preview[
                    (df_preview["x"] >= zf["x_min"]) & (df_preview["x"] < zf["x_max"])
                    & (df_preview["y"] >= zf["y_min"]) & (df_preview["y"] < zf["y_max"])
                ]
            else:
                df_preview = df_preview[(df_preview[axis] >= zf["min"]) & (df_preview[axis] < zf["max"])]

        sc1, sc2 = st.columns([3, 1])
        active_str = " | ".join([
            f"{f['axis'].upper()} [{f['min'] if 'min' in f else f['x_min']}-{f['max'] if 'max' in f else f['x_max']}]"
            for f in filters
        ])
        sc1.info(f"📌 Filtres actifs: {active_str}")
        if sc2.button("❌ Effacer tout", use_container_width=True):
            st.session_state.ui_map_zone_filters = []
            st.rerun()

    st.markdown("### 🔍 Aperçu & Visualisations")
    if df_preview.empty:
        st.warning("⚠️ Aucun événement ne correspond à cette combinaison de filtres.")
        return

    p_c1, p_c2 = st.columns(2)
    p_c1.metric("Clips à générer", len(df_preview))

    st.markdown("##### 📍 Cartes de visualisation")

    oc1, oc2, oc3, oc4 = st.columns(4)
    with oc1:
        default_interactive = len(df_preview) <= 1000
        use_interactive = st.toggle("✨ Interactif", value=default_interactive, help="Mode Click-to-Watch (Désactivé par défaut si > 1000 événements)")
        if len(df_preview) > 1000 and use_interactive:
            st.warning("⚠️ Affichage lourd : > 1000 actions, cela peut ralentir le navigateur.")
    with oc2:
        show_pitch_grid = st.toggle("🏁 Zones", value=True, help="Quadrillage Tactique")
    with oc3:
        color_by_outcome = st.toggle("🔴 Réussite", value=False)
    with oc4:
        drag_mode = st.toggle("🖱️ Lasso Select", value=True)

    if use_interactive:
        i_col1, i_col2 = st.columns([2.5, 1.5])
        with i_col1:
            fig = plot_interactive_pitch(
                df_preview,
                show_grid=show_pitch_grid,
                color_by_outcome=color_by_outcome,
                show_percentages=True,
                dragmode="select" if drag_mode else "pan",
            )
            event_data = st.plotly_chart(fig, use_container_width=True, on_select="rerun")

            if event_data and "selection" in event_data and event_data["selection"]["points"]:
                sel_pts = event_data["selection"]["points"]

                all_sel_idxs = []
                for p in sel_pts:
                    cdata = p.get("customdata")
                    if cdata is None:
                        continue

                    # Plotly event markers return customdata as a list or single value
                    # With the new tooltips, it's often [index, minute, opponent]
                    if isinstance(cdata, (list, tuple)):
                        # Skip if it's a zone filter (handled later)
                        if isinstance(cdata[0], str) and cdata[0].startswith("zone_filter"):
                            continue
                        try:
                            all_sel_idxs.append(int(cdata[0]))
                        except:
                            pass
                    elif isinstance(cdata, (int, float, str)) and not str(cdata).startswith("zone_filter"):
                        try:
                            all_sel_idxs.append(int(cdata))
                        except:
                            pass
                all_sel_idxs = sorted(list(set(all_sel_idxs)))

                if not all_sel_idxs:
                    new_filter = None
                    for p in sel_pts:
                        cdata = p.get("customdata")
                        if isinstance(cdata, str) and cdata.startswith("zone_filter"):
                            zf_parts = cdata.split("|")
                            if zf_parts[1] == "both":
                                new_filter = {
                                    "axis": "both",
                                    "x_min": float(zf_parts[2]), "x_max": float(zf_parts[3]),
                                    "y_min": float(zf_parts[4]), "y_max": float(zf_parts[5]),
                                }
                            else:
                                new_filter = {"axis": zf_parts[1], "min": float(zf_parts[2]), "max": float(zf_parts[3])}
                            break
                    if new_filter:
                        current_filters = st.session_state.ui_map_zone_filters
                        if new_filter not in current_filters:
                            current_filters.append(new_filter)
                            st.session_state.ui_map_zone_filters = current_filters
                        st.rerun()
                else:
                    if len(all_sel_idxs) > 1:
                        if st.session_state.get("ui_click_event_idxs") != all_sel_idxs:
                            st.session_state.ui_click_event_idxs = all_sel_idxs
                            st.session_state.ui_click_event_idx = None
                            st.session_state.ui_batch_preview_active = False
                            st.rerun()
                    elif len(all_sel_idxs) == 1:
                        if st.session_state.get("ui_click_event_idx") != all_sel_idxs[0]:
                            st.session_state.ui_click_event_idx = all_sel_idxs[0]
                            st.session_state.ui_click_event_idxs = None
                            st.session_state.ui_batch_preview_active = False
                            st.rerun()

        with i_col2:
            st.markdown("##### ⏱️ Réglages Durée (Aperçu)")
            bc1, bc2 = st.columns(2)
            with bc1:
                st.number_input("Buffer Avant (s)", 0, 30, value=st.session_state.ui_preview_before, key="ui_preview_before")
            with bc2:
                st.number_input("Buffer Après (s)", 0, 30, value=st.session_state.ui_preview_after, key="ui_preview_after")
            st.divider()

            # --- MULTI-SELECTION PLAYBACK ---
            if st.session_state.get("ui_click_event_idxs"):
                sel_count = len(st.session_state.ui_click_event_idxs)
                st.info(f"📍 {sel_count} actions sélectionnées.")

                if st.button("🎬 Générer Aperçu en Rafale", use_container_width=True, type="primary"):
                    st.session_state.ui_batch_preview_active = True

                if st.session_state.get("ui_batch_preview_active"):
                    try:
                        current_idxs = [idx for idx in st.session_state.ui_click_event_idxs if idx in df_preview.index]
                        if not current_idxs:
                            st.warning("🔄 Sélection obsolète.")
                            st.session_state.ui_click_event_idxs = None
                            st.rerun()

                        event_rows = df_preview.loc[current_idxs].sort_values(["minute", "second"]).copy()
                        half1_ts = st.session_state.get("ui_half1", "0:00")
                        half2_ts = st.session_state.get("ui_half2", "0:00")
                        p_start = {1: to_seconds(half1_ts or "0:00"), 2: to_seconds(half2_ts or "0:00")}
                        p_offset = {1: (0, 0), 2: (45, 0)}

                        preview_config = {
                            "before_buffer": st.session_state.ui_preview_before,
                            "after_buffer": st.session_state.ui_preview_after,
                            "min_clip_gap": 0.5,
                            "video_file": st.session_state.video_path,
                            "video2_file": st.session_state.video2_path,
                            "split_video": st.session_state.get("ui_split_video", False),
                        }

                        batch_specs = get_merged_specs_from_df(event_rows, preview_config, p_start, p_offset)

                        if batch_specs:
                            if not os.path.exists("temp_previews"):
                                os.makedirs("temp_previews", exist_ok=True)

                            batch_id = hash(tuple(st.session_state.ui_click_event_idxs) + (st.session_state.ui_preview_before, st.session_state.ui_preview_after))
                            batch_file = f"temp_previews/batch_{abs(batch_id)}.mp4"

                            if not os.path.exists(batch_file):
                                with st.spinner(f"⚡ Extraction et Assemblage de {len(batch_specs)} clips..."):
                                    parts = []
                                    for i, spec in enumerate(batch_specs):
                                        part_f = f"temp_previews/part_{abs(batch_id)}_{i}.ts"
                                        subprocess.run(
                                            [get_ffmpeg_binary(), "-y", "-ss", str(max(0, spec["start"])),
                                             "-to", str(spec["end"]), "-i", spec["src"],
                                             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                                             "-c:a", "aac", "-b:a", "128k", "-f", "mpegts", part_f],
                                            capture_output=True,
                                        )
                                        if os.path.exists(part_f):
                                            parts.append(part_f)

                                    if parts:
                                        concat_str = "|".join(parts)
                                        subprocess.run(
                                            [get_ffmpeg_binary(), "-y", "-i", f"concat:{concat_str}", "-c", "copy", batch_file],
                                            capture_output=True,
                                        )
                                        for pf in parts:
                                            try:
                                                os.remove(pf)
                                            except:
                                                pass

                            if os.path.exists(batch_file):
                                st.video(batch_file, autoplay=True)
                                b_c1, b_c2 = st.columns(2)
                                with b_c1:
                                    if st.button("🛒 Ajouter Tout au Panier", use_container_width=True):
                                        added = 0
                                        for spec in batch_specs:
                                            if spec not in st.session_state.clip_basket:
                                                st.session_state.clip_basket.append(spec)
                                                added += 1
                                        st.toast(f"✅ {added} clips ajoutés au Panier !", icon="🛒")
                                with b_c2:
                                    if st.button("🗑️ Vider Sélection", use_container_width=True):
                                        st.session_state.ui_click_event_idxs = None
                                        st.rerun()
                        else:
                            st.warning("Aucun clip valide dans la sélection.")
                    except Exception as e:
                        st.error(f"Erreur batch : {e}")

            # --- SINGLE SELECTION PLAYBACK ---
            elif st.session_state.ui_click_event_idx is not None:
                try:
                    _click_idx = st.session_state.ui_click_event_idx
                    if _click_idx in df_preview.index:
                        event_row = df_preview.loc[[_click_idx]].copy()
                    elif st.session_state.opta_df is not None and _click_idx in st.session_state.opta_df.index:
                        event_row = st.session_state.opta_df.loc[[_click_idx]].copy()
                    else:
                        st.warning("🔄 Action introuvable.")
                        st.session_state.ui_click_event_idx = None
                        st.rerun()

                    p_col = st.session_state.get("period_column", "period") if not st.session_state.get("use_fallback") else None
                    f_row = st.session_state.get("fallback_row", 0)
                    try:
                        event_row = assign_periods(event_row, p_col, f_row)
                    except:
                        event_row["resolved_period"] = 1

                    half1_ts = st.session_state.get("ui_half1", "0:00")
                    half2_ts = st.session_state.get("ui_half2", "0:00")
                    p_start = {1: to_seconds(half1_ts or "0:00"), 2: to_seconds(half2_ts or "0:00")}
                    p_offset = {1: (0, 0), 2: (45, 0)}

                    preview_config = {
                        "before_buffer": st.session_state.ui_preview_before,
                        "after_buffer": st.session_state.ui_preview_after,
                        "min_clip_gap": 0.5,
                        "video_file": st.session_state.video_path,
                        "video2_file": st.session_state.video2_path,
                        "split_video": st.session_state.get("ui_split_video", False),
                    }

                    specs = get_merged_specs_from_df(event_row, preview_config, p_start, p_offset)
                    if specs:
                        spec = specs[0]
                        v_src = spec["src"]
                        t_start, t_end = spec["start"], spec["end"]

                        if not os.path.exists("temp_previews"):
                            os.makedirs("temp_previews", exist_ok=True)
                        match_id_clean = "".join(x for x in str(spec.get("match_id", "single")) if x.isalnum())
                        preview_file = f"temp_previews/preview_{match_id_clean}_{st.session_state.ui_click_event_idx}_{st.session_state.ui_preview_before}_{st.session_state.ui_preview_after}.mp4"

                        if not os.path.exists(preview_file):
                            with st.spinner("✂️ Extraction du clip..."):
                                subprocess.run(
                                    [get_ffmpeg_binary(), "-y", "-ss", str(max(0, t_start)),
                                     "-to", str(t_end), "-i", v_src,
                                     "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                                     "-c:a", "aac", "-b:a", "128k", preview_file],
                                    capture_output=True,
                                )

                        if os.path.exists(preview_file):
                            st.video(preview_file, autoplay=True)
                            st.markdown(f"**Action :** {spec['label']}")
                            if st.button("🗑️ Vider Aperçu"):
                                st.session_state.ui_click_event_idx = None
                                st.rerun()
                        else:
                            st.error("Impossible de générer l'aperçu.")
                    else:
                        st.warning("Temps de l'action non défini (H1/H2 Kickoff?)")
                except Exception as e:
                    st.error(f"Erreur rendu : {e}")
            else:
                st.info("💡 Cliquez sur un point ou sélectionnez une zone (Lasso) pour charger les vidéos.")

    st.divider()

    # --- Static map options ---
    with st.expander("⚙️ Options de la Carte Statique (Matplotlib)", key="expander_map_opts"):
        oc1, oc2 = st.columns(2)
        with oc1:
            show_heatmap = st.checkbox("Afficher la Heatmap", value=st.session_state.ui_map_heatmap, key="ui_map_heatmap")
            show_hull = st.checkbox("Afficher l'Enveloppe (Hull)", value=st.session_state.ui_map_hull, key="ui_map_hull")
        with oc2:
            show_center = st.checkbox("Afficher le Centre de Gravité", value=st.session_state.ui_map_center, key="ui_map_center")
            show_names = st.checkbox("Afficher les Noms (Max 50)", value=st.session_state.ui_map_names, key="ui_map_names")

    m_col1, m_col2, m_col3 = st.columns(3)
    with m_col1:
        if st.button("🗺️ Carte du Terrain", use_container_width=True):
            try:
                from visualizations import plot_events_on_pitch
                with st.spinner("Génération de la carte terrain..."):
                    fig, err = plot_events_on_pitch(
                        df_preview,
                        show_heatmap=st.session_state.ui_map_heatmap,
                        show_hull=st.session_state.ui_map_hull,
                        show_center=st.session_state.ui_map_center,
                        show_names=st.session_state.ui_map_names,
                    )
                    if err:
                        st.info(err)
                    elif fig:
                        st.pyplot(fig, clear_figure=True)
            except Exception as e:
                st.error(f"Erreur terrain : {e}")
    with m_col2:
        if st.button("🎯 Vue Offensive", use_container_width=True):
            try:
                from visualizations import plot_vertical_shot_map
                with st.spinner("Génération du focus offensif..."):
                    fig, err = plot_vertical_shot_map(df_preview)
                    if err:
                        st.info(err)
                    elif fig:
                        st.pyplot(fig, clear_figure=True)
            except Exception as e:
                st.error(f"Erreur vue offensive : {e}")
    with m_col3:
        has_shots = any(df_preview["type"].astype(str).str.contains("Shot|Goal", case=False, na=False))
        if st.button("🥅 Vue de la Cage", use_container_width=True, disabled=not has_shots):
            try:
                from visualizations import plot_goal_map
                with st.spinner("Génération de la vue cage..."):
                    fig, err = plot_goal_map(df_preview)
                    if err:
                        st.info(err)
                    elif fig:
                        st.pyplot(fig, clear_figure=True)
            except Exception as e:
                st.error(f"Erreur cage : {e}")

    # --- Event detail table ---
    with st.expander("Voir le détail des événements sélectionnés", key="expander_details"):
        st.markdown("#### 📝 Liste des clips à générer")
        cols_to_show = ["minute", "second", "type", "playerName", "teamName", "oppositionTeamName", "outcomeType"]
        actual_cols = [c for c in cols_to_show if c in df_preview.columns]
        preview_display_df = df_preview[actual_cols].copy()

        if "minute" in preview_display_df.columns and "second" in preview_display_df.columns:
            preview_display_df["Temps Match"] = preview_display_df.apply(
                lambda r: f"{int(r['minute'])}:{int(r['second']):02d}", axis=1
            )

        rename_map = {
            "type": "Action", "playerName": "Joueur", "teamName": "Équipe",
            "oppositionTeamName": "Adversaire", "outcomeType": "Résultat",
        }
        preview_display_df = preview_display_df.rename(columns={k: v for k, v in rename_map.items() if k in preview_display_df.columns})
        final_cols = ["Temps Match"] + [v for k, v in rename_map.items() if v in preview_display_df.columns]

        adv_markers = [c for c in df_preview.columns if str(c).startswith("adv_")]
        if adv_markers:
            def get_adv_str(row):
                active = [c.replace("adv_", "").replace("_", " ").title() for c in adv_markers if row[c] == True]
                if pd.notna(row.get("one_two_score")) and row.get("one_two_score", 0) > 0:
                    active.append(f"⭐ Note 1-2: {row['one_two_score']}")
                return ", ".join(active) if active else "-"
            preview_display_df["Info"] = df_preview.apply(get_adv_str, axis=1)
            final_cols.append("Info")

        if "next_action_type" in df_preview.columns:
            preview_display_df["Puis..."] = df_preview["next_action_type"].fillna("-")
            ins_pos = final_cols.index("Action") + 1 if "Action" in final_cols else 1
            final_cols.insert(ins_pos, "Puis...")

        st.dataframe(preview_display_df[final_cols], hide_index=True, use_container_width=True)
        st.divider()

        d_c1, d_c2, d_c3, d_c4, d_c5, d_c6, d_c7 = st.columns(7)
        with d_c1:
            if "type" in df_preview.columns:
                st.caption("Actions restantes")
                st.dataframe(df_preview["type"].value_counts().reset_index().rename(columns={"type": "Action", "count": "Total"}), hide_index=True, use_container_width=True)
        with d_c2:
            t_col_prev = "teamName" if "teamName" in df_preview.columns else "team"
            if t_col_prev in df_preview.columns:
                st.caption("📈 Équipes")
                st.dataframe(df_preview[t_col_prev].value_counts().reset_index().rename(columns={t_col_prev: "Équipe", "count": "Total"}), hide_index=True, use_container_width=True)
        with d_c3:
            if "oppositionTeamName" in df_preview.columns:
                st.caption("🛡️ Équipes Adv.")
                st.dataframe(df_preview["oppositionTeamName"].value_counts().reset_index().rename(columns={"oppositionTeamName": "Adverse", "count": "Total"}), hide_index=True, use_container_width=True)
        with d_c4:
            name_col_prev = "playerName" if "playerName" in df_preview.columns else "name"
            if name_col_prev in df_preview.columns:
                st.caption("Joueurs impliqués")
                st.dataframe(df_preview[name_col_prev].fillna("Inconnu").value_counts().reset_index().rename(columns={name_col_prev: "Joueur", "count": "Total"}).head(10), hide_index=True, use_container_width=True)
        with d_c5:
            if "receiver" in df_preview.columns:
                st.caption("Receveurs")
                st.dataframe(df_preview["receiver"].dropna().value_counts().reset_index().rename(columns={"receiver": "Receveur", "count": "Total"}).head(10), hide_index=True, use_container_width=True)
        with d_c6:
            if "oppositionPlayerName" in df_preview.columns:
                st.caption("Adversaires")
                st.dataframe(df_preview["oppositionPlayerName"].dropna().value_counts().reset_index().rename(columns={"oppositionPlayerName": "Adversaire", "count": "Total"}).head(10), hide_index=True, use_container_width=True)
        with d_c7:
            adv_cols_prev = [c for c in df_preview.columns if str(c).startswith("adv_")]
            if adv_cols_prev:
                st.caption("Filtres Avancés")
                adv_counts_list = [{"Filtre": c.replace("adv_", "").replace("_", " ").title(), "Total": (df_preview[c] == True).sum()} for c in adv_cols_prev]
                adv_counts_list = sorted([item for item in adv_counts_list if item["Total"] > 0], key=lambda x: x["Total"], reverse=True)
                if adv_counts_list:
                    st.dataframe(pd.DataFrame(adv_counts_list), hide_index=True, use_container_width=True)
                else:
                    st.write("Aucun")

        # Zone distribution
        st.write("---")
        z_c1, z_c2 = st.columns(2)
        with z_c1:
            if "x" in df_preview.columns and "y" in df_preview.columns:
                st.caption("Zones de départ")
                x_data = df_preview["x"].astype(float)
                y_data = df_preview["y"].astype(float)
                zone_counts_list = []
                for zname, z in FLAT_ZONES.items():
                    z_mask = (x_data >= z["x"][0]) & (x_data <= z["x"][1]) & (y_data >= z["y"][0]) & (y_data <= z["y"][1])
                    cnt = z_mask.sum()
                    if cnt > 0:
                        zone_counts_list.append({"Zone": zname, "Total": cnt})
                zone_counts_list.sort(key=lambda x: x["Total"], reverse=True)
                if zone_counts_list:
                    st.dataframe(pd.DataFrame(zone_counts_list), hide_index=True, use_container_width=True)
                else:
                    st.write("Aucune")
        with z_c2:
            if "endX" in df_preview.columns and "endY" in df_preview.columns:
                st.caption("Zones d'arrivée")
                ex_data = df_preview["endX"].astype(float)
                ey_data = df_preview["endY"].astype(float)
                valid_end = ex_data.notna() & ey_data.notna()
                if valid_end.any():
                    ex_data = ex_data[valid_end]
                    ey_data = ey_data[valid_end]
                    end_zone_counts_list = []
                    for zname, z in FLAT_ZONES.items():
                        z_mask = (ex_data >= z["x"][0]) & (ex_data <= z["x"][1]) & (ey_data >= z["y"][0]) & (ey_data <= z["y"][1])
                        cnt = z_mask.sum()
                        if cnt > 0:
                            end_zone_counts_list.append({"Zone": zname, "Total": cnt})
                    end_zone_counts_list.sort(key=lambda x: x["Total"], reverse=True)
                    if end_zone_counts_list:
                        st.dataframe(pd.DataFrame(end_zone_counts_list), hide_index=True, use_container_width=True)
                    else:
                        st.write("Aucune")
                else:
                    st.write("Aucune")

        # One-two distributions
        st.write("---")
        s_c1, s_c2, s_c3 = st.columns(3)
        with s_c1:
            if "shot_goal_zone" in df_preview.columns:
                st.caption("🎯 Zones de Cage (Tirs)")
                st.dataframe(df_preview["shot_goal_zone"].dropna().value_counts().reset_index().rename(columns={"shot_goal_zone": "Zone", "count": "Total"}), hide_index=True, use_container_width=True)
        with s_c2:
            if "one_two_initiator" in df_preview.columns:
                st.caption("🤝 Initiateurs Une-Deux")
                st.dataframe(df_preview["one_two_initiator"].dropna().value_counts().reset_index().rename(columns={"one_two_initiator": "Joueur", "count": "Total"}), hide_index=True, use_container_width=True)
        with s_c3:
            if "one_two_returner" in df_preview.columns:
                st.caption("🔄 Remiseurs Une-Deux")
                st.dataframe(df_preview["one_two_returner"].dropna().value_counts().reset_index().rename(columns={"one_two_returner": "Joueur", "count": "Total"}), hide_index=True, use_container_width=True)
