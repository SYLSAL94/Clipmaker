import os
import pandas as pd
import numpy as np
import datetime
import math
import json
import multiprocessing
from typing import List, Dict, Any, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed

# =============================================================================
# LOGIQUE DE TRAITEMENT OPTA (COPIE INTÉGRALE LIGNE À LIGNE)
# =============================================================================

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
        k = str(qualifier_key).lower().strip()
        v = event.get('qualifiers', {}).get(k)
        if v is None: return False
        if isinstance(v, float) and pd.isna(v): return False
        return v not in [False, 0, 0.0, 'False', 'false', '0', '0.0', '']

    def has_qualifier_with_value(self, event: Dict, key: str, value: Any) -> bool:
        k = str(key).lower().strip()
        v = event.get('qualifiers', {}).get(k)
        if v is None: return False
        if isinstance(v, float) and pd.isna(v): return False
        try:
            if float(v) == float(value): return True
        except (ValueError, TypeError):
            if str(v).lower().strip() == str(value).lower().strip(): return True
        if v in [True, 1, 1.0, 'True', 'true', 'Yes', 'yes']: return True
        return False

    def process_file(self, file_path: str) -> List[Dict]:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path)
            df_header = pd.read_excel(file_path, header=None, nrows=3)
        else:
            encodings = ['utf-8', 'latin-1', 'cp1252', 'utf-16']
            df, df_header = None, None
            for enc in encodings:
                try:
                    df = pd.read_csv(file_path, encoding=enc)
                    df_header = pd.read_csv(file_path, header=None, nrows=3, encoding=enc)
                    break
                except: continue
            if df is None:
                df = pd.read_csv(file_path)
                df_header = pd.read_csv(file_path, header=None, nrows=3)
            
        rows = df.to_dict('records')
        home, away, score, venue, season = 'Équipe Domicile', 'Équipe Extérieur', 'N/A', 'Stade ?', '?'
        if rows:
            r0 = rows[0]
            score = str(r0.get('ft', score)); venue = str(r0.get('venueName', venue)); season = str(r0.get('season', season))
        if len(df_header) >= 3:
            h = list(df_header.iloc[0]); r1 = list(df_header.iloc[1]); r2 = list(df_header.iloc[2])
            try:
                idx_team = h.index('teamName'); idx_ha = h.index('h_a')
                if idx_team != -1 and idx_ha != -1:
                    is_h = lambda row: 'home' in str(row[idx_ha]).lower()
                    if is_h(r1): home, away = r1[idx_team], r2[idx_team]
                    else: home, away = r2[idx_team], r1[idx_team]
            except: pass
        raw_match_name = f"{home} {score} {away}"; date_hint = ""
        if rows and 'timeStamp' in rows[0]:
            ts = rows[0]['timeStamp']
            try:
                if isinstance(ts, (int, float)): dt = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=ts)
                else: dt = pd.to_datetime(ts)
                date_hint = f" ({dt.strftime('%d/%m/%Y')})"
            except: pass
        match_name = f"{raw_match_name}{date_hint} - {season}" if season != '?' else f"{raw_match_name}{date_hint}"
        pid_to_name = {}
        for r in rows:
            p_id = r.get('playerId'); name = r.get('name') or r.get('playerName')
            if pd.notna(p_id) and pd.notna(name):
                if p_id not in pid_to_name or pid_to_name[p_id] == 'Inconnu': pid_to_name[p_id] = str(name).strip()
        ev_id_to_info = {}
        for r in rows:
            ev_id = r.get('eventId')
            if pd.notna(ev_id):
                if ev_id not in ev_id_to_info: ev_id_to_info[ev_id] = []
                team_name = r.get('teamName') or (home if 'home' in str(r.get('h_a', '')).lower() else away)
                p_name = r.get('playerName') or r.get('name') or pid_to_name.get(r.get('playerId')) or 'Inconnu'
                ev_id_to_info[ev_id].append({'playerName': str(p_name).strip(), 'teamName': str(team_name).strip()})
        events, receipts = [], []
        for i, row in enumerate(rows):
            p_id = row.get('playerId'); team = row.get('teamName') or (home if 'home' in str(row.get('h_a', '')).lower() else away)
            player = row.get('playerName') or row.get('name') or pid_to_name.get(p_id) or 'Inconnu'
            player, team = str(player).strip(), str(team).strip(); opposition_team = away if team == home else home
            def is_valid_val(val):
                if val is None: return False
                if isinstance(val, (int, float)) and pd.isna(val): return False
                return str(val).strip().lower() not in ['', 'nan', 'none', 'false', '0', '0.0']
            qualifiers = {}
            for k, v in row.items():
                k_str = str(k).strip(); prefixes = ['qualifiers.', 'type_value_', 'type.value.', 'type.value_', 'value_', 'value.']
                rk = k_str
                for p in prefixes:
                    if k_str.lower().startswith(p.lower()): rk = k_str[len(p):].strip(); break
                ck = rk.replace('_', ' ').replace('.', ' ').replace('\n', ' ').strip()
                for var in [rk, rk.lower(), ck, ck.lower()]:
                    if var not in qualifiers or (not is_valid_val(qualifiers[var]) and is_valid_val(v)): qualifiers[var] = v
            val_opp = row.get('value_OppositeRelatedEvent') or row.get('value_Opposite related event ID')
            opp_player_name = None; is_duel = row.get('type') in self.duel_types
            if val_opp:
                cand = ev_id_to_info.get(val_opp)
                if cand:
                    rel = next((c for c in cand if c['teamName'] != team), None)
                    if rel: opp_player_name, is_duel = rel['playerName'], True
            base = {
                'id': f"{os.path.basename(file_path)}-{row.get('id', i+1)}", 'eventId': row.get('eventId'), 'matchName': match_name,
                'teamName': team, 'playerName': player, 'position': row.get('formation_position') or row.get('position') or '?',
                'formation_position': row.get('formation_position'),
                'jerseyNumber': row.get('value_Jersey number.y') or row.get('value_Jersey number') or 'N/A',
                'venue': venue, 'season': season, 'score': score, 'period': row.get('period', 'N/A'), 
                'minute': float(row.get('minute', 0)), 'second': float(row.get('second', 0)),
                'cumulative_mins': float(row.get('cumulative_mins', 0)), 'type': row.get('type'), 'isDuel': is_duel,
                'outcomeType': row.get('outcomeType', 'Unknown'), 'x': float(row.get('x', 0)), 'y': float(row.get('y', 0)),
                'endX': float(row['endX']) if pd.notna(row.get('endX')) else None, 'endY': float(row['endY']) if pd.notna(row.get('endY')) else None,
                'assist': int(row['assist']) if pd.notna(row.get('assist')) else 0, 'secondAssist': 0, 'oneTwoStatus': None, 'isBigChanceCreated': False,
                'timeStamp': row.get('timeStamp'), 'h_a': row.get('h_a'), 'oppositionPlayerName': opp_player_name, 'oppositionTeamName': opposition_team,
                'possession_id': float(row['possession_id']) if pd.notna(row.get('possession_id')) else None,
                'possession_team': row.get('possession_team', team), 'formation_name': row.get('formation_name'), 'qualifiers': qualifiers, 
                'value_OppositeRelatedEvent': val_opp, 'xT': float(row['xT']) if pd.notna(row.get('xT')) else None, 'receiver': None, 
                'value_Length': float(row['value_Length']) if pd.notna(row.get('value_Length')) else None,
                'prog_pass': float(row['prog_pass']) if pd.notna(row.get('prog_pass')) else None,
                'prog_carry': float(row['prog_carry']) if pd.notna(row.get('prog_carry')) else None,
                'value_Goal mouth y coordinate': float(row['value_Goal mouth y coordinate']) if pd.notna(row.get('value_Goal mouth y coordinate')) else None,
                'value_Goal mouth z coordinate': float(row['value_Goal mouth z coordinate']) if pd.notna(row.get('value_Goal mouth z coordinate')) else None,
            }
            if base['type'] in self.unsuccessful_types: base['outcomeType'] = 'Unsuccessful'
            if base['type'] == 'Pass' and base['outcomeType'] == 'Successful' and i + 1 < len(rows):
                nxt = rows[i+1]; rn = nxt.get('playerName') or nxt.get('name') or pid_to_name.get(nxt.get('playerId'))
                if rn:
                    rt = nxt.get('teamName') or (home if 'home' in str(nxt.get('h_a', '')).lower() else away)
                    if not rt or not team or rt.lower() == team.lower():
                        rec = base.copy(); rec['id'] += "-receipt"; rec['type'] = 'Ball Receipt*'
                        rec['playerName'], rec['sender'] = rn, player; rec['cumulative_mins'] += 0.0001
                        rec['x'], rec['y'] = base['endX'], base['endY']; rec['endX'], rec['endY'], rec['assist'], rec['isDuel'] = None, None, 0, False
                        rec.pop('qualifiers', None); receipts.append(rec)
            if base['type'] != 'Carry' or (base['x'] != 0 and base['y'] != 0): events.append(base)
        all_ev = sorted(events + receipts, key=lambda x: x['cumulative_mins'])
        self.assign_receivers(all_ev); self.enrich_carries(all_ev); self.detect_special_events(all_ev)
        self.detect_second_assists(all_ev); self.analyze_possession_sequences(all_ev); self.analyze_defensive_actions(all_ev)
        self.assign_main_positions(all_ev); self.apply_advanced_filters(all_ev)
        return all_ev

    def assign_receivers(self, all_events):
        for i, event in enumerate(all_events):
            if event['type'] == 'Pass' and event['outcomeType'] == 'Successful':
                pt = event['teamName'].lower() if event['teamName'] else None
                for j in range(i + 1, len(all_events)):
                    nxt = all_events[j]
                    if nxt['cumulative_mins'] - event['cumulative_mins'] > 5/60: break
                    if nxt['type'] == 'Ball Receipt*' and nxt.get('sender') == event['playerName']:
                        rt = nxt['teamName'].lower() if nxt['teamName'] else None
                        if not rt or not pt or rt == pt: event['receiver'] = nxt['playerName']; break

    def enrich_carries(self, all_events):
        for i, event in enumerate(all_events):
            if event['type'] == 'Carry':
                for j in range(i + 1, len(all_events)):
                    nx = all_events[j]
                    if nx['playerName'] == event['playerName'] and nx['type'] != 'Carry':
                        event['endX'], event['endY'] = nx['x'], nx['y']
                        dx, dy = (nx['x']-event['x'])*1.05, (nx['y']-event['y'])*0.68
                        dist, dt = math.sqrt(dx**2 + dy**2), (nx['cumulative_mins']-event['cumulative_mins'])*60
                        event['carry_distance'] = dist
                        if dist > 1 and dt > 0: event['carrySpeed_mps'] = dist/dt; event['carrySpeed_kmh'] = (dist/dt)*3.6
                        break
        ev_id_to_out = {e['eventId']: e['outcomeType'] for e in all_events if e['eventId']}
        for i in range(len(all_events)-1, -1, -1):
            e = all_events[i]
            if e['type'] == 'Carry':
                rel = e.get('qualifiers', {}).get('relatedEventId') or e.get('relatedEventId')
                if rel and rel in ev_id_to_out:
                    out = ev_id_to_out[rel]; e['outcomeType'] = out
                    if e['eventId']: ev_id_to_out[e['eventId']] = out

    def detect_special_events(self, all_events):
        idx = 0
        while idx < len(all_events):
            e1 = all_events[idx]; t1 = e1['teamName'].lower() if e1['teamName'] else None
            if e1['type'] == 'Pass' and e1['outcomeType'] == 'Successful' and e1.get('receiver'):
                for j in range(idx + 1, len(all_events)):
                    nxt = all_events[j]
                    if nxt['cumulative_mins'] - e1['cumulative_mins'] > 10/60: break
                    t2 = nxt['teamName'].lower() if nxt['teamName'] else None
                    if t1 and t2 and t1 == t2 and nxt['type'] == 'Pass' and nxt['outcomeType'] == 'Successful' and nxt.get('receiver'):
                        if e1['playerName'] == nxt.get('receiver') and e1.get('receiver') == nxt['playerName']:
                            e1['oneTwoStatus'], nxt['oneTwoStatus'] = 'initiator', 'return'
                            e1['one_two_initiator'] = nxt['one_two_initiator'] = e1['playerName']
                            e1['one_two_returner'] = nxt['one_two_returner'] = nxt['playerName']
                            idx = j; break
            if e1['type'] in ['Shot', 'MissedShots', 'Goal'] and self.has_qualifier_with_value(e1, 'Big Chance', 214):
                for k in range(idx - 1, -1, -1):
                    p = all_events[k]
                    if e1['cumulative_mins'] - p['cumulative_mins'] > 5/60: break
                    if p['teamName'] == e1['teamName'] and p['type'] == 'Pass' and p['outcomeType'] == 'Successful':
                        p['isBigChanceCreated'] = True; break
            idx += 1

    def detect_second_assists(self, all_events):
        for i, e in enumerate(all_events):
            if e['type'] == 'Pass' and e.get('assist') == 1:
                for j in range(i - 1, -1, -1):
                    p = all_events[j]
                    if e['cumulative_mins'] - p['cumulative_mins'] > 15/60 or (p['type'] == 'Pass' and p['outcomeType'] == 'Unsuccessful' and p['teamName'] == e['teamName']): break
                    if p['type'] == 'Pass' and p['outcomeType'] == 'Successful' and p['teamName'] == e['teamName']: p['secondAssist'] = 1; break

    def analyze_possession_sequences(self, all_events):
        pg = {}
        for ev in all_events:
            pid = ev.get('possession_id')
            if pid is not None:
                if pid not in pg: pg[pid] = []
                pg[pid].append(ev)
        stypes = ['Goal', 'SavedShot', 'MissedShots', 'ShotOnPost', 'Shot']
        for pid, evs in pg.items():
            sh, gl = any(e['type'] in stypes for e in evs), any(e['type'] == 'Goal' for e in evs)
            fb = any(self.has_qualifier_with_value(e, 'Fast Break', 23) for e in evs)
            pc = sum(1 for e in evs if e['type'] == 'Pass' and e['outcomeType'] == 'Successful')
            pt = next((e.get('possession_team') for e in evs if e.get('possession_team')), None)
            for e in evs:
                if pt is None or e.get('teamName') == pt: e['seq_has_shot'], e['seq_has_goal'], e['seq_is_fast_break'], e['seq_pass_count'] = sh, gl, fb, pc

    def analyze_defensive_actions(self, all_events):
        for i, e in enumerate(all_events):
            isr = e['type'] in ['BallRecovery', 'Interception'] or (e['type'] == 'Tackle' and e['outcomeType'] == 'Successful')
            if isr:
                if e['x'] >= 60 and e.get('seq_has_shot', False): e['is_high_turnover_chance'] = True
                for j in range(i - 1, -1, -1):
                    prv = all_events[j]
                    if e['cumulative_mins'] - prv['cumulative_mins'] > 7/60: break
                    if prv['teamName'] == e['teamName'] and prv['x'] >= 50 and (prv['type'] in ['Dispossessed'] or (prv['type'] in ['BallTouch', 'TakeOn', 'Pass'] and prv['outcomeType'] == 'Unsuccessful')):
                        e['is_gegenpressing'] = True; break

    def assign_main_positions(self, all_events):
        counts = {}
        for e in all_events:
            p, r = e['playerName'], e.get('position')
            if p and r and r != '?':
                cat = self.position_mapping.get(r) or self.position_mapping.get(str(r).upper())
                if cat:
                    if p not in counts: counts[p] = {}
                    counts[p][cat] = counts[p].get(cat, 0) + 1
        pm = {p: max(cats, key=cats.get) for p, cats in counts.items()}
        for e in all_events: e['mainPositionCategory'] = pm.get(e['playerName'], 'Inconnu')

    def apply_advanced_filters(self, all_events):
        for e in all_events:
            # Existing filters (L529+)
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
            e['adv_PROGRESSIVE_ACTION_10M'] = (e['type'] in ['Pass', 'Carry']) and e.get('endX') is not None and (e['endX'] - e['x'] >= 10)
            e['adv_PENETRATING_PASS_AREA'] = e['type'] == 'Pass' and not (e['x'] >= 88.5 and 13.84 <= e['y'] <= 54.16) and (e.get('endX', 0) >= 88.5 and 13.84 <= e.get('endY', 0) <= 54.16)
            e['adv_PENETRATING_CARRY_AREA'] = e['type'] == 'Carry' and not (e['x'] >= 88.5 and 13.84 <= e['y'] <= 54.16) and (e.get('endX', 0) >= 88.5 and 13.84 <= e.get('endY', 0) <= 54.16)
            e['adv_ERROR_LEAD_TO_GOAL'] = e['type'] == 'Error' and self.has_qualifier_with_value(e, 'Leading to goal', 170)
            e['adv_ERROR_LEAD_TO_SHOT'] = e['type'] == 'Error' and self.has_qualifier_with_value(e, 'Leading to attempt', 169)
            e['adv_YELLOW_CARD'] = e.get('cardType') == 'Yellow' or self.has_qualifier_with_value(e, 'Yellow Card', 31)
            e['adv_RED_CARD'] = e.get('cardType') == 'Red' or self.has_qualifier_with_value(e, 'Red Card', 33)

            # Possession Sequences (Build-up) Filters
            e['adv_PART_OF_SHOT_SEQUENCE'] = e.get('seq_has_shot') == True
            e['adv_PART_OF_GOAL_SEQUENCE'] = e.get('seq_has_goal') == True
            e['adv_FAST_BREAK_SEQUENCE'] = e.get('seq_is_fast_break') == True
            e['adv_10_PLUS_PASS_SEQUENCE'] = e.get('seq_pass_count', 0) >= 10
            e['adv_15_PLUS_PASS_SEQUENCE'] = e.get('seq_pass_count', 0) >= 15

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

            shot_types = ['Goal', 'SavedShot', 'MissedShots', 'ShotOnPost', 'Shot']
            is_shot = e['type'] in shot_types
            e['adv_SHOT_SWERVE_LEFT'] = is_shot and self.has_qualifier_with_value(e, 'Swerve Left', 120)
            e['adv_SHOT_SWERVE_RIGHT'] = is_shot and self.has_qualifier_with_value(e, 'Swerve Right', 121)
            e['adv_SHOT_FAST_BREAK'] = is_shot and self.has_qualifier_with_value(e, 'Fast Break', 23)
            e['adv_SHOT_ONE_ON_ONE'] = is_shot and self.has_qualifier_with_value(e, '1 on 1', 89)
            e['adv_SHOT_DEFLECTION'] = is_shot and self.has_qualifier_with_value(e, 'Deflection', 133)
            e['adv_SHOT_BLOCKED'] = is_shot and self.has_qualifier_with_value(e, 'Blocked', 89)
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

            if is_shot:
                tx = 100 if e['x'] > 50 else 0; ty = 50
                dx, dy = (e['x']-tx)*1.05, (e['y']-ty)*0.68
                e['shot_distance'] = math.sqrt(dx**2 + dy**2)
                gy, gz = e.get('value_Goal mouth y coordinate'), e.get('value_Goal mouth z coordinate')
                if gy is not None and gz is not None:
                    vp = "Top" if gz > 24 else ("Middle" if gz > 12 else "Bottom")
                    hp = "Left" if gy > 51.67 else ("Right" if gy < 48.33 else "Center")
                    e['shot_goal_zone'] = f"{vp} {hp}"

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
            is_handball = any('hand' in k.lower() for k in e.get('qualifiers', {}).keys() if self.has_qualifier_with_value(e, k, 10))
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

# =============================================================================
# LOGIQUE DE BATCH PORTABLE
# =============================================================================

def proc_file(fp):
    processor = OptaProcessor(); fn = os.path.basename(fp)
    bn, _ = os.path.splitext(fp); dn = os.path.dirname(fp); cp = bn + "_PROCESSED_OPTA.csv"
    try:
        pref = os.path.basename(bn)
        for f in os.listdir(dn):
            if f.startswith(pref) and "_PROCESSED_OPTA" in f:
                try: os.remove(os.path.join(dn, f))
                except: pass
        data = processor.process_file(fp)
        pd.DataFrame(data).to_csv(cp, index=False, encoding='utf-8')
        return f"OK: {fn}"
    except Exception as e: return f"ERROR: {fn} -> {e}"

def run_portable():
    sd = os.path.dirname(os.path.abspath(__file__)); sup = ('.xlsx', '.xls', '.csv')
    print("="*60 + "\n      CLIPMAKER - PORTABLE FULL 1:1 PROCESSOR\n" + "="*60)
    print(f"Scan : {sd}\n")
    to_proc = []
    for r, ds, fs in os.walk(sd):
        for f in fs:
            if "_PROCESSED_OPTA" in f: continue
            if f.lower().endswith(sup): to_proc.append(os.path.join(r, f))
    if not to_proc: print("Aucun fichier source."); os.system("pause"); return
    nw = max(1, multiprocessing.cpu_count() - 1)
    print(f"Lancement ({nw} coeurs) pour {len(to_proc)} fichiers...\n")
    with ProcessPoolExecutor(max_workers=nw) as ex:
        futs = {ex.submit(proc_file, fp): fp for fp in to_proc}
        for i, fut in enumerate(as_completed(futs), 1): print(f"[{i}/{len(to_proc)}] {fut.result()}")
    print("\n" + "="*60 + "\nTraitement 100%% Terminé.\n" + "="*60); os.system("pause")

if __name__ == "__main__":
    multiprocessing.freeze_support(); run_portable()
