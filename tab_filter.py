"""
tab_filter.py
=============
Onglet "Filtrage Actions" de ClipMaker SUAOL.
Contient tous les expandeurs de filtres (types, joueurs, équipes,
positions, zones spatiales, filtres avancés Opta, one-two, gaps, etc.)
ainsi que la logique de profils (sauvegarde / chargement).
"""

import json
import os

import pandas as pd
import streamlit as st

from dashboard_analytics import extract_ui_filters_options
from ui_theme import step_header, ACCENT
from ui_session_state import build_global_filter_config


# =============================================================================
# HELPERS
# =============================================================================

def _normalize_adv_groups(raw):
    """Normalise les groupes avancés (supporte l'ancien format liste)."""
    result = []
    if isinstance(raw, list):
        for g in raw:
            if isinstance(g, dict):
                result.append(g)
            elif isinstance(g, list):
                result.append({"filters": g, "and": False, "start": [], "end": []})
    if not result:
        result = [{"filters": [], "and": False, "start": [], "end": []}]
    return result


# =============================================================================
# RENDER
# =============================================================================

def render_tab_filter(_df, available_profiles: list, PROFILE_DIR: str, FLAT_ZONES: dict):
    """
    Affiche l'onglet de filtrage.
    _df : DataFrame courant (optionnel, peut être None si aucune données Opta)
    """
    st.markdown(step_header(3, "Filtrage des Actions"), unsafe_allow_html=True)

    # ---- Profile management ----
    with st.expander("📋 Profils de Filtres", expanded=False, key="expander_profiles"):
        pf_col1, pf_col2, pf_col3 = st.columns([2, 2, 1])
        profile_sel = pf_col1.selectbox(
            "Charger un profil",
            [""] + available_profiles,
            key="ui_sel_profile",
            label_visibility="collapsed",
            placeholder="Choisir un profil...",
        )
        if profile_sel:
            if pf_col2.button("📂 Appliquer le profil", use_container_width=True):
                path = os.path.join(PROFILE_DIR, profile_sel)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    PROFILE_KEYS = [
                        "ui_types", "ui_exclude_types", "ui_players", "ui_teams", "ui_opposition_teams", "ui_opponents",
                        "ui_outcomes", "ui_receivers", "ui_positions", "ui_exclude_positions", "ui_start", "ui_end",
                        "ui_adv_groups", "ui_adv_group_count", "ui_exclude_adv", "ui_prog_only", "ui_xt_min", "ui_top_n",
                        "ui_min_length", "ui_seq_pass_min", "ui_seq_pass_max", "ui_prog_pass", "ui_prog_carry",
                        "ui_carry_speed", "ui_shot_goal_zones", "ui_shot_dist_min", "ui_shot_dist_max",
                        "ui_one_two_initiators", "ui_one_two_returners", "ui_ot_init_prog", "ui_ot_init_xt",
                        "ui_ot_ret_prog", "ui_ot_ret_xt", "ui_ot_min_score", "ui_replay_gap_on",
                        "ui_replay_gap_threshold", "ui_spatial_and_logic", "ui_spatial_and_cross",
                        "ui_seq_score_min", "ui_seq_conceded_score_min", "ui_action_danger_score_min",
                        "ui_next_actions",
                    ]
                    for k in PROFILE_KEYS:
                        if k in data:
                            st.session_state[k] = data[k]
                    st.success(f"✅ Profil '{profile_sel}' appliqué.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur : {e}")

            if pf_col3.button("🗑️ Supprimer", use_container_width=True):
                path = os.path.join(PROFILE_DIR, profile_sel)
                if os.path.exists(path):
                    os.remove(path)
                    st.toast(f"✅ Profil '{profile_sel}' supprimé.", icon="🗑️")
                    st.rerun()

        new_profile_name = pf_col2.text_input("Nom du profil", placeholder="Ex: Passes clés...", label_visibility="collapsed", key="ui_new_profile_name")
        if pf_col1.button("💾 Sauvegarder les Filtres", use_container_width=True):
            n = st.session_state.get("ui_new_profile_name", "").strip()
            if n:
                if not n.endswith(".json"):
                    n += ".json"
                path = os.path.join(PROFILE_DIR, n)
                state_snapshot = {k: st.session_state.get(k) for k in [
                    "ui_types", "ui_exclude_types", "ui_players", "ui_teams", "ui_opposition_teams", "ui_opponents",
                    "ui_outcomes", "ui_receivers", "ui_positions", "ui_exclude_positions", "ui_start", "ui_end",
                    "ui_adv_groups", "ui_adv_group_count", "ui_exclude_adv", "ui_prog_only", "ui_xt_min", "ui_top_n",
                    "ui_min_length", "ui_seq_pass_min", "ui_seq_pass_max", "ui_prog_pass", "ui_prog_carry",
                    "ui_carry_speed", "ui_shot_goal_zones", "ui_shot_dist_min", "ui_shot_dist_max",
                    "ui_one_two_initiators", "ui_one_two_returners", "ui_ot_init_prog", "ui_ot_init_xt",
                    "ui_ot_ret_prog", "ui_ot_ret_xt", "ui_ot_min_score", "ui_replay_gap_on",
                    "ui_replay_gap_threshold", "ui_spatial_and_logic", "ui_spatial_and_cross",
                    "ui_seq_score_min", "ui_seq_conceded_score_min", "ui_action_danger_score_min",
                    "ui_next_actions",
                ]}
                os.makedirs(PROFILE_DIR, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(state_snapshot, f, indent=4)
                st.toast(f"✅ Profil '{n}' sauvegardé.", icon="💾")
            else:
                st.warning("Veuillez entrer un nom de profil.")

    # ---- Filters state extraction from current df ----
    if _df is None or _df.empty:
        st.info("💡 Chargez des données Opta dans l'onglet 'Config Match' pour activer les filtres.")
        return

    # Detect name column
    name_col = "playerName" if "playerName" in _df.columns else "name"

    # ---- CACHE DES OPTIONS DE FILTRES (Optimisation Majeure) ----
    # On ne recalcule les options et les compteurs (Passes, Joueurs, etc.) 
    # que si la taille du DataFrame source a changé (nouveau match ou chargement).
    if "ui_filter_opts" not in st.session_state or st.session_state.get("ui_filter_last_len") != len(_df):
        with st.spinner("Analyse des options de filtrage..."):
            st.session_state.ui_filter_opts = extract_ui_filters_options(_df, name_col, FLAT_ZONES)
            st.session_state.ui_filter_last_len = len(_df)
    
    filter_opts = st.session_state.ui_filter_opts

    # Map actual returned keys to local variables
    types            = filter_opts.get("action_types", [])
    players          = filter_opts.get("player_names", [])
    teams            = filter_opts.get("team_names", [])
    opponents        = filter_opts.get("opponent_names", [])
    opposition_teams = filter_opts.get("opposition_team_names", [])
    outcomes         = filter_opts.get("outcome_types", [])
    receivers        = filter_opts.get("receiver_names", [])
    positions        = filter_opts.get("positions", [])
    adv_cols         = filter_opts.get("adv_cols", [])
    has_coords       = filter_opts.get("has_coords", False)
    has_xt           = filter_opts.get("has_xt", False)
    has_prog         = filter_opts.get("has_prog", False)
    shot_goal_zones  = filter_opts.get("shot_goal_zones", [])
    one_two_initiators = filter_opts.get("one_two_initiators", [])
    one_two_returners  = filter_opts.get("one_two_returners", [])

    # next_action_types: derive from df if column exists
    next_action_types = sorted(_df["next_action_type"].dropna().unique().tolist()) if "next_action_type" in _df.columns else []

    # Pre-computed counts (already in filter_opts)
    type_counts        = filter_opts.get("action_counts", {})
    player_counts      = filter_opts.get("player_counts", {})
    team_counts        = filter_opts.get("team_counts", {})
    receiver_counts    = filter_opts.get("receiver_counts", {})
    opp_counts         = filter_opts.get("opponent_counts", {})
    opp_team_counts    = filter_opts.get("opposition_team_counts", {})
    position_counts    = filter_opts.get("position_counts", {})
    adv_counts_dict    = filter_opts.get("adv_counts", {})
    start_zone_counts  = filter_opts.get("start_zone_counts", {})
    end_zone_counts    = filter_opts.get("end_zone_counts", {})
    shot_goal_zone_counts      = filter_opts.get("shot_goal_zone_counts", {})
    one_two_initiator_counts   = filter_opts.get("one_two_initiator_counts", {})
    one_two_returner_counts    = filter_opts.get("one_two_returner_counts", {})

    # All counts already available from filter_opts above — nothing to recalculate.

    # =========================================================================
    # FILTER EXPANDERS
    # =========================================================================

    # --- Basic filters ---
    with st.expander("⚡ Filtres Primaires (Types & Entités)", expanded=True, key="expander_filt_primary"):
        c1, c2 = st.columns(2)
        with c1:
            st.multiselect(
                "Types d'Actions",
                options=types,
                format_func=lambda x: f"{x} ({type_counts.get(x, 0)})",
                placeholder="Tous les types inclus si vide",
                key="ui_types",
            )
            st.multiselect(
                "❌ Exclure Types",
                options=types,
                format_func=lambda x: f"{x} ({type_counts.get(x, 0)})",
                placeholder="Aucune exclusion",
                key="ui_exclude_types",
            )
        with c2:
            st.multiselect(
                "Résultats",
                options=outcomes,
                format_func=lambda x: f"{x} ({_df.get('outcomeType', pd.Series()).value_counts().get(x, 0)})" if "outcomeType" in _df.columns else x,
                placeholder="Tous résultats inclus si vide",
                key="ui_outcomes",
            )
            nxt_opts = [t for t in next_action_types if t]
            st.multiselect(
                "Action Suivante",
                options=nxt_opts,
                placeholder="Filtrer par action suivante",
                key="ui_next_actions",
            )

        p1, p2 = st.columns(2)
        with p1:
            st.multiselect(
                "Joueurs",
                options=players,
                format_func=lambda x: f"{x} ({player_counts.get(x, 0)})",
                placeholder="Tous les joueurs inclus si vide",
                key="ui_players",
            )
        with p2:
            st.multiselect(
                "Receveurs",
                options=receivers,
                format_func=lambda x: f"{x} ({receiver_counts.get(x, 0)})",
                placeholder="Tous les receveurs inclus si vide",
                key="ui_receivers",
            )

        t1, t2 = st.columns(2)
        with t1:
            st.multiselect(
                "Équipes",
                options=teams,
                format_func=lambda x: f"{x} ({team_counts.get(x, 0)})",
                placeholder="Toutes les équipes incluses si vide",
                key="ui_teams",
            )
        with t2:
            st.multiselect(
                "Équipes Adverses",
                options=opposition_teams,
                format_func=lambda x: f"{x} ({opp_team_counts.get(x, 0)})",
                placeholder="Toutes adversaires incluses si vide",
                key="ui_opposition_teams",
            )

        o1, o2 = st.columns(2)
        with o1:
            st.multiselect(
                "⚔️ Adversaires Directs",
                options=opponents,
                format_func=lambda x: f"{x} ({opp_counts.get(x, 0)})",
                placeholder="Filtrer par adversaire direct",
                key="ui_opponents",
            )
        with o2:
            pass

        pc1, pc2 = st.columns(2)
        with pc1:
            st.selectbox(
                "📊 Filtrer par Mi-Temps",
                options=["Both halves", "1st half only", "2nd half only"],
                key="ui_half_filter",
            )
        with pc2:
            st.multiselect(
                "⚙️ Positions",
                options=positions,
                format_func=lambda x: f"{x} ({position_counts.get(x, 0)})",
                placeholder="All positions included if left blank",
                disabled=not positions,
                key="ui_positions",
            )
            st.multiselect(
                "❌ Exclure Positions",
                options=positions,
                format_func=lambda x: f"{x} ({position_counts.get(x, 0)})",
                placeholder="Aucune exclusion",
                disabled=not positions,
                key="ui_exclude_positions",
            )

    # --- Spatial filters ---
    with st.expander("🗺️ Filtres Spatiaux (Zones du terrain)", key="expander_filt_spatial"):
        zc1, zc2 = st.columns(2)
        with zc1:
            filter_start_zones = st.multiselect(
                "Zone de départ",
                options=list(FLAT_ZONES.keys()),
                format_func=lambda x: f"{x} ({start_zone_counts.get(x, 0)})" if has_coords else x,
                placeholder="Toutes zones",
                disabled=not has_coords,
                key="ui_start",
            )
        with zc2:
            filter_end_zones = st.multiselect(
                "Zone d'arrivée (Passes/Tirs)",
                options=list(FLAT_ZONES.keys()),
                format_func=lambda x: f"{x} ({end_zone_counts.get(x, 0)})" if has_coords else x,
                placeholder="Toutes zones",
                disabled=not has_coords,
                key="ui_end",
            )
        st.caption("Filtrez les actions par leur zone de début et/ou de fin sur le terrain.")

        sc1, sc2 = st.columns(2)
        with sc1:
            st.checkbox("🎯 Intersection (Zone 1 ET Zone 2)", key="ui_spatial_and_logic")
        with sc2:
            st.checkbox("↔️ Traversée (Départ ET Arrivée)", key="ui_spatial_and_cross")

    # --- Advanced filters ---
    with st.expander("📊 Filtres Avancés & Modèles (xT, Opta)", key="expander_filt_advanced"):
        st.markdown("##### 🔍 Opta Advanced Filters (Multi-Sélecteurs)")
        st.caption("Ajoutez des sélecteurs pour définir plusieurs contextes. Les sélecteurs s'additionnent entre eux (**OU**).")

        group_count = st.session_state.get("ui_adv_group_count", 1)
        raw_groups = st.session_state.get("ui_adv_groups", [{"filters": [], "and": False}])
        adv_groups_data = _normalize_adv_groups(raw_groups)

        while len(adv_groups_data) < group_count:
            adv_groups_data.append({"filters": [], "and": False, "start": [], "end": []})
        while len(adv_groups_data) > group_count:
            adv_groups_data.pop()

        def add_adv_group():
            current = []
            for j in range(st.session_state.get("ui_adv_group_count", 1)):
                current.append({
                    "filters": st.session_state.get(f"ui_adv_group_filters_{j}", []),
                    "and": st.session_state.get(f"ui_adv_group_and_{j}", False),
                    "start": st.session_state.get(f"ui_adv_group_start_{j}", []),
                    "end": st.session_state.get(f"ui_adv_group_end_{j}", []),
                })
            current.append({"filters": [], "and": False, "start": [], "end": []})
            st.session_state["ui_adv_groups"] = current
            st.session_state["ui_adv_group_count"] = len(current)

        def remove_adv_group(idx):
            current = []
            for j in range(st.session_state.get("ui_adv_group_count", 1)):
                if j == idx:
                    continue
                current.append({
                    "filters": st.session_state.get(f"ui_adv_group_filters_{j}", []),
                    "and": st.session_state.get(f"ui_adv_group_and_{j}", False),
                    "start": st.session_state.get(f"ui_adv_group_start_{j}", []),
                    "end": st.session_state.get(f"ui_adv_group_end_{j}", []),
                })
            st.session_state["ui_adv_groups"] = current
            st.session_state["ui_adv_group_count"] = len(current)
            st.rerun()

        collected_groups = []
        for i in range(group_count):
            grp_col_key = f"ui_adv_group_filters_{i}"
            grp_and_key = f"ui_adv_group_and_{i}"
            grp_start_key = f"ui_adv_group_start_{i}"
            grp_end_key = f"ui_adv_group_end_{i}"

            # We will pass default values directly to the widgets to ensure Streamlit reliably reconstructs them.
            cur_filters = [v for v in adv_groups_data[i].get("filters", []) if v in adv_cols] if i < len(adv_groups_data) else []
            cur_and = adv_groups_data[i].get("and", False) if i < len(adv_groups_data) else False
            cur_start = [v for v in adv_groups_data[i].get("start", []) if v in list(FLAT_ZONES.keys())] if i < len(adv_groups_data) else []
            cur_end = [v for v in adv_groups_data[i].get("end", []) if v in list(FLAT_ZONES.keys())] if i < len(adv_groups_data) else []

            label = f"Sélecteur {i+1}" + (" (OU)" if i > 0 else "")
            c_row1, c_row2, c_row3 = st.columns([7, 2, 1])

            with c_row1:
                sel_cols = st.multiselect(
                    label,
                    options=adv_cols,
                    format_func=lambda x: f"{x.replace('adv_', '').replace('_', ' ').title()} ({adv_counts_dict.get(x, 0)})",
                    placeholder="Choix des filtres",
                    disabled=not adv_cols,
                    key=grp_col_key,
                    default=cur_filters,
                )
            with c_row2:
                st.write("")
                st.write("")
                grp_and_val = st.checkbox("Logique ET", key=grp_and_key, value=cur_and)
            with c_row3:
                st.write("")
                st.write("")
                if group_count > 1:
                    if st.button("🗑️", key=f"del_adv_grp_{i}"):
                        remove_adv_group(i)
                else:
                    st.button("🗑️", disabled=True, key=f"del_adv_grp_{i}")

            with st.expander(f"🗺️ Configuration Spatiale - {label}", expanded=False):
                z_c1, z_c2 = st.columns(2)
                with z_c1:
                    sel_start = st.multiselect(
                        "Zone départ", options=list(FLAT_ZONES.keys()),
                        format_func=lambda x: f"{x} ({start_zone_counts.get(x, 0)})" if has_coords else x,
                        key=grp_start_key,
                        placeholder="Tout terrain",
                        default=cur_start,
                    )
                with z_c2:
                    sel_end = st.multiselect(
                        "Zone arrivée", options=list(FLAT_ZONES.keys()),
                        format_func=lambda x: f"{x} ({end_zone_counts.get(x, 0)})" if has_coords else x,
                        key=grp_end_key,
                        placeholder="Tout terrain",
                        default=cur_end,
                    )
                st.caption("Ces zones ne s'appliquent qu'à ce sélecteur spécifique.")

            collected_groups.append({
                "filters": sel_cols,
                "and": grp_and_val,
                "start": sel_start,
                "end": sel_end,
            })

        st.button("➕ AJOUTER UN SÉLECTEUR (Addition)", on_click=add_adv_group, use_container_width=True, disabled=not adv_cols, key="btn_add_adv_group")
        st.session_state["ui_adv_groups"] = collected_groups

        st.divider()

        exclude_adv_filters = st.multiselect(
            "❌ Exclude Opta Advanced Filters",
            options=adv_cols,
            format_func=lambda x: f"{x.replace('adv_', '').replace('_', ' ').title()} ({adv_counts_dict.get(x, 0)})",
            placeholder="Select filters to exclude",
            disabled=not adv_cols,
            key="ui_exclude_adv",
        )

        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            st.checkbox("Progressive actions only", disabled=not has_prog, key="ui_prog_only")
        with fc2:
            st.number_input("Top N actions (xT)", min_value=0, step=1, disabled=not has_xt, key="ui_top_n")
        with fc3:
            st.write("") # Placeholder

        fc4, fc5, fc6 = st.columns(3)
        with fc4:
            st.number_input("Min xT value", min_value=0.0, step=0.001, format="%.3f", disabled=not has_xt, key="ui_xt_min")
        with fc5:
            st.number_input("Min Length (m)", min_value=0.0, step=1.0, format="%.1f", key="ui_min_length")
        with fc6:
            st.number_input("Passe prog. min (m)", min_value=0.0, step=1.0, format="%.1f", disabled=not has_prog, key="ui_prog_pass")

        fc7, fc8, fc9 = st.columns(3)
        with fc7:
            st.number_input("Portée prog. min (m)", min_value=0.0, step=1.0, format="%.1f", disabled=not has_prog, key="ui_prog_carry")
        with fc8:
            st.number_input("Vitesse Carry min (km/h) >10m", min_value=0.0, step=1.0, format="%.1f", key="ui_carry_speed")
        with fc9:
            st.number_input("Danger Séquence (Score Min)", min_value=0.0, step=1.0, format="%.1f", key="ui_seq_score_min")

        fc10, fc11, fc12 = st.columns(3)
        with fc10:
            st.number_input("Danger Subi (Score Min)", min_value=0.0, step=1.0, format="%.1f", key="ui_seq_conceded_score_min")

        c_ads1, c_ads2, c_ads3 = st.columns(3)
        with c_ads1:
            st.number_input(
                "🎯 Note Action (Score Min, 0–10)",
                min_value=0.0, max_value=10.0, step=0.5, format="%.1f",
                key="ui_action_danger_score_min",
                help="Filtre sur la dangerosité individuelle de l'action (indépendant du score séquence).\n"
                     "0 = désactivé | 3+ = actions notables | 6+ = actions décisives | 10 = but",
            )
        with c_ads2:
            st.caption("💡 Exemples de notes")
            st.caption("🟢 Passe prog. mi-terrain : ~1-2")
            st.caption("🟡 Dribble surface : ~3-5")
        with c_ads3:
            st.caption(" ")
            st.caption("🟠 Passe décisive / Key Pass : ~4-7")
            st.caption("🔴 Tir cadré / Big Chance : ~6-9")

        qc1, qc2 = st.columns(2)
        with qc1:
            seq_pass_min = st.number_input("Min passes (Séquence)", min_value=0, step=1, key="ui_seq_pass_min")
        with qc2:
            seq_pass_max = st.number_input("Max passes (Séquence)", min_value=0, step=1, key="ui_seq_pass_max")

        st.markdown("---")
        st.markdown("##### 🥅 Filtres de Tirs (Cage & Distance)")
        sc_c1, sc_c2, sc_c3 = st.columns(3)
        with sc_c1:
            filter_shot_zones = st.multiselect("Zones de la cage", options=shot_goal_zones, format_func=lambda x: f"{x} ({shot_goal_zone_counts.get(x, 0)})", placeholder="Toutes zones", key="ui_shot_goal_zones")
        with sc_c2:
            shot_dist_min = st.number_input("Dist. Tir Min (m)", min_value=0.0, step=1.0, key="ui_shot_dist_min")
        with sc_c3:
            shot_dist_max = st.number_input("Dist. Tir Max (m)", min_value=0.0, step=1.0, key="ui_shot_dist_max")

        st.markdown("---")
        st.markdown("##### 🤝 One-Two (Une-Deux)")
        ot_c1, ot_c2 = st.columns(2)
        with ot_c1:
            st.multiselect("Initiateur (Donneur)", options=one_two_initiators, format_func=lambda x: f"{x} ({one_two_initiator_counts.get(x, 0)})", key="ui_one_two_initiators")
            ot_init_prog = st.number_input("Init: Passe prog. min (m)", min_value=0.0, step=1.0, format="%.1f", key="ui_ot_init_prog")
            ot_init_xt = st.number_input("Init: Min xT value", min_value=0.0, step=0.001, format="%.3f", key="ui_ot_init_xt")
        with ot_c2:
            st.multiselect("Remiseur (Appui)", options=one_two_returners, format_func=lambda x: f"{x} ({one_two_returner_counts.get(x, 0)})", key="ui_one_two_returners")
            ot_ret_prog = st.number_input("Ret: Passe prog. min (m)", min_value=0.0, step=1.0, format="%.1f", key="ui_ot_ret_prog")
            ot_ret_xt = st.number_input("Ret: Min xT value", min_value=0.0, step=0.001, format="%.3f", key="ui_ot_ret_xt")
        st.slider("⭐ Note minimale One-Two (0-100)", 0.0, 100.0, 0.0, key="ui_ot_min_score")

    # --- GAP (Ralentis) ---
    with st.expander("🎬 Détection des Ralentis (Gaps)", key="expander_filt_gaps"):
        st.markdown(
            """
            L'idée est de détecter les moments où "rien ne se passe" dans les données Opta (temps mort).
            Souvent, la réalisation TV en profite pour diffuser un ralenti d'une action précédente.
            """
        )
        g_c1, g_c2 = st.columns([1, 2])
        with g_c1:
            replay_gap_on = st.checkbox("Filtrer par Gaps (Ralentis)", key="ui_replay_gap_on")
        with g_c2:
            replay_gap_threshold = st.slider("Seuil de temps mort (secondes)", 5, 30, 8, key="ui_replay_gap_threshold")
        st.caption("ℹ️ Ce filtre ne gardera QUE les actions qui suivent immédiatement un temps mort.")
