"""
run_logic.py
============
Logique de rendu de ClipMaker SUAOL.
Contient les trois modes de génération vidéo :
  - process_single_match_dialog  → un seul match (dialog st)
  - process_turbo_batch_dialog   → plusieurs matchs en parallèle (Turbo)
  - process_aggregate_dialog     → mode agrégat multi-match
Et la fonction utilitaire `process_batch_item` utilisée en thread.
"""

import json
import os
import queue
import re
import threading
import time
import concurrent.futures

import streamlit as st

from clip_processing import (
    apply_filters, run_clip_maker, export_to_premiere_xml,
    cut_and_concat_ffmpeg, get_ffmpeg_binary,
)


# =============================================================================
# PROCESS BATCH ITEM (worker thread, called from turbo/aggregate)
# =============================================================================

def process_batch_item(config_name, filter_config, batch_params, log_queue, progress_queue, allowed_ids=None, dir_override=None):
    """
    Worker function executed in a thread for each config.
    Loads match config JSON, applies filters, and runs clip extraction.
    Sends log/specs/done messages via log_queue and progress_queue.
    """
    MATCH_CONFIG_DIR = dir_override or batch_params.get("MATCH_CONFIG_DIR", "match_configs")
    config_path = os.path.join(MATCH_CONFIG_DIR, config_name)

    def log(msg):
        log_queue.put({"type": "log", "msg": msg})

    if not os.path.exists(config_path):
        log(f"❌ ERROR: Config file not found: {config_path}")
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            match_config = json.load(f)
    except Exception as e:
        log(f"❌ ERROR reading config {config_name}: {e}")
        return

    from worker_utils import get_opta_cache_path
    import pandas as pd

    csv_p = match_config.get("csv_path", "").strip().strip("\"'")
    cache_p = get_opta_cache_path(csv_p)

    if not os.path.exists(cache_p):
        log(f"❌ ERROR: Cache not found for {config_name}: {cache_p}")
        return

    try:
        df = pd.read_csv(cache_p)
        if allowed_ids is not None:
            df = df[df["id"].isin(allowed_ids)]
        if df.empty:
            log(f"⚠️ WARNING: No matching events in {config_name}")
            return
    except Exception as e:
        log(f"❌ ERROR loading cache for {config_name}: {e}")
        return

    try:
        fc = dict(filter_config)  # shallow copy
        df_filtered, _ = apply_filters(df.copy(), fc)
        n_events = len(df_filtered)
        log(f"✓ Found {n_events} events in {config_name}")
    except Exception as e:
        log(f"❌ ERROR applying filters for {config_name}: {e}")
        return

    if df_filtered.empty:
        log_queue.put({"type": "done", "config": config_name, "clip_specs": []})
        return

    # Build clip config
    period_col = batch_params.get("period_col", "period")
    use_fallback = batch_params.get("use_fallback", False)
    fallback_row = batch_params.get("fallback_row", 0)
    before_buf = batch_params.get("before_buf", 5)
    after_buf = batch_params.get("after_buf", 8)
    min_gap = batch_params.get("min_gap", 6)
    final_out_dir = batch_params.get("final_out_dir", "output")
    out_filename = batch_params.get("out_filename", "Highlights.mp4")
    individual = batch_params.get("individual", False)
    group_by_player = batch_params.get("group_by_player", False)
    dry_run = batch_params.get("dry_run", False)
    xml_only = batch_params.get("xml_only", False)
    custom_text_options = batch_params.get("custom_text_options", {})

    h1 = match_config.get("ui_half1", "")
    h2 = match_config.get("ui_half2", "")
    video_path = match_config.get("video_path", "").strip().strip("\"'")
    video2_path = match_config.get("video2_path", "").strip().strip("\"'")
    split_video = match_config.get("ui_split_video", False)
    h3 = match_config.get("ui_half3", "")
    h4 = match_config.get("ui_half4", "")

    item_config = {
        "video_file": video_path,
        "video2_file": video2_path,
        "split_video": split_video,
        "data_file": csv_p,
        "half1_time": h1,
        "half2_time": h2,
        "half3_time": h3 or "",
        "half4_time": h4 or "",
        "period_column": "" if use_fallback else period_col,
        "fallback_row": int(fallback_row) if use_fallback else None,
        "before_buffer": before_buf,
        "after_buffer": after_buf,
        "min_gap": min_gap,
        "output_dir": os.path.join(final_out_dir, os.path.splitext(os.path.basename(config_name))[0]),
        "output_filename": out_filename,
        "individual_clips": individual,
        "group_by_player": group_by_player,
        "custom_text_options": custom_text_options,
        "dry_run": dry_run,
        "xml_only": xml_only,
        "opta_df": df_filtered,
    }
    item_config.update(fc)

    try:
        run_clip_maker(item_config, log_queue, progress_queue)
        # Collect specs for global assembly
        from clip_processing import get_merged_specs_from_df, to_seconds, assign_periods
        from clip_processing import match_clock_to_video_time

        p_col = "" if use_fallback else period_col
        df_filtered = assign_periods(df_filtered, p_col if p_col else None, fallback_row)
        p_start = {1: to_seconds(h1 or "0:00"), 2: to_seconds(h2 or "0:00")}
        p_offset = {1: (0, 0), 2: (45, 0)}
        clip_cfg = {
            "before_buffer": before_buf, "after_buffer": after_buf, "min_clip_gap": min_gap,
            "video_file": video_path, "video2_file": video2_path, "split_video": split_video,
        }
        specs = get_merged_specs_from_df(df_filtered, clip_cfg, p_start, p_offset)
        log_queue.put({
            "type": "specs",
            "clip_specs": specs,
            "match_date": match_config.get("match_date"),
        })
    except Exception as e:
        log(f"❌ FATAL ERROR running clip_maker for {config_name}: {e}")
        import traceback
        log(traceback.format_exc())

    log_queue.put({"type": "done", "config": config_name})


# =============================================================================
# SINGLE MATCH DIALOG
# =============================================================================

def process_single_match_dialog(config, open_file_location_fn, open_premiere_fn, play_video_fn):
    """Ouvre un dialog Streamlit pour le rendu d'un seul match."""
    st.session_state["dlg_sgl_done"] = False

    @st.dialog("🎬 Progression du Rendu (ClipMaker)", width="large")
    def _dialog():
        st.markdown("### ⚙️ Traitement en cours...")
        progress_placeholder = st.empty()
        log_placeholder = st.empty()

        def render_finished():
            if "dlg_sgl_logs" in st.session_state:
                log_placeholder.markdown(
                    f'<div class="log-box">{"<br>".join(st.session_state["dlg_sgl_logs"])}</div>',
                    unsafe_allow_html=True,
                )
            progress_placeholder.empty()
            st.success("✅ Traitement terminé !")
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                if st.button("Fermer", type="primary", use_container_width=True):
                    st.rerun()
            with c_btn2:
                current_fp = st.session_state.get("dlg_sgl_path")
                if (
                    not config.get("individual_clips")
                    and not config.get("group_by_player")
                    and current_fp
                    and os.path.exists(current_fp)
                ):
                    if current_fp.endswith(".xml"):
                        if st.button("🎬 Ouvrir sur Premiere Pro", use_container_width=True):
                            open_premiere_fn(current_fp)
                    else:
                        if st.button("▶️ Lire la vidéo (VLC)", use_container_width=True):
                            play_video_fn(current_fp)
                else:
                    if st.button("📂 Ouvrir le dossier", use_container_width=True):
                        open_file_location_fn(config.get("output_dir", "output"))

        if st.session_state.get("dlg_sgl_done", False):
            render_finished()
            return

        log_queue = queue.Queue()
        progress_queue = queue.Queue()
        log_lines = []
        last_progress = {"current": 0, "total": 1, "elapsed": 0}

        thread = threading.Thread(target=run_clip_maker, args=(config, log_queue, progress_queue), daemon=True)
        thread.start()

        while thread.is_alive() or not log_queue.empty():
            while not progress_queue.empty():
                last_progress = progress_queue.get_nowait()

            updated = False
            while not log_queue.empty():
                msg = log_queue.get_nowait()
                if msg["type"] == "log":
                    log_lines.append(msg["msg"])
                    updated = True

            cur = last_progress["current"]
            tot = last_progress["total"]
            elapsed = last_progress["elapsed"]
            frac = cur / tot if tot > 0 else 0
            phase = last_progress.get("phase", "clips")

            if cur > 0 and elapsed > 0:
                rate = cur / elapsed
                remaining = (tot - cur) / rate
                eta_str = f"{int(remaining // 60)}m {int(remaining % 60):02d}s remaining"
            else:
                eta_str = "Calculating..."

            if phase == "assembly":
                label_str = (
                    "Finalising — merging audio and video, almost done..."
                    if frac >= 0.99
                    else f"Assembling — frame {cur:,} of {tot:,} — {eta_str}"
                )
            else:
                label_str = f"Clip {cur} of {tot} — {eta_str}"

            with progress_placeholder.container():
                st.markdown(f'<div class="progress-label">{label_str}</div>', unsafe_allow_html=True)
                st.progress(frac)

            if updated:
                log_placeholder.markdown(
                    f'<div class="log-box">{"<br>".join(log_lines)}</div>',
                    unsafe_allow_html=True,
                )

            time.sleep(0.3)

        thread.join()

        while not log_queue.empty():
            msg = log_queue.get_nowait()
            if msg["type"] == "log":
                log_lines.append(msg["msg"])

        final_found_path = os.path.join(config.get("output_dir", "output"), config.get("output_filename", "Highlights.mp4"))
        for log_msg in reversed(log_lines):
            if "Saved to:" in log_msg:
                final_found_path = log_msg.split("Saved to:")[1].strip()
                break
            if "Project XML exported to:" in log_msg:
                final_found_path = log_msg.split("Project XML exported to:")[1].strip()
                break

        st.session_state["dlg_sgl_logs"] = log_lines
        st.session_state["dlg_sgl_path"] = final_found_path
        st.session_state["dlg_sgl_done"] = True
        render_finished()

    _dialog()


# =============================================================================
# TURBO BATCH DIALOG
# =============================================================================

def process_turbo_batch_dialog(
    batch_configs, base_filters, global_batch_params,
    interleave_specs_fn, out_filename, final_out_dir,
    is_global_reel, custom_text_options,
    open_file_location_fn, play_video_fn,
):
    """Dialog de rendu Turbo Batch (multi-match en parallèle)."""
    st.session_state["dlg_turbo_done"] = False

    @st.dialog("🚀 Turbo Batch en cours...", width="large")
    def _dialog():
        batch_log_placeholder = st.empty()

        def render_finished():
            if "dlg_turbo_logs" in st.session_state:
                batch_log_placeholder.markdown(
                    f'<div class="log-box">{"<br>".join(st.session_state["dlg_turbo_logs"])}</div>',
                    unsafe_allow_html=True,
                )
            st.success(st.session_state.get("dlg_turbo_msg", "Terminé !"))
            st.balloons()
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("Fermer", type="primary", use_container_width=True):
                    st.rerun()
            with col_btn2:
                current_fp = st.session_state.get("dlg_turbo_path")
                if current_fp and os.path.exists(current_fp):
                    if st.button("▶️ Lire la vidéo (VLC)", use_container_width=True):
                        play_video_fn(current_fp)
                else:
                    if st.button("📂 Ouvrir le dossier", use_container_width=True):
                        open_file_location_fn(final_out_dir)

        if st.session_state.get("dlg_turbo_done", False):
            render_finished()
            return

        batch_log_lines = ["<b>🚀 Démarrage du traitement Turbo (5 concurrents)...</b>"]
        batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)

        all_master_specs_dict = {name: [] for name in batch_configs}
        specs_lock = threading.Lock()
        batch_total_events = batch_total_clips = batch_matches_done = 0

        active_futures = []
        batch_start_time = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            for config_name in batch_configs:
                lq = queue.Queue()
                pq = queue.Queue()
                f = executor.submit(process_batch_item, config_name, base_filters, global_batch_params, lq, pq)
                active_futures.append({"future": f, "lq": lq, "pq": pq, "name": config_name, "done_notified": False})

            while any(not x["future"].done() for x in active_futures) or any(not x["lq"].empty() for x in active_futures):
                updated = False
                for item in active_futures:
                    while not item["lq"].empty():
                        m = item["lq"].get_nowait()
                        if m["type"] == "log":
                            msg = m["msg"]
                            color = "red" if ("ERROR" in msg or "❌" in msg) else "#00ff88" if any(x in msg for x in ["Successfully", "Saved", "Found", "✓"]) else "white"
                            display_msg = msg.strip().replace("\n", "<br>")
                            batch_log_lines.append(f"&nbsp;&nbsp;<small style='color:{color};'><b>[{item['name']}]</b> {display_msg}</small>")
                            updated = True
                            cm = re.search(r"Found (\d+) events .* (\d+) clips", msg)
                            if cm:
                                batch_total_events += int(cm.group(1))
                                batch_total_clips += int(cm.group(2))
                        elif m["type"] == "specs":
                            with specs_lock:
                                all_master_specs_dict[item["name"]].extend(m.get("clip_specs", []))

                    if item["future"].done() and not item["done_notified"]:
                        try:
                            item["future"].result()
                            batch_log_lines.append(f"<span style='color:white;'>&nbsp;&nbsp;🏁 <b>{item['name']}</b> terminé.</span>")
                        except Exception as e:
                            batch_log_lines.append(f"<span style='color:red;'>&nbsp;&nbsp;❌ <b>{item['name']}</b> Erreur fatale: {e}</span>")
                        item["done_notified"] = True
                        batch_matches_done += 1
                        updated = True

                if updated:
                    if len(batch_log_lines) > 200:
                        batch_log_lines = batch_log_lines[-200:]
                    batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)
                time.sleep(0.5)

        # Combine specs
        all_master_specs = []
        if st.session_state.ui_mixed_assembly:
            lists_to_mix = [all_master_specs_dict[name] for name in batch_configs if all_master_specs_dict[name]]
            all_master_specs = interleave_specs_fn(lists_to_mix)
        else:
            for name in batch_configs:
                all_master_specs.extend(all_master_specs_dict[name])

        # Global assembly
        final_path = None
        if is_global_reel and all_master_specs:
            try:
                batch_log_lines.append(f"<br><b style='color:#00ff88;'>🚀 ASSEMBLAGE GLOBAL ({len(all_master_specs)} CLIPS)...</b>")
                progress_line_idx = len(batch_log_lines)
                batch_log_lines.append("&nbsp;&nbsp;⏳ Préparation...")
                batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)

                ffmpeg_bin = get_ffmpeg_binary()
                final_filename = f"GLOBAL_BATCH_MERGE_{out_filename}"
                final_path = os.path.join(final_out_dir, final_filename)
                os.makedirs(final_out_dir, exist_ok=True)

                g_pq = queue.Queue()
                t_assemble = threading.Thread(target=cut_and_concat_ffmpeg, args=(ffmpeg_bin, all_master_specs, final_path, g_pq, time.time(), custom_text_options))
                t_assemble.start()

                while t_assemble.is_alive() or not g_pq.empty():
                    try:
                        m = g_pq.get(timeout=0.2)
                        if m.get("phase") == "clips":
                            curr, tot = m.get("current", 0), m.get("total", 0)
                            batch_log_lines[progress_line_idx] = f"&nbsp;&nbsp;⏳ Rendu : {int(curr/tot*100)}% ({curr}/{tot} clips)"
                            batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)
                    except:
                        pass
                t_assemble.join()

                batch_log_lines[progress_line_idx] = f"<span style='color:#00ff88;'>&nbsp;&nbsp;✅ VIDÉO GLOBALE CRÉÉE : {final_filename}</span>"
                batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)
            except Exception as e:
                batch_log_lines.append(f"<span style='color:red;'>&nbsp;&nbsp;❌ Erreur assemblage global: {e}</span>")
                batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)

        # Summary
        real_total_clips = len(all_master_specs)
        total_duration = sum(s.get("end", 0) - s.get("start", 0) for s in all_master_specs)
        vd_h, vd_r = divmod(int(total_duration), 3600)
        vd_m, vd_s = divmod(vd_r, 60)
        elapsed = time.time() - batch_start_time
        h, r = divmod(int(elapsed), 3600)
        m_e, s_e = divmod(r, 60)

        for line in [
            f"<br><b style='color:#00d9ff;'>{'='*50}</b>",
            f"<b style='color:#00d9ff;'>📊 RÉSUMÉ GLOBAL</b>",
            f"<b style='color:#00d9ff;'>&nbsp;&nbsp;Matchs traités : {batch_matches_done}/{len(batch_configs)}</b>",
            f"<b style='color:#00d9ff;'>&nbsp;&nbsp;Total clips : {real_total_clips}</b>",
            f"<b style='color:#00d9ff;'>&nbsp;&nbsp;Durée vidéo finale : {vd_h:02d}:{vd_m:02d}:{vd_s:02d}</b>",
            f"<b style='color:#00d9ff;'>&nbsp;&nbsp;Temps écoulé : {h:02d}:{m_e:02d}:{s_e:02d}</b>",
            f"<b style='color:#00d9ff;'>{'='*50}</b>",
            "<br><b style='color:#00ff88;'>TRAITEMENT BATCH TERMINÉ !</b>",
        ]:
            batch_log_lines.append(line)

        st.session_state["dlg_turbo_logs"] = batch_log_lines
        st.session_state["dlg_turbo_msg"] = f"Traitement terminé ! {real_total_clips} clips depuis {batch_matches_done} matchs. Fichiers dans : {os.path.abspath(final_out_dir)}"
        st.session_state["dlg_turbo_path"] = final_path
        st.session_state["dlg_turbo_done"] = True
        render_finished()

    _dialog()


# =============================================================================
# AGGREGATE DIALOG
# =============================================================================

def process_aggregate_dialog(
    configs_to_process, df_filtered, dummy_config, batch_params,
    out_filename, final_out_dir, xml_actually_requested,
    interleave_specs_fn, open_file_location_fn, open_premiere_fn, play_video_fn,
):
    """Dialog de rendu en mode Agrégat (multi-match via session state)."""
    st.session_state["dlg_agg_done"] = False

    @st.dialog("🌐 Multi-Analyse (Aggregate) en cours...", width="large")
    def _dialog():
        batch_log_placeholder = st.empty()

        def render_finished():
            if "dlg_agg_logs" in st.session_state:
                batch_log_placeholder.markdown(
                    f'<div class="log-box">{"<br>".join(st.session_state["dlg_agg_logs"])}</div>',
                    unsafe_allow_html=True,
                )
            st.success(st.session_state.get("dlg_agg_msg", "Terminé !"))
            st.balloons()
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("Fermer", type="primary", use_container_width=True):
                    st.rerun()
            with col_btn2:
                current_fp = st.session_state.get("dlg_agg_path")
                if current_fp and os.path.exists(current_fp):
                    if current_fp.endswith(".xml"):
                        if st.button("🎬 Ouvrir sur Premiere Pro", use_container_width=True):
                            open_premiere_fn(current_fp)
                    else:
                        if st.button("▶️ Lire la vidéo (VLC)", use_container_width=True):
                            play_video_fn(current_fp)
                else:
                    if st.button("📂 Ouvrir le dossier", use_container_width=True):
                        open_file_location_fn(final_out_dir)

        if st.session_state.get("dlg_agg_done", False):
            render_finished()
            return

        batch_log_lines = [f"<b style='color:#00ff88;'>DÉMARRAGE MULTI-ANALYSE ({len(configs_to_process)} MATCHS)</b>"]
        from threading import Lock

        all_master_specs_dict = {name: [] for name in configs_to_process}
        specs_lock = Lock()
        agg_total_events = agg_total_clips = agg_matches_done = 0

        active_futures = []
        agg_start_time = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            for config_name in configs_to_process:
                match_slice = df_filtered[df_filtered["_source_config_file"] == config_name]
                match_allowed_ids = match_slice["id"].tolist() if "id" in match_slice.columns else None
                dir_override = None
                if "_source_config_dir" in match_slice.columns:
                    dir_override = match_slice["_source_config_dir"].iloc[0]
                lq = queue.Queue()
                pq = queue.Queue()
                f = executor.submit(process_batch_item, config_name, dummy_config, batch_params, lq, pq, match_allowed_ids, dir_override)
                active_futures.append({"future": f, "lq": lq, "pq": pq, "name": config_name, "done_notified": False})

            while any(not x["future"].done() for x in active_futures) or any(not x["lq"].empty() for x in active_futures):
                updated = False
                for item in active_futures:
                    while not item["lq"].empty():
                        m = item["lq"].get_nowait()
                        if m["type"] == "log":
                            msg = m["msg"]
                            color = "red" if ("ERROR" in msg or "❌" in msg) else "#00ff88" if any(x in msg for x in ["Successfully", "Saved", "Found", "✓"]) else "white"
                            batch_log_lines.append(f"&nbsp;&nbsp;<small style='color:{color};'><b>[{item['name']}]</b> {msg.strip().replace(chr(10), '<br>')}</small>")
                            updated = True
                            cm = re.search(r"Found (\d+) events .* (\d+) clips", msg)
                            if cm:
                                agg_total_events += int(cm.group(1))
                                agg_total_clips += int(cm.group(2))
                        elif m["type"] == "specs":
                            with specs_lock:
                                all_master_specs_dict[item["name"]].extend(m.get("clip_specs", []))

                    if item["future"].done() and not item["done_notified"]:
                        try:
                            item["future"].result()
                            batch_log_lines.append(f"<span style='color:white;'>&nbsp;&nbsp;🏁 <b>{item['name']}</b> terminé.</span>")
                        except Exception as e:
                            batch_log_lines.append(f"<span style='color:red;'>&nbsp;&nbsp;❌ <b>{item['name']}</b> Erreur: {e}</span>")
                        item["done_notified"] = True
                        agg_matches_done += 1
                        updated = True

                if updated:
                    if len(batch_log_lines) > 200:
                        batch_log_lines = batch_log_lines[-200:]
                    batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)
                time.sleep(0.5)

        all_master_specs = []
        if st.session_state.ui_mixed_assembly:
            lists_to_mix = [all_master_specs_dict[name] for name in configs_to_process if all_master_specs_dict[name]]
            all_master_specs = interleave_specs_fn(lists_to_mix)
        else:
            for name in configs_to_process:
                all_master_specs.extend(all_master_specs_dict[name])

        # XML export
        final_path = None
        if xml_actually_requested:
            base_name, _ = os.path.splitext(out_filename)
            xml_out = os.path.join(final_out_dir, f"{base_name}.xml")
            export_to_premiere_xml(all_master_specs, xml_out)
            batch_log_lines.append(f"<b style='color:#00d9ff;'>{'='*50}</b>")
            batch_log_lines.append(f"<br><b style='color:#00ff88;'>✅ PROJET XML CRÉÉ : {os.path.basename(xml_out)}</b>")
            st.session_state["dlg_agg_logs"] = batch_log_lines
            st.session_state["dlg_agg_msg"] = f"XML exporté : {os.path.basename(xml_out)}"
            st.session_state["dlg_agg_path"] = xml_out
            st.session_state["dlg_agg_done"] = True
            render_finished()
            return

        is_global_reel = batch_params.get("is_global_reel", False)
        if is_global_reel and all_master_specs:
            try:
                batch_log_lines.append(f"<br><b style='color:#00ff88;'>🚀 ASSEMBLAGE GLOBAL ({len(all_master_specs)} CLIPS)...</b>")
                progress_line_idx = len(batch_log_lines)
                batch_log_lines.append("&nbsp;&nbsp;⏳ Préparation...")
                batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)

                ffmpeg_bin = get_ffmpeg_binary()
                final_path = os.path.join(final_out_dir, f"GLOBAL_MULTI_ANALYSE_{out_filename}")
                os.makedirs(final_out_dir, exist_ok=True)
                custom_text_options = batch_params.get("custom_text_options", {})
                g_pq = queue.Queue()
                t_assemble = threading.Thread(target=cut_and_concat_ffmpeg, args=(ffmpeg_bin, all_master_specs, final_path, g_pq, time.time(), custom_text_options))
                t_assemble.start()

                while t_assemble.is_alive() or not g_pq.empty():
                    try:
                        m = g_pq.get(timeout=0.2)
                        if m.get("phase") == "clips":
                            curr, tot = m.get("current", 0), m.get("total", 0)
                            batch_log_lines[progress_line_idx] = f"&nbsp;&nbsp;⏳ Rendu : {int(curr/tot*100)}% ({curr}/{tot} clips)"
                            batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)
                    except:
                        pass
                t_assemble.join()
                batch_log_lines[progress_line_idx] = f"<span style='color:#00ff88;'>&nbsp;&nbsp;✅ VIDÉO FINALE CRÉÉE : {os.path.basename(final_path)}</span>"
                batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)
            except Exception as e:
                batch_log_lines.append(f"<span style='color:red;'>❌ Erreur assemblage global: {e}</span>")
                batch_log_placeholder.markdown(f'<div class="log-box">{"<br>".join(batch_log_lines)}</div>', unsafe_allow_html=True)

        total_duration = sum(s.get("end", 0) - s.get("start", 0) for s in all_master_specs)
        vd_h, vd_r = divmod(int(total_duration), 3600)
        vd_m, vd_s = divmod(vd_r, 60)
        elapsed = time.time() - agg_start_time
        h_e, r_e = divmod(int(elapsed), 3600)
        m_e, s_e = divmod(r_e, 60)

        for line in [
            f"<br><b style='color:#00d9ff;'>{'='*50}</b>",
            f"<b style='color:#00d9ff;'>📊 RÉSUMÉ GLOBAL</b>",
            f"<b style='color:#00d9ff;'>&nbsp;&nbsp;Matchs traités : {agg_matches_done}/{len(configs_to_process)}</b>",
            f"<b style='color:#00d9ff;'>&nbsp;&nbsp;Total événements filtrés : {agg_total_events}</b>",
            f"<b style='color:#00d9ff;'>&nbsp;&nbsp;Total clips (après fusion) : {agg_total_clips}</b>",
            f"<b style='color:#00d9ff;'>&nbsp;&nbsp;Durée vidéo finale : {vd_h:02d}:{vd_m:02d}:{vd_s:02d}</b>",
            f"<b style='color:#00d9ff;'>&nbsp;&nbsp;Temps écoulé : {h_e:02d}:{m_e:02d}:{s_e:02d}</b>",
            f"<b style='color:#00d9ff;'>{'='*50}</b>",
            "<br><b style='color:#00ff88;'>TRAITEMENT MULTI-ANALYSE TERMINÉ !</b>",
        ]:
            batch_log_lines.append(line)

        st.session_state["dlg_agg_logs"] = batch_log_lines
        st.session_state["dlg_agg_msg"] = f"Traitement terminé ! {agg_total_clips} clips depuis {agg_matches_done} matchs. Fichiers dans : {os.path.abspath(final_out_dir)}"
        st.session_state["dlg_agg_path"] = final_path
        st.session_state["dlg_agg_done"] = True
        render_finished()

    _dialog()
