import os
import queue
import threading
import time
import platform
import re
import requests
import pandas as pd

PERIOD_MAP = {
    "FirstHalf": 1, "SecondHalf": 2,
    "ExtraTimeFirstHalf": 3, "ExtraTimeSecondHalf": 4,
    1: 1, 2: 2, 3: 3, 4: 4,
}

# =============================================================================
# ZONE DEFINITIONS (105m x 68m pitch)
# =============================================================================
FIELD_ZONES = {
    "🌍 Moitiés de terrain": {
        "Moitié Défensive (DEF_HALF)": {"x": [0, 52.5], "y": [0, 68]},
        "Moitié Offensive (OFF_HALF)": {"x": [52.5, 105], "y": [0, 68]},
    },
    "📏 Tiers longitudinaux": {
        "Tiers Défensif (DEF_THIRD)": {"x": [0, 35], "y": [0, 68]},
        "Tiers Central (MID_THIRD)": {"x": [35, 70], "y": [0, 68]},
        "Tiers Offensif (FINAL_THIRD)": {"x": [70, 105], "y": [0, 68]},
    },
    "↕️ Couloirs latéraux": {
        "Aile Gauche (LEFT_WING)": {"x": [0, 105], "y": [54.4, 68]},
        "Demi-espace Gauche (HALF_SPACE_LEFT)": {"x": [0, 105], "y": [40.8, 54.4]},
        "Axe Central (CENTER_CHANNEL)": {"x": [0, 105], "y": [27.2, 40.8]},
        "Demi-espace Droit (HALF_SPACE_RIGHT)": {"x": [0, 105], "y": [13.6, 27.2]},
        "Aile Droite (RIGHT_WING)": {"x": [0, 105], "y": [0, 13.6]},
    },
    "🥅 Zones spécifiques": {
        "Surface de réparation défensive (BOX_DEF)": {"x": [0, 16.5], "y": [13.84, 54.16]},
        "Surface de réparation offensive (BOX_OFF)": {"x": [88.5, 105], "y": [13.84, 54.16]},
        "Zone 14 (ZONE_14)": {"x": [70, 88.5], "y": [13.84, 54.16]},
    }
}

# Flatten for multiselect
FLAT_ZONES = {}
for cat_name, zones in FIELD_ZONES.items():
    for name, bounds in zones.items():
        FLAT_ZONES[name] = bounds

def to_seconds(timestamp):
    ts = timestamp.strip()
    if not ts: return 0
    is_neg = ts.startswith("-")
    if is_neg:
        ts = ts[1:].strip()
    
    parts = list(map(int, ts.split(":")))
    if len(parts) == 2:
        val = parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        val = parts[0] * 3600 + parts[1] * 60 + parts[2]
    else:
        try:
            val = float(ts)
        except:
            raise ValueError(f"Invalid timestamp: '{timestamp}' — use MM:SS or HH:MM:SS")
    
    return -val if is_neg else val

def assign_periods(df, period_column, fallback_row):
    if period_column:
        if period_column not in df.columns:
            raise ValueError(f"Column '{period_column}' not found. Available: {list(df.columns)}")
        
        df["resolved_period"] = df[period_column].map(PERIOD_MAP)
        
        # If there are unrecognized values, we filter them out instead of crashing
        if df["resolved_period"].isna().any():
            bad = df[df["resolved_period"].isna()][period_column].unique()
            # We keep only rows with a valid period mapping
            df = df.dropna(subset=["resolved_period"]).copy()
            
        df["resolved_period"] = df["resolved_period"].astype(int)
        return df
    if fallback_row is not None:
        df = df.reset_index(drop=True)
        df["resolved_period"] = (df.index >= fallback_row).astype(int) + 1
        return df
    raise ValueError("No period column or fallback row set.")

def match_clock_to_video_time(minute, second, period, period_start, period_offset):
    if period not in period_start:
        raise ValueError(f"Period {period} not in PERIOD_START_IN_VIDEO.")
    offset_min, offset_sec = period_offset[period]
    elapsed = (minute * 60 + second) - (offset_min * 60 + offset_sec)
    
    # We allow a small tolerance for events slightly before the official period start (e.g. 44:58 for 45:00)
    # but the final video timestamp MUST be positive.
    video_time = period_start[period] + elapsed
    
    if video_time < -2: # Allowance for buffer, but generally video_time should be >= 0
        raise ValueError(f"Event at {minute}:{second:02d} P{period} is before video start (Video Time: {video_time:.1f}s)")
    
    return max(0, video_time)

def monitor_file_progress(out_path, total_frames, fps, progress_queue, stop_event):
    """
    Monitors output file size in a background thread to estimate
    encoding progress. Pushes updates to progress_queue until stop_event is set.
    Estimated file size = (total_frames / fps) * bitrate_estimate
    """
    import os, time
    # Wait for file to be created
    for _ in range(20):
        if os.path.exists(out_path):
            break
        time.sleep(0.5)

    # Estimate final file size from a ~2Mbps bitrate baseline
    estimated_bytes = (total_frames / max(fps, 1)) * 250_000
    start_time = time.time()

    while not stop_event.is_set():
        try:
            current_bytes = os.path.getsize(out_path)
            frac = min(current_bytes / estimated_bytes, 0.99)
            current_frame = int(frac * total_frames)
            elapsed = time.time() - start_time
            progress_queue.put({
                "current": current_frame,
                "total": total_frames,
                "elapsed": elapsed,
                "phase": "assembly"
            })
        except Exception:
            pass
        time.sleep(0.5)


def merge_overlapping_windows(windows, min_gap):
    """Windows are tuples of (start, end, label, period).
    Only merge windows from the same period (same video file in split mode)."""
    if not windows:
        return []
    merged = [list(windows[0])]
    for start, end, label, period in windows[1:]:
        prev = merged[-1]
        if start <= prev[1] + min_gap and period == prev[3]:
            prev[1] = max(prev[1], end)
    return [tuple(w) for w in merged]

def interleave_specs(specs_list):
    """
    Interleaves clips from multiple matches or selectors with spatial continuity and rotation.
    Attempts to balance three goals:
    1. Alternate between matches/selectors (Round-robin logic).
    2. Avoid consecutive clips of the same type.
    3. Maintain positional flow (follow the ball's end position).
    """
    if not specs_list: return []
    
    from collections import deque
    # Each source match/selector is a queue of clip specs
    lists = [deque(s) for s in specs_list if s]
    if not lists: return []
    
    interleaved = []
    last_type = None
    last_pos = None # Reference (x, y) to follow
    last_match_idx = -1
    curr_list_idx = 0 # Match that "should" be next in rotation
    
    while any(lists):
        best_idx = -1
        best_score = float('inf')
        
        # We try to prioritize the "next" match in rotation (curr_list_idx)
        # but weighting it against spatial and type matches.
        
        for i in range(len(lists)):
            if not lists[i]: continue
            
            candidate = lists[i][0]
            # candidate is structured {start, end, label, players, etc.}
            
            # 1. Rotation Penalty (Stronger to force interleaving)
            # How many steps away from curr_list_idx is this match?
            dist = (i - curr_list_idx) % len(lists)
            score = dist * 100 # Increased from 10 to 100 to prioritize rotation
            
            # 2. Category Similarity Penalty
            # Try to avoid 2 identical action types in a row
            c_type = candidate.get("types", ["None"])[0] if "types" in candidate else candidate.get("type", "None")
            if c_type == last_type:
                score += 50
            
            # 3. Spatial Continuity Bonus
            # If the ball ended at (X, Y) in last clip, prioritize clips starting near (X, Y)
            if last_pos is not None:
                c_x = candidate.get("first_x")
                c_y = candidate.get("first_y")
                if c_x is not None and c_y is not None:
                    dist_sq = (c_x - last_pos[0])**2 + (c_y - last_pos[1])**2
                    score += (dist_sq ** 0.5) * 0.5 # Add distance in meters-ish
            
            if score < best_score:
                best_score = score
                best_idx = i
        
        if best_idx != -1:
            chosen = lists[best_idx].popleft()
            interleaved.append(chosen)
            
            # Update state
            last_type = chosen.get("types", ["None"])[0] if "types" in chosen else chosen.get("type", "None")
            last_pos = (chosen.get("last_endX"), chosen.get("last_endY")) if chosen.get("last_endX") is not None else \
                       (chosen.get("last_x"), chosen.get("last_y"))
            
            # Rotate target match
            curr_list_idx = (best_idx + 1) % len(lists)
        else:
            break
            
    return interleaved

def get_merged_specs_from_df(df, config, period_start, period_offset):
    """Reusable logic to convert a filtered DataFrame or single-row Series into merged clip specifications."""
    # Ensure we handle both single events (Series) and multiple events (DataFrame)
    if isinstance(df, pd.Series):
        df = df.to_frame().T
    
    # Ensure resolved_period exists for sorting and processing
    if "resolved_period" not in df.columns:
        if "period" in df.columns:
            # Map common Opta/WhoScored period strings to integers
            df["resolved_period"] = df["period"].map(PERIOD_MAP).fillna(1).astype(int)
        else:
            df["resolved_period"] = 1
        
    # Dynamic source detection for Multi-Match (Aggregate) data
    has_source_info = "_source_config_file" in df.columns
    config_cache = {}
    
    def get_source_data(row):
        if not has_source_info:
            return period_start, period_offset, config.get("video_file"), config.get("video2_file"), config.get("split_video"), None
        
        c_name = row["_source_config_file"]
        c_dir = row.get("_source_config_dir", "match_configs")
        ckey = (c_dir, c_name)
        
        if ckey not in config_cache:
            try:
                import json
                final_path = os.path.join(c_dir, c_name)
                with open(final_path, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
                
                v1 = c_data.get("video_path", "").strip().strip("\"'")
                v2 = c_data.get("video2_path", "").strip().strip("\"'")
                split = c_data.get("ui_split_video", False)
                p_start = {
                    1: to_seconds(c_data.get("ui_half1", "0:00")),
                    2: to_seconds(c_data.get("ui_half2", "0:00")),
                }
                if c_data.get("ui_half3"): p_start[3] = to_seconds(c_data["ui_half3"])
                if c_data.get("ui_half4"): p_start[4] = to_seconds(c_data["ui_half4"])
                p_offset = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0)}
                
                config_cache[ckey] = (p_start, p_offset, v1, v2, split, c_name)
            except:
                config_cache[ckey] = (period_start, period_offset, config.get("video_file"), config.get("video2_file"), config.get("split_video"), c_name)
        
        return config_cache[ckey]

    # Re-calculate video timestamps using match-specific timings
    video_timestamps = []
    source_videos = []
    
    for _, row in df.iterrows():
        try:
            p_s, p_o, v1, v2, split, _ = get_source_data(row)
            period = int(row["resolved_period"])
            
            ts = match_clock_to_video_time(
                int(row["minute"]), int(row["second"]),
                period, p_s, p_o
            )
            video_timestamps.append(ts)
            
            # Determine which file to use for this period
            if split and v2 and period >= 2:
                source_videos.append(v2)
            else:
                source_videos.append(v1)
        except Exception:
            video_timestamps.append(None)
            source_videos.append(None)
            
    df = df.copy()
    df["video_timestamp"] = video_timestamps
    df["_clip_src"] = source_videos
    # Important: sort by match and period to keep merging logical
    sort_cols = ["_source_config_file", "resolved_period", "video_timestamp"] if has_source_info else ["resolved_period", "video_timestamp"]
    df = df.dropna(subset=["video_timestamp", "_clip_src"]).sort_values(sort_cols)
    
    raw_windows = []
    for _, row in df.iterrows():
        ts = row["video_timestamp"]
        period = int(row["resolved_period"])
        
        p_name = str(row["name"]) if "name" in row and pd.notna(row["name"]) else ""
        opp_team = str(row["oppositionTeamName"]) if "oppositionTeamName" in row and pd.notna(row["oppositionTeamName"]) else ""
        action_team = str(row["teamName"]) if "teamName" in row and pd.notna(row["teamName"]) else \
                      str(row["team"]) if "team" in row and pd.notna(row["team"]) else ""
        
        label_parts = [row['type']]
        if p_name: label_parts.append(f"({p_name})")
        
        t_gap = row.get("time_gap", 0)
        threshold = config.get("replay_gap_threshold", 0)
        is_gap_event = threshold > 0 and t_gap >= threshold
        
        if is_gap_event:
            win_start = ts - t_gap - 0.5
            win_end = ts + 0.5
            display_label = f"🎬 REPLAY (Gap {int(t_gap)}s) before {row['type']} @ {int(row['minute'])}:{int(row['second']):02d}"
        else:
            win_start = ts - config["before_buffer"]
            win_end = ts + config["after_buffer"]
            display_label = f"{' '.join(label_parts)} @ {int(row['minute'])}:{int(row['second']):02d} (P{period})"
            
        raw_windows.append({
            "window": (win_start, win_end),
            "label": display_label,
            "period": period,
            "player": p_name,
            "action_team": action_team,
            "opposition_team": opp_team,
            "type": row['type'],
            "x": row.get("x"),
            "y": row.get("y"),
            "endX": row.get("endX"),
            "endY": row.get("endY"),
            "src": row["_clip_src"],
            "match_id": row.get("_source_config_file", "global")
        })

    def merge_logic(raw_items, min_gap):
        if not raw_items: return []
        first = raw_items[0]
        merged = [{
            "start": first["window"][0],
            "end": first["window"][1],
            "label": first["label"],
            "period": first["period"],
            "players": {first["player"]} if first["player"] else set(),
            "action_teams": {first["action_team"]} if first["action_team"] else set(),
            "opposition_teams": {first["opposition_team"]} if first["opposition_team"] else set(),
            "types": [first["type"]],
            "first_x": first.get("x"), "first_y": first.get("y"),
            "last_x": first.get("x"), "last_y": first.get("y"),
            "last_endX": first.get("endX"), "last_endY": first.get("endY"),
            "last_type": first["type"],
            "src": first["src"],
            "match_id": first["match_id"]
        }]
        for item in raw_items[1:]:
            prev = merged[-1]
            start, end = item["window"]
            # Only merge if same match/source AND same period
            if start <= prev["end"] + min_gap and item["period"] == prev["period"] and item["match_id"] == prev["match_id"]:
                prev["end"] = max(prev["end"], end)
                if item["player"] and item["player"] not in prev["players"]:
                    prev["players"].add(item["player"])
                    prev["label"] = prev["label"] + " + " + item["player"]
                prev["types"].append(item["type"])
                # Update positions
                prev["last_x"], prev["last_y"] = item.get("x"), item.get("y")
                prev["last_endX"], prev["last_endY"] = item.get("endX"), item.get("endY")
            else:
                merged.append({
                    "start": start, "end": end, "label": item["label"], "period": item["period"],
                    "players": {item["player"]} if item["player"] else set(),
                    "action_teams": {item["action_team"]} if item["action_team"] else set(),
                    "opposition_teams": {item["opposition_team"]} if item["opposition_team"] else set(),
                    "types": [item["type"]],
                    "first_x": item.get("x"), "first_y": item.get("y"),
                    "last_x": item.get("x"), "last_y": item.get("y"),
                    "last_endX": item.get("endX"), "last_endY": item.get("endY"),
                    "last_type": item["type"],
                    "src": item["src"],
                    "match_id": item["match_id"]
                })
        return merged

    return merge_logic(raw_windows, config.get("min_clip_gap", 0.5))

def apply_filters(df, config):
    """Apply xT, progressive, and action type filters."""
    original = len(df)
    full_df_context = df.copy() # Keep for cross-event filters like One-Two
    df = df.copy()

    # Detect coordinate scaling BEFORE filtering anything
    # (Checking on the full DF is more reliable to see the range)
    has_xs = "x" in df.columns and "y" in df.columns
    has_xe = "endX" in df.columns and "endY" in df.columns
    
    scale_factor_x = 1.0
    scale_factor_y = 1.0
    if has_xs:
        xs_raw = pd.to_numeric(df["x"], errors="coerce")
        if not xs_raw.empty and xs_raw.max() <= 101:
            scale_factor_x = 1.05
            scale_factor_y = 0.68
    
    # Pre-calculate scaled coordinates for all filters (Global & local)
    if has_xs:
        df["_xs"] = pd.to_numeric(df["x"], errors="coerce").fillna(0) * scale_factor_x
        df["_ys"] = pd.to_numeric(df["y"], errors="coerce").fillna(0) * scale_factor_y
    if has_xe:
        df["_xe"] = pd.to_numeric(df["endX"], errors="coerce").fillna(0) * scale_factor_x
        df["_ye"] = pd.to_numeric(df["endY"], errors="coerce").fillna(0) * scale_factor_y


    # 0. Whitelist ID filter (Primary filter if coming from Aggregate UI)
    if config.get("whitelist_ids"):
        ids = config["whitelist_ids"]
        if isinstance(ids, list) and len(ids) > 0:
            df = df[df["id"].isin(ids)]

    # Action type filter
    if config.get("filter_types"):
        selected = config["filter_types"]
        if selected:
            df = df[df["type"].isin(selected)]

    # Logique d'action suivante (Deep filtering)
    if config.get("filter_next_actions"):
        selected_next = config["filter_next_actions"]
        if selected_next:
            if "next_action_type" in df.columns:
                df = df[df["next_action_type"].isin(selected_next)]
            else:
                # If column missing, no action can match a positive filter on it
                df = df.iloc[0:0]

    # Action type exclusions
    if config.get("exclude_types"):
        excluded = config["exclude_types"]
        if excluded:
            df = df[~df["type"].isin(excluded)]

    # Player filter
    if config.get("filter_players"):
        selected = config["filter_players"]
        if selected:
            p_col = "name" if "name" in df.columns else "playerName" if "playerName" in df.columns else None
            if p_col:
                df = df[df[p_col].fillna('Inconnu').isin(selected)]

    # Outcome filter
    if config.get("filter_outcomes") and "outcomeType" in df.columns:
        selected = config["filter_outcomes"]
        if selected:
            df = df[df["outcomeType"].isin(selected)]

    # Opponent filter
    if config.get("filter_opponents") and "oppositionPlayerName" in df.columns:
        selected = config["filter_opponents"]
        if selected:
            df = df[df["oppositionPlayerName"].isin(selected)]

    # Progressive actions filter
    if config.get("progressive_only"):
        prog_cols = [c for c in ["prog_pass", "prog_carry"] if c in df.columns]
        if prog_cols:
            mask = df[prog_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
            df = df[(mask > 0).any(axis=1)]

    # Prog pass min filter
    if config.get("prog_pass_min") and "prog_pass" in df.columns:
        min_val = config.get("prog_pass_min", 0)
        if min_val > 0:
            mask = pd.to_numeric(df["prog_pass"], errors="coerce").fillna(0)
            # Only filter out "Pass" if prog_pass is below threshold.
            df = df[(df["type"] != "Pass") | (mask >= min_val)]

    # Prog carry min filter
    if config.get("prog_carry_min") and "prog_carry" in df.columns:
        min_val = config.get("prog_carry_min", 0)
        if min_val > 0:
            mask = pd.to_numeric(df["prog_carry"], errors="coerce").fillna(0)
            # Only filter out "Carry" if prog_carry is below threshold.
            df = df[(df["type"] != "Carry") | (mask >= min_val)]

    # Carry speed min filter (> 10m)
    if config.get("carry_speed_min") and "carrySpeed_kmh" in df.columns:
        min_speed = config.get("carry_speed_min", 0)
        if min_speed > 0:
            mask = pd.to_numeric(df["carrySpeed_kmh"], errors="coerce").fillna(0)
            # Enforce distance > 10m by checking carry_distance or using the pre-calculated speed logic
            # Since speed is only calculated if time > 0, we also ensure we only pick valid carries.
            # We also ensure the carry length itself is >= 10 to match the user request.
            if "carry_distance" in df.columns:
                 distances = pd.to_numeric(df["carry_distance"], errors="coerce").fillna(0)
                 df = df[(df["type"] != "Carry") | ((mask >= min_speed) & (distances >= 10))]
            else:
                 df = df[(df["type"] != "Carry") | (mask >= min_speed)]

    # Min length filter
    if config.get("min_length") and config["min_length"] > 0:
        min_l = config["min_length"]
        is_pc = df["type"].isin(["Pass", "Carry"])
        
        has_col_length = "value_Length" in df.columns
        has_col_pass_length = "passLength" in df.columns
        has_coords = "x" in df.columns and "endX" in df.columns and "y" in df.columns and "endY" in df.columns
        
        if has_col_length:
            lengths = pd.to_numeric(df["value_Length"], errors="coerce").fillna(0)
            df = df[~is_pc | (lengths >= min_l)]
        elif has_col_pass_length:
            lengths = pd.to_numeric(df["passLength"], errors="coerce").fillna(0)
            df = df[~is_pc | (lengths >= min_l)]
        elif has_coords:
            x_m = df["x"].astype(float)
            y_m = df["y"].astype(float)
            ex_m = df["endX"].astype(float)
            ey_m = df["endY"].astype(float)
            
            mask_has_ends = df["endX"].notna() & df["endY"].notna()
            dist = pd.Series(0.0, index=df.index)
            dist[mask_has_ends] = ((x_m[mask_has_ends] - ex_m[mask_has_ends])**2 + (y_m[mask_has_ends] - ey_m[mask_has_ends])**2)**0.5
            
            # Use distance to filter only the passes and carries
            df = df[~is_pc | (mask_has_ends & (dist >= min_l))]

    # Sequence pass counts filter
    if config.get("seq_pass_min") and "seq_pass_count" in df.columns:
        if config["seq_pass_min"] > 0:
            mask = df["seq_pass_count"].fillna(0) >= config["seq_pass_min"]
            # Only filter out "Pass" if their sequence count is too low
            df = df[(df["type"] != "Pass") | mask]
            
    if config.get("seq_pass_max") and "seq_pass_count" in df.columns:
        if config["seq_pass_max"] > 0:
            mask = df["seq_pass_count"].fillna(0) <= config["seq_pass_max"]
            # Only filter out "Pass" if their sequence count is too high
            df = df[(df["type"] != "Pass") | mask]
            
    # Sequence Score filter
    if config.get("seq_score_min") and "seq_score" in df.columns:
        if config["seq_score_min"] > 0:
            mask = df["seq_score"].fillna(0) >= config["seq_score_min"]
            # Filter ANY event if its sequence score is below threshold
            df = df[mask]
            
    # Conceded Danger filter (Danger Subi)
    if config.get("seq_conceded_score_min") and "seq_conceded_score" in df.columns:
        if config["seq_conceded_score_min"] > 0:
            mask = df["seq_conceded_score"].fillna(0) >= config["seq_conceded_score_min"]
            df = df[mask]

    # Action Danger Score filter (note individuelle 0-10)
    if config.get("action_danger_score_min") and "action_danger_score" in df.columns:
        if config["action_danger_score_min"] > 0:
            mask = pd.to_numeric(df["action_danger_score"], errors="coerce").fillna(0) >= config["action_danger_score_min"]
            df = df[mask]




    # xT filter
    if config.get("xt_min") is not None and "xT" in df.columns:
        xt_min = config["xt_min"]
        if xt_min > 0:
            xt_values = pd.to_numeric(df["xT"], errors="coerce").fillna(0)
            # Only filter out "Pass" actions if their xT is below the threshold.
            # This ensures that non-passing actions (Shots, etc.) remain in the data.
            df = df[(df["type"] != "Pass") | (xt_values >= xt_min)]

    # Top N by xT
    if config.get("top_n") and "xT" in df.columns:
        n = config["top_n"]
        df = df.copy()
        df["_xt_num"] = pd.to_numeric(df["xT"], errors="coerce").fillna(0)
        
        if not config.get("progressive_only"):
            is_pass = df["type"] == "Pass"
            df_pass = df[is_pass].nlargest(n, "_xt_num")
            df_other = df[~is_pass]
            df = pd.concat([df_pass, df_other]).sort_index()
            df = df.drop(columns=["_xt_num"])
        else:
            df = df.nlargest(n, "_xt_num").drop(columns=["_xt_num"])

    # Position filter
    if config.get("filter_positions") and "mainPositionCategory" in df.columns:
        selected = config["filter_positions"]
        if selected:
            df = df[df["mainPositionCategory"].isin(selected)]

    # Position exclusion filter
    if config.get("exclude_positions") and "mainPositionCategory" in df.columns:
        excluded = config["exclude_positions"]
        if excluded:
            df = df[~df["mainPositionCategory"].isin(excluded)]

    # Receiver filter (for Passes)
    if config.get("filter_receivers"):
        selected = config["filter_receivers"]
        if selected:
            # We include the event if it's a pass to one of these players
            # OR if it's a Ball Receipt* event BY one of these players
            is_target_pass = (df["type"] == "Pass") & (df["receiver"].isin(selected))
            is_target_receipt = (df["type"] == "Ball Receipt*") & (df["name"].isin(selected))
            df = df[is_target_pass | is_target_receipt | (~df["type"].isin(["Pass", "Ball Receipt*"]))]
            # Note: The line above keeps other event types untouched by this specific filter. 
            # If the user also selected a Player filter, the combination is handled by the overall df reduction.

    # Advanced filters (Multi-group support)
    raw_groups = config.get("adv_filter_groups")
    # Robust normalization: support list of lists (legacy) or list of dicts (new)
    adv_groups = []
    if raw_groups and isinstance(raw_groups, list):
        for g in raw_groups:
            if isinstance(g, dict):
                adv_groups.append(g)
            elif isinstance(g, list):
                adv_groups.append({"filters": g, "and": config.get("adv_and_logic", False)})
    
    non_empty_groups = [g for g in adv_groups if g.get("filters")]
    
    if non_empty_groups:
        # OR logic between groups (Addition mode)
        final_mask = pd.Series(False, index=df.index)
        for group in non_empty_groups:
            cols = group.get("filters", [])
            use_and = group.get("and", False)
            
            if use_and:
                group_mask = pd.Series(True, index=df.index)
                for f_col in cols:
                    if f_col in df.columns:
                        v = df[f_col]
                        col_mask = (pd.to_numeric(v, errors="coerce").fillna(0) == 1) | (v == True) | (v.astype(str).str.lower() == 'true')
                        group_mask &= col_mask
                    else:
                        group_mask &= False
            else:
                group_mask = pd.Series(False, index=df.index)
                for f_col in cols:
                    if f_col in df.columns:
                        v = df[f_col]
                        col_mask = (pd.to_numeric(v, errors="coerce").fillna(0) == 1) | (v == True) | (v.astype(str).str.lower() == 'true')
                        group_mask |= col_mask
            
            # Apply per-group spatial filters (Local)
            for z_type in ["start", "end"]:
                z_list = group.get(z_type, [])
                if not z_list: continue
                
                # Dynamic coordinate check
                coord_prefix = "_xs" if z_type == "start" else "_xe"
                y_coord_prefix = "_ys" if z_type == "start" else "_ye"
                
                if coord_prefix in df.columns:
                    z_mask = pd.Series(False, index=df.index)
                    for zname in z_list:
                        z = FLAT_ZONES.get(zname)
                        if z:
                            z_mask |= (df[coord_prefix] >= z["x"][0]) & (df[coord_prefix] <= z["x"][1]) & \
                                      (df[y_coord_prefix] >= z["y"][0]) & (df[y_coord_prefix] <= z["y"][1])
                    group_mask &= z_mask
            
            final_mask |= group_mask
        df = df[final_mask]
    else:
        # Legacy flat list logic (Fall-back)
        adv_filters = config.get("advanced_filters", [])
        if adv_filters:
            # Check if AND logic is requested
            use_and = config.get("adv_and_logic", False)
            
            if use_and:
                mask = pd.Series(True, index=df.index)
                for f_col in adv_filters:
                    if f_col in df.columns:
                        # Robust check: handles booleans, strings "True", and float 1.0 from CSV
                        v = df[f_col]
                        col_mask = (pd.to_numeric(v, errors="coerce").fillna(0) == 1) | (v == True) | (v.astype(str).str.lower() == 'true')
                        mask &= col_mask
                    else:
                        mask &= False # missing column empty INTERSECTION
            else:
                mask = pd.Series(False, index=df.index)
                for f_col in adv_filters:
                    if f_col in df.columns:
                        v = df[f_col]
                        col_mask = (pd.to_numeric(v, errors="coerce").fillna(0) == 1) | (v == True) | (v.astype(str).str.lower() == 'true')
                        mask |= col_mask
                        
            if mask.any() or use_and: # Use_and might lead to empty df, which is correct
                df = df[mask]

    # Advanced filters exclusions
    exclude_adv_filters = config.get("exclude_adv_filters", [])
    if exclude_adv_filters:
        mask = pd.Series(False, index=df.index)
        for f_col in exclude_adv_filters:
            if f_col in df.columns:
                v = df[f_col]
                col_mask = (pd.to_numeric(v, errors="coerce").fillna(0) == 1) | (v == True) | (v.astype(str).str.lower() == 'true')
                mask |= col_mask
        if mask.any():
            df = df[~mask]

    # Team filter
    if config.get("filter_teams"):
        selected = config["filter_teams"]
        if selected:
            if "teamName" in df.columns:
                df = df[df["teamName"].isin(selected)]
            elif "team" in df.columns:
                df = df[df["team"].isin(selected)]

    # Opposition Team filter
    if config.get("filter_opposition_teams"):
        selected = config["filter_opposition_teams"]
        if selected:
            if "oppositionTeamName" in df.columns:
                df = df[df["oppositionTeamName"].isin(selected)]

    # Half filter (moved here for consistency with preview)
    half_sel = config.get("half_filter", "Both halves")
    if "resolved_period" in df.columns:
        if half_sel == "1st half only":
            df = df[df["resolved_period"] == 1]
        elif half_sel == "2nd half only":
            df = df[df["resolved_period"] == 2]

    # Zone filtering with two independent options:
    # 1) spatial_and_logic = "Intersection": AND between zones WITHIN the same list
    #    e.g. Start=[DEF_THIRD, LEFT_WING] => action must be in DEF_THIRD AND LEFT_WING (= the corner)
    # 2) spatial_and_cross = "Traversée": AND between Start list and End list
    #    e.g. Start must match AND End must match (instead of OR)
    spatial_intersect = config.get("spatial_and_logic", False)
    spatial_cross = config.get("spatial_and_cross", False)
    start_zones = config.get("filter_start_zones", [])
    end_zones = config.get("filter_end_zones", [])
    
    if (start_zones or end_zones):
        # --- START ZONES ---
        mask_any_start = pd.Series(True, index=df.index)
        if start_zones and "_xs" in df.columns:
            xs, ys = df["_xs"], df["_ys"]
            
            if spatial_intersect:
                # AND logic: action must be in ALL selected zones simultaneously
                mask_s = pd.Series(True, index=df.index)
                for zname in start_zones:
                    z = FLAT_ZONES.get(zname)
                    if z:
                        mask_s &= (xs >= z["x"][0]) & (xs <= z["x"][1]) & \
                                  (ys >= z["y"][0]) & (ys <= z["y"][1])
            else:
                # OR logic: action must be in ANY of the selected zones
                mask_s = pd.Series(False, index=df.index)
                for zname in start_zones:
                    z = FLAT_ZONES.get(zname)
                    if z:
                        mask_s |= (xs >= z["x"][0]) & (xs <= z["x"][1]) & \
                                  (ys >= z["y"][0]) & (ys <= z["y"][1])
            mask_any_start = mask_s
            
        # --- END ZONES ---
        mask_any_end = pd.Series(True, index=df.index)
        if end_zones and "_xe" in df.columns:
            valid_ends = df["endX"].notna() & df["endY"].notna()
            xe, ye = df["_xe"], df["_ye"]
            
            if spatial_intersect:
                # AND logic within end zones
                mask_e = pd.Series(True, index=df.index)
                for zname in end_zones:
                    z = FLAT_ZONES.get(zname)
                    if z:
                        mask_e &= (xe >= z["x"][0]) & (xe <= z["x"][1]) & \
                                  (ye >= z["y"][0]) & (ye <= z["y"][1])
            else:
                # OR logic within end zones
                mask_e = pd.Series(False, index=df.index)
                for zname in end_zones:
                    z = FLAT_ZONES.get(zname)
                    if z:
                        mask_e |= (xe >= z["x"][0]) & (xe <= z["x"][1]) & \
                                  (ye >= z["y"][0]) & (ye <= z["y"][1])
            mask_any_end = valid_ends & mask_e

        # --- COMBINE Start & End ---
        if start_zones and end_zones:
            if spatial_cross:
                # Traversée: must match Start AND End
                df = df[mask_any_start & mask_any_end]
            else:
                # Default: matches Start OR End
                df = df[mask_any_start | mask_any_end]
        elif start_zones:
            df = df[mask_any_start]
        elif end_zones:
            df = df[mask_any_end]

    # Shot Goal Zones filter
    if config.get("filter_shot_goal_zones") and "shot_goal_zone" in df.columns:
        selected = config["filter_shot_goal_zones"]
        if selected:
            is_shot = df["type"].str.contains("Shot|Goal", case=False, na=False)
            df = df[(~is_shot) | df["shot_goal_zone"].isin(selected)]
            
    # Shot Distance filter
    if config.get("shot_distance_min") and "shot_distance" in df.columns:
        d_min = config["shot_distance_min"]
        if d_min > 0:
            is_shot = df["type"].str.contains("Shot|Goal", case=False, na=False)
            mask = pd.to_numeric(df["shot_distance"], errors="coerce").fillna(0)
            df = df[(~is_shot) | (mask >= d_min)]
            
    if config.get("shot_distance_max") and "shot_distance" in df.columns:
        d_max = config["shot_distance_max"]
        if d_max > 0:
            is_shot = df["type"].str.contains("Shot|Goal", case=False, na=False)
            mask = pd.to_numeric(df["shot_distance"], errors="coerce").fillna(0)
            df = df[(~is_shot) | (mask <= d_max)]

    # One-Two filters
    if "oneTwoStatus" in df.columns or "one_two_initiator" in df.columns:
        ot_min_score_val = float(config.get("ot_min_score", 0))
        ot_min_score_active = config.get("ot_min_score") is not None and ot_min_score_val > 0
        ot_active = (config.get("filter_one_two_initiators") or config.get("filter_one_two_returners") or
                     config.get("ot_init_prog") or config.get("ot_init_xt") or
                     config.get("ot_ret_prog") or config.get("ot_ret_xt") or
                     ot_min_score_active)
        
        if ot_active:
            if ot_min_score_active:
                print(f"[DEBUG] One-Two Note Filter Active: >= {ot_min_score_val}")
                try:
                    log_queue.put({"type": "log", "msg": f"?? Filtrage Note One-Two : >= {ot_min_score_val}"})
                except: pass

            # 1. Vectorized Pre-filters
            if ot_min_score_active and "one_two_score" in df.columns:
                is_ot = pd.Series(False, index=df.index)
                if "oneTwoStatus" in df.columns:
                    is_ot |= df["oneTwoStatus"].notna()
                if "adv_ONE_TWO" in df.columns:
                    is_ot |= (df["adv_ONE_TWO"] == True)
                
                series_score = pd.to_numeric(df["one_two_score"], errors="coerce").fillna(0)
                df = df[~is_ot | (series_score >= ot_min_score_val)]

            if config.get("filter_one_two_initiators") and "one_two_initiator" in df.columns:
                df = df[df["one_two_initiator"].isna() | df["one_two_initiator"].isin(config["filter_one_two_initiators"])]
            
            if config.get("filter_one_two_returners") and "one_two_returner" in df.columns:
                df = df[df["one_two_returner"].isna() | df["one_two_returner"].isin(config["filter_one_two_returners"])]
            
            # 2. Strict Pair Validation
            if "oneTwoStatus" in df.columns and "one_two_target_id" in df.columns:
                mask_has_ot = df["oneTwoStatus"].isin(["initiator", "return"])
                if mask_has_ot.any():
                    pair_filters_active = (config.get("ot_init_prog") or config.get("ot_init_xt") or
                                         config.get("ot_ret_prog") or config.get("ot_ret_xt"))
                    
                    if pair_filters_active:
                        ot_pool = full_df_context[full_df_context["oneTwoStatus"].notna()].copy()
                        
                        def validate_ot_pair(row, pool, cfg):
                            status = row.get("oneTwoStatus")
                            ts = row["cumulative_mins"]
                            init_name = row.get("one_two_initiator")
                            ret_name = row.get("one_two_returner")
                            
                            if status == "initiator":
                                match = pool[(pool["oneTwoStatus"] == "return") & 
                                             (pool["one_two_initiator"] == init_name) &
                                             (pool["one_two_returner"] == ret_name) &
                                             (pool["cumulative_mins"] > ts) &
                                             (pool["cumulative_mins"] < ts + 0.2)]
                                init_row, ret_row = row, (match.iloc[0] if not match.empty else None)
                            else:
                                match = pool[(pool["oneTwoStatus"] == "initiator") & 
                                             (pool["one_two_initiator"] == init_name) &
                                             (pool["one_two_returner"] == ret_name) &
                                             (pool["cumulative_mins"] < ts) &
                                             (pool["cumulative_mins"] > ts - 0.2)]
                                init_row, ret_row = (match.iloc[0] if not match.empty else None), row
                            
                            if init_row is None or ret_row is None: return False
                            
                            if cfg.get("ot_init_prog") and float(init_row.get("prog_pass", 0)) < cfg["ot_init_prog"]: return False
                            if cfg.get("ot_init_xt") and float(init_row.get("xT", 0)) < cfg["ot_init_xt"]: return False
                            if cfg.get("ot_ret_prog") and float(ret_row.get("prog_pass", 0)) < cfg["ot_ret_prog"]: return False
                            if cfg.get("ot_ret_xt") and float(ret_row.get("xT", 0)) < cfg["ot_ret_xt"]: return False
                            return True

                        ot_candidates = df[mask_has_ot]
                        valid_mask = ot_candidates.apply(lambda r: validate_ot_pair(r, ot_pool, config), axis=1)
                        df = pd.concat([df[~mask_has_ot], ot_candidates[valid_mask]]).sort_index()
                    else:
                        mask_ot_to_check = df["oneTwoStatus"].isin(["initiator", "return"])
                        ot_pool_indices = set(df.index)
                        
                        final_valid_indices = set()
                        for idx, row in df[mask_ot_to_check].iterrows():
                            partner_idx = row.get("one_two_target_id")
                            if partner_idx in ot_pool_indices:
                                final_valid_indices.add(idx)
                                final_valid_indices.add(partner_idx)
                        
                        df = df[~mask_ot_to_check | df.index.isin(final_valid_indices)]

    # Dynamic Gap / Replay filter
    if config.get("replay_gap_threshold"):
        threshold = config["replay_gap_threshold"]
        if threshold > 0 and "time_gap" in df.columns:
            # We filter for events that happen AFTER a long gap
            df = df[df["time_gap"] >= threshold]

    return df, original - len(df)

# =============================================================================
# FFmpeg HELPERS (EXTRACTED)
# =============================================================================

def get_ffmpeg_binary():
    """Get the FFmpeg binary path — from PATH or MoviePy's bundled copy."""
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
    raise ValueError("FFmpeg not found. Please ensure FFmpeg is installed.")

def get_video_duration(path, ffmpeg_bin):
    """Get video duration in seconds using ffmpeg -i stderr output."""
    import subprocess, re
    
    # If it's a URL, we need to be careful, but we'll usually have downloaded it by now
    r = subprocess.run(
        [ffmpeg_bin, "-i", path],
        capture_output=True, text=True
    )
    output = r.stdout + r.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", output)
    if not m:
        # Fallback for some remote streams or weird headers
        return 0
    return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))

def download_google_drive_video(url, dest_folder="temp_drive_videos"):
    """
    Downloads a Google Drive video locally for efficient FFmpeg clipping.
    Returns the local path.
    """
    os.makedirs(dest_folder, exist_ok=True)
    
    # Extract file ID
    file_id = ""
    if "id=" in url:
        file_id = url.split("id=")[1].split("&")[0]
    elif "/d/" in url:
        file_id = url.split("/d/")[1].split("/")[0]
    
    if not file_id:
        return url # Not a GDrive link or already local

    local_path = os.path.join(dest_folder, f"{file_id}.mp4")
    
    if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
        return local_path # Already downloaded

    print(f"📥 Downloading Google Drive video (ID: {file_id})...")
    
    def get_confirm_token(response):
        for key, value in response.cookies.items():
            if key.startswith('download_warning'):
                return value
        return None

    def save_response_content(response, destination):
        CHUNK_SIZE = 32768
        with open(destination, "wb") as f:
            for chunk in response.iter_content(CHUNK_SIZE):
                if chunk: # filter out keep-alive new chunks
                    f.write(chunk)

    URL = "https://docs.google.com/uc?export=download"
    session = requests.Session()
    response = session.get(URL, params={'id': file_id}, stream=True)
    token = get_confirm_token(response)

    if token:
        params = {'id': file_id, 'confirm': token}
        response = session.get(URL, params=params, stream=True)

    save_response_content(response, local_path)
    return local_path

def cut_clip_ffmpeg(ffmpeg_bin, src_path, start, end, out_path, custom_text_options=None, crop_params=None):
    """Cut a clip directly with FFmpeg — bypasses MoviePy entirely.
    Uses stream copy for speed when possible, falls back to re-encode."""
    import subprocess
    duration = end - start
    # -map 0:v:0 -map 0:a:0 picks first video and first audio stream
    # -avoid_negative_ts make_zero fixes timestamp issues in .mkv files
    
    if custom_text_options and custom_text_options.get("text"):
        opts = custom_text_options
        txt = opts["text"].replace("'", "'\\''").replace(":", "\\:")
        size = opts.get("size", 36)
        op = opts.get("opacity", 1.0)
        
        # FFmpeg Color: [0x|#]RRGGBB[AA] - Using AA hex for alpha is more stable than @
        alpha_hex = f"{int(op * 255):02x}"
        font_color = f"0x{opts.get('color', 'FFFFFF')}{alpha_hex}"
        
        bg_on = 1 if opts.get("bg", True) else 0
        bg_op = opts.get("bg_opacity", 0.6)
        bg_alpha_hex = f"{int(bg_op * 255):02x}"
        bg_color = f"0x000000{bg_alpha_hex}"
        
        # Font path resolution
        if platform.system() == "Windows":
            font_map = {
                "Arial": "C\:/Windows/Fonts/arial.ttf",
                "Verdana": "C\:/Windows/Fonts/verdana.ttf",
                "Tahoma": "C\:/Windows/Fonts/tahoma.ttf",
                "Courier New": "C\:/Windows/Fonts/cour.ttf",
                "Consolas": "C\:/Windows/Fonts/consola.ttf",
                "Impact": "C\:/Windows/Fonts/impact.ttf"
            }
            font_path = font_map.get(opts.get("font", "Arial"), "C\:/Windows/Fonts/arial.ttf")
        else:
            # Common Linux font paths (Ubuntu/Debian)
            font_map = {
                "Arial": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "Verdana": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "Tahoma": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "Courier New": "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
                "Consolas": "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
                "Impact": "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
            }
            # Fallback to a generic font if specific ones aren't installed
            font_path = font_map.get(opts.get("font", "Arial"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
            if not os.path.exists(font_path):
                font_path = "DejaVuSans" # Let FFmpeg try to find it by name
        
        vf_arg = f"drawtext=fontfile='{font_path}':text='{txt}':x=(w-text_w)/2:y=h-th-40:fontsize={size}:fontcolor={font_color}:box={bg_on}:boxcolor={bg_color}:boxborderw=8"
    else:
        vf_arg = None
    
    # Crop logic: crop=w:h:x:y
    crop_filter = None
    if crop_params:
        # Assuming streamlit-cropper Image object properties or dict. 
        # Box is often (left, top, right, bottom) in PIL or similar.
        # If we passed the cropped image, we need to know its relative box.
        # Let's assume we pass a dict or have to handle the Image return of st_cropper.
        try:
            # If Box/Image object, we might need to extract coords.
            # For FFmpeg we need w, h, x, y. 
            # If crop_params has 'left', etc.
            if isinstance(crop_params, dict):
                w = int(crop_params.get('width', 0))
                h = int(crop_params.get('height', 0))
                x = int(crop_params.get('left', 0))
                y = int(crop_params.get('top', 0))
                if w > 0 and h > 0:
                    crop_filter = f"crop={w}:{h}:{x}:{y}"
        except:
            pass

    # STANDARDIZATION: To allow merging clips from DIFFERENT matches (resolutions/fps/audio), 
    # we force a standard 1080p 30fps YUV420 format and 44.1k Stereo AAC.
    standard_vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    
    # Combine filters
    filters = []
    if crop_filter: filters.append(crop_filter)
    if vf_arg: filters.append(vf_arg)
    filters.append(standard_vf)
    
    final_vf = ",".join(filters)
        
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss", str(start),
        "-i", src_path,
        "-t", str(duration),
        "-map", "0:v:0",
        "-map", "0:a:0?",   # optional audio — won't fail if missing
        "-vf", final_vf,
        "-r", "30",         # Force 30fps for stability in concat
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        "-ar", "44100",     # Standardize audio sample rate
        "-ac", "2",         # Standardize to Stereo
        "-avoid_negative_ts", "make_zero",
        out_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError(f"FFmpeg error cutting clip: {result.stderr[-500:]}")

def cut_and_concat_ffmpeg(ffmpeg_bin, clip_specs, out_path, progress_queue, start_time, custom_text_options=None, crop_params=None):
    """Cut all clips and concatenate using FFmpeg concat demuxer."""
    import subprocess, tempfile
    tmp_dir = tempfile.mkdtemp()
    tmp_files = []
    total = len(clip_specs)

    from concurrent.futures import ThreadPoolExecutor
    
    def process_clip(args):
        i, spec = args
        if isinstance(spec, dict):
            src, start, end = spec["src"], spec["start"], spec["end"]
        elif len(spec) >= 4:
            src, start, end, _type = spec
        else:
            src, start, end = spec
            
        tmp_path = os.path.join(tmp_dir, f"part_{i:04d}.mp4")
        cut_clip_ffmpeg(ffmpeg_bin, src, start, end, tmp_path, custom_text_options, crop_params)
        
        elapsed = time.time() - start_time
        progress_queue.put({"current": i, "total": total, "elapsed": elapsed, "phase": "clips"})
        return tmp_path

    # Parallelize the cutting phase with 8 workers
    with ThreadPoolExecutor(max_workers=8) as executor:
        tmp_files = list(executor.map(process_clip, enumerate(clip_specs, 1)))

    # Write concat list
    list_path = os.path.join(tmp_dir, "concat.txt")
    with open(list_path, "w") as f:
        for p in tmp_files:
            f.write(f"file '{p}'\n")

    # Concatenate
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError(f"FFmpeg concat error: {result.stderr[-500:]}")

    # Cleanup
    for p in tmp_files:
        try: os.remove(p)
        except: pass
    try: os.remove(list_path)
    except: pass
    try: os.rmdir(tmp_dir)
    except: pass


def export_to_premiere_xml(clip_specs, out_path, fps=30):
    """
    Generate a Final Cut Pro XML (FCP XML) file for Adobe Premiere Pro.
    Allows users to import the cuts directly onto their timeline.
    """
    import os
    import xml.etree.ElementTree as ET
    from xml.dom import minidom
    from urllib.parse import quote
    
    seq_name = os.path.basename(out_path).replace(".xml", "")
    
    # --- Pre-calculate total duration ---
    total_frames = 0
    parsed_clips = []
    for spec in clip_specs:
        if isinstance(spec, dict):
            src, start_s, end_s = spec["src"], spec["start"], spec["end"]
            clip_type = spec.get("type", "Unknown")
        elif len(spec) >= 4:
            src, start_s, end_s, clip_type = spec
        else:
            src, start_s, end_s = spec
            clip_type = "Unknown"
        dur_s = end_s - start_s
        if dur_s <= 0: continue
        f_in = int(round(start_s * fps))
        f_out = int(round(end_s * fps))
        parsed_clips.append((src, f_in, f_out, clip_type))
        total_frames += (f_out - f_in)
    
    # --- Build file ID map: unique source path -> unique ID ---
    file_id_map = {}
    file_defined = set()  # Track which file IDs have been fully defined
    for src, _, _, _ in parsed_clips:
        abs_src = os.path.abspath(src).replace("\\", "/")
        if abs_src not in file_id_map:
            file_id_map[abs_src] = f"file-{len(file_id_map)+1}"
    
    def make_pathurl(abs_path):
        """Create a proper file:/// URL with encoded special characters."""
        if platform.system() == "Windows":
            # Split drive letter from rest
            if len(abs_path) >= 2 and abs_path[1] == ':':
                drive = abs_path[0:2]  # e.g. "D:"
                rest = abs_path[2:]
            else:
                drive = ""
                rest = abs_path
            
            # Encode each path component separately (preserve / separators)
            parts = rest.split("/")
            encoded_parts = [quote(p, safe="") for p in parts]
            encoded_path = "/".join(encoded_parts)
            return f"file://localhost/{drive}{encoded_path}"
        else:
            # Linux paths start with "/"
            parts = abs_path.split("/")
            encoded_parts = [quote(p, safe="") for p in parts]
            encoded_path = "/".join(encoded_parts)
            return f"file://localhost{encoded_path}"
    
    def add_file_element(parent, file_id, abs_src, basename):
        """Add a <file> element. Full definition on first use, reference-only after."""
        if file_id in file_defined:
            # Just reference by ID, no children
            ET.SubElement(parent, "file", id=file_id)
        else:
            # First occurrence: full definition
            file_defined.add(file_id)
            f_node = ET.SubElement(parent, "file", id=file_id)
            ET.SubElement(f_node, "name").text = basename
            ET.SubElement(f_node, "pathurl").text = make_pathurl(abs_src)
            ET.SubElement(f_node, "duration").text = str(int(24 * 3600 * fps))
            f_rate = ET.SubElement(f_node, "rate")
            ET.SubElement(f_rate, "timebase").text = str(fps)
            ET.SubElement(f_rate, "ntsc").text = "FALSE"
            f_media = ET.SubElement(f_node, "media")
            f_video = ET.SubElement(f_media, "video")
            ET.SubElement(f_video, "duration").text = str(int(24 * 3600 * fps))
            f_audio = ET.SubElement(f_media, "audio")
            ET.SubElement(f_audio, "channelcount").text = "2"
    
    # --- Root ---
    xmeml = ET.Element("xmeml", version="4")
    
    project = ET.SubElement(xmeml, "project")
    ET.SubElement(project, "name").text = seq_name
    children = ET.SubElement(project, "children")
    
    sequence = ET.SubElement(children, "sequence", id="sequence-1")
    ET.SubElement(sequence, "name").text = seq_name
    ET.SubElement(sequence, "duration").text = str(total_frames)
    
    s_rate = ET.SubElement(sequence, "rate")
    ET.SubElement(s_rate, "timebase").text = str(fps)
    ET.SubElement(s_rate, "ntsc").text = "FALSE"
    
    # Timecode
    tc = ET.SubElement(sequence, "timecode")
    tc_rate = ET.SubElement(tc, "rate")
    ET.SubElement(tc_rate, "timebase").text = str(fps)
    ET.SubElement(tc_rate, "ntsc").text = "FALSE"
    ET.SubElement(tc, "string").text = "00:00:00:00"
    ET.SubElement(tc, "frame").text = "0"
    ET.SubElement(tc, "displayformat").text = "NDF"
    
    media = ET.SubElement(sequence, "media")
    
    # --- Video ---
    video = ET.SubElement(media, "video")
    
    # Video format
    v_format = ET.SubElement(video, "format")
    v_sc = ET.SubElement(v_format, "samplecharacteristics")
    ET.SubElement(v_sc, "width").text = "1920"
    ET.SubElement(v_sc, "height").text = "1080"
    ET.SubElement(v_sc, "anamorphic").text = "FALSE"
    ET.SubElement(v_sc, "pixelaspectratio").text = "square"
    ET.SubElement(v_sc, "fielddominance").text = "none"
    sc_rate = ET.SubElement(v_sc, "rate")
    ET.SubElement(sc_rate, "timebase").text = str(fps)
    ET.SubElement(sc_rate, "ntsc").text = "FALSE"
    
    v_track = ET.SubElement(video, "track")
    
    # --- Audio ---
    audio = ET.SubElement(media, "audio")
    
    a_format = ET.SubElement(audio, "format")
    a_sc = ET.SubElement(a_format, "samplecharacteristics")
    ET.SubElement(a_sc, "depth").text = "16"
    ET.SubElement(a_sc, "samplerate").text = "48000"
    
    a_track1 = ET.SubElement(audio, "track")
    
    # --- Populate clips ---
    current_frame = 0
    
    def get_color_for_type(c_type):
        c_type = str(c_type).lower()
        if "but" in c_type or "goal" in c_type: return "Rose"
        if "passe" in c_type or "pass" in c_type: return "Cerulean"
        if "tir" in c_type or "shot" in c_type: return "Mango"
        if "duel" in c_type or "tackle" in c_type: return "Purple"
        if "faute" in c_type or "foul" in c_type: return "Lavender"
        if "dribble" in c_type or "carry" in c_type: return "Caribbean"
        if "interception" in c_type or "recover" in c_type: return "Yellow"
        return "Forest"
    
    for i, (src, f_in, f_out, clip_type) in enumerate(parsed_clips, 1):
        f_dur = f_out - f_in
        f_start = current_frame
        f_end = current_frame + f_dur
        
        abs_src = os.path.abspath(src).replace("\\", "/")
        file_id = file_id_map[abs_src]
        basename = os.path.basename(src)
        
        # --- Video clipitem ---
        v_clip = ET.SubElement(v_track, "clipitem", id=f"clipitem-{i}")
        ET.SubElement(v_clip, "masterclipid").text = f"masterclip-{file_id}"
        ET.SubElement(v_clip, "name").text = basename
        ET.SubElement(v_clip, "duration").text = str(int(24 * 3600 * fps))
        v_rate = ET.SubElement(v_clip, "rate")
        ET.SubElement(v_rate, "timebase").text = str(fps)
        ET.SubElement(v_rate, "ntsc").text = "FALSE"
        ET.SubElement(v_clip, "in").text = str(f_in)
        ET.SubElement(v_clip, "out").text = str(f_out)
        ET.SubElement(v_clip, "start").text = str(f_start)
        ET.SubElement(v_clip, "end").text = str(f_end)
        
        add_file_element(v_clip, file_id, abs_src, basename)
        
        v_labels = ET.SubElement(v_clip, "labels")
        ET.SubElement(v_labels, "label2").text = get_color_for_type(clip_type)
        
        # Link video
        link1 = ET.SubElement(v_clip, "link")
        ET.SubElement(link1, "linkclipref").text = f"clipitem-{i}"
        ET.SubElement(link1, "mediatype").text = "video"
        ET.SubElement(link1, "trackindex").text = "1"
        ET.SubElement(link1, "clipindex").text = str(i)
        
        link2 = ET.SubElement(v_clip, "link")
        ET.SubElement(link2, "linkclipref").text = f"clipitem-{i}a1"
        ET.SubElement(link2, "mediatype").text = "audio"
        ET.SubElement(link2, "trackindex").text = "1"
        ET.SubElement(link2, "clipindex").text = str(i)
        
        # --- Audio clipitems ---
        for a_idx, a_track in enumerate([a_track1], 1):
            a_clip = ET.SubElement(a_track, "clipitem", id=f"clipitem-{i}a{a_idx}")
            ET.SubElement(a_clip, "masterclipid").text = f"masterclip-{file_id}"
            ET.SubElement(a_clip, "name").text = basename
            ET.SubElement(a_clip, "duration").text = str(int(24 * 3600 * fps))
            a_rate = ET.SubElement(a_clip, "rate")
            ET.SubElement(a_rate, "timebase").text = str(fps)
            ET.SubElement(a_rate, "ntsc").text = "FALSE"
            ET.SubElement(a_clip, "in").text = str(f_in)
            ET.SubElement(a_clip, "out").text = str(f_out)
            ET.SubElement(a_clip, "start").text = str(f_start)
            ET.SubElement(a_clip, "end").text = str(f_end)
            
            add_file_element(a_clip, file_id, abs_src, basename)
            
            a_labels = ET.SubElement(a_clip, "labels")
            ET.SubElement(a_labels, "label2").text = get_color_for_type(clip_type)
            
            ET.SubElement(a_clip, "sourcetrack").text = str(a_idx)
        
        current_frame += f_dur

    # --- Write XML ---
    xml_str = ET.tostring(xmeml, encoding="utf-8", xml_declaration=True)
    reparsed = minidom.parseString(xml_str)
    pretty_xml = reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode("UTF-8")
    
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(pretty_xml)


def run_clip_maker(config, log_queue, progress_queue):
    from concurrent.futures import ThreadPoolExecutor
    def log(msg):
        log_queue.put({"type": "log", "msg": msg})
    
    log("🚀 CLIPMAKER PROCESS STARTED")
    def prog(current, total, elapsed):
        progress_queue.put({"current": current, "total": total, "elapsed": elapsed})

    try:
        if config.get("opta_df") is not None:
            df = config["opta_df"]
            # Rename playerName to name for consistency with your previous changes if needed, 
            # though my apply_filters now handles playerName
            if "playerName" in df.columns and "name" not in df.columns:
                df = df.rename(columns={"playerName": "name"})
        else:
            df = pd.read_csv(config["data_file"])
            
        # Extract match date if available (from timeStamp column)
        match_date = ""
        if "timeStamp" in df.columns and not df.empty:
            raw_ts = str(df["timeStamp"].iloc[0])
            # Get YYYY-MM-DD and ensure it's safe for filenames
            match_date = raw_ts.split(" ")[0].split("T")[0].replace("/", "-").replace(":", "-")

        for col in ["minute", "second", "type"]:
            if col not in df.columns:
                raise ValueError(f"CSV missing column: '{col}'")

        split_video = config.get("split_video", False)

        # In split mode each period's timestamp is relative to its own file.
        # period_start stores kick-off position within each file.
        # In single-file mode period_start stores position in the one file.
        period_start = {
            1: to_seconds(config["half1_time"]),
            2: to_seconds(config["half2_time"]),
        }
        if config["half3_time"].strip():
            period_start[3] = to_seconds(config["half3_time"])
        if config["half4_time"].strip():
            period_start[4] = to_seconds(config["half4_time"])

        # In split mode: each file starts from its own clock zero.
        # Period offset is always the match clock at kick-off of that period.
        # In single-file mode: period_start already accounts for the global offset.
        if split_video:
            # Each file is independent — period offset is match clock at KO
            period_offset = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0)}
        else:
            period_offset = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0)}

        fallback = config["fallback_row"]
        period_col = config["period_column"] or None
        df = assign_periods(df, period_col, fallback)

        # Determiner si on doit entrelacer les sélecteurs
        raw_groups = config.get("adv_filter_groups", [])
        # On entrelace si Montage Mixte (Interleaved) est coché - Indépendant de l'AND interne
        do_mixed = config.get("ui_mixed_assembly", False)
        non_empty_groups = [g for g in raw_groups if g.get("filters")]
        
        if do_mixed and len(non_empty_groups) > 1:
            log("?? MODE MIXTE : Entrelacement des sélecteurs activé")
            specs_by_group = []
            seen_clips = set() # To avoid duplicates between selectors
            for i, group in enumerate(non_empty_groups):
                mini_cfg = config.copy()
                mini_cfg["adv_filter_groups"] = [group]
                # Filter specifically for this selector
                g_df, _ = apply_filters(df.copy(), mini_cfg)
                # Group 1 match indices to Specs
                g_specs = get_merged_specs_from_df(g_df, mini_cfg, period_start, period_offset)
                
                # Deduplicate: only take clips not seen in previous groups
                unique_g_specs = []
                for s in g_specs:
                    # Identifier based on period and rounded timestamps
                    clip_id = (s["period"], round(s["start"], 2), round(s["end"], 2))
                    if clip_id not in seen_clips:
                        unique_g_specs.append(s)
                        seen_clips.add(clip_id)
                
                if unique_g_specs:
                    specs_by_group.append(unique_g_specs)
                    log(f"  - Sélecteur {i+1}: {len(unique_g_specs)} clips uniques trouvés")
            
            merged_windows = interleave_specs(specs_by_group)
            log(f"?? {len(merged_windows)} clips uniques entrelacés au total.")
        else:
            # Mode standard (Logique globale sur le DF)
            filtered_df, filtered_count = apply_filters(df, config)
            if filtered_count > 0:
                log(f"Filters removed {filtered_count} events.")
            merged_windows = get_merged_specs_from_df(filtered_df, config, period_start, period_offset)

        if not merged_windows:
            log("❌ Aucun événement ne correspond aux filtres.")
            log_queue.put({"type": "done"})
            return

        # Restore log format for UI regex parsing
        total_events = len(df) if not do_mixed else sum(len(g.get("filters", [])) for g in non_empty_groups) # Approximation for mixed
        log(f"Found {total_events} events → {len(merged_windows)} clips after merging.\n")

        if config["dry_run"]:
            total_dur = 0
            type_counts = {}
            for i, mw in enumerate(merged_windows, 1):
                clip_dur = mw['end'] - mw['start']
                total_dur += clip_dur
                log(f"  Clip {i:02d}: {mw['start']:.1f}s – {mw['end']:.1f}s  ({clip_dur:.0f}s)  |  {mw['label']}")
                # Count types
                for t in mw.get("types", []):
                    type_counts[t] = type_counts.get(t, 0) + 1
            
            log(f"\n{'='*50}")
            log(f"📊 RÉSUMÉ DRY RUN")
            log(f"  Total clips : {len(merged_windows)}")
            log(f"  Durée totale : {total_dur:.1f}s ({total_dur/60:.1f} min)")
            if type_counts:
                log(f"  Répartition :")
                for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                    log(f"    • {t}: {c}")
            log(f"{'='*50}")
            log("\n✓ DRY RUN complete.")
            log_queue.put({"type": "done"})
            return


        log("Loading video...")
        ffmpeg_bin = get_ffmpeg_binary()
        src_durations_cache = {}
        
        def get_cached_duration(path):
            if path not in src_durations_cache:
                src_durations_cache[path] = get_video_duration(path, ffmpeg_bin)
            return src_durations_cache[path]

        video1_path = config["video_file"].strip().strip("\"'")
        video1_duration = get_cached_duration(video1_path)
        log(f"  Video 1 duration: {video1_duration:.2f}s")

        if split_video and config.get("video2_file"):
            video2_path_str = config["video2_file"].strip().strip("\"'")
            video2_duration = get_cached_duration(video2_path_str)
            log(f"  Video 2 duration: {video2_duration:.2f}s")
            log("  Two-file mode: 1st half from file 1, 2nd half from file 2.")
        else:
            video2_path_str = None
            video2_duration = None

        def get_src_and_duration(period):
            raw_path = video2_path_str if split_video and video2_path_str and period >= 2 else video1_path
            
            # Handle Google Drive
            if "drive.google.com" in raw_path or "docs.google.com" in raw_path:
                log(f"🔗 Google Drive link detected. Checking local cache...")
                local_path = download_google_drive_video(raw_path)
                log(f"✅ Video ready: {os.path.basename(local_path)}")
                return local_path, get_cached_duration(local_path)
            
            return raw_path, get_cached_duration(raw_path)

        out_dir = config["output_dir"]
        os.makedirs(out_dir, exist_ok=True)

        total_clips = len(merged_windows)
        start_time = time.time()
        
        organize_folders = config.get("group_by_player", False)  # We kept the config key the same for backwards wrapper

        if config["individual_clips"]:
            tasks = []
            for i, mw in enumerate(merged_windows, 1):
                # Use stored src if available (for Aggregate projects), otherwise fallback to global logic
                if mw.get("src"):
                    v_src = mw["src"]
                    src_dur = get_cached_duration(v_src) 
                else:
                    v_src, src_dur = get_src_and_duration(mw["period"])
                    
                v_s = max(0, mw["start"])
                v_e = min(src_dur, mw["end"])
                if v_e <= v_s:
                    log(f"  SKIPPED clip {i:02d}: {v_s:.1f}s–{v_e:.1f}s outside video duration {src_dur:.1f}s")
                    continue
                
                # Filename logic: dominant type + player name(s). Remove invalid characters like '*'
                dominant_type = max(set(mw["types"]), key=mw["types"].count).replace(" ", "_").replace("*", "")
                
                name_part = ""
                player_folder = ""
                if mw["players"]:
                    # Clean up names for filename (replace spaces/special chars)
                    clean_names = ["_".join("".join(c if c.isalnum() or c.isspace() else '' for c in p).split()) for p in mw["players"]]
                    name_part = f"_{'_'.join(sorted(clean_names))}"
                    player_folder = "_".join(sorted(clean_names))
                else:
                    player_folder = "Unknown_Player"
                    
                team_folder = ""
                if mw["action_teams"]:
                    clean_teams = ["_".join("".join(c if c.isalnum() or c.isspace() else '' for c in t).split()) for t in mw["action_teams"]]
                    team_folder = "_".join(sorted(clean_teams))
                else:
                    team_folder = "Unknown_Team"
                
                opp_part = ""
                opp_folder_part = "Unknown"
                if mw["opposition_teams"]:
                    clean_opps = ["_".join("".join(c if c.isalnum() or c.isspace() else '' for c in o).split()) for o in mw["opposition_teams"]]
                    opp_part = f"_VS_{'_'.join(sorted(clean_opps))}"
                    opp_folder_part = "_".join(sorted(clean_opps))

                date_part = f"_{match_date}" if match_date else ""
                filename = f"{i:02d}_{dominant_type}{name_part}{opp_part}{date_part}.mp4"
                
                if organize_folders:
                    match_folder = f"VS_{opp_folder_part}{date_part}"
                    target_dir = os.path.join(out_dir, team_folder, player_folder, match_folder)
                    os.makedirs(target_dir, exist_ok=True)
                    filepath = os.path.join(target_dir, filename)
                else:
                    filepath = os.path.join(out_dir, filename)
                
                tasks.append((i, v_src, v_s, v_e, filepath))

            # Parallel rendering phase
            from concurrent.futures import ThreadPoolExecutor
            def render_worker(args):
                idx, src_path, start, end, out_path = args
                cut_clip_ffmpeg(ffmpeg_bin, src_path, start, end, out_path, config.get("custom_text_options"), config.get("crop_params") if config.get("use_crop") else None)
                prog(idx, total_clips, time.time() - start_time)
                return out_path

            log(f"⚡ FAST-MODE: Parallel rendering of {len(tasks)} clips (8 workers)...")
            with ThreadPoolExecutor(max_workers=8) as executor:
                saved = list(executor.map(render_worker, tasks))
                
            log(f"\n✓ {len(saved)} clips saved to: {os.path.abspath(out_dir)}/")
        else:
            if organize_folders:
                # Group windows by team and player
                groups_map = {}
                for mw in merged_windows:
                    t_folder = "Unknown_Team"
                    if mw["action_teams"]:
                        clean_teams = ["_".join("".join(c if c.isalnum() or c.isspace() else '' for c in t).split()) for t in mw["action_teams"]]
                        t_folder = "_".join(sorted(clean_teams))
                        
                    if not mw["players"]:
                        group_key = (t_folder, "Unknown_Player")
                        if group_key not in groups_map:
                            groups_map[group_key] = []
                        groups_map[group_key].append(mw)
                    else:
                        for p in mw["players"]:
                            p_clean = "_".join("".join(c if c.isalnum() or c.isspace() else '' for c in p).split())
                            group_key = (t_folder, p_clean)
                            if group_key not in groups_map:
                                groups_map[group_key] = []
                            groups_map[group_key].append(mw)
                    
                total_groups = len(groups_map)
                log(f"Assembling reels for {total_groups} player(s)/team(s) in parallel...")
                
                def process_player_reel(args_in):
                    g_idx, ((t_folder, p_folder), g_windows) = args_in
                    clip_specs = []
                    for mw in g_windows:
                        if mw.get("src"):
                            src = mw["src"]
                            src_dur = get_cached_duration(src)
                        else:
                            src, src_dur = get_src_and_duration(mw["period"])
                        s = max(0, mw["start"])
                        e = min(src_dur, mw["end"])
                        if e > s:
                            clip_specs.append({"src": src, "start": s, "end": e})
                            
                    if not clip_specs:
                        return None
                        
                    total_dur = sum(spec["end"] - spec["start"] for spec in clip_specs)
                    
                    # Add opponent and date to filename
                    group_opps = set()
                    for item in g_windows:
                        if item.get("opposition_teams"):
                            group_opps.update(item["opposition_teams"])
                    
                    opp_suffix = ""
                    opp_folder_part = "Unknown"
                    if group_opps:
                        clean_opps = ["_".join("".join(c if c.isalnum() or c.isspace() else '' for c in o).split()) for o in group_opps]
                        opp_suffix = f"_VS_{'_'.join(sorted(clean_opps))}"
                        opp_folder_part = "_".join(sorted(clean_opps))
                    
                    date_suffix = f"_{match_date}" if match_date else ""
                    match_folder = f"VS_{opp_folder_part}{date_suffix}"
                    target_dir = os.path.join(out_dir, t_folder, p_folder, match_folder)
                    os.makedirs(target_dir, exist_ok=True)
                    
                    base_name, ext = os.path.splitext(config["output_filename"])
                    out_path = os.path.join(target_dir, f"{base_name}_{p_folder}{opp_suffix}{date_suffix}{ext}")
                    
                    assembly_start = time.time()
                    # We use a dedicated progress queue for each player or let them share the main one?
                    # The UI might struggle with multiple progress bars/text, but for overall visibility, 
                    # we let them write to progress_queue.
                    cut_and_concat_ffmpeg(ffmpeg_bin, clip_specs, out_path, progress_queue, assembly_start, config.get("custom_text_options"), config.get("crop_params") if config.get("use_crop") else None)
                    return out_path

                with ThreadPoolExecutor(max_workers=4) as reel_executor:
                    # Map players to the renderer
                    list(reel_executor.map(process_player_reel, enumerate(groups_map.items(), 1)))
                
                log("\n✓ All organised reels saved.")
                
            else:
                clip_specs = []
                for i, mw in enumerate(merged_windows, 1):
                    if mw.get("src"):
                        src = mw["src"]
                        src_dur = get_cached_duration(src)
                    else:
                        src, src_dur = get_src_and_duration(mw["period"])
                    s = max(0, mw["start"])
                    e = min(src_dur, mw["end"])
                    if e <= s:
                        log(f"  SKIPPED clip {i:02d}: {s:.1f}s–{e:.1f}s outside video duration {src_dur:.1f}s")
                        continue
                        
                    dominant_type = max(set(mw["types"]), key=mw["types"].count) if mw["types"] else "Unknown"
                    clip_specs.append({
                        "src": src, "start": s, "end": e, "type": dominant_type,
                        "first_x": mw.get("first_x"), "first_y": mw.get("first_y"),
                        "last_x": mw.get("last_x"), "last_y": mw.get("last_y"),
                        "last_endX": mw.get("last_endX"), "last_endY": mw.get("last_endY"),
                        "last_type": mw.get("last_type")
                    })

                if config.get("return_specs"):
                    log_queue.put({"type": "specs", "clip_specs": clip_specs, "match_date": match_date})
                    return

                total_dur = sum(spec["end"] - spec["start"] for spec in clip_specs)
                log(f"Assembling {len(clip_specs)} clips ({total_dur:.1f}s)...")
                
                # Add opponent and date to global filename
                all_opps = set()
                for mw in merged_windows:
                    if mw.get("opposition_teams"):
                        all_opps.update(mw["opposition_teams"])
                
                opp_suffix = ""
                if all_opps:
                    clean_opps = ["_".join("".join(c if c.isalnum() or c.isspace() else '' for c in o).split()) for o in all_opps]
                    opp_suffix = f"_VS_{'_'.join(sorted(clean_opps))}"
                
                date_suffix = f"_{match_date}" if match_date else ""
                
                base_name, ext = os.path.splitext(config["output_filename"])
                out_path = os.path.join(out_dir, f"{base_name}{opp_suffix}{date_suffix}{ext}")

                if config.get("xml_only"):
                    xml_out = out_path.replace(".mp4", ".xml").replace(".mkv", ".xml")
                    export_to_premiere_xml(clip_specs, xml_out)
                    log(f"\n✓ Project XML exported to: {xml_out}")
                    log_queue.put({"type": "done"})
                    return

                # For progress bar — estimate based on clip count
                assembly_start = time.time()
                stop_event = threading.Event()
                fps_est = 25
                total_frames = int(total_dur * fps_est)
                monitor_thread = threading.Thread(
                    target=monitor_file_progress,
                    args=(out_path, total_frames, fps_est, progress_queue, stop_event),
                    daemon=True
                )
                monitor_thread.start()
                cut_and_concat_ffmpeg(ffmpeg_bin, clip_specs, out_path, progress_queue, assembly_start, config.get("custom_text_options"), config.get("crop_params") if config.get("use_crop") else None)
                stop_event.set()
                monitor_thread.join()
                log(f"\n✓ Saved to: {out_path}")

        log_queue.put({"type": "done"})


    except Exception as e:
        log(f"\n✗ ERROR: {e}")
        log_queue.put({"type": "error"})

# =============================================================================
# TACTICAL SEQUENCE DETECTION (BUILD-UP)
# =============================================================================

def detect_progressive_chains(df_all, min_chain_length=3):
    """
    Detect sequences of consecutive actions (Passes, Carries) by the same team 
    that show overall progression.
    """
    if df_all is None or df_all.empty:
        return []

    # Sort df to be sure it's temporal
    # Use cumulative_mins if available as it handles period transitions better
    time_cols = ["period", "minute", "second"]
    if "cumulative_mins" in df_all.columns:
        time_cols = ["cumulative_mins"]
    
    df_temporal = df_all.sort_values(time_cols + (["index"] if "index" in df_all.columns else []))

    def _get_val(row, col):
        v = row.get(col, 0)
        try: return float(v or 0)
        except: return 0.0

    def _is_prog_action(row):
        # 1. explicit prog_pass/carry
        if _get_val(row, "prog_pass") > 0: return True
        if _get_val(row, "prog_carry") > 0: return True
        
        # 2. adv filter
        if row.get("adv_PROGRESSIVE_ACTION_10M") == True: return True
        
        # 3. Geometric fallback: endX - x >= 10
        rtype = str(row.get("type", ""))
        if "Pass" in rtype or "Carry" in rtype or "TakeOn" in rtype:
            x = _get_val(row, "x")
            ex = _get_val(row, "endX") or x
            if (ex - x) >= 10: return True
            
        return False

    def _is_valid_chain_action(row):
        # Include Passes, Carries, TakeOns and Receipts
        rtype = str(row.get("type", ""))
        if any(x in rtype for x in ["Pass", "Carry", "TakeOn", "Receipt", "Dribble"]):
            # Only successful actions (except receipts which are neutral or successful by nature)
            if "Receipt" in rtype: return True
            outcome = str(row.get("outcomeType", "")).lower()
            return outcome in ["successful", "1", "1.0", "true"]
        return False

    def _build_chain(chain_idxs, current_team):
        if not chain_idxs: return None
        s  = df_all.loc[chain_idxs[0]]
        e  = df_all.loc[chain_idxs[-1]]
        
        # Start and End coordinates
        sx = _get_val(s, "x")
        ex = _get_val(e, "endX") or _get_val(e, "x")
        
        # Time
        sm = int(s.get("minute", 0) or 0)
        ss = int(float(s.get("second", 0) or 0)) 
        em = int(e.get("minute", 0) or 0)
        es = int(float(e.get("second", 0) or 0))
        
        # Prog metrics
        prog_actions = sum(1 for idx in chain_idxs if _is_prog_action(df_all.loc[idx]))
        
        # Analytical Metadata from Processor
        p_id = s.get("possession_id")
        has_shot = any(df_all.loc[idx].get("seq_has_shot", False) or df_all.loc[idx]["type"] in ["Shot", "Goal", "SavedShot"] for idx in chain_idxs)
        has_goal = any(df_all.loc[idx].get("seq_has_goal", False) or df_all.loc[idx]["type"] == "Goal" for idx in chain_idxs)
        is_break = any(df_all.loc[idx].get("seq_is_fast_break", False) or df_all.loc[idx].get("is_off_transition", False) for idx in chain_idxs)

        def _parse_period(val):
            if val is None or pd.isna(val): return 1
            v_str = str(val).lower()
            if v_str in ["firsthalf", "1sthalf", "h1", "1", "1.0"]: return 1
            if v_str in ["secondhalf", "2ndhalf", "h2", "2", "2.0"]: return 2
            try: return int(float(val))
            except: return 1

        # Players involved
        players_involved = list(set(str(df_all.loc[idx].get("playerName") or df_all.loc[idx].get("name") or "Inconnu") 
                                for idx in chain_idxs))

        return {
            "start_idx":        chain_idxs[0],
            "end_idx":          chain_idxs[-1],
            "team":             current_team,
            "start_minute":     sm,
            "start_second":     ss,
            "end_minute":       em,
            "end_second":       es,
            "start_period":     _parse_period(s.get("period")),
            "end_period":       _parse_period(e.get("period")),
            "action_count":     len(chain_idxs),
            "prog_action_count": prog_actions,
            "start_x":          sx,
            "end_x":            ex,
            "total_prog":       ex - sx,
            "starts_in_own_half": sx < 50,
            "reaches_opp_half": ex > 50,
            "duration_seconds": max(0, (em*60 + es) - (sm*60 + ss)),
            "possession_id":    p_id,
            "has_shot":         has_shot,
            "has_goal":         has_goal,
            "is_fast_break":    is_break,
            "players":          players_involved,
        }

    chains = []
    current_chain = []
    current_team = None
    current_match = None

    for idx, row in df_temporal.iterrows():
        this_team = row.get("team") if pd.notna(row.get("team")) else row.get("teamName", "")
        this_match = row.get("_source_config_file", "")
        
        if _is_valid_chain_action(row):
            # BREAK CHAIN IF MATCH CHANGED (Even if team is same)
            if current_match is not None and this_match != current_match:
                if len(current_chain) >= min_chain_length:
                    c = _build_chain(current_chain, current_team)
                    if c and c["prog_action_count"] > 0:
                        c["match_id"] = current_match
                        chains.append(c)
                current_chain = []
                current_team = None
            
            if current_team is None or this_team == current_team:
                current_chain.append(idx)
                current_team = this_team
                current_match = this_match
            else:
                # Team changed, process existing
                if len(current_chain) >= min_chain_length:
                    c = _build_chain(current_chain, current_team)
                    if c and c["prog_action_count"] > 0:
                        c["match_id"] = current_match
                        chains.append(c)
                current_chain = [idx]
                current_team = this_team
                current_match = this_match
        else:
            # Not a chain action (e.g. Foul, Tackle by opponent, etc)
            # This breaks the current chain
            if len(current_chain) >= min_chain_length:
                c = _build_chain(current_chain, current_team)
                if c and c["prog_action_count"] > 0:
                    c["match_id"] = current_match
                    chains.append(c)
            current_chain = []
            current_team = None
            current_match = None

    if len(current_chain) >= min_chain_length:
        c = _build_chain(current_chain, current_team)
        if c and c["prog_action_count"] > 0:
            chains.append(c)

    return chains

def get_chain_actions(df_all, chain):
    """Return a DataFrame slice of all events belonging to a build-up chain."""
    # Since we sorted df_temporal, we should use the index list if we had stored it.
    # But usually chain works on index range in temporal order.
    # Range query on index is safe if match_id also matches
    mask = (df_all.index >= chain["start_idx"]) & (df_all.index <= chain["end_idx"])
    if "match_id" in chain and "_source_config_file" in df_all.columns:
        mask = mask & (df_all["_source_config_file"] == chain["match_id"])
    return df_all[mask].copy()
