import pandas as pd
import numpy as np
import datetime
import math
import json
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

class OptaProcessor:
    def __init__(self):
        self.duel_types = ['Tackle', 'TakeOn', 'Aerial', 'Foul', 'Dispossessed', 'Interception', 'BlockedPass', 'Challenge']
        self.unsuccessful_types = ['SavedShot', 'Dispossessed', 'OffsidePass', 'MissedShots', 'Card']
        self.position_mapping = {
            'GK': 'Gardiens',
            'RB': 'Latéral', 'LB': 'Latéral', 'RWB': 'Latéral', 'LWB': 'Latéral', 'DR': 'Latéral', 'DL': 'Latéral', 'WBR': 'Latéral', 'WBL': 'Latéral',
            'CB': 'Défenseur central', 'CD': 'Défenseur central', 'RCB': 'Défenseur central', 'RCD': 'Défenseur central', 'LCB': 'Défenseur central', 'LCD': 'Défenseur central', 'DC': 'Défenseur central',
            'DM': 'Milieu défensif', 'RDM': 'Milieu défensif', 'LDM': 'Milieu défensif', 'DMF': 'Milieu défensif', 'RDMF': 'Milieu défensif', 'LDMF': 'Milieu défensif', 'DMC': 'Milieu défensif',
            'CM': 'Milieu central', 'RCM': 'Milieu central', 'LCM': 'Milieu central', 'CMF': 'Milieu central', 'RCMF': 'Milieu central', 'LCMF': 'Milieu central', 'MC': 'Milieu central',
            'RM': 'Milieu latéral', 'LM': 'Milieu latéral', 'RMD': 'Milieu latéral', 'LMD': 'Milieu latéral', 'MR': 'Milieu latéral', 'ML': 'Milieu latéral',
            'AM': 'Milieu offensif', 'AMF': 'Milieu offensif', 'AMC': 'Milieu offensif',
            'RAM': 'Ailier', 'LAM': 'Ailier', 'RW': 'Ailier', 'LW': 'Ailier', 'RWF': 'Ailier', 'LWF': 'Ailier', 'RAMF': 'Ailier', 'LAMF': 'Ailier', 'AMR': 'Ailier', 'AML': 'Ailier',
            'CF': 'Avant centre', 'ST': 'Avant centre', 'RS': 'Avant centre', 'RF': 'Avant centre', 'LS': 'Avant centre', 'LF': 'Avant centre', 'FW': 'Avant centre', 'FWC': 'Avant centre', 'FWR': 'Avant centre', 'FWL': 'Avant centre'
        }

    def has_qualifier(self, event: Dict, qualifier_key: str) -> bool:
        # Fast O(1) lookup
        qualifiers = event.get('qualifiers')
        if not qualifiers: return False
        
        # We assume keys are already normalized in the processing loop
        v = qualifiers.get(qualifier_key)
        if v is None: return False
        
        # Check if value is truthy
        return v not in [False, 0, 0.0, 'False', 'false', '0', '0.0', '']

    def has_qualifier_with_value(self, event: Dict, key: str, value: Any) -> bool:
        qualifiers = event.get('qualifiers')
        if not qualifiers: return False
        
        v = qualifiers.get(key)
        if v is None: return False
        
        # Try numeric comparison first (fastest)
        try:
            fv = float(v)
            fval = float(value)
            if fv == fval: return True
        except (ValueError, TypeError):
            pass
            
        # String comparison
        if str(v) == str(value):
            return True
    def process_file_stream(self, file_stream, file_name: str, log_callback=None) -> List[Dict]:
        """ZERO-DISK : Lit directement le flux binaire de Streamlit via openpyxl ou pandas"""
        def log(msg):
            if log_callback: log_callback(msg)
            else: print(msg)

        log(f"--- Ingestion en mémoire : {file_name}")
        ext = os.path.splitext(file_name)[1].lower()
        rows = []
        df_header_info = {}
        
        if ext in ['.txt', '.json']:
            log("Parsing du format JSON/JSONP Opta...")
            # For bytes stream, decode to text
            text = file_stream.read().decode('utf-8')
            # Handle JSONP
            start = text.find('(')
            end = text.rfind(')')
            if start != -1 and end != -1:
                json_str = text[start+1:end]
            else:
                json_str = text
            data = json.loads(json_str)
            
            match_info = data.get('matchInfo', {})
            live_data = data.get('liveData', {})
            events = live_data.get('event', [])
            log(f"OK : {len(events)} événements bruts trouvés.")
            
            # Map teams
            log("Mappage des joueurs et équipes...")
            contestants = match_info.get('contestant', [])
            home_team, away_team = "Équipe Domicile", "Équipe Extérieur"
            home_id, away_id = None, None
            for c in contestants:
                if c.get('position') == 'home':
                    home_team = c.get('name', 'Home')
                    home_id = c.get('id')
                else:
                    away_team = c.get('name', 'Away')
                    away_id = c.get('id')
            
            # Score
            score_data = live_data.get('matchDetails', {}).get('scores', {}).get('ft', {})
            score = f"{score_data.get('home', 0)} : {score_data.get('away', 0)}"
            venue = match_info.get('venue', {}).get('longName', 'Stade ?')
            season = match_info.get('tournamentCalendar', {}).get('name', '?')
            
            # Type mapped
            type_mapping = {
                1: 'Pass', 2: 'OffsidePass', 3: 'TakeOn', 4: 'Foul', 5: 'Out', 6: 'CornerAwarded', 7: 'Tackle', 8: 'Interception',
                9: 'Turnover', 10: 'Save', 11: 'Claim', 12: 'Clearance', 13: 'MissedShots', 14: 'ShotOnPost', 15: 'SavedShot',
                16: 'Goal', 17: 'Card', 41: 'Punch', 42: 'GoodSkill', 43: 'DeletedEvent', 44: 'Aerial', 45: 'Challenge',
                49: 'BallRecovery', 50: 'Dispossessed', 51: 'Error', 52: 'KeeperPickup', 53: 'CrossNotClaimed', 54: 'Smother',
                55: 'OffsideProvoked', 56: 'ShieldBallOpp', 57: 'FoulThrowIn', 58: 'PenaltyFaced', 59: 'KeeperSweeper',
                60: 'ChanceMissed', 61: 'BallTouch', 63: 'Temp_Goal', 64: 'Resume', 65: 'ContentiousRefereeDecision',
                67: '50/50', 68: 'RefereeDropBall', 74: 'BlockedPass', 83: 'AttemptedTackle'
            }
            
            # Known qualifier mapping (fallback to ID strings if unknown)
            q_map = {131: 'Team player formation', 130: 'Team formation', 59: 'Jersey number', 227: 'Resume', 197: 'Team kit', 194: 'Captain', 44: 'Player position', 30: 'Involved', 127: 'Direction of Play', 279: 'Kick Off', 213: 'Angle', 212: 'Length', 56: 'Zone', 140: 'Pass End X', 141: 'Pass End Y', 1: 'Long ball', 155: 'Chipped', 233: 'Opposite related event ID', 285: 'Defensive', 286: 'Offensive', 3: 'Head pass', 168: 'Flick-on', 157: 'Launch', 178: 'Standing', 154: 'Intentional\nassist', 20: 'Right footed', 210: 'Assist', 218: '2nd assist', 2: 'Cross', 224: 'Out-swinger', 55: 'Related event ID', 328: 'First Touch', 22: 'Regular play', 29: 'Assisted', 17: 'Box-centre', 230: 'GK X blocked', 102: 'Goal mouth y coordinate', 231: 'GK Y Coordinate', 103: 'Goal mouth z coordinate', 75: 'Right', 15: 'Head', 13: 'Foul', 152: 'Direct', 265: 'Attempted Tackle', 189: 'Not visible', 5: 'Free kick taken', 0: 'None', 295: 'Shirt Pull/Holding', 167: 'Out of play', 107: 'Throw-in', 156: 'Lay-off', 146: 'Blocked x co-ordinate', 133: 'Deflection', 215: 'Individual Play', 147: 'Blocked y co-ordinate', 76: 'Low left', 18: 'Out of box-centre', 180: 'Stooping', 182: 'Hands', 177: 'Collected', 72: 'Left footed', 345: 'Overhit Cross', 237: 'Low', 124: 'Goal Kick', 73: 'Left', 6: 'Corner taken', 223: 'In-swinger', 77: 'High left', 136: 'Keeper Touched', 113: 'Strong', 196: 'Switch of play', 236: 'Blocked\nPass', 82: 'Blocked', 80: 'Low right', 25: 'From corner', 94: 'Def block', 225: 'Straight', 108: 'Volley', 121: 'Swerve Right', 174: 'Parried danger', 179: 'Diving', 211: 'Overrun', 4: 'Through ball', 78: 'Low centre', 139: 'Own Player', 64: 'Box-left', 228: 'Own Shot Blocked', 74: 'High', 123: 'Keeper Throw', 7: 'Players caught offside', 241: 'Indirect', 23: 'Fast Break', 294: 'Shove/push', 31: 'Yellow Card', 63: 'Box-right', 199: 'Gk kick from hands', 300: 'Solo run', 79: 'High centre', 88: 'High claim', 170: 'Leading to goal', 214: 'Big Chance', 16: 'Small box- centre', 264: 'Aerial Foul', 57: 'End type', 185: 'Blocked cross', 138: 'Hit Woodwork', 275: 'Hit Bar', 173: 'Parried safe', 42: 'Tactical', 292: 'Detailed Position ID', 293: 'Position Side ID', 145: 'Formation slot', 287: 'Over-arm', 14: 'Last line', 83: 'Close left', 283: 'Coach ID', 184: "Dissent", 62: "Box-deep right", 100: "Six yard blocked", 101: "Saved off line", 41: "Injury", 81: "High Right", 319: "Captain change", 120: "Swerve Left", 85: "Close high"}
            
            for ev in events:
                # --- 1. Basic properties ---
                row = {
                    'id': float(ev.get('id', 0)), 'eventId': ev.get('eventId'),
                    'typeId': ev.get('typeId'), 'period': ev.get('periodId'),
                    'minute': ev.get('timeMin'), 'second': ev.get('timeSec'),
                    'contestantId': ev.get('contestantId'), 'playerId': ev.get('playerId'),
                    'playerName': ev.get('playerName'), 'x': ev.get('x'), 'y': ev.get('y'),
                    'timeStamp': ev.get('timeStamp'),
                    'outcomeType': 'Successful' if ev.get('outcome') == 1 else 'Unsuccessful',
                    'h_a': 'home' if ev.get('contestantId') == home_id else 'away',
                    'teamName': home_team if ev.get('contestantId') == home_id else away_team,
                    'type': type_mapping.get(ev.get('typeId'), str(ev.get('typeId'))),
                    'ft': score, 'venueName': venue, 'season': season
                }
                
                # --- 2. Cumulative time (vector-friendly) ---
                p = row['period']
                if p == 1: row['cumulative_mins'] = row['minute'] + row['second']/60.0
                elif p == 2: row['cumulative_mins'] = 45.0 + row['minute'] + row['second']/60.0
                else: row['cumulative_mins'] = 90.0 + row['minute'] + row['second']/60.0

                # --- 3. Process Qualifiers (Optimization) ---
                q_dict = {}
                for q in ev.get('qualifier', []):
                    qid = q.get('qualifierId')
                    qname = q_map.get(qid, str(qid))
                    val = q.get('value', True)
                    
                    q_dict[qname] = val
                    
                    # Essential flattened keys for compatibility
                    row[f'value_{qname}'] = val
                    if qid == 140: row['endX'] = val
                    if qid == 141: row['endY'] = val
                    if qid == 210: row['assist'] = 1
                    if qid == 218: row['secondAssist'] = 1
                
                row['qualifiers'] = q_dict
                rows.append(row)
                
            df_header_info['home'] = home_team
            df_header_info['away'] = away_team
            df_header_info['score'] = score
            df_header_info['venue'] = venue
            df_header_info['season'] = season
            
            # Create a mock df for dict mapping below
            df = pd.DataFrame(rows)
            
        elif ext in ['.xlsx', '.xls']:
            # Lecture 100% en mémoire vive (RAM)
            df = pd.read_excel(file_stream, engine='openpyxl')
            
            # Remise à zéro du curseur pour la 2ème lecture du header
            file_stream.seek(0)
            df_header = pd.read_excel(file_stream, header=None, nrows=3, engine='openpyxl')
            rows = df.to_dict('records')
        else:
            encodings = ['utf-8', 'latin-1', 'cp1252', 'utf-16']
            df = None
            df_header = None
            for enc in encodings:
                try:
                    # On remet le curseur au début pour chaque tentative
                    file_stream.seek(0)
                    df = pd.read_csv(file_stream, encoding=enc)
                    file_stream.seek(0)
                    df_header = pd.read_csv(file_stream, header=None, nrows=3, encoding=enc)
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            
            if df is None:
                file_stream.seek(0)
                df = pd.read_csv(file_stream)
                file_stream.seek(0)
                df_header = pd.read_csv(file_stream, header=None, nrows=3)
            rows = df.to_dict('records')
        
        # Metadata extraction
        home, away, score, venue, season = 'Équipe Domicile', 'Équipe Extérieur', 'N/A', 'Stade ?', '?'
        if rows:
            r0 = rows[0]
            score = str(r0.get('ft', score))
            venue = str(r0.get('venueName', venue))
            season = str(r0.get('season', season))

        if ext in ['.txt', '.json']:
            home = df_header_info.get('home', home)
            away = df_header_info.get('away', away)
        else:
            # Replicate header logic for home/away for csv/xlsx
            if 'df_header' in locals() and df_header is not None and len(df_header) >= 3:
                h = list(df_header.iloc[0])
                r1 = list(df_header.iloc[1])
                r2 = list(df_header.iloc[2])
                try:
                    idx_team = h.index('teamName')
                    idx_ha = h.index('h_a')
                    if idx_team != -1 and idx_ha != -1:
                        is_home = lambda row: 'home' in str(row[idx_ha]).lower()
                        if is_home(r1):
                            home, away = r1[idx_team], r2[idx_team]
                        else:
                            home, away = r2[idx_team], r1[idx_team]
                except (ValueError):
                    pass

        raw_match_name = f"{home} {score} {away}"
        date_hint = ""
        if rows and 'timeStamp' in rows[0]:
            ts = rows[0]['timeStamp']
            try:
                if isinstance(ts, (int, float)):
                    # Excel serial date
                    dt = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=ts)
                else:
                    dt = pd.to_datetime(ts)
                date_hint = f" ({dt.strftime('%d/%m/%Y')})"
            except:
                pass
        
        match_name = f"{raw_match_name}{date_hint} - {season}" if season != '?' else f"{raw_match_name}{date_hint}"

        # Player ID to Name Map
        log("Recherche des noms de joueurs...")
        player_id_to_name = {}
        for r in rows:
            p_id = r.get('playerId')
            name = r.get('name')
            if pd.isna(name): name = r.get('playerName')
            if pd.notna(p_id) and pd.notna(name):
                if p_id not in player_id_to_name or player_id_to_name[p_id] == 'Inconnu':
                    player_id_to_name[p_id] = str(name).strip()

        # Event ID to info for duels
        event_id_to_info = {}
        for r in rows:
            ev_id = r.get('eventId')
            if pd.notna(ev_id):
                if ev_id not in event_id_to_info:
                    event_id_to_info[ev_id] = []
                team_name = r.get('teamName')
                if pd.isna(team_name): team_name = (home if 'home' in str(r.get('h_a', '')).lower() else away)
                name_from_map = player_id_to_name.get(r.get('playerId'))
                
                player_name = r.get('playerName')
                if pd.isna(player_name): player_name = r.get('name')
                if pd.isna(player_name): player_name = name_from_map
                if pd.isna(player_name): player_name = 'Inconnu'
                
                event_id_to_info[ev_id].append({'playerName': str(player_name).strip(), 'teamName': str(team_name).strip()})

        events = []
        receipts = []

        # Pre-calculate column variants for qualifiers to avoid redundant string ops
        col_to_variants = {}
        prefixes = ['qualifiers.', 'type_value_', 'type.value.', 'type.value_', 'value_', 'value.']
        for k in df.columns:
            k_str = str(k).strip()
            raw_key = None
            for p in prefixes:
                if k_str.lower().startswith(p.lower()):
                    raw_key = k_str[len(p):].strip()
                    break
            if not raw_key: raw_key = k_str
            clean_key = raw_key.replace('_', ' ').replace('.', ' ').replace('\n', ' ').replace('\t', ' ').strip()
            col_to_variants[k] = [raw_key, raw_key.lower(), clean_key, clean_key.lower()]

        log("Création des dictionnaires secondaires (duels)...")
        for i, row in enumerate(rows):
            p_id = row.get('playerId')
            name_from_map = player_id_to_name.get(p_id)
            
            player = row.get('playerName')
            if pd.isna(player): player = row.get('name')
            if pd.isna(player): player = name_from_map
            if pd.isna(player): player = 'Inconnu'
            player = str(player).strip()
            
            team = row.get('teamName')
            if pd.isna(team): team = (home if 'home' in str(row.get('h_a', '')).lower() else away)
            team = str(team).strip()
            
            opposition_team = away if team == home else home

            def is_valid_val(val):
                if val is None: return False
                if isinstance(val, (int, float)) and pd.isna(val): return False
                return str(val).strip().lower() not in ['', 'nan', 'none', 'false', '0', '0.0']

            qualifiers = {}
            for k, v in row.items():
                if k not in col_to_variants: continue
                # Update only if current value is better than existing
                for var in col_to_variants[k]:
                    if var not in qualifiers or (not is_valid_val(qualifiers[var]) and is_valid_val(v)):
                        qualifiers[var] = v
                    elif var not in qualifiers:
                        qualifiers[var] = v

            opposition_player_name = None
            is_duel = row.get('type') in self.duel_types
            val_opp = row.get('value_OppositeRelatedEvent') or row.get('value_Opposite related event ID')
            
            if val_opp:
                candidates = event_id_to_info.get(val_opp)
                if candidates:
                    related_info = next((c for c in candidates if c['teamName'] != team), None)
                    if related_info:
                        opposition_player_name = related_info['playerName']
                        is_duel = True

            # Mission DevOps : On pack l'enrichissement dans 'qualifiers' pour ne rien perdre en SQL
            qualifiers.update({
                'xT': float(row['xT']) if pd.notna(row.get('xT')) else 0.0,
                'prog_pass': float(row['prog_pass']) if pd.notna(row.get('prog_pass')) else 0.0,
                'prog_carry': float(row['prog_carry']) if pd.notna(row.get('prog_carry')) else 0.0,
                'carry_distance': float(row.get('carry_distance', 0)),
                'assist': int(row['assist']) if pd.notna(row.get('assist')) else 0,
                'secondAssist': int(row.get('second_assist', 0)) if pd.notna(row.get('second_assist')) else int(row.get('secondAssist', 0)) if pd.notna(row.get('secondAssist')) else 0,
                'isBigChanceCreated': False  # Sera mis à jour plus bas
            })

            base = {
                'id': f"{os.path.basename(file_path)}-{row.get('id', i+1)}",
                'eventId': row.get('eventId'),
                'matchName': match_name,
                'teamName': team,
                'playerName': player,
                'position': row.get('formation_position') or row.get('position') or '?',
                'formation_position': row.get('formation_position'),
                'jerseyNumber': row.get('value_Jersey number.y') or row.get('value_Jersey number') or 'N/A',
                'venue': venue,
                'season': season,
                'score': score,
                'period': row.get('period', 'N/A'),
                'minute': float(row.get('minute', 0)),
                'second': float(row.get('second', 0)),
                'cumulative_mins': float(row.get('cumulative_mins', 0)),
                'type': row.get('type'),
                'isDuel': is_duel,
                'outcomeType': row.get('outcomeType', 'Unknown'),
                'x': float(row.get('x', 0)),
                'y': float(row.get('y', 0)),
                'endX': float(row['endX']) if pd.notna(row.get('endX')) else None,
                'endY': float(row['endY']) if pd.notna(row.get('endY')) else None,
                'timeStamp': row.get('timeStamp'),
                'h_a': row.get('h_a'),
                'oppositionPlayerName': opposition_player_name,
                'oppositionTeamName': opposition_team,
                'possession_id': float(row['possession_id']) if pd.notna(row.get('possession_id')) else None,
                'possession_team': row.get('possession_team', team),
                'qualifiers': qualifiers,  # Contient maintenant l'enrichissement !
            }

            if base['type'] in self.unsuccessful_types:
                base['outcomeType'] = 'Unsuccessful'

            # Ball Receipt* logic
            if base['type'] == 'Pass' and base['outcomeType'] == 'Successful':
                if i + 1 < len(rows):
                    next_row = rows[i+1]
                    r_id = next_row.get('playerId')
                    r_name_from_map = player_id_to_name.get(r_id)
                    receiver_name = next_row.get('playerName') or next_row.get('name') or r_name_from_map
                    
                    if receiver_name:
                        r_team = next_row.get('teamName') or (home if 'home' in str(next_row.get('h_a', '')).lower() else away)
                        passer_team_norm = team.lower() if team else None
                        receiver_team_norm = r_team.lower() if r_team else None
                        
                        should_accept = not receiver_team_norm or not passer_team_norm or receiver_team_norm == passer_team_norm
                        
                        if should_accept:
                            receipt = base.copy()
                            receipt['id'] = f"{base['id']}-receipt"
                            receipt['type'] = 'Ball Receipt*'
                            receipt['playerName'] = receiver_name
                            receipt['sender'] = player
                            receipt['teamName'] = team # Use passer's team for consistency as per JS
                            receipt['position'] = next_row.get('formation_position') or next_row.get('position') or '?'
                            receipt['x'] = base['endX']
                            receipt['y'] = base['endY']
                            receipt['cumulative_mins'] = base['cumulative_mins'] + 0.0001
                            receipt['endX'] = None
                            receipt['endY'] = None
                            receipt['assist'] = 0
                            receipt['isDuel'] = False
                            # Marking progressive receptions
                            b_ex = base.get('endX') or 0
                            b_sx = base.get('x') or 0
                            if (b_ex - b_sx) >= 10:
                                receipt['is_progressive_reception'] = True
                            receipt.pop('qualifiers', None)
                            receipts.append(receipt)

            if base['type'] != 'Carry' or (base['x'] != 0 and base['y'] != 0):
                events.append(base)

        all_events = sorted(events + receipts, key=lambda x: x['cumulative_mins'])

        log("Enrichment : Mappage des receveurs...")
        self.assign_receivers(all_events)
        log("Enrichment : Calcul des conduits (Carries)...")
        self.enrich_carries(all_events)
        log("Enrichment : Détection événements spéciaux (BC, One-Two)...")
        self.detect_special_events(all_events)
        log("Enrichment : Détection second assists...")
        self.detect_second_assists(all_events)
        log("Analyse des séquences de possession (Build-Up)...")
        self.analyze_possession_sequences(all_events)
        log("Analyse des actions défensives (Gegenpressing, Turnovers)...")
        self.analyze_defensive_actions(all_events)
        log("Raffinement des tirs (Saved vs Blocked)...")
        self.refine_shot_classification(all_events)
        log("Analyse des occasions concédées...")
        self.analyze_conceded_danger(all_events)
        log("Assignation des positions principales...")
        self.assign_main_positions(all_events)
        log("Application des filtres avancés par défaut...")
        self.apply_advanced_filters(all_events)
        log("Traitement Opta terminé avec succès.")

        all_events.sort(key=lambda x: (x.get('periodId', 1), x.get('minute', 0), x.get('second', 0)))
        
        # --- NEXT ACTION LOGIC (Ignoring Ball Receipt*) ---
        for i in range(len(all_events)):
            curr = all_events[i]
            # Trouve la prochaine action significative (pas un Ball Receipt*)
            for j in range(i + 1, len(all_events)):
                candidate = all_events[j]
                if candidate['type'] == 'Ball Receipt*':
                    continue
                # On a trouvé la prochaine action
                curr['next_action_type'] = candidate['type']
                curr['next_action_id'] = candidate['id']
                break

        # --- REPLAY / GAP DETECTION LOGIC ---
        for i in range(1, len(all_events)):
            prev = all_events[i-1]
            curr = all_events[i]
            
            # Gaps only make sense within the same period (1=1st half, 2=2nd half, etc)
            p_prev = prev.get('periodId') or prev.get('period')
            p_curr = curr.get('periodId') or curr.get('period')
            
            if p_curr == p_prev:
                t_prev = prev.get('minute', 0) * 60 + prev.get('second', 0)
                t_curr = curr.get('minute', 0) * 60 + curr.get('second', 0)
                gap = t_curr - t_prev
                
                curr['time_gap'] = gap
                if gap >= 8:
                    curr['adv_GAP_DETECTED'] = True
                    # Let's also tag the previous action, as the replay often follows it
                    prev['adv_PRECEDES_REPLAY'] = True
                else:
                    curr['adv_GAP_DETECTED'] = False
            else:
                curr['time_gap'] = 0
                curr['adv_GAP_DETECTED'] = False

        # --- FINAL SYNC TO QUALIFIERS (DevOps Strategy) ---
        # On s'assure que les colonnes enrichies sont sauvegardées dans le JSONB pour PostgreSQL
        # Cela permet de garder une table SQL propre (8 colonnes) sans perdre d'information.
        enriched_keys = [
            'xT', 'prog_pass', 'prog_carry', 'carry_distance', 'carrySpeed_kmh',
            'isBigChanceCreated', 'oneTwoStatus', 'one_two_score', 'receiver', 'sender',
            'possession_id', 'sub_sequence_id', 'action_danger_score', 'time_gap',
            'adv_GAP_DETECTED', 'adv_PRECEDES_REPLAY'
        ]
        for e in all_events:
            if 'qualifiers' not in e: e['qualifiers'] = {}
            for k in enriched_keys:
                if k in e and e[k] is not None:
                    e['qualifiers'][k] = e[k]

        return all_events

    def ingest_to_db(self, all_events: List[Dict], log_callback=None):
        """
        ZERO-DISK : Ingeste les événements traités directement dans PostgreSQL (datafoot_db).
        Utilise SQLAlchemy pour la performance et la sécurité.
        """
        def log(msg):
            if log_callback: log_callback(msg)
            else: print(msg)

        if not all_events:
            log("⚠️ Aucun événement à ingérer.")
            return False

        try:
            # 1. Préparation des identifiants
            load_dotenv('/home/datafoot/.env')
            DB_PWD = os.getenv('POSTGRES_PWD')
            if not DB_PWD:
                log("❌ POSTGRES_PWD manquante dans le .env")
                return False

            # 2. Conversion et Filtrage Strict (Architecture DevOps)
            df = pd.DataFrame(all_events)
            
            target_cols = ['id', 'matchName', 'teamName', 'playerName', 'minute', 'second', 'type', 'qualifiers']
            
            # Sécurité : Si une colonne manque, on la crée vide
            for col in target_cols:
                if col not in df.columns:
                    df[col] = None
            
            # Sérialisation des dictionnaires complexes (qualifiers) en JSON pour SQL
            if 'qualifiers' in df.columns:
                df['qualifiers'] = df['qualifiers'].apply(lambda x: json.dumps(x) if isinstance(x, dict) else x)

            # Application du masque de colonnes (On ignore le surplus pour PostgreSQL)
            df = df[target_cols]

            # 3. Connexion et Ingestion
            db_url = f"postgresql://analyst_admin:{DB_PWD}@localhost:5432/datafoot_db"
            engine = create_engine(db_url)
            
            match_name = all_events[0].get('matchName', 'Unknown Match')
            
            with engine.begin() as conn:
                # Nettoyage des anciennes données pour ce match (Évite les doublons)
                log(f"🧹 Nettoyage des anciens événements pour : {match_name}")
                conn.execute(text("DELETE FROM opta_events WHERE \"matchName\" = :m"), {"m": match_name})
                
                # Ingestion massive via to_sql
                log(f"🚀 Ingestion SQL de {len(df)} événements...")
                df.to_sql('opta_events', con=conn, if_exists='append', index=False, method='multi', chunksize=1000)
            
            log("✅ Ingestion PostgreSQL terminée avec succès.")
            return True
        except Exception as e:
            log(f"❌ Erreur lors de l'ingestion SQL : {e}")
            return False

    def process_file(self, file_path: str, log_callback=None) -> List[Dict]:
        """Compatibilité descendante pour les appels par chemin de fichier."""
        with open(file_path, 'rb') as f:
            return self.process_file_stream(f, os.path.basename(file_path), log_callback)

    def assign_receivers(self, all_events):
        for i, event in enumerate(all_events):
            if event['type'] == 'Pass' and event['outcomeType'] == 'Successful':
                passer_team = event['teamName'].lower() if event['teamName'] else None
                for j in range(i + 1, len(all_events)):
                    next_event = all_events[j]
                    if next_event['cumulative_mins'] - event['cumulative_mins'] > 5 / 60:
                        break
                    
                    if next_event['type'] == 'Ball Receipt*' and next_event.get('sender') == event['playerName']:
                        receiver_team = next_event['teamName'].lower() if next_event['teamName'] else None
                        should_accept = not receiver_team or not passer_team or receiver_team == passer_team
                        if should_accept:
                            event['receiver'] = next_event['playerName']
                            break

    def enrich_carries(self, all_events):
        # Pass 1: Coordinates and speed
        for i, event in enumerate(all_events):
            if event['type'] == 'Carry':
                for j in range(i + 1, len(all_events)):
                    next_event = all_events[j]
                    if next_event['playerName'] == event['playerName'] and next_event['type'] != 'Carry':
                        event['endX'] = next_event['x']
                        event['endY'] = next_event['y']
                        
                        dist_x = (event['endX'] - event['x']) * 1.05
                        dist_y = (event['endY'] - event['y']) * 0.68
                        distance = math.sqrt(dist_x**2 + dist_y**2)
                        time_diff = (next_event['cumulative_mins'] - event['cumulative_mins']) * 60
                        
                        if distance > 1 and time_diff > 0:
                            mps = distance / time_diff
                            event['carry_distance'] = distance
                            event['carrySpeed_mps'] = mps
                            event['carrySpeed_kmh'] = mps * 3.6
                        break
        
        # Pass 3: Outcome
        ev_id_to_outcome = {e['eventId']: e['outcomeType'] for e in all_events if e['eventId']}
        for i in range(len(all_events) - 1, -1, -1):
            event = all_events[i]
            if event['type'] == 'Carry':
                rel_id = event.get('qualifiers', {}).get('relatedEventId') or event.get('relatedEventId')
                if rel_id and rel_id in ev_id_to_outcome:
                    outcome = ev_id_to_outcome[rel_id]
                    event['outcomeType'] = outcome
                    if event['eventId']:
                        ev_id_to_outcome[event['eventId']] = outcome

    def detect_special_events(self, all_events):
        i = 0
        while i < len(all_events):
            event1 = all_events[i]
            team1 = event1['teamName'].lower() if event1['teamName'] else None

            # One-Two
            if event1['type'] == 'Pass' and event1['outcomeType'] == 'Successful' and event1.get('receiver'):
                for j in range(i + 1, len(all_events)):
                    next_event = all_events[j]
                    if next_event['cumulative_mins'] - event1['cumulative_mins'] > 10 / 60:
                        break
                    
                    team2 = next_event['teamName'].lower() if next_event['teamName'] else None
                    if team1 and team2 and team1 != team2:
                        continue
                        
                    if next_event['type'] == 'Pass' and next_event['outcomeType'] == 'Successful' and next_event.get('receiver'):
                        if event1['playerName'] == next_event.get('receiver') and event1.get('receiver') == next_event['playerName']:
                            event1['oneTwoStatus'] = 'initiator'
                            next_event['oneTwoStatus'] = 'return'
                            
                            # Store both players on both events
                            event1['one_two_initiator'] = event1['playerName']
                            event1['one_two_returner'] = next_event['playerName']
                            next_event['one_two_initiator'] = event1['playerName']
                            next_event['one_two_returner'] = next_event['playerName']
                            
                            # Calculate a score/rating for the one-two (0-100 scale)
                            xt1 = float(event1.get('xT') or 0)
                            xt2 = float(next_event.get('xT') or 0)
                            prog1 = float(event1.get('prog_pass') or 0)
                            prog2 = float(next_event.get('prog_pass') or 0)
                            
                            tx, ty = 100, 50
                            ex2, ey2 = next_event.get('endX') or 0, next_event.get('endY') or 0
                            dist_to_goal = math.sqrt(((ex2 - tx)*1.05)**2 + ((ey2 - ty)*0.68)**2)
                            
                            # Score components: xT (50%), Progression (30%), Goal Proximity (20%)
                            xt_comp = (xt1 + xt2) * 500
                            prog_comp = (prog1 + prog2)
                            dist_comp = max(0, 50 - dist_to_goal) / 1.5
                            
                            final_note = min(100.0, xt_comp + prog_comp + dist_comp)
                            event1['one_two_score'] = round(final_note, 1)
                            next_event['one_two_score'] = round(final_note, 1)
                            
                            i = j # Match JS logic: skip to the return event
                            break
            
            # Big Chance Created
            is_big_chance_shot = (event1['type'] in ['Shot', 'MissedShots', 'Goal']) and self.has_qualifier_with_value(event1, 'Big Chance', 214)
            if is_big_chance_shot:
                for k in range(i - 1, -1, -1):
                    preceding = all_events[k]
                    if event1['cumulative_mins'] - preceding['cumulative_mins'] > 5 / 60:
                        break
                    
                    p_team = preceding['teamName'].lower() if preceding['teamName'] else None
                    if team1 and p_team and team1 != p_team:
                        continue
                    
                    if preceding['type'] == 'Pass' and preceding['outcomeType'] == 'Successful':
                        preceding['isBigChanceCreated'] = True
                        break
                    if preceding['type'] == 'Pass' and preceding['outcomeType'] != 'Successful':
                        break
            i += 1

    def detect_second_assists(self, all_events):
        for i, event in enumerate(all_events):
            if event['type'] == 'Pass' and event.get('assist') == 1:
                # Si l'événement cible a déjà une secondAssist (ex: via Opta), on ne fait rien
                # Ou on cherche à flagger le prédecesseur si secondAssist est à 0.
                for j in range(i - 1, -1, -1):
                    prev = all_events[j]
                    if event['cumulative_mins'] - prev['cumulative_mins'] > 15 / 60:
                        break
                    if prev['type'] == 'Pass' and prev['outcomeType'] == 'Unsuccessful' and prev['teamName'] == event['teamName']:
                        break
                    if prev['type'] == 'Pass' and prev['outcomeType'] == 'Successful' and prev['teamName'] == event['teamName']:
                        prev['secondAssist'] = 1
                        break

    def analyze_possession_sequences(self, all_events):
        """
        Groups events by possession_id but adds a tactical layer: 
        it breaks sequences if significant time gaps (stoppages) or flow-breaking 
        events (fouls, ball out) occur.
        
        Each event is enriched with a unique sub_sequence_id so the Build-Up tab
        can simply groupby(sub_sequence_id) instead of re-detecting sequences.
        """
        possession_groups = {}
        for event in all_events:
            pid = event.get('possession_id')
            if pid is not None:
                if pid not in possession_groups:
                    possession_groups[pid] = []
                possession_groups[pid].append(event)
        
        shot_types = ['Goal', 'SavedShot', 'MissedShots', 'ShotOnPost', 'Shot']
        # Events that stop the physical flow of the match
        stoppage_events = ['Foul', 'Offside', 'Substitution', 'Injury', 'Out', 'BallOut', 'Card', 'Whistle']
        # Events that usually reset the tactical "build-up" phase even within the same possession
        reset_events = ['Interception', 'Clearance', 'Claim', 'Tackle', 'Challenge', 'BlockedPass', 'Recovery']
        progressive_types = ['Pass', 'Carry', 'TakeOn']
        gap_threshold = 8.0 # seconds of total inactivity between 2 actions

        sub_seq_counter = 0  # Global counter for unique sub_sequence_id

        for pid, full_possession in possession_groups.items():
            # Sub-divide the possession group into "active flow" segments
            sub_sequences = []
            current_sub = []
            
            for i, e in enumerate(full_possession):
                e_type = e.get('type', '')
                e_outcome = e.get('outcomeType', 'Successful')
                
                if i > 0:
                    prev = full_possession[i-1]
                    prev_type = prev.get('type', '')
                    
                    # 1. Check for time gaps (stoppages)
                    gap = (e['cumulative_mins'] - prev['cumulative_mins']) * 60
                    
                    # 2. Check for flow-breaking events or resets
                    should_break = False
                    if gap >= gap_threshold:
                        should_break = True
                    elif prev_type in stoppage_events or prev_type in reset_events:
                        should_break = True
                    elif prev.get('outcomeType') == 'Unsuccessful' and prev_type in ['Pass', 'Carry', 'TakeOn']:
                        # A failed action resets the build-up flow even if team recovers it immediately
                        should_break = True
                    
                    if should_break:
                        if current_sub:
                            sub_sequences.append(current_sub)
                        current_sub = []
                        
                current_sub.append(e)
                
                # If the current event itself is a major stoppage, it should end the sub-sequence
                if e_type in stoppage_events:
                    sub_sequences.append(current_sub)
                    current_sub = []
            
            if current_sub:
                sub_sequences.append(current_sub)
            
            # Enrich each sub-sequence individually
            for sub in sub_sequences:
                sub_seq_counter += 1
                current_sub_id = f"{pid}_{sub_seq_counter}"
                
                has_shot = False
                has_goal = False
                is_fast_break = False
                successful_passes = 0
                prog_action_count = 0
                seq_total_xt = 0.0
                
                for e in sub:
                    seq_total_xt += float(e.get('xT', 0) or 0)
                    
                    if e['type'] in shot_types:
                        has_shot = True
                        if self.has_qualifier_with_value(e, 'Fast Break', 23):
                            is_fast_break = True
                    if e['type'] == 'Goal':
                        has_goal = True
                    if e['type'] == 'Pass' and e['outcomeType'] == 'Successful':
                        successful_passes += 1
                    # Count progressive actions
                    if e['type'] in progressive_types:
                        ex = e.get('endX') or e.get('x') or 0
                        sx = e.get('x') or 0
                        try:
                            if (float(ex) - float(sx)) >= 10:
                                prog_action_count += 1
                        except (ValueError, TypeError):
                            pass
                        if float(e.get('prog_pass', 0) or 0) > 0 or float(e.get('prog_carry', 0) or 0) > 0:
                            prog_action_count += 1
                
                # Determine team more robustly (most common team in the sequence)
                team_counts = {}
                for e in sub:
                    t = e.get('possession_team') or e.get('teamName')
                    if t:
                        team_counts[t] = team_counts.get(t, 0) + 1
                
                poss_team = max(team_counts, key=team_counts.get) if team_counts else None
                
                # Calculate metrics for the sub-flow
                if len(sub) > 1:
                    dur_s = (sub[-1]['cumulative_mins'] - sub[0]['cumulative_mins']) * 60
                    tempo_val = dur_s / (successful_passes + 1)
                else:
                    dur_s = 0.0
                    tempo_val = 99.0

                # Collect players involved
                players_in_sub = list(set(
                    str(e.get('playerName') or e.get('name') or 'Inconnu') 
                    for e in sub if e.get('playerName') or e.get('name')
                ))

                # Start/End spatial data
                start_x = float(sub[0].get('x', 0) or 0)
                end_x_val = sub[-1].get('endX') or sub[-1].get('x') or 0
                end_x = float(end_x_val)
                
                # Calculate sequence danger score
                # Base : xT total * 10 (e.g., 0.5 xT = 5.0 score)
                base_score = seq_total_xt * 10

                # 1. Résultat de la séquence
                if has_goal:
                    base_score += 2.0
                elif has_shot:
                    # Bonus supplémentaire si Big Chance ou 1vs1 dans la séquence
                    seq_has_big_chance = any(
                        self.has_qualifier_with_value(e, 'Big Chance', 214)
                        for e in sub
                        if e.get('type') in ['Shot', 'MissedShots', 'Goal', 'SavedShot', 'ShotOnPost']
                    )
                    seq_has_one_on_one = any(
                        self.has_qualifier_with_value(e, '1 on 1', 89)
                        for e in sub
                        if e.get('type') in ['Shot', 'MissedShots', 'Goal', 'SavedShot', 'ShotOnPost']
                    )
                    if seq_has_big_chance:
                        base_score += 2.0   # Big Chance = très dangereux
                    elif seq_has_one_on_one:
                        base_score += 1.0   # 1 contre 1
                    else:
                        base_score += 0.5   # Tir standard

                # 2. Bonus Fast Break / Contre-attaque
                if is_fast_break:
                    base_score += 1.0

                # 3. Zone de fin de séquence (proximité du but adverse)
                if end_x >= 83:
                    base_score += 1.5   # Dans ou près de la surface adverse
                elif end_x >= 70:
                    base_score += 0.5   # Dernier tiers adverse

                # 4. Bonus progression (verticalité)
                base_score += prog_action_count * 0.1

                # 5. Bonus tempo : séquence rapide avec tir (contre-attaque fulgurant < 8s)
                if dur_s > 0 and dur_s < 8 and has_shot:
                    base_score += 0.8

                # 6. Pénalité : possession stérile (beaucoup de passes, pas de tir, pas de progression)
                if successful_passes >= 8 and not has_shot and end_x < 70:
                    base_score *= 0.7

                seq_score = round(base_score, 2)
                    
                for e in sub:
                    if poss_team is None or e.get('teamName') == poss_team:
                        e['seq_has_shot'] = has_shot
                        e['seq_has_goal'] = has_goal
                        e['seq_is_fast_break'] = is_fast_break
                        e['seq_pass_count'] = successful_passes
                        e['seq_tempo_s'] = tempo_val
                        # New Build-Up fields
                        e['sub_sequence_id'] = current_sub_id
                        e['seq_team'] = poss_team
                        e['seq_action_count'] = len(sub)
                        e['seq_prog_action_count'] = prog_action_count
                        e['seq_total_xt'] = seq_total_xt
                        e['seq_score'] = seq_score
                        e['seq_start_minute'] = int(sub[0].get('minute', 0) or 0)
                        e['seq_start_second'] = int(float(sub[0].get('second', 0) or 0))
                        e['seq_end_minute'] = int(sub[-1].get('minute', 0) or 0)
                        e['seq_end_second'] = int(float(sub[-1].get('second', 0) or 0))
                        e['seq_start_x'] = start_x
                        e['seq_end_x'] = end_x
                        e['seq_duration_seconds'] = dur_s
                        e['seq_starts_own_half'] = start_x < 50
                        e['seq_reaches_opp_half'] = end_x > 50
                        e['seq_players'] = players_in_sub

    def analyze_defensive_actions(self, all_events):
        for i, event in enumerate(all_events):
            is_recovery = event['type'] in ['BallRecovery', 'Interception'] or (event['type'] == 'Tackle' and event['outcomeType'] == 'Successful')
            
            if is_recovery:
                # 1. High Turnovers leading to a chance
                is_high = event['x'] >= 60  # Opta x is 0-100, 60 is attacking 40m
                has_shot = event.get('seq_has_shot', False)
                # Fallback: check next 15 seconds if possession grouping missed it
                if is_high and not has_shot:
                    for j in range(i + 1, min(i + 20, len(all_events))):
                        next_e = all_events[j]
                        if next_e['cumulative_mins'] - event['cumulative_mins'] > 15 / 60:
                            break
                        if next_e['teamName'] == event['teamName'] and next_e['type'] in ['Shot', 'Goal', 'SavedShot', 'MissedShots', 'ShotOnPost']:
                            has_shot = True
                            break
                
                if is_high and has_shot:
                    event['is_high_turnover_chance'] = True

                # 2. Gegenpressing (Recovery within 7s of a turnover in attacking half)
                for j in range(i - 1, -1, -1):
                    prev = all_events[j]
                    if event['cumulative_mins'] - prev['cumulative_mins'] > 7 / 60:
                        break
                    
                    if prev['teamName'] == event['teamName']:
                        is_turnover = (prev['type'] == 'BallTouch' and prev['outcomeType'] == 'Unsuccessful') or \
                                      prev['type'] == 'Dispossessed' or \
                                      (prev['type'] == 'TakeOn' and prev['outcomeType'] == 'Unsuccessful') or \
                                      (prev['type'] == 'Pass' and prev['outcomeType'] == 'Unsuccessful')
                        
                        if is_turnover and prev['x'] >= 50:
                            event['is_gegenpressing'] = True
                            break
                
                # 3. Offensive Transitions (Recovery -> Entrance into Opp Box within 10s)
                if is_recovery:
                    for j in range(i + 1, min(i + 40, len(all_events))):
                        next_e = all_events[j]
                        if next_e['cumulative_mins'] - event['cumulative_mins'] > 10 / 60: break
                        if next_e['teamName'] == event['teamName'] and (next_e.get('endX') or 0) >= 85:
                            event['is_off_transition'] = True
                            break

    def analyze_conceded_danger(self, all_events):
        for i, event in enumerate(all_events):
            e_type = event.get('type')
            e_outcome = event.get('outcomeType')
            e_team = event.get('teamName')
            
            is_turnover = False
            if e_outcome == 'Unsuccessful' and e_type in ['Pass', 'TakeOn', 'BallTouch', 'Error', 'Carry']:
                is_turnover = True
            elif e_type == 'Dispossessed':
                is_turnover = True
                
            if is_turnover and e_team:
                for j in range(i + 1, min(i + 60, len(all_events))):
                    next_e = all_events[j]
                    if (next_e['cumulative_mins'] - event['cumulative_mins']) * 60 > 25:
                        break
                        
                    n_team = next_e.get('teamName')
                    if n_team and n_team != e_team:
                        if 'sub_sequence_id' in next_e and next_e.get('type') != 'Ball Receipt*':
                            event['seq_conceded_score'] = round(float(next_e.get('seq_score', 0.0)), 2)
                            break

    def refine_shot_classification(self, all_events):
        """
        Reclassifies 'SavedShot' as 'BlockedShot' if the corresponding 'Save' at 
        the same timestamp was not performed by a goalkeeper.
        """
        # 1. Build a lookup of saves by timestamp
        save_lookup = {}
        for ev in all_events:
            if ev.get('type') == 'Save':
                key = (ev.get('period'), int(ev.get('minute', 0)), int(ev.get('second', 0)))
                # Rank: prefers GK saves if multiple saves exist at same time
                is_gk = str(ev.get('position', '')).upper() in ['GK', '1', 'GARDIENS']
                if key not in save_lookup or is_gk:
                    save_lookup[key] = is_gk

        # 2. Refine SavedShots
        for ev in all_events:
            if ev.get('type') == 'SavedShot':
                key = (ev.get('period'), int(ev.get('minute', 0)), int(ev.get('second', 0)))
                save_is_gk = save_lookup.get(key)
                
                # If there's a corresponding save and it's NOT by a GK
                if save_is_gk is False: 
                    ev['type'] = 'BlockedShot'
                    ev['adv_BLOCKED_BY_OUTFIELDER'] = True

    def assign_main_positions(self, all_events):
        player_counts = {}
        for event in all_events:
            player = event['playerName']
            raw_pos = event.get('position') or event.get('formation_position')
            if player and raw_pos and raw_pos != '?':
                category = self.position_mapping.get(raw_pos) or self.position_mapping.get(str(raw_pos).upper())
                if category:
                    if player not in player_counts:
                        player_counts[player] = {}
                    player_counts[player][category] = player_counts[player].get(category, 0) + 1
        
        player_main_pos = {}
        for player, cats in player_counts.items():
            max_cat = max(cats, key=cats.get)
            player_main_pos[player] = max_cat
            
        for event in all_events:
            event['mainPositionCategory'] = player_main_pos.get(event['playerName'], 'Inconnu')

    def apply_advanced_filters(self, all_events):
        for i, e in enumerate(all_events):
            # Existing filters
            e['adv_IS_DUEL'] = e.get('isDuel') == True
            e['adv_ONE_TWO'] = e.get('oneTwoStatus') in ['initiator', 'return']
            e['adv_ONE_TWO_(INITIATEUR)'] = e.get('oneTwoStatus') == 'initiator'
            e['adv_ONE_TWO_(REMISEUR)'] = e.get('oneTwoStatus') == 'return'
            e['adv_BIG_CHANCE_CREATED'] = e.get('isBigChanceCreated') == True
            e['adv_ASSIST'] = e.get('assist') == 1
            e['adv_SECOND_ASSIST'] = e.get('secondAssist') == 1
            e['adv_DRIBBLE_SUCCESSFUL'] = e['type'] == 'TakeOn' and e['outcomeType'] == 'Successful'
            e['adv_AERIAL_DUEL_WON'] = e['type'] == 'Aerial' and e['outcomeType'] == 'Successful'
            e['adv_HEADED_CLEARANCE'] = e['type'] == 'Clearance' and self.has_qualifier(e, 'Head')
            e['adv_TURNOVER_ALL'] = ( (e['type'] == 'BallTouch' and e['outcomeType'] == 'Unsuccessful') or 
                                       e['type'] == 'Dispossessed' or 
                                      (e['type'] == 'TakeOn' and e['outcomeType'] == 'Unsuccessful') or 
                                      (e['type'] == 'Pass' and e['outcomeType'] == 'Unsuccessful') )
            e['adv_DISPOSSESSED'] = e['type'] == 'Dispossessed'
            e['adv_PASS_UNSUCCESSFUL'] = e['type'] == 'Pass' and e['outcomeType'] == 'Unsuccessful'
            e['adv_TACKLE_WON'] = e['type'] == 'Tackle' and e['outcomeType'] == 'Successful'
            e['adv_INTERCEPTION'] = e['type'] == 'Interception'
            e['adv_RECOVERY_DEFENSIVE'] = e['type'] == 'BallRecovery' and e['x'] <= 35
            e['adv_RECOVERY_MIDDLE'] = e['type'] == 'BallRecovery' and e['x'] > 35 and e['x'] <= 70
            e['adv_RECOVERY_ATTACKING'] = e['type'] == 'BallRecovery' and e['x'] > 70
            e['adv_CLEARANCE'] = e['type'] == 'Clearance'
            e['adv_GK_CLAIM'] = e['type'] == 'Claim'
            e['adv_GK_PUNCH'] = e['type'] == 'Punch'
            e['adv_FOUL_SUFFERED'] = e['type'] == 'Foul' and e['outcomeType'] == 'Successful'
            e['adv_PROGRESSIVE_ACTION_10M'] = (e['type'] in ['Pass', 'Carry']) and (e.get('endX') is not None) and (e.get('x') is not None) and ((e.get('endX') or 0) - (e.get('x') or 0) >= 10)
            e['adv_PENETRATING_PASS_AREA'] = e['type'] == 'Pass' and not (e['x'] >= 88.5 and 13.84 <= e['y'] <= 54.16) and ((e.get('endX') or 0) >= 88.5 and 13.84 <= (e.get('endY') or 0) <= 54.16)
            e['adv_PENETRATING_CARRY_AREA'] = e['type'] == 'Carry' and not (e['x'] >= 88.5 and 13.84 <= e['y'] <= 54.16) and ((e.get('endX') or 0) >= 88.5 and 13.84 <= (e.get('endY') or 0) <= 54.16)
            e['adv_ERROR_LEAD_TO_GOAL'] = e['type'] == 'Error' and self.has_qualifier_with_value(e, 'Leading to goal', 170)
            e['adv_ERROR_LEAD_TO_SHOT'] = e['type'] == 'Error' and self.has_qualifier_with_value(e, 'Leading to attempt', 169)
            e['adv_YELLOW_CARD'] = e.get('cardType') == 'Yellow' or self.has_qualifier_with_value(e, 'Yellow Card', 31)
            e['adv_RED_CARD'] = e.get('cardType') == 'Red' or self.has_qualifier_with_value(e, 'Red Card', 33)

            # Possession Sequences (Build-up) Filters
            e['adv_PART_OF_SHOT_SEQUENCE'] = e.get('seq_has_shot') == True
            e['adv_PART_OF_GOAL_SEQUENCE'] = e.get('seq_has_goal') == True
            e['adv_FAST_BREAK_SEQUENCE'] = e.get('seq_is_fast_break') == True
            e['adv_10_PLUS_PASS_SEQUENCE'] = (e.get('seq_pass_count') or 0) >= 10
            e['adv_15_PLUS_PASS_SEQUENCE'] = (e.get('seq_pass_count') or 0) >= 15

            # Defensive Actions Filters
            e['adv_GEGENPRESSING_RECOVERY'] = e.get('is_gegenpressing') == True
            e['adv_HIGH_TURNOVER_CHANCE'] = e.get('is_high_turnover_chance') == True

            # Specific Pass Filters
            e['adv_PASS_TYPE_CHIPPED'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Chipped', 155)
            e['adv_PASS_TYPE_LONG_BALL'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Long ball', 1)
            e['adv_LONG_BALL_SUCCESSFUL'] = e['type'] == 'Pass' and e['outcomeType'] == 'Successful' and self.has_qualifier(e, 'Long ball')
            e['adv_CROSS'] = self.has_qualifier(e, 'Cross') or self.has_qualifier_with_value(e, 'Cross', 2)
            e['adv_PASS_TYPE_HEAD_PASS'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Head pass', 3)
            e['adv_PASS_TYPE_FLICK_ON'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Flick-on', 168)
            e['adv_PASS_TYPE_LAY_OFF'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Lay-off', 156)
            e['adv_THROUGH_BALL'] = self.has_qualifier_with_value(e, 'Through ball', 4)
            e['adv_PASS_TYPE_LAUNCH'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Launch', 157)
            e['adv_SWITCH_OF_PLAY'] = self.has_qualifier_with_value(e, 'Switch of play', 196)
            e['adv_PASS_TYPE_PULL_BACK'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Pull Back', 195)
            e['adv_PASS_TYPE_ASSIST'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Assist', 210)
            e['adv_PASS_TYPE_CORNER_TAKEN'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Corner taken', 6)
            e['adv_THROW_IN'] = self.has_qualifier_with_value(e, 'Throw-in', 107)
            e['adv_PASS_TYPE_KEEPER_THROW'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Keeper Throw', 123)
            e['adv_PASS_TYPE_GOAL_KICK'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Goal Kick', 124)
            e['adv_PASS_TYPE_FREE_KICK_TAKEN'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Free kick taken', 5)
            e['adv_PASS_OVERHIT_CROSS'] = e['type'] == 'Pass' and self.has_qualifier_with_value(e, 'Overhit Cross', 345)

            shot_types = ['Goal', 'SavedShot', 'MissedShots', 'ShotOnPost', 'Shot', 'BlockedShot']
            is_shot = e['type'] in shot_types
            e['adv_ALL_SHOTS'] = is_shot
            e['adv_SHOT_ON_TARGET'] = is_shot and e.get('outcomeType') == 'Successful'
            e['adv_SHOT_SWERVE_LEFT'] = is_shot and self.has_qualifier_with_value(e, 'Swerve Left', 120)
            e['adv_SHOT_SWERVE_RIGHT'] = is_shot and self.has_qualifier_with_value(e, 'Swerve Right', 121)
            e['adv_SHOT_FAST_BREAK'] = is_shot and self.has_qualifier_with_value(e, 'Fast Break', 23)
            e['adv_SHOT_ONE_ON_ONE'] = is_shot and self.has_qualifier_with_value(e, '1 on 1', 89)
            e['adv_SHOT_DEFLECTION'] = is_shot and self.has_qualifier_with_value(e, 'Deflection', 133)
            e['adv_SHOT_BLOCKED'] = is_shot and (self.has_qualifier_with_value(e, 'Blocked', 82) or e.get('adv_BLOCKED_BY_OUTFIELDER', False))
            e['adv_SHOT_INDIVIDUAL_PLAY'] = is_shot and self.has_qualifier_with_value(e, 'Individual Play', 215)
            e['adv_SHOT_OUT_OF_BOX_CENTRE'] = is_shot and self.has_qualifier_with_value(e, 'Out of box-centre', 18)
            e['adv_SHOT_FOLLOWS_DRIBBLE'] = is_shot and self.has_qualifier_with_value(e, 'Follows a Dribble', 254)
            e['adv_SHOT_ASSIST_TEAM'] = is_shot and self.has_qualifier_with_value(e, 'Assist Team', 282)
            e['adv_SHOT_FANTASY'] = is_shot and self.has_qualifier_with_value(e, 'Fantasy', 281)
            e['adv_SHOT_FANTASY_ASSIST_TYPE'] = is_shot and self.has_qualifier_with_value(e, 'Fantasy Assist Type', 280)
            e['adv_SHOT_VOLLEY'] = is_shot and self.has_qualifier_with_value(e, 'Volley', 108)
            e['adv_SHOT_LEFT_FOOTED'] = is_shot and self.has_qualifier_with_value(e, 'Left footed', 72)
            e['adv_SHOT_RIGHT_FOOTED'] = is_shot and self.has_qualifier_with_value(e, 'Right footed', 20)
            e['adv_SHOT_HIT_WOODWORK'] = is_shot and self.has_qualifier_with_value(e, 'Hit Woodwork', 138)
            e['adv_SHOT_BIG_CHANCE'] = is_shot and self.has_qualifier_with_value(e, 'Big Chance', 214)
            e['adv_SHOT_FIRST_TOUCH'] = is_shot and self.has_qualifier_with_value(e, 'First Touch', 328)
            e['adv_SHOT_KEEPER_TOUCHED'] = is_shot and self.has_qualifier_with_value(e, 'Keeper Touched', 136)
            e['adv_SHOT_ASSISTED'] = is_shot and self.has_qualifier_with_value(e, 'Assisted', 29)
            e['adv_SHOT_REGULAR_PLAY'] = is_shot and self.has_qualifier_with_value(e, 'Regular play', 22)
            e['adv_SHOT_HEAD'] = is_shot and self.has_qualifier_with_value(e, 'Head', 15)
            e['adv_SHOT_STRONG'] = is_shot and self.has_qualifier_with_value(e, 'Strong', 113)
            
            # Distance and Goal Zone Enrichment
            if is_shot:
                # 1. Distance Calculation (Assuming Opta 0-100 scale, pitch 105x68)
                # target is x=100 (if shooting right) or x=0 (if shooting left)
                # But for simplicity, we use distance to nearest goal center (100, 50) or (0, 50)
                tx = 100 if e['x'] > 50 else 0
                ty = 50
                dist_x = (e['x'] - tx) * 1.05
                dist_y = (e['y'] - ty) * 0.68
                e['shot_distance'] = math.sqrt(dist_x**2 + dist_y**2)
                
                # 2. Goal Zone Mapping (from value_Goal mouth y/z coordinate)
                gy = e.get('value_Goal mouth y coordinate')
                gz = e.get('value_Goal mouth z coordinate')
                if gy is not None and gz is not None:
                    # Vertical: 0-12 Bottom, 12-24 Middle, 24-36 Top
                    if gz > 24: v_pos = "Top"
                    elif gz > 12: v_pos = "Middle"
                    else: v_pos = "Bottom"
                    
                    # Horizontal: 45-48.33 Right, 48.33-51.67 Center, 51.67-55 Left
                    if gy > 51.67: h_pos = "Left"
                    elif gy < 48.33: h_pos = "Right"
                    else: h_pos = "Center"
                    
                    e['shot_goal_zone'] = f"{v_pos} {h_pos}"
                
                # xA Approximation: find the pass that led to this shot
                if i > 0:
                    for k in range(i - 1, -1, -1):
                        preceding = all_events[k]
                        if e['cumulative_mins'] - preceding['cumulative_mins'] > 12 / 60: break
                        if preceding['type'] == 'Pass' and preceding['outcomeType'] == 'Successful' and preceding['teamName'] == e['teamName']:
                            # Score based on proximity to goal
                            dist = e.get('shot_distance') or 25
                            preceding['xA_approx'] = 1.0 / (dist + 5.0)
                            if preceding['xA_approx'] > 0.08:
                                preceding['adv_HIGH_xA_PASS'] = True
                            break

            # NEW FILTERS
            is_pass = e['type'] == 'Pass' and e['outcomeType'] == 'Successful'
            e['adv_PROGRESSIVE_RECEPTION'] = e.get('is_progressive_reception', False)
            e['adv_OFF_TRANSITION_10S'] = e.get('is_off_transition', False)
            e['adv_HIGH_TEMPO_SEQUENCE'] = (e.get('seq_tempo_s') or 99) < 2.5
            b_ex = e.get('endX')
            b_sx = e.get('x')
            e['adv_LINE_BREAKING_PASS'] = (is_pass and b_ex is not None and b_sx is not None and (b_ex - b_sx > 30))
            e['adv_HIGH_xA_PASS'] = e.get('adv_HIGH_xA_PASS', False)

            e['adv_TAKEON_DEFENSIVE'] = e['type'] == 'TakeOn' and self.has_qualifier_with_value(e, 'Defensive', 285)
            e['adv_TAKEON_OFFENSIVE'] = e['type'] == 'TakeOn' and self.has_qualifier_with_value(e, 'Offensive', 256)
            e['adv_TAKEON_OVERRUN'] = e['type'] == 'TakeOn' and self.has_qualifier_with_value(e, 'Overrun', 211)
            e['adv_TACKLE_OUT_OF_PLAY'] = e['type'] == 'Tackle' and self.has_qualifier_with_value(e, 'Out of play', 167)

            e['adv_FOUL_SHIRT_PULL'] = e['type'] == 'Foul' and self.has_qualifier_with_value(e, 'Shirt Pull/Holding', 295)
            e['adv_FOUL_SHOVE_PUSH'] = e['type'] == 'Foul' and self.has_qualifier_with_value(e, 'Shove/push', 294)
            e['adv_FOUL_ATTEMPTED_TACKLE'] = e['type'] == 'Foul' and self.has_qualifier_with_value(e, 'Attempted Tackle', 265)
            e['adv_FOUL_AERIAL'] = e['type'] == 'Foul' and self.has_qualifier_with_value(e, 'Aerial Foul', 264)

            # Filtres spécifiques avec vérification du type d'événement
            e['adv_TACKLE_STANDING'] = e.get('type') == 'Tackle' and self.has_qualifier_with_value(e, 'Standing', 178)
            e['adv_TACKLE_SLIDING'] = e.get('type') == 'Tackle' and not self.has_qualifier_with_value(e, 'Standing', 178)
            e['adv_TACKLE_LAST_LINE'] = e.get('type') == 'Tackle' and self.has_qualifier_with_value(e, 'Last line', 14)
            e['adv_INTERCEPTION_LAST_LINE'] = e.get('type') == 'Interception' and self.has_qualifier_with_value(e, 'Last line', 14)

            # Faute de main (flexible sur la clé du qualifier)
            # Optimisation handball (recherche directe au lieu de boucle any)
            is_handball = self.has_qualifier_with_value(e, 'Hand', 10) or self.has_qualifier_with_value(e, 'Handball', 10)
            e['adv_FOUL_HANDBALL'] = e.get('type') == 'Foul' and is_handball

            # Pénaltys basés sur les fautes
            e['adv_FOUL_PENALTY_PROVOKED'] = e.get('type') == 'Foul' and e.get('outcomeType') == 'Successful' and self.has_qualifier_with_value(e, 'Penalty', 9)
            e['adv_FOUL_PENALTY_COMMITTED'] = e.get('type') == 'Foul' and e.get('outcomeType') == 'Unsuccessful' and self.has_qualifier_with_value(e, 'Penalty', 9)

            is_save = e['type'] == 'Save'
            e['adv_SAVE_HIT_RIGHT_POST'] = is_save and self.has_qualifier_with_value(e, 'Hit Right Post', 273)
            e['adv_SAVE_FEET'] = is_save and self.has_qualifier_with_value(e, 'Feet', 183)
            e['adv_SAVE_STOOPING'] = is_save and self.has_qualifier_with_value(e, 'Stooping', 180)
            e['adv_SAVE_PARRIED_DANGER'] = is_save and self.has_qualifier_with_value(e, 'Parried danger', 174)
            e['adv_SAVE_HANDS'] = is_save and self.has_qualifier_with_value(e, 'Hands', 182)
            e['adv_SAVE_PARRIED_SAFE'] = is_save and self.has_qualifier_with_value(e, 'Parried safe', 173)
            e['adv_SAVE_DIVING'] = is_save and self.has_qualifier_with_value(e, 'Diving', 179)
            e['adv_SAVE_DEF_BLOCK'] = is_save and self.has_qualifier_with_value(e, 'Def block', 94)
            e['adv_SAVE_OTHER_BODY_PART'] = is_save and self.has_qualifier_with_value(e, 'Other body part', 21)
            e['adv_SAVE_CAUGHT'] = is_save and self.has_qualifier_with_value(e, 'Caught', 176)
            e['adv_SAVE_OWN_PLAYER'] = is_save and self.has_qualifier_with_value(e, 'Own Player', 139)
            e['adv_SAVE_REACHING'] = is_save and self.has_qualifier_with_value(e, 'Reaching', 181)


            e['adv_NOT_VISIBLE'] = self.has_qualifier_with_value(e, 'Not visible', 189)

            # ---------------------------------------------------------------
            # action_danger_score : note de dangerosité individuelle (0–10)
            # Mesure la contribution intrinsèque de l'action, indépendamment
            # de la séquence collective (complémentaire de seq_score).
            # ---------------------------------------------------------------
            e_type   = e.get('type', '')
            e_out    = e.get('outcomeType', '')
            e_xT     = float(e.get('xT') or 0)
            e_x      = float(e.get('x') or 0)
            e_endX   = float(e.get('endX') or e_x)
            e_endY   = float(e.get('endY') or e.get('y') or 50)
            e_prog_p = float(e.get('prog_pass') or 0)
            e_prog_c = float(e.get('prog_carry') or 0)

            is_shot_type = e_type in ['Goal', 'SavedShot', 'MissedShots', 'ShotOnPost', 'Shot', 'BlockedShot']

            # 1. Base xT (0–3 pts)
            ads = min(e_xT * 15, 3.0)

            # 2. Zone de fin d'action (proximité du but adverse)
            if is_shot_type:
                # Pour les tirs, utiliser la position de départ
                ref_x = e_x
            else:
                ref_x = e_endX
            if ref_x >= 83:
                ads += 3.0    # Dans/près de la surface adverse
            elif ref_x >= 70:
                ads += 1.5    # Dernier tiers adverse
            elif ref_x >= 50:
                ads += 0.3    # Mi-terrain offensif

            # 3. Bonus selon le type et résultat
            if e_type == 'Goal':
                ads = 10.0    # Cap direct
            elif e_type == 'SavedShot':
                if self.has_qualifier_with_value(e, 'Big Chance', 214):
                    ads += 3.0
                else:
                    ads += 2.5
            elif e_type in ['MissedShots', 'ShotOnPost', 'BlockedShot']:
                ads += 1.5
            elif e_type == 'Pass' and e.get('assist') == 1:
                ads += 2.5    # Passe décisive confirmée
            elif e.get('isBigChanceCreated'):
                ads += 2.0    # Key pass (big chance créée)
            elif e.get('adv_HIGH_xA_PASS'):
                ads += 1.5    # Passe avec xA élevé
            elif e_type == 'TakeOn' and e_out == 'Successful':
                ads += 1.5    # Dribble réussi
            elif e_type == 'Carry' and e_out == 'Successful':
                if e_prog_c >= 10:
                    ads += 1.0  # Portée très progressive
                elif e_prog_c > 0:
                    ads += 0.5
            elif e_type == 'Pass' and e_out == 'Successful':
                if e_prog_p >= 10:
                    ads += 0.5  # Passe très progressive

            # 4. Bonus qualificateurs contextuels
            if is_shot_type:
                if self.has_qualifier_with_value(e, '1 on 1', 89):
                    ads += 1.5   # Situation 1 vs 1
                if self.has_qualifier_with_value(e, 'Fast Break', 23):
                    ads += 1.0   # Tir en contre
            if e.get('adv_PENETRATING_PASS_AREA') or e.get('adv_PENETRATING_CARRY_AREA'):
                ads += 1.0       # Action pénétrante dans la surface
            if self.has_qualifier_with_value(e, 'Through ball', 4):
                ads += 0.5       # Passe en profondeur

            e['action_danger_score'] = round(min(ads, 10.0), 2)



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Process Opta Excel files replicating Worker logic.")
    parser.add_argument("files", nargs="+", help="Path to Excel files")
    parser.add_argument("--output", default="processed_data.json", help="Output JSON file")
    args = parser.parse_args()

    processor = OptaProcessor()
    all_results = []
    for f in args.files:
        print(f"Processing {f}...")
        results = processor.process_file(f)
        all_results.extend(results)
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print(f"Finished. Total events: {len(all_results)}. Saved to {args.output}")
