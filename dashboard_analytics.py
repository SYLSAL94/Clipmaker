import pandas as pd

def compute_pass_connections(df, name_col):
    if "receiver" in df.columns and name_col in df.columns and "type" in df.columns:
        passes_df = df[(df["type"] == "Pass") & (df["outcomeType"] == "Successful")]
        if not passes_df.empty:
            pass_conn = passes_df.groupby([name_col, "receiver"]).size().reset_index(name="Total")
            pass_conn = pass_conn.sort_values(by="Total", ascending=False)
            pass_conn.columns = ["Passeur", "Receveur", "Total"]
            return pass_conn
    return None

def compute_duel_connections(df, name_col):
    if "oppositionPlayerName" in df.columns and name_col in df.columns:
        duels_df = df[df["oppositionPlayerName"].notna()]
        if not duels_df.empty:
            duel_conn = duels_df.groupby([name_col, "oppositionPlayerName"]).size().reset_index(name="Total")
            mask = duel_conn[name_col].astype(str) < duel_conn["oppositionPlayerName"].astype(str)
            duel_conn = duel_conn[mask]
            duel_conn = duel_conn.sort_values(by="Total", ascending=False)
            duel_conn.columns = ["Joueur 1", "Joueur 2", "Total"]
            return duel_conn
    return None

def compute_player_leaderboard(df, name_col):
    if name_col in df.columns:
        st_df = df.copy()
        st_df["Passes Réussies"] = (st_df["type"] == "Pass") & (st_df["outcomeType"] == "Successful")
        
        has_prog_agg = any(c in st_df.columns for c in ["prog_pass", "prog_carry"])
        if has_prog_agg:
            p_pass = pd.to_numeric(st_df.get("prog_pass", 0), errors="coerce").fillna(0)
            p_carry = pd.to_numeric(st_df.get("prog_carry", 0), errors="coerce").fillna(0)
            st_df["Actions Prog."] = ((p_pass > 0) | (p_carry > 0)).astype(int)
        
        duel_cols = ["adv_AERIAL_DUEL_WON", "adv_TACKLE_WON", "adv_DRIBBLE_SUCCESSFUL"]
        avail_duel_cols = [c for c in duel_cols if c in st_df.columns]
        st_df["Duels Gagnés"] = st_df[avail_duel_cols].sum(axis=1) if avail_duel_cols else 0
        
        st_df["Récupérations"] = (st_df["type"] == "BallRecovery").astype(int)
        st_df["xT"] = pd.to_numeric(st_df.get("xT", 0), errors="coerce").fillna(0)
        
        has_seq_score = "seq_score" in st_df.columns
        if has_seq_score:
            st_df["Danger Séquence (Total)"] = pd.to_numeric(st_df["seq_score"], errors="coerce").fillna(0)
            st_df["Danger Séquence (Moy)"] = st_df["Danger Séquence (Total)"]
            
        has_seq_conceded = "seq_conceded_score" in st_df.columns
        if has_seq_conceded:
            # Note: Pandas .mean() automatically ignores NaN, so the mean will only be over the actual turnovers!
            st_df["Danger Subi (Total)"] = pd.to_numeric(st_df["seq_conceded_score"], errors="coerce")
            st_df["Danger Subi (Moy)"] = st_df["Danger Subi (Total)"]
        

        agg_dict = {
            "id": "count",
            "xT": "sum",
            "Passes Réussies": "sum",
            "Duels Gagnés": "sum",
            "Récupérations": "sum"
        }
        
        if has_prog_agg:
            agg_dict["Actions Prog."] = "sum"
            
        if has_seq_score:
            agg_dict["Danger Séquence (Total)"] = "sum"
            agg_dict["Danger Séquence (Moy)"] = "mean"
            
        if has_seq_conceded:
            agg_dict["Danger Subi (Total)"] = "sum"
            agg_dict["Danger Subi (Moy)"] = "mean"
        
        player_stats = st_df.groupby(name_col).agg(agg_dict).reset_index()
        player_stats = player_stats.rename(columns={"id": "Total Actions", "xT": "xT Généré", name_col: "Joueur"})
        
        player_stats["xT Généré"] = player_stats["xT Généré"].round(3)
        if has_seq_score:
            player_stats["Danger Séquence (Total)"] = player_stats["Danger Séquence (Total)"].round(1)
            player_stats["Danger Séquence (Moy)"] = player_stats["Danger Séquence (Moy)"].round(2)
            
        if has_seq_conceded:
            # Replace NaN resulting from sum/mean on empty groups (like keepers with no turnovers) with 0.0
            player_stats["Danger Subi (Total)"] = player_stats["Danger Subi (Total)"].fillna(0).round(1)
            player_stats["Danger Subi (Moy)"] = player_stats["Danger Subi (Moy)"].fillna(0).round(2)
            
        player_stats = player_stats.sort_values(by="xT Généré", ascending=False)
        return player_stats
    return None

def extract_ui_filters_options(df, name_col, flat_zones):
    team_col = "teamName" if "teamName" in df.columns else ("team" if "team" in df.columns else None)
    
    action_types = sorted(df["type"].dropna().unique().tolist()) if "type" in df.columns else []
    action_counts = df["type"].value_counts().to_dict() if "type" in df.columns else {}
    
    player_names = sorted(df[name_col].fillna('Inconnu').unique().tolist()) if name_col in df.columns else []
    player_counts = df[name_col].fillna('Inconnu').value_counts().to_dict() if name_col in df.columns else {}
    
    team_names = sorted(df[team_col].dropna().unique().tolist()) if team_col else []
    team_counts = df[team_col].value_counts().to_dict() if team_col else {}
    
    outcome_types = sorted(df["outcomeType"].dropna().unique().tolist()) if "outcomeType" in df.columns else []
    outcome_counts = df["outcomeType"].value_counts().to_dict() if "outcomeType" in df.columns else {}
    
    receiver_names = sorted(df["receiver"].dropna().unique().tolist()) if "receiver" in df.columns else []
    receiver_counts = df["receiver"].value_counts().to_dict() if "receiver" in df.columns else {}
    
    opponent_names = sorted(df["oppositionPlayerName"].dropna().unique().tolist()) if "oppositionPlayerName" in df.columns else []
    opponent_counts = df["oppositionPlayerName"].value_counts().to_dict() if "oppositionPlayerName" in df.columns else {}
    
    opposition_team_names = sorted(df["oppositionTeamName"].dropna().unique().tolist()) if "oppositionTeamName" in df.columns else []
    opposition_team_counts = df["oppositionTeamName"].value_counts().to_dict() if "oppositionTeamName" in df.columns else {}
    
    positions = sorted(df["mainPositionCategory"].dropna().unique().tolist()) if "mainPositionCategory" in df.columns else []
    position_counts = df["mainPositionCategory"].value_counts().to_dict() if "mainPositionCategory" in df.columns else {}
    
    adv_cols = [c for c in df.columns if str(c).startswith("adv_")]
    adv_counts = {c: (df[c] == True).sum() for c in adv_cols}
    
    has_xt = "xT" in df.columns
    has_prog = any(c in df.columns for c in ["prog_pass", "prog_carry"])
    has_coords = "x" in df.columns and "y" in df.columns

    start_zone_counts = {}
    end_zone_counts = {}
    
    if has_coords:
        x_data = df["x"].astype(float).copy()
        y_data = df["y"].astype(float).copy()
        # Only scale if we are sure it's Opta 0-100 (x_max < 101)
        if x_data.max() <= 101: 
            x_data = x_data * 1.05
            y_data = y_data * 0.68
        for zname, z in flat_zones.items():
            zone_mask = (x_data >= z["x"][0]) & (x_data <= z["x"][1]) & (y_data >= z["y"][0]) & (y_data <= z["y"][1])
            start_zone_counts[zname] = zone_mask.sum()
            
        if "endX" in df.columns and "endY" in df.columns:
            end_df = df[df["endX"].notna() & df["endY"].notna()]
            if not end_df.empty:
                ex_data = end_df["endX"].astype(float).copy()
                ey_data = end_df["endY"].astype(float).copy()
                # Similarly for end coordinates
                if ex_data.max() <= 101: 
                    ex_data = ex_data * 1.05
                    ey_data = ey_data * 0.68
                for zname, z in flat_zones.items():
                    zone_mask = (ex_data >= z["x"][0]) & (ex_data <= z["x"][1]) & (ey_data >= z["y"][0]) & (ey_data <= z["y"][1])
                    end_zone_counts[zname] = zone_mask.sum()
                    
    # Shot specific options
    shot_goal_zones = sorted(df["shot_goal_zone"].dropna().unique().tolist()) if "shot_goal_zone" in df.columns else []
    shot_goal_zone_counts = df["shot_goal_zone"].value_counts().to_dict() if "shot_goal_zone" in df.columns else {}
    has_shot_dist = "shot_distance" in df.columns

    # One-Two specific options
    one_two_initiators = sorted(df["one_two_initiator"].dropna().unique().tolist()) if "one_two_initiator" in df.columns else []
    one_two_initiator_counts = df["one_two_initiator"].value_counts().to_dict() if "one_two_initiator" in df.columns else {}
    one_two_returners = sorted(df["one_two_returner"].dropna().unique().tolist()) if "one_two_returner" in df.columns else []
    one_two_returner_counts = df["one_two_returner"].value_counts().to_dict() if "one_two_returner" in df.columns else {}

    return {
        "action_types": action_types,
        "action_counts": action_counts,
        "player_names": player_names,
        "player_counts": player_counts,
        "team_names": team_names,
        "team_counts": team_counts,
        "outcome_types": outcome_types,
        "outcome_counts": outcome_counts,
        "receiver_names": receiver_names,
        "receiver_counts": receiver_counts,
        "opponent_names": opponent_names,
        "opponent_counts": opponent_counts,
        "opposition_team_names": opposition_team_names,
        "opposition_team_counts": opposition_team_counts,
        "positions": positions,
        "position_counts": position_counts,
        "adv_cols": adv_cols,
        "adv_counts": adv_counts,
        "has_xt": has_xt,
        "has_prog": has_prog,
        "has_coords": has_coords,
        "start_zone_counts": start_zone_counts,
        "end_zone_counts": end_zone_counts,
        "shot_goal_zones": shot_goal_zones,
        "shot_goal_zone_counts": shot_goal_zone_counts,
        "has_shot_dist": has_shot_dist,
        "one_two_initiators": one_two_initiators,
        "one_two_initiator_counts": one_two_initiator_counts,
        "one_two_returners": one_two_returners,
        "one_two_returner_counts": one_two_returner_counts
    }
