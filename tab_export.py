"""
tab_export.py
=============
Onglet "Export & Logs" de ClipMaker SUAOL.
Paramètres de rendu (half detection, clip settings, dossier de sortie,
texte en surimpression, mode dry run).
"""

import os
import platform
import streamlit as st

from ui_theme import step_header
from ui_helpers import open_file_location, browse_folder, get_initial_dir


def render_tab_export() -> dict:
    """
    Affiche l'onglet Export & Logs.
    Retourne un dict avec tous les paramètres de rendu saisis par l'utilisateur.
    """
    st.markdown(step_header(6, "Export & Finalisation du Rendu"), unsafe_allow_html=True)
    st.subheader("🎥 Paramètres de Rendu")

    # --- Half Detection ---
    st.subheader("Half Detection")
    period_col = st.text_input(
        "Period Column Name",
        value="period",
        help="The CSV column that says FirstHalf/SecondHalf or 1/2. Leave blank if none.",
    )
    fallback_row = st.number_input(
        "Fallback Row Index",
        min_value=0,
        value=0,
        step=1,
        help="Row index where 2nd half begins. Only used if period column is blank.",
    )
    use_fallback = st.checkbox("Use fallback row index instead of period column")

    # --- Clip Settings ---
    st.subheader("Clip Settings")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        before_buf = st.number_input("Before (s)", value=5, min_value=0)
    with sc2:
        after_buf = st.number_input("After (s)", value=8, min_value=0)
    with sc3:
        min_gap = st.number_input(
            "Merge Gap (s)",
            value=6,
            min_value=0,
            help=(
                "Events within this many seconds of each other are merged into one clip. "
                "A sequence of passes in the same move becomes one clip rather than many. "
                "Increase to merge more aggressively, decrease to keep events separate."
            ),
        )

    # --- Output ---
    st.subheader("Format d'Export (Output)")
    oc1, oc2, oc3 = st.columns([4, 0.8, 0.8])
    with oc1:
        out_dir_input = st.text_input(
            "Dossier de destination",
            value=st.session_state.output_dir,
            placeholder="Cliquez sur Browse pour choisir le dossier",
        )
    with oc2:
        st.write("")
        st.write("")
        if platform.system() == "Windows":
            if st.button("Browse", key="browse_out", use_container_width=True):
                init_dir = get_initial_dir(st.session_state.output_dir)
                picked = browse_folder(initialdir=init_dir)
                if picked:
                    st.session_state.output_dir = picked
                    st.rerun()
        else:
            st.button("Browse", key="browse_out", use_container_width=True, disabled=True, help="Désactivé sur VPS")
    with oc3:
        st.write("")
        st.write("")
        if st.button("📂", key="open_out_dir", help="Ouvrir l'emplacement", use_container_width=True):
            open_file_location(st.session_state.output_dir)

    # Export mode info (read from sidebar)
    export_mode = st.session_state.get("ui_right_export_mode", "Vidéos longues par joueur/équipe")
    st.markdown("##### Structure des vidéos (Configurée dans la barre latérale ⚡)")
    if "Vidéos longues" in export_mode:
        st.info("📂 Va créer une longue vidéo compilée par joueur ciblé. Ex: `FCBarcelona/LamineYamal/Highlights_LamineYamal.mp4`")
    elif "Vidéo unique" in export_mode:
        st.info("🎞️ Toutes les actions filtrées seront assemblées dans un seul fichier.")
    else:
        st.info("✂️ Va exporter une multitude de petits fichiers de quelques secondes.")

    # --- Text Overlay ---
    st.markdown("---")
    st.markdown("##### ✏️ Texte en surimpression")
    custom_text_overlay = st.text_input(
        "Texte à afficher",
        placeholder="Ex: Lamine Yamal - FC Barcelona",
        help="Le texte s'affichera en bas au centre des clips de la vidéo. Laissez vide pour ne rien afficher.",
        key="ui_custom_text",
    )

    with st.expander("Paramètres du texte", key="expander_text_opts"):
        ct_c1, ct_c2, ct_c3 = st.columns(3)
        with ct_c1:
            custom_text_size = st.number_input("Taille", min_value=10, max_value=200, step=2, key="ui_custom_text_size")
        with ct_c2:
            custom_text_font = st.selectbox(
                "Police",
                options=["Arial", "Verdana", "Tahoma", "Courier New", "Consolas", "Impact"],
                key="ui_custom_text_font",
            )
        with ct_c3:
            custom_text_color = st.color_picker("Couleur", key="ui_custom_text_color")

        ct_o1, ct_b1, ct_b2 = st.columns(3)
        with ct_o1:
            custom_text_opacity = st.slider(
                "Opacité du texte", min_value=0.0, max_value=1.0, step=0.1, key="ui_custom_text_opacity"
            )
        with ct_b1:
            custom_text_bg = st.checkbox("Activer le fond noir", key="ui_custom_text_bg")
        with ct_b2:
            custom_text_bg_opacity = st.slider(
                "Opacité du fond",
                min_value=0.0,
                max_value=1.0,
                step=0.1,
                disabled=not custom_text_bg,
                key="ui_custom_text_bg_opacity",
            )

    st.markdown("---")
    dry_run = st.checkbox(
        "🧪 Mode Simulation (Dry Run)",
        help="Ne crée pas les vidéos, affiche juste les temps coupés dans la console ci-dessous pour tester.",
    )

    return {
        "period_col": period_col,
        "fallback_row": fallback_row,
        "use_fallback": use_fallback,
        "before_buf": before_buf,
        "after_buf": after_buf,
        "min_gap": min_gap,
        "out_dir_input": out_dir_input,
        "custom_text_overlay": custom_text_overlay,
        "custom_text_size": custom_text_size,
        "custom_text_font": custom_text_font,
        "custom_text_color": custom_text_color,
        "custom_text_opacity": custom_text_opacity,
        "custom_text_bg": custom_text_bg,
        "custom_text_bg_opacity": custom_text_bg_opacity,
        "dry_run": dry_run,
    }
