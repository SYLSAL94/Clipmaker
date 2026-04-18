"""
ui_sidebar.py
=============
Rendu de la barre latérale (sidebar) de ClipMaker :
- Logo & en-tête
- Métrique "Actions filtrées"
- Boutons Appliquer / Réinitialiser les filtres
- Panier de clips (clip_basket)
- Panneau Export & Rendu (boutons LANCER / XML)
"""

import os
import time

import streamlit as st
from clip_processing import get_ffmpeg_binary

from ui_theme import logo_header
from ui_helpers import open_file_location


def reset_action_filters():
    keys_to_reset = [
        "ui_types", "ui_exclude_types", "ui_players", "ui_teams", "ui_opposition_teams", "ui_opponents",
        "ui_outcomes", "ui_receivers", "ui_positions", "ui_exclude_positions", "ui_start", "ui_end", "ui_exclude_adv",
        "ui_shot_goal_zones", "ui_shot_dist_min", "ui_shot_dist_max", "ui_one_two_initiators", "ui_one_two_returners",
        "ui_prog_only", "ui_xt_min", "ui_top_n", "ui_min_length", "ui_seq_pass_min", "ui_seq_pass_max",
        "ui_replay_gap_on", "ui_replay_gap_threshold", "ui_prog_pass", "ui_prog_carry", "ui_carry_speed",
        "ui_ot_init_prog", "ui_ot_init_xt", "ui_ot_ret_prog", "ui_ot_ret_xt", "ui_ot_min_score",
        "ui_map_heatmap", "ui_map_hull", "ui_map_center", "ui_map_names", "ui_next_actions",
        "ui_spatial_and_logic", "ui_spatial_and_cross",
    ]
    for k in keys_to_reset:
        if k in [
            "ui_xt_min", "ui_min_length", "ui_prog_pass", "ui_prog_carry", "ui_carry_speed",
            "ui_shot_dist_min", "ui_shot_dist_max",
            "ui_ot_init_prog", "ui_ot_init_xt", "ui_ot_ret_prog", "ui_ot_ret_xt", "ui_ot_min_score",
            "ui_seq_score_min", "ui_seq_conceded_score_min", "ui_action_danger_score_min",
        ]:
            st.session_state[k] = 0.0
        elif k in ["ui_top_n", "ui_seq_pass_min", "ui_seq_pass_max"]:
            st.session_state[k] = 0
        elif k == "ui_replay_gap_threshold":
            st.session_state[k] = 8
        elif k in ["ui_map_heatmap", "ui_map_hull", "ui_map_center", "ui_map_names"]:
            st.session_state[k] = True
        elif k in ["ui_prog_only", "ui_replay_gap_on", "ui_spatial_and_logic", "ui_spatial_and_cross"]:
            st.session_state[k] = False
        else:
            st.session_state[k] = []

    old_count = st.session_state.get("ui_adv_group_count", 1)
    for i in range(old_count):
        key_legacy = f"ui_adv_group_{i}"
        if key_legacy in st.session_state:
            del st.session_state[key_legacy]
        for suffix in ["filters", "and", "start", "end"]:
            key = f"ui_adv_group_{suffix}_{i}"
            if key in st.session_state:
                del st.session_state[key]
    st.session_state["ui_adv_groups"] = [{"filters": [], "and": False, "start": [], "end": []}]
    st.session_state["ui_adv_group_count"] = 1
    st.toast("Filtres réinitialisés !", icon="🔄")


def render_sidebar(match_config_dir: str) -> dict:
    """
    Rendu de la sidebar complète.
    Retourne un dict avec les valeurs configurées par l'utilisateur :
      - export_mode, individual, group_by_player, out_filename
      - sidebar_run_btn, sidebar_xml_btn
    """
    result = {}

    with st.sidebar:
        st.markdown(
            logo_header("CLIPMAKER", "SUAOL Edition", "ClipMaker_logo.png"),
            unsafe_allow_html=True,
        )
        st.divider()

        # Metric showing current filtered result
        p_count = len(st.session_state.df_preview) if st.session_state.df_preview is not None else 0

        if st.session_state.get("is_aggregate_mode"):
            st.metric("Actions filtrées (Multi-Match)", p_count)
        else:
            st.metric("Actions filtrées (Match actuel)", p_count)
            turbo_configs = (
                [f for f in os.listdir(match_config_dir) if f.endswith(".json")]
                if os.path.isdir(match_config_dir)
                else []
            )
            if len(turbo_configs) > 1:
                st.caption(
                    f"⚠️ Mode Turbo: le rendu traitera **{len(turbo_configs)} matchs** "
                    f"(le compteur n'affiche que le match actuel)"
                )

        st.divider()

        def trigger_apply_filters():
            st.session_state.ui_filters_applied = True

        # Apply Filters Button
        st.button(
            "✅ Appliquer les Filtres",
            type="primary",
            use_container_width=True,
            on_click=trigger_apply_filters,
            help="Applique les filtres sélectionnés à la visualisation et à l'aperçu.",
        )


        st.checkbox(
            "Auto-appliquer (Live Review)",
            key="ui_auto_apply_filters",
            help="Applique les filtres automatiquement à chaque modification.",
        )

        # --- CLIP BASKET (MAP SELECTIONS) ---
        st.sidebar.divider()
        render_basket_fragment()

        st.divider()
        st.divider()
        st.markdown(
            """
            <div class="tip-box">
            💡 <b>Astuce :</b> Vous pouvez configurer vos filtres dans l'onglet <b>Filtrage</b> et voir le résultat instantanément dans l'onglet <b>Aperçu</b> avant de lancer le rendu.
            </div>
            """,
            unsafe_allow_html=True,
        )

    return result


def render_right_column() -> dict:
    """
    Rendu de la colonne de droite : filtres actifs + panneau export.
    Retourne un dict avec export_mode, individual, group_by_player, out_filename,
    sidebar_run_btn, sidebar_xml_btn.
    """
    result = {}

    st.markdown("### 🏷️ Filtres Actifs")

    active_badges = []
    if len(st.session_state.ui_players) > 0:
        active_badges.append(f"👤 {len(st.session_state.ui_players)} Joueur(s)")
    if len(st.session_state.ui_types) > 0:
        active_badges.append(f"⚡ {len(st.session_state.ui_types)} Action(s)")
    if len(st.session_state.ui_start) > 0 or len(st.session_state.ui_end) > 0:
        active_badges.append("📍 Zones Spatiales")
    if getattr(st.session_state, "ui_adv_groups", None):
        if any(
            [
                g
                for g in st.session_state.ui_adv_groups
                if (isinstance(g, dict) and g.get("filters")) or (isinstance(g, list) and g)
            ]
        ):
            active_badges.append("🧠 Filtres Avancés")

    if active_badges:
        st.markdown(" ".join([f'<span class="active-badge">{b}</span>' for b in active_badges]), unsafe_allow_html=True)
    else:
        st.caption("Aucun filtre spécifique actif.")

    st.divider()
    st.markdown("### 💿 Export & Rendu")
    export_mode = st.radio(
        "Organisation du rendu",
        options=[
            "Vidéos longues par joueur/équipe",
            "Vidéo unique globale",
            "Clips indépendants séparés",
        ],
        index=0,
        key="ui_right_export_mode",
        help="Choisissez comment les clips seront assemblés.",
    )

    if "Vidéos longues" in export_mode:
        individual = False
        group_by_player = True
        out_filename = st.text_input("Suffixe (Ex: Highlights.mp4)", value="Highlights.mp4", key="ui_right_suffix")
    elif "Vidéo unique" in export_mode:
        individual = False
        group_by_player = False
        out_filename = st.text_input("Nom du fichier", value="Highlights.mp4", key="ui_right_filename")
        st.checkbox(
            "🚀 Montage Mixte (Interleaved)",
            key="ui_mixed_assembly",
            help="Alterne les clips si vous traitez plusieurs matchs.",
        )
    else:
        individual = True
        group_by_player = st.checkbox("Ranger par dossier joueur", value=True, key="ui_right_group")
        out_filename = "Highlights.mp4"

    result["export_mode"] = export_mode
    result["individual"] = individual
    result["group_by_player"] = group_by_player
    result["out_filename"] = out_filename

    st.divider()
    result["sidebar_run_btn"] = st.button(
        "🚀 LANCER CLIPMAKER",
        type="primary",
        use_container_width=True,
        help="Démarre la génération des vidéos avec les réglages actuels.",
    )
    result["sidebar_xml_btn"] = st.button(
        "📽️ Exporter XML Premiere Pro",
        use_container_width=True,
        help="Exporte un projet XML interactif pour Premiere Pro au lieu de vidéos mp4.",
    )

    st.divider()
    def _reset_app_state():
        # On supprime TOUTES les clés d'UI (y compris celles générées dynamiquement comme les groupes avancés)
        keys_to_delete = []
        for key in st.session_state.keys():
            if key.startswith("ui_"):
                # On préserve la navigation territoriale et les matchs chargés
                if key not in ["ui_match_bases", "ui_active_base", "ui_active_tab"]:
                    keys_to_delete.append(key)
                    
        for key in keys_to_delete:
            del st.session_state[key]
            
        # On réinitialise également les marqueurs système
        st.session_state.df_preview = None
        st.session_state.ui_last_filter_hash = None
        st.session_state.ui_filters_applied = True

    st.divider()
    st.button("🔄 Réinitialiser l'App (Filtres)", use_container_width=True, help="Remet à zéro tous vos filtres (joueurs, zones, build-up) sans décharger le match.", on_click=_reset_app_state)

    return result


@st.fragment
def render_basket_fragment():
    """Rendu isolé du panier de clips."""
    basket_len = len(st.session_state.get("clip_basket", []))
    with st.expander(f"🧺 Panier de Clips ({basket_len})", expanded=basket_len > 0):
        if basket_len == 0:
            st.info("Le panier est vide. Sélectionnez des actions sur la carte pour les ajouter.")
        else:
            from collections import Counter

            labels = [c.get("label", "Action") for c in st.session_state.clip_basket]
            counts = Counter(labels)
            for label, count in counts.items():
                st.text(f"• {label} x{count}")

            st.divider()
            if st.button("🎬 Exporter tout le Panier", key="side_export_basket", use_container_width=True, type="primary"):
                try:
                    all_specs = st.session_state.clip_basket
                    if all_specs:
                        if not os.path.exists("temp_previews"):
                            os.makedirs("temp_previews", exist_ok=True)
                        final_basket_file = f"temp_previews/basket_export_{int(time.time())}.mp4"

                        with st.status(f"⚡ Exportation de {len(all_specs)} clips...", expanded=True) as status:
                            import subprocess
                            from clip_processing import get_ffmpeg_binary

                            p_files = []
                            for i, spec in enumerate(all_specs):
                                p_f = f"temp_previews/basket_part_{i}.ts"
                                subprocess.run(
                                    [
                                        get_ffmpeg_binary(), "-y", "-ss", str(max(0, spec["start"])),
                                        "-to", str(spec["end"]), "-i", spec["src"],
                                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                                        "-c:a", "aac", "-b:a", "128k", "-f", "mpegts", p_f,
                                    ],
                                    capture_output=True,
                                )
                                if os.path.exists(p_f):
                                    p_files.append(p_f)

                            if p_files:
                                concat_str = "|".join(p_files)
                                subprocess.run(
                                    [
                                        get_ffmpeg_binary(), "-y", "-i", f"concat:{concat_str}",
                                        "-c", "copy", final_basket_file,
                                    ],
                                    capture_output=True,
                                )
                                for pf in p_files:
                                    try:
                                        os.remove(pf)
                                    except:
                                        pass

                            if os.path.exists(final_basket_file):
                                status.update(label="✅ Export terminé !", state="complete")
                                with open(final_basket_file, "rb") as f:
                                    st.download_button(
                                        "💾 Télécharger le Montage Final",
                                        f,
                                        file_name="export_panier.mp4",
                                        mime="video/mp4",
                                        use_container_width=True,
                                    )
                            else:
                                status.update(label="❌ Erreur export", state="error")
                except Exception as e:
                    st.error(f"Erreur Panier: {e}")

            if st.button("🗑️ Vider le Panier", key="side_clear_basket", use_container_width=True):
                st.session_state.clip_basket = []
                st.rerun()

