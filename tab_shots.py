"""
tab_shots.py
============
Onglet "Shot Map" de ClipMaker SUAOL.
Visualisation et filtrage avancé des tirs (zone terrain, résultat,
attributs tactiques, cage, distance) avec preview vidéo intégrée.
"""

import os
import subprocess

import pandas as pd
import streamlit as st

from clip_processing import to_seconds, get_merged_specs_from_df, get_ffmpeg_binary
from smp_component import shot_map
from ui_theme import step_header, ACCENT


def render_tab_shots(FLAT_ZONES: dict):
    """Affiche l'onglet Shot Map."""
    st.markdown(step_header(6, "Exploration Analytique des Tirs (Shot Map)"), unsafe_allow_html=True)

    if st.session_state.opta_df is None or st.session_state.opta_df.empty:
        st.info("💡 Chargez des données Opta pour activer la Shot Map.")
        return

    df_shots = st.session_state.opta_df[
        st.session_state.opta_df["type"].astype(str).str.contains("Shot|Goal", case=False, na=False)
    ].copy()

    if df_shots.empty:
        st.warning("⚠️ Aucun tir détecté dans ce match.")
        return

    # --- Teams ---
    all_teams = df_shots["teamName"].unique().tolist()
    h_team = all_teams[0] if len(all_teams) > 0 else "Home"
    a_team = all_teams[1] if len(all_teams) > 1 else "Away"

    # --- Filter UI ---
    st.markdown("##### 🛠️ FILTRES DE PRÉCISION")
    c1, c2, c3, c4 = st.columns(4)

    sel_zone = c1.selectbox("Zone Terrain", ["Toutes"] + list(FLAT_ZONES.keys()), key="ui_shot_zone")
    f_team = c2.multiselect("Équipes", options=all_teams, default=all_teams, key="smp_team_ui")
    f_player = c3.multiselect("Joueurs", sorted(df_shots["playerName"].dropna().unique().tolist()), key="smp_player_ui")

    outcomes = ["But ✅", "Arrêt 👐", "Contré 🛡️", "Poteau 🥅", "Hors-cadre ❌"]

    st.markdown("<small style='color:gray'>SÉLECTION RAPIDE :</small>", unsafe_allow_html=True)
    qs_c1, qs_c2, qs_c3 = st.columns([1, 1, 1])
    if qs_c1.button("⚽ Buts Seuls", use_container_width=True):
        st.session_state.smp_outcome_ui = ["But ✅"]
        st.rerun()
    if qs_c2.button("🎯 Tous les Cadrés", use_container_width=True):
        st.session_state.smp_outcome_ui = ["But ✅", "Arrêt 👐"]
        st.rerun()
    if qs_c3.button("🔄 Tout Réinitialiser", use_container_width=True):
        st.session_state.smp_outcome_ui = outcomes
        st.rerun()

    f_outcome = c4.multiselect("Résultats", outcomes, default=outcomes, key="smp_outcome_ui")

    # --- Tactical Tags ---
    st.markdown("##### 🧪 ATTRIBUTS TACTIQUES")
    body_tags = {"Tête": "adv_SHOT_HEAD", "Pied Gauche": "adv_SHOT_LEFT_FOOTED", "Pied Droit": "adv_SHOT_RIGHT_FOOTED"}
    context_tags = {
        "Jeu Placé": "adv_SHOT_REGULAR_PLAY", "Contre-attaque": "adv_SHOT_FAST_BREAK",
        "Face-à-face": "adv_SHOT_ONE_ON_ONE", "Action Individuelle": "adv_SHOT_INDIVIDUAL_PLAY",
        "Après Dribble": "adv_SHOT_FOLLOWS_DRIBBLE", "Sur Transition": "adv_OFF_TRANSITION_10S",
        "Hors Surface": "adv_SHOT_OUT_OF_BOX_CENTRE", "Suite à Passe": "adv_SHOT_ASSISTED",
    }
    quality_tags = {
        "Grosse Occase": "adv_SHOT_BIG_CHANCE", "Volée": "adv_SHOT_VOLLEY",
        "Sans Contrôle": "adv_SHOT_FIRST_TOUCH", "Déviation": "adv_SHOT_DEFLECTION",
        "Frappe Puissante": "adv_SHOT_STRONG", "Effet Gauche": "adv_SHOT_SWERVE_LEFT",
        "Effet Droit": "adv_SHOT_SWERVE_RIGHT", "Touché Gardien": "adv_SHOT_KEEPER_TOUCHED",
        "Tir Cadré": "adv_SHOT_ON_TARGET",
    }

    gt_c1, gt_c2, gt_c3 = st.columns(3)
    f_body = gt_c1.multiselect("🦶 Partie du Corps", options=list(body_tags.keys()), key="smp_body_ui")
    f_context = gt_c2.multiselect("🏟️ Situation Tactique", options=list(context_tags.keys()), key="smp_context_ui")
    f_quality = gt_c3.multiselect("✨ Type / Qualité", options=list(quality_tags.keys()), key="smp_quality_ui")

    # --- Goal zone & Distance ---
    st.markdown("##### 🥅 Filtres de Tirs (Cage & Distance)")
    sc_c1, sc_c2, sc_c3 = st.columns(3)
    shot_goal_zones_smp = ["Bottom Left", "Bottom Right", "Top Left", "Top Right", "Centre"]
    sel_cage = sc_c1.multiselect("Zones de la cage", options=shot_goal_zones_smp, key="smp_cage_ui")
    smp_dist_min = sc_c2.number_input("Dist. Tir Min (m)", min_value=0.0, step=1.0, key="smp_dist_min_ui")
    smp_dist_max = sc_c3.number_input("Dist. Tir Max (m)", min_value=0.0, step=1.0, key="smp_dist_max_ui")

    # --- Apply filters (Vectorized) ---
    df_disp = df_shots.copy()
    if sel_zone != "Toutes":
        z = FLAT_ZONES[sel_zone]
        df_disp = df_disp[(df_disp["x"] >= z["x"][0]) & (df_disp["x"] <= z["x"][1]) & (df_disp["y"] >= z["y"][0]) & (df_disp["y"] <= z["y"][1])]
    if f_team:
        df_disp = df_disp[df_disp["teamName"].isin(f_team)]
    if f_player:
        df_disp = df_disp[df_disp["playerName"].isin(f_player)]
    
    if f_outcome:
        # Vectorisation du filtrage des résultats
        stypes = df_disp["type"].astype(str).str.lower()
        mask = pd.Series(False, index=df_disp.index)
        if "But ✅" in f_outcome: mask |= stypes.str.contains("goal")
        if "Arrêt 👐" in f_outcome: mask |= stypes.str.contains("saved")
        if "Contré 🛡️" in f_outcome: mask |= stypes.str.contains("blocked")
        if "Poteau 🥅" in f_outcome: mask |= stypes.str.contains("post|woodwork")
        if "Hors-cadre ❌" in f_outcome:
            mask |= ~stypes.str.contains("goal|saved|post|woodwork|blocked")
        df_disp = df_disp[mask]

    if f_body:
        cols = [body_tags[t] for t in f_body if body_tags[t] in df_disp.columns]
        if cols:
            df_disp = df_disp[df_disp[cols].any(axis=1)]
    if f_context:
        cols = [context_tags[t] for t in f_context if context_tags[t] in df_disp.columns]
        if cols:
            df_disp = df_disp[df_disp[cols].any(axis=1)]
    if f_quality:
        cols = [quality_tags[t] for t in f_quality if quality_tags[t] in df_disp.columns]
        if cols:
            df_disp = df_disp[df_disp[cols].any(axis=1)]
    if sel_cage and "shot_goal_zone" in df_disp.columns:
        df_disp = df_disp[df_disp["shot_goal_zone"].isin(sel_cage)]
    if smp_dist_min > 0 and "shot_distance" in df_disp.columns:
        mask = pd.to_numeric(df_disp["shot_distance"], errors="coerce").fillna(0)
        df_disp = df_disp[mask >= smp_dist_min]
    if smp_dist_max > 0 and "shot_distance" in df_disp.columns:
        mask = pd.to_numeric(df_disp["shot_distance"], errors="coerce").fillna(0)
        df_disp = df_disp[mask <= smp_dist_max]

    # --- Stats bar ---
    st.markdown(
        f"""
        <div style='display:flex; gap:20px; background:#1a1a1a; padding:15px; border-radius:5px; margin-bottom:20px; border-left:4px solid {ACCENT}'>
            <div><small style='color:#767575'>TIRS FILTRÉS</small><br><b style='font-size:18px'>{len(df_disp)}</b></div>
            <div><small style='color:#767575'>BUTS</small><br><b style='font-size:18px'>{len(df_disp[df_disp['type'].astype(str).str.contains('Goal', case=False, na=False)])}</b></div>
            <div><small style='color:#767575'>CADRÉS</small><br><b style='font-size:18px'>{len(df_disp[df_disp['outcomeType']=='Successful']) if 'outcomeType' in df_disp.columns else '—'}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Reclassification vectorisée ---
    stypes_all = df_disp["type"].astype(str)
    reclassified = pd.Series("MissedShot", index=df_disp.index)
    reclassified[stypes_all.str.contains("Goal")] = "Goal"
    reclassified[stypes_all.str.contains("Saved")] = "SavedShot"
    reclassified[stypes_all.str.contains("Blocked")] = "BlockedShot"
    reclassified[stypes_all.str.contains("Post")] = "ShotOnPost"
    df_disp["_shot_class"] = reclassified

    # Build shots_json for smp_component
    shots_json = []
    for idx, row in df_disp.iterrows():
        mx = float(row.get("x", 0))
        my = float(row.get("y", 0))
        gy = row.get("value_Goal mouth y coordinate")
        gz = row.get("value_Goal mouth z coordinate")
        shots_json.append({
            "df_idx": int(idx),
            "playerName": str(row.get("playerName", "Inconnu")),
            "team": str(row.get("teamName", "")),
            "vs": str(row.get("oppositionTeamName", "")),
            "type": row["_shot_class"],
            "x": mx, "y": my,
            "goal_mouth_y": float(gy) if pd.notna(gy) else None,
            "goal_mouth_z": float(gz) if pd.notna(gz) else None,
            "minute": int(row.get("minute", 0)),
            "second": int(row.get("second", 0)),
            "period": str(row.get("period", "1H")),
            "is_home": row.get("teamName") == h_team,
        })

    shot_col_map, shot_col_preview = st.columns([2, 1])

    with shot_col_map:
        sel_shot_idx_smp = st.session_state.get("ui_shot_sel_idx")

        if sel_shot_idx_smp is not None and sel_shot_idx_smp in df_disp.index:
            shot_map([next(s for s in shots_json if s["df_idx"] == sel_shot_idx_smp)], h_team, a_team, view="goalframe", key="smp_gf")

        raw_click = shot_map(shots_json, h_team, a_team, view="halfpitch_vert", selected_idx=sel_shot_idx_smp, key="smp_pitch")

        if raw_click:
            clicked_idx = raw_click[0] if isinstance(raw_click, list) else raw_click
            if clicked_idx != st.session_state.get("ui_shot_sel_idx"):
                st.session_state.ui_shot_sel_idx = clicked_idx
                st.session_state.ui_shot_preview_active = False
                st.rerun()

    with shot_col_preview:
        if st.session_state.get("ui_shot_sel_idx") is not None and st.session_state.ui_shot_sel_idx in df_shots.index:
            sel_row = df_shots.loc[st.session_state.ui_shot_sel_idx]
            st.markdown("### 📋 Détails du Tir")
            st.write(f"**Joueur :** {sel_row['playerName']}")
            st.write(f"**Temps :** {int(sel_row['minute'])}:{int(sel_row['second']):02d}")

            # Note: For single display we can use a quick reclassification
            st_type = df_disp.loc[st.session_state.ui_shot_sel_idx, "_shot_class"] if st.session_state.ui_shot_sel_idx in df_disp.index else "MissedShot"
            color = "#00FF00" if st_type == "Goal" else "#00FFFF" if st_type == "BlockedShot" else "#FFFF00" if st_type == "SavedShot" else "#FF0000"
            st.markdown(
                f"<span style='background:{color}; color:black; padding:2px 8px; border-radius:3px; font-weight:bold'>{st_type.upper()}</span>",
                unsafe_allow_html=True,
            )

            adv_tags = [c.replace("adv_", "").replace("_", " ").title() for c in sel_row.index if str(c).startswith("adv_") and sel_row[c] == True]
            if adv_tags:
                st.write("**Caractéristiques :**")
                st.write(", ".join(adv_tags))

            st.divider()

            if st.button("📽️ Charger Vidéo", use_container_width=True):
                st.session_state.ui_shot_preview_active = True

            if st.session_state.get("ui_shot_preview_active"):
                event_row = sel_row
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
                    match_id_clean = "".join(x for x in str(spec.get("match_id", "single")) if x.isalnum())
                    preview_file = f"temp_previews/shot_prev_{match_id_clean}_{st.session_state.ui_shot_sel_idx}_{st.session_state.ui_preview_before}_{st.session_state.ui_preview_after}.mp4"
                    if not os.path.exists(preview_file):
                        subprocess.run(
                            [get_ffmpeg_binary(), "-y", "-ss", str(max(0, spec["start"])),
                             "-to", str(spec["end"]), "-i", spec["src"],
                             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                             "-c:a", "aac", "-b:a", "128k", preview_file],
                            capture_output=True,
                        )
                    if os.path.exists(preview_file):
                        st.video(preview_file, autoplay=True)

            if st.button("❌ Fermer Détails"):
                st.session_state.ui_shot_sel_idx = None
                st.rerun()
        else:
            st.info("💡 Cliquez sur un tir pour voir les détails et la vidéo.")
