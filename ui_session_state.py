"""
ui_session_state.py
===================
Initialisation du session state Streamlit et constructeur centralisé
du dictionnaire de configuration des filtres (build_global_filter_config).
"""

import streamlit as st


# =============================================================================
# SESSION STATE DEFAULTS
# =============================================================================

SESSION_DEFAULTS = [
    ("video_path", ""), ("video2_path", ""), ("csv_path", ""), ("output_dir", ""),
    ("opta_processed", False), ("opta_df", None),
    ("ui_types", []), ("ui_exclude_types", []), ("ui_players", []), ("ui_teams", []), ("ui_opponents", []),
    ("ui_outcomes", []), ("ui_receivers", []), ("ui_positions", []), ("ui_exclude_positions", []),
    ("ui_start", []), ("ui_end", []), ("ui_adv_groups", [[]]), ("ui_adv_group_count", 1), ("ui_exclude_adv", []),
    ("ui_prog_only", False), ("ui_xt_min", 0.0), ("ui_top_n", 0), ("ui_min_length", 0.0),
    ("ui_seq_pass_min", 0), ("ui_seq_pass_max", 0),
    ("ui_prog_pass", 0.0), ("ui_prog_carry", 0.0), ("ui_carry_speed", 0.0),
    ("ui_split_video", False), ("ui_half1", ""), ("ui_half2", ""), ("ui_half3", ""), ("ui_half4", ""),
    ("ui_use_crop", False), ("ui_crop_params", None), ("ui_half_filter", "Both halves"),
    ("ui_aggregate_matches", []), ("is_aggregate_mode", False), ("ui_mixed_assembly", False),
    ("ui_shot_goal_zones", []), ("ui_shot_dist_min", 0.0), ("ui_shot_dist_max", 0.0),
    ("ui_spatial_and_logic", False), ("ui_spatial_and_cross", False), ("ui_one_two_initiators", []), ("ui_one_two_returners", []),
    ("ui_opposition_teams", []), ("ui_replay_gap_on", False), ("ui_replay_gap_threshold", 8),
    ("ui_ot_init_prog", 0.0), ("ui_ot_init_xt", 0.0), ("ui_ot_ret_prog", 0.0), ("ui_ot_ret_xt", 0.0), ("ui_ot_min_score", 0.0),
    ("ui_map_heatmap", True), ("ui_map_hull", True), ("ui_map_center", True), ("ui_map_names", True),
    ("ui_auto_apply_filters", True), ("ui_filters_applied", False), ("df_preview", None),
    ("ui_match_bases", {"Default": "match_configs"}), ("ui_active_base", "Default"),
    ("ui_show_test_h1", False), ("ui_show_test_h2", False),
    ("ui_show_img_h1", False), ("ui_show_img_h2", False),
    ("ui_next_actions", []),
    ("ui_basket", []),
    ("ui_click_event_idx", None),
    ("ui_click_video_path", None),
    ("ui_bu_idx", None),
    ("ui_bu_chains", []),
    ("ui_bu_team", "Toutes"),
    ("ui_bu_contre", False),
    ("ui_bu_min_passes", 0),
    ("ui_bu_min_actions", 1),
    ("ui_bu_min_prog", 0),
    ("ui_bu_starts_own", False),
    ("ui_bu_reaches_opp", False),
    ("ui_bu_shots", False),
    ("ui_bu_fast_break", False),
    ("ui_bu_rendering", False),
    ("ui_bu_batch_mode", "merge"),
    ("ui_bu_trigger_batch", False),
    ("bu_batch_done", False),
    ("ui_seq_score_min", 0.0),
    ("ui_seq_conceded_score_min", 0.0),
    ("ui_action_danger_score_min", 0.0),
    ("ui_bu_exclude_players", []),
    ("ui_preview_before", 4),
    ("ui_preview_after", 6),
    ("ui_batch_preview_active", False),
    ("ui_shot_preview_active", False),
    ("ui_last_filter_hash", None),
    ("ui_bu_page", 0),
    ("ui_active_tab", "⚙️ Config Match"),
]

FILTER_KEYS = [
    "ui_types", "ui_exclude_types", "ui_players", "ui_teams", "ui_opposition_teams", "ui_opponents",
    "ui_outcomes", "ui_receivers", "ui_positions", "ui_exclude_positions", "ui_start", "ui_end",
    "ui_adv_groups", "ui_adv_group_count", "ui_exclude_adv", "ui_prog_only", "ui_xt_min", "ui_top_n",
    "ui_min_length", "ui_seq_pass_min", "ui_seq_pass_max", "ui_prog_pass", "ui_prog_carry",
    "ui_carry_speed", "ui_shot_goal_zones", "ui_shot_dist_min", "ui_shot_dist_max",
    "ui_one_two_initiators", "ui_one_two_returners", "ui_ot_init_prog", "ui_ot_init_xt",
    "ui_ot_ret_prog", "ui_ot_ret_xt", "ui_ot_min_score", "ui_replay_gap_on",
    "ui_replay_gap_threshold", "ui_spatial_and_logic", "ui_spatial_and_cross",
    "ui_next_actions", "ui_half_filter",
] + [f"ui_adv_group_{suffix}_{i}" for i in range(10) for suffix in ["filters", "and", "start", "end"]]


def init_session_state():
    """Initialise toutes les clés du session state avec leurs valeurs par défaut."""
    for key, default in SESSION_DEFAULTS:
        if key not in st.session_state:
            st.session_state[key] = default


# =============================================================================
# CENTRALIZED FILTER CONFIGURATION BUILDER
# =============================================================================

def build_global_filter_config(source_data=None):
    """
    Construit le dictionnaire de configuration de filtrage unique.
    Si source_data est None, lit depuis st.session_state.
    """
    data = source_data if source_data is not None else st.session_state

    adv_groups = data.get("ui_adv_groups", [])
    if source_data is None:
        adv_groups = [
            g
            for g in st.session_state.get("ui_adv_groups", [])
            if (isinstance(g, dict) and g.get("filters")) or (isinstance(g, list) and g)
        ]

    adv_and_logic_val = data.get(
        "ui_adv_and_logic", len([g for g in adv_groups if g]) > 1
    )

    return {
        "filter_types": data.get("ui_types", []),
        "exclude_types": data.get("ui_exclude_types", []),
        "filter_players": data.get("ui_players", []),
        "filter_teams": data.get("ui_teams", []),
        "filter_opposition_teams": data.get("ui_opposition_teams", []),
        "filter_opponents": data.get("ui_opponents", []),
        "filter_outcomes": data.get("ui_outcomes", []),
        "filter_receivers": data.get("ui_receivers", []),
        "filter_positions": data.get("ui_positions", []),
        "exclude_positions": data.get("ui_exclude_positions", []),
        "filter_start_zones": data.get("ui_start", []),
        "filter_end_zones": data.get("ui_end", []),
        "advanced_filters": data.get("ui_adv", []),
        "adv_filter_groups": adv_groups,
        "exclude_adv_filters": data.get("ui_exclude_adv", []),
        "progressive_only": data.get("ui_prog_only", False),
        "prog_pass_min": data.get("ui_prog_pass", 0.0),
        "prog_carry_min": data.get("ui_prog_carry", 0.0),
        "carry_speed_min": data.get("ui_carry_speed", 0.0),
        "xt_min": data.get("ui_xt_min", 0.0),
        "min_length": data.get("ui_min_length", 0.0),
        "top_n": int(data.get("ui_top_n", 0)) if data.get("ui_top_n", 0) > 0 else None,
        "seq_pass_min": data.get("ui_seq_pass_min", 0),
        "seq_pass_max": data.get("ui_seq_pass_max", 0),
        "seq_score_min": data.get("ui_seq_score_min", 0.0),
        "seq_conceded_score_min": data.get("ui_seq_conceded_score_min", 0.0),
        "action_danger_score_min": data.get("ui_action_danger_score_min", 0.0),
        "filter_shot_goal_zones": data.get("ui_shot_goal_zones", []),
        "shot_distance_min": data.get("ui_shot_dist_min", 0.0),
        "shot_distance_max": data.get("ui_shot_dist_max", 0.0),
        "filter_one_two_initiators": data.get("ui_one_two_initiators", []),
        "filter_one_two_returners": data.get("ui_one_two_returners", []),
        "ot_init_prog": data.get("ui_ot_init_prog", 0.0),
        "ot_init_xt": data.get("ui_ot_init_xt", 0.0),
        "ot_ret_prog": data.get("ui_ot_ret_prog", 0.0),
        "ot_ret_xt": data.get("ui_ot_ret_xt", 0.0),
        "ot_min_score": data.get("ui_ot_min_score", 0.0),
        "adv_and_logic": adv_and_logic_val,
        "spatial_and_logic": data.get("ui_spatial_and_logic", False),
        "spatial_and_cross": data.get("ui_spatial_and_cross", False),
        "filter_next_actions": data.get("ui_next_actions", []),
        "half_filter": data.get("ui_half_filter", "Both halves"),
        "replay_gap_threshold": (
            data.get("ui_replay_gap_threshold", 0)
            if data.get("ui_replay_gap_on", False)
            else 0
        ),
    }

def get_filter_hash(config_dict):
    """Génère un hash unique pour une configuration de filtrage donnée."""
    import hashlib
    import json
    # On sérialise en triant les clés pour la consistance
    encoded = json.dumps(config_dict, sort_keys=True, default=str).encode()
    return hashlib.md5(encoded).hexdigest()
