"""
ui_helpers.py
=============
Fonctions utilitaires UI : dialogues fichiers/dossiers (tkinter),
ouverture de fichiers/dossiers, lecture vidéo, logique d'entrelacement
de clips multi-match (interleave_specs) et safe_rerun.
"""

import os
import platform
import queue
import threading

import streamlit as st


# =============================================================================
# FILE / FOLDER DIALOG HELPERS (tkinter)
# =============================================================================

def get_initial_dir(current_path):
    if not current_path:
        return None
    current_path = str(current_path).strip().strip("\"'")
    if os.path.exists(current_path):
        if os.path.isdir(current_path):
            return current_path
        return os.path.dirname(os.path.abspath(current_path))
    return None


def _pick_file_thread(result_queue, filetypes, initialdir=None):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        if platform.system() == "Windows":
            root.wm_attributes("-topmost", True)
        elif platform.system() == "Darwin":
            os.system("osascript -e 'tell application \"Python\" to activate'")
    except Exception:
        pass
    path = filedialog.askopenfilename(filetypes=filetypes, initialdir=initialdir)
    root.destroy()
    result_queue.put(path)


def _pick_folder_thread(result_queue, initialdir=None):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        if platform.system() == "Windows":
            root.wm_attributes("-topmost", True)
        elif platform.system() == "Darwin":
            os.system("osascript -e 'tell application \"Python\" to activate'")
    except Exception:
        pass
    path = filedialog.askdirectory(initialdir=initialdir)
    root.destroy()
    result_queue.put(path)


def browse_file(filetypes, initialdir=None):
    q = queue.Queue()
    t = threading.Thread(
        target=_pick_file_thread, args=(q, filetypes, initialdir), daemon=True
    )
    t.start()
    t.join(timeout=60)
    try:
        return q.get_nowait()
    except queue.Empty:
        return ""


def browse_folder(initialdir=None):
    q = queue.Queue()
    t = threading.Thread(
        target=_pick_folder_thread, args=(q, initialdir), daemon=True
    )
    t.start()
    t.join(timeout=60)
    try:
        return q.get_nowait()
    except queue.Empty:
        return ""


# =============================================================================
# FILE ACTIONS
# =============================================================================

def open_file_location(path):
    if not path:
        st.warning("Aucun chemin spécifié.")
        return
    
    if platform.system() != "Windows":
        st.info(f"📁 Chemin sur le serveur : {path}")
        return

    clean_path = path.strip().strip("\"'")
    if os.path.exists(clean_path):
        target = (
            clean_path
            if os.path.isdir(clean_path)
            else os.path.dirname(os.path.abspath(clean_path))
        )
        if os.path.exists(target):
            try:
                os.startfile(target)
            except Exception as e:
                st.error(f"Erreur lors de l'ouverture : {e}")
        else:
            st.error("Dossier introuvable.")
    else:
        st.error(f"Le chemin n'existe pas : {clean_path}")


def play_video(path):
    import subprocess

    if platform.system() != "Windows":
        st.info("📺 Lecture vidéo locale désactivée sur le VPS. Utilisez l'onglet Aperçu.")
        return

    clean_path = path.strip().strip("\"'")
    if os.path.exists(clean_path):
        vlc_paths = [
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        ]
        vlc_exe = next((p for p in vlc_paths if os.path.exists(p)), None)
        if vlc_exe:
            try:
                subprocess.Popen([vlc_exe, clean_path])
            except:
                os.startfile(clean_path)
        else:
            try:
                os.startfile(clean_path)
            except:
                pass
    else:
        st.error(f"Le fichier n'existe pas : {clean_path}")


def open_premiere(path):
    import glob
    import subprocess

    if platform.system() != "Windows":
        st.info("🎬 Export Premiere : Fichier XML généré. Téléchargez-le depuis le dossier d'export.")
        return

    clean_path = path.strip().strip("\"'")
    if os.path.exists(clean_path):
        prem_paths = glob.glob(
            r"C:\Program Files\Adobe\Adobe Premiere Pro*\Adobe Premiere Pro.exe"
        )
        if prem_paths:
            try:
                subprocess.Popen([prem_paths[-1], clean_path])
                return
            except:
                pass
        try:
            os.startfile(clean_path)
        except:
            pass
    else:
        st.error(f"Le fichier n'existe pas : {clean_path}")


def get_ffmpeg_path():
    import shutil

    cmd = shutil.which("ffmpeg")
    if cmd:
        return cmd
    try:
        from moviepy.config import FFMPEG_BINARY

        if os.path.exists(FFMPEG_BINARY):
            return FFMPEG_BINARY
    except Exception:
        pass
    return "ffmpeg"


# =============================================================================
# INTERLEAVE SPECS (multi-match clip assembly)
# =============================================================================

def interleave_specs(specs_list):
    """
    Interleaves clips from multiple matches with spatial continuity and match rotation.
    Attempts to balance three goals:
    1. Alternate between matches (Round-robin logic).
    2. Avoid consecutive clips of the same type.
    3. Maintain positional flow (follow the ball's end position).
    """
    if not specs_list:
        return []

    from collections import deque

    lists = [deque(s) for s in specs_list if s]
    if not lists:
        return []

    interleaved = []
    last_type = None
    last_pos = None
    last_match_idx = -1
    curr_list_idx = 0

    while any(lists):
        best_idx = -1
        best_score = float("inf")

        for i, l in enumerate(lists):
            if not l:
                continue
            spec = l[0]

            if isinstance(spec, dict):
                sx, sy = spec.get("first_x"), spec.get("first_y")
                c_type = spec.get("type")
            else:
                sx, sy = None, None
                c_type = spec[3] if len(spec) >= 4 else None

            dist_score = 0
            if last_pos is not None and sx is not None and sy is not None:
                dist_score = ((sx - last_pos[0]) ** 2 + (sy - last_pos[1]) ** 2) ** 0.5
            elif last_pos is not None:
                dist_score = 40

            type_penalty = 40 if (last_type is not None and c_type == last_type) else 0
            match_rep_penalty = 200 if i == last_match_idx else 0
            rot_dist = (i - curr_list_idx) % len(lists)
            rotation_penalty = rot_dist * 100

            score = dist_score + type_penalty + match_rep_penalty + rotation_penalty

            if score < best_score:
                best_score = score
                best_idx = i

        if best_idx != -1:
            spec = lists[best_idx].popleft()
            interleaved.append(spec)

            if isinstance(spec, dict):
                last_type = spec.get("type")
                lx, ly = spec.get("last_x"), spec.get("last_y")
                lex, ley = spec.get("last_endX"), spec.get("last_endY")
                ltype = spec.get("last_type")

                if ltype in ["Pass", "Carry"] and lex is not None and ley is not None:
                    last_pos = (lex, ley)
                elif lx is not None and ly is not None:
                    last_pos = (lx, ly)
            else:
                last_type = spec[3] if len(spec) >= 4 else None
                last_pos = None

            last_match_idx = best_idx
            curr_list_idx = (best_idx + 1) % len(lists)
        else:
            break

    return interleaved


# =============================================================================
# STREAMLIT HELPERS
# =============================================================================

def safe_rerun():
    for k in ["ui_half1", "ui_half2", "ui_half3", "ui_half4", "ui_split_video", "ui_match_config_name"]:
        if k in st.session_state:
            try:
                st.session_state[k] = st.session_state[k]
            except Exception:
                pass
    st.rerun()
