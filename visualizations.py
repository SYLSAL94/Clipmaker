import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

def _get_title_info(df):
    """Return (main_title, sub_label) based on player/team in the data."""
    team_name = ""
    player_name = ""
    p_col = 'playerName' if 'playerName' in df.columns else 'name' if 'name' in df.columns else None
    if 'teamName' in df.columns and not df.empty:
        team_name = str(df['teamName'].iloc[0])
    if p_col:
        unique_players = df[p_col].dropna().unique()
        unique_players = [p for p in unique_players if str(p) not in ('nan', '', 'Inconnu')]
        if len(unique_players) == 1:
            player_name = str(unique_players[0])
    
    if player_name and team_name:
        return player_name.upper(), f"({team_name})"
    elif player_name:
        return player_name.upper(), ""
    elif team_name:
        return team_name.upper(), ""
    return "ÉQUIPE", ""

def plot_events_on_pitch(df, show_heatmap=True, show_hull=True, show_center=True, show_names=True):
    """
    Generate a professional mplsoccer Pitch plot with a premium aesthetic.
    Covers ALL event types: Passes, Carries, Shots, TakeOns, Defensive actions, etc.
    """
    try:
        from mplsoccer import Pitch, FontManager
        from scipy.spatial import ConvexHull
        import matplotlib.pyplot as plt
        from matplotlib.colors import LinearSegmentedColormap
    except ImportError:
        return None, "Les modules requis (mplsoccer, scipy, matplotlib) ne sont pas installés."

    try:
        if df is None or df.empty:
            pitch = Pitch(pitch_type='custom', pitch_length=105, pitch_width=68, 
                          pitch_color='#1a1d23', line_color='#454a54')
            fig, ax = pitch.draw(figsize=(12, 8))
            return fig, None

        # --- 1. CONFIGURATION DU PITCH & GRID ---
        bg_color = '#1a1d23'
        line_color = '#454a54'
        
        pitch = Pitch(pitch_type='custom', pitch_length=105, pitch_width=68, 
                      pitch_color=bg_color, line_color=line_color, line_zorder=2)
        
        fig, axs = pitch.grid(endnote_height=0.03, endnote_space=0, figheight=12,
                              title_height=0.08, title_space=0,
                              axis=False, grid_height=0.82)
        fig.set_facecolor(bg_color)
        ax = axs['pitch']

        # Données valides
        df_valid = df.dropna(subset=['x', 'y']).copy()
        for c in ['x', 'y', 'endX', 'endY']:
            if c in df_valid.columns:
                df_valid[c] = pd.to_numeric(df_valid[c], errors='coerce')
        df_valid = df_valid.dropna(subset=['x', 'y'])
        
        if df_valid.empty:
            return fig, None

        # --- 2. HEATMAP (Optionnelle) ---
        if show_heatmap and len(df_valid) > 2:
            try:
                pitch.kdeplot(df_valid.x, df_valid.y, ax=ax, 
                              cmap='Greens', fill=True, alpha=0.12, levels=8, zorder=1)
            except: pass

        # --- 3. CONVEX HULL / TERRITOIRE ---
        if show_hull and len(df_valid) >= 3:
            try:
                points = df_valid[['x', 'y']].values
                hull = ConvexHull(points)
                ax.fill(points[hull.vertices, 0], points[hull.vertices, 1], color='#00d9ff', alpha=0.03, zorder=1)
                for simplex in hull.simplices:
                    ax.plot(points[simplex, 0], points[simplex, 1], color='#00d9ff', linestyle=':', alpha=0.2, zorder=2, lw=1)
            except: pass

        # --- 4. POSITION MOYENNE ---
        if show_center:
            avg_x, avg_y = df_valid.x.mean(), df_valid.y.mean()
            ax.scatter(avg_x, avg_y, color='#00ff88', s=250, marker='o', edgecolors='white', linewidth=2, zorder=10, alpha=0.8)

        # --- 5. CLASSIFICATION DES ACTIONS ---
        df_valid['is_success'] = df_valid['outcomeType'].astype(str) == 'Successful'
        has_ends = "endX" in df_valid.columns and "endY" in df_valid.columns
        
        # == PASSES ==
        passes = df_valid[df_valid['type'].astype(str) == 'Pass'].copy()
        if has_ends and not passes.empty:
            complete = passes[passes['is_success']].dropna(subset=['endX', 'endY'])
            incomplete = passes[~passes['is_success']].dropna(subset=['endX', 'endY'])
            
            if not complete.empty:
                pitch.lines(complete.x, complete.y, complete.endX, complete.endY,
                            lw=4, transparent=True, comet=True, label='Passes Réussies',
                            color='#ad993c', ax=ax, zorder=4)
            if not incomplete.empty:
                pitch.lines(incomplete.x, incomplete.y, incomplete.endX, incomplete.endY,
                            lw=3, transparent=True, comet=True, label='Passes Manquées',
                            color='#ba4f45', ax=ax, alpha=0.5, zorder=3)

        # == CARRIES (Conduites de balle) — Style gradient avec flèche ==
        carries = df_valid[df_valid['type'].astype(str) == 'Carry'].copy()
        if has_ends and not carries.empty:
            carries_with_ends = carries.dropna(subset=['endX', 'endY'])
            if not carries_with_ends.empty:
                # Calcul de la distance progressive pour colorer
                carries_with_ends = carries_with_ends.copy()
                carries_with_ends['dx'] = carries_with_ends['endX'] - carries_with_ends['x']
                carries_with_ends['dist'] = np.sqrt(
                    (carries_with_ends['endX'] - carries_with_ends['x'])**2 + 
                    (carries_with_ends['endY'] - carries_with_ends['y'])**2
                )
                
                # Séparer Carry progressives et recul
                progressive = carries_with_ends[carries_with_ends['dx'] > 10]
                neutral = carries_with_ends[(carries_with_ends['dx'] >= -10) & (carries_with_ends['dx'] <= 10)]
                regressive = carries_with_ends[carries_with_ends['dx'] < -10]
                
                # Progressive carries — Turquoise gradient, épaisseur selon distance
                if not progressive.empty:
                    pitch.lines(progressive.x, progressive.y, progressive.endX, progressive.endY,
                                lw=3, transparent=True, comet=True, 
                                color='#00d9ff', ax=ax, zorder=4, alpha=0.7, label='Conduites Progressives')
                    # Flèches de direction
                    for _, row in progressive.iterrows():
                        ax.annotate('', xy=(row['endX'], row['endY']), xytext=(row['x'], row['y']),
                                    arrowprops=dict(arrowstyle='-|>', color='#00d9ff', lw=2.5, alpha=1.0, mutation_scale=25),
                                    zorder=5)
                
                # Neutral carries — blanc subtil
                if not neutral.empty:
                    pitch.lines(neutral.x, neutral.y, neutral.endX, neutral.endY,
                                lw=2, transparent=True, comet=True, 
                                color='#ffffff', ax=ax, zorder=3, alpha=0.2, label='Conduites Latérales')
                
                # Regressive carries — orange
                if not regressive.empty:
                    pitch.lines(regressive.x, regressive.y, regressive.endX, regressive.endY,
                                lw=3, transparent=True, comet=True, 
                                color='#e67e22', ax=ax, zorder=3, alpha=0.4, label='Conduites en Recul')
                    
                # Points de départ de toutes les conduites  
                pitch.scatter(carries_with_ends.x, carries_with_ends.y, 
                              c='#00d9ff', s=30, ax=ax, zorder=5, edgecolors='white', linewidths=0.5, alpha=0.6)

        # == TIRS ==
        shot_types = ['Goal', 'SavedShot', 'MissedShots', 'ShotOnPost', 'Shot']
        shots = df_valid[df_valid['type'].astype(str).str.contains('|'.join(shot_types), case=False, na=False)].copy()
        if not shots.empty:
            goals = shots[shots['type'].astype(str).str.contains('Goal', case=False, na=False)]
            saved = shots[shots['type'].astype(str).str.contains('SavedShot', case=False, na=False)]
            others_shots = shots[~shots.index.isin(goals.index) & ~shots.index.isin(saved.index)]
            
            if not goals.empty:
                pitch.scatter(goals.x, goals.y, marker='football', c='#2ecc71', s=450, ax=ax, zorder=6, edgecolors='white', linewidths=2, label='Buts')
            if not saved.empty:
                pitch.scatter(saved.x, saved.y, marker='football', c='#f1c40f', s=300, ax=ax, zorder=6, edgecolors='white', linewidths=1.5, label='Arrêts')
            if not others_shots.empty:
                pitch.scatter(others_shots.x, others_shots.y, marker='football', c='#e74c3c', s=250, ax=ax, zorder=6, edgecolors='white', linewidths=1, alpha=0.8, label='Tirs (Autres)')

        # == TAKE ON (Dribbles) ==
        takeons = df_valid[df_valid['type'].astype(str) == 'TakeOn'].copy()
        if not takeons.empty:
            to_success = takeons[takeons['is_success']]
            to_fail = takeons[~takeons['is_success']]
            if not to_success.empty:
                pitch.scatter(to_success.x, to_success.y, c='#e74c3c', s=180, ax=ax, zorder=5, 
                              edgecolors='white', linewidths=1.5, marker='D', alpha=0.9, label='Dribble Réussi')
            if not to_fail.empty:
                pitch.scatter(to_fail.x, to_fail.y, c='#c0392b', s=120, ax=ax, zorder=5, 
                              edgecolors='white', linewidths=1, marker='D', alpha=0.4, label='Dribble Raté')

        # == ACTIONS DÉFENSIVES (Tackle, Interception, Clearance, BallRecovery, BlockedPass, Aerial) ==
        defensive_types = ['Tackle', 'Interception', 'Clearance', 'BallRecovery', 'BlockedPass', 'Aerial']
        defensive = df_valid[df_valid['type'].astype(str).isin(defensive_types)].copy()
        if not defensive.empty:
            # Couleurs et marqueurs par type défensif
            def_styles = {
                'Tackle':       {'color': '#3498db', 'marker': 's', 'label': 'Tacles'},
                'Interception': {'color': '#2ecc71', 'marker': '^', 'label': 'Interceptions'},
                'Clearance':    {'color': '#9b59b6', 'marker': 'v', 'label': 'Dégagements'},
                'BallRecovery': {'color': '#1abc9c', 'marker': 'p', 'label': 'Récupérations'},
                'BlockedPass':  {'color': '#e67e22', 'marker': 'h', 'label': 'Passes Bloquées'},
                'Aerial':       {'color': '#f39c12', 'marker': '8', 'label': 'Duels Aériens'},
            }
            
            for dtype, style in def_styles.items():
                dtype_df = defensive[defensive['type'].astype(str) == dtype]
                if not dtype_df.empty:
                    success = dtype_df[dtype_df['is_success']]
                    fail = dtype_df[~dtype_df['is_success']]
                    if not success.empty:
                        pitch.scatter(success.x, success.y, c=style['color'], s=130, ax=ax, zorder=5,
                                      edgecolors='white', linewidths=1.2, marker=style['marker'], 
                                      alpha=0.9, label=f"{style['label']} ✅")
                    if not fail.empty:
                        pitch.scatter(fail.x, fail.y, c=style['color'], s=80, ax=ax, zorder=5,
                                      edgecolors='white', linewidths=0.8, marker=style['marker'], 
                                      alpha=0.35, label=f"{style['label']} ❌")

        # == FOUL / DISPOSSESSED / OTHER ==
        misc_types = ['Foul', 'Dispossessed', 'OffsidePass', 'CornerAwarded', 'KeeperPickup',
                      'End', 'Start', 'SubstitutionOn', 'SubstitutionOff', 'FormationChange',
                      'FormationSet', 'Card']
        others = df_valid[
            ~df_valid['type'].astype(str).isin(['Pass', 'Carry'] + shot_types + ['TakeOn'] + defensive_types + misc_types)
        ].copy()
        if not others.empty:
            others_success = others[others['is_success']]
            others_fail = others[~others['is_success']]
            
            if not others_success.empty:
                pitch.scatter(others_success.x, others_success.y, c='#1abc9c', s=100, ax=ax, zorder=5, edgecolors='white', alpha=0.9, label='Autres ✅')
            if not others_fail.empty:
                pitch.scatter(others_fail.x, others_fail.y, c='#95a5a6', s=80, ax=ax, zorder=5, edgecolors='white', alpha=0.5, label='Autres ❌')

        # --- 6. LABELS & TYPOGRAPHIE ---
        if show_names and len(df_valid) < 50:
            for _, row in df_valid.iterrows():
                p_name = str(row.get('playerName', ''))
                if p_name and p_name != 'nan':
                    short_name = p_name.split(' ')[-1]
                    ax.text(row.x, row.y + 2, short_name, color='white', fontsize=9, ha='center', fontweight='bold', alpha=0.8, zorder=7)

        # --- 7. STATS RÉSUMÉ ---
        n_pass = len(df_valid[df_valid['type'].astype(str) == 'Pass'])
        n_carry = len(df_valid[df_valid['type'].astype(str) == 'Carry'])
        n_shot = len(shots) if not shots.empty else 0
        n_tackle = len(df_valid[df_valid['type'].astype(str).isin(defensive_types)])
        n_dribble = len(df_valid[df_valid['type'].astype(str) == 'TakeOn'])
        
        stats_parts = []
        if n_pass > 0: stats_parts.append(f"{n_pass} passes")
        if n_carry > 0: stats_parts.append(f"{n_carry} conduites")
        if n_dribble > 0: stats_parts.append(f"{n_dribble} dribbles")
        if n_tackle > 0: stats_parts.append(f"{n_tackle} défensifs")
        if n_shot > 0: stats_parts.append(f"{n_shot} tirs")
        stats_str = " · ".join(stats_parts) if stats_parts else f"{len(df_valid)} actions"

        # --- 8. TITRE & NOTES ---
        main_title, sub_label = _get_title_info(df_valid)
        
        axs['title'].text(0.5, 0.7, main_title, color='#dee6ea', va='center', ha='center', fontsize=30, fontweight='bold')
        if sub_label:
            axs['title'].text(0.5, 0.42, sub_label, color='#aaaaaa', va='center', ha='center', fontsize=18)
        axs['title'].text(0.5, 0.12, stats_str, color='#888888', va='center', ha='center', fontsize=14)
        
        axs['endnote'].text(1, 0.5, 'Généré par ClipMaker by B4L1', va='center', ha='right', fontsize=12, color='#454a54', fontstyle='italic')

        # Légende — dédupliquée et compacte
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            by_label = dict(zip(labels, handles))
            ncol = min(4, len(by_label))
            legend = ax.legend(by_label.values(), by_label.keys(), facecolor=bg_color, handlelength=3, 
                               edgecolor='None', loc='lower center', bbox_to_anchor=(0.5, -0.05), ncol=ncol)
            plt.setp(legend.get_texts(), color='#dee6ea', fontsize=11)

        return fig, None
    except Exception as e:
        import traceback
        return None, f"Erreur lors de la création de la carte : {str(e)}\n{traceback.format_exc()}"

def plot_goal_map(df):
    """
    Génère une vue de face de la cage (Goalmouth) PREMIUM et RÉALISTE.
    Effets de profondeur sur les poteaux, pelouse texturée, filet hexagonal
    et rendu 3D des impacts.
    """
    try:
        if df is None or df.empty:
            return None, "Pas de données pour la cage."
            
        shot_types = ['Goal', 'SavedShot', 'MissedShots', 'ShotOnPost', 'Shot']
        shots = df[df['type'].astype(str).str.contains('|'.join(shot_types), case=False, na=False)].copy()
        
        if shots.empty:
            return None, "Aucun tir sélectionné."

        # Coordonnées cibles Opta
        shots['y_goal'] = pd.to_numeric(shots['value_Goal mouth y coordinate'], errors='coerce')
        shots['z_goal'] = pd.to_numeric(shots['value_Goal mouth z coordinate'], errors='coerce')
        shots = shots.dropna(subset=['y_goal', 'z_goal'])
        
        if shots.empty:
            return None, "Coordonnées de cage absentes."

        # Configuration visuelle premium
        bg_color = '#0b0e14' # Darker UI matching app
        post_color = '#fdfdfd'
        grass_color = '#152b1f'
        grass_line = '#00ff88'
        
        fig, ax = plt.subplots(figsize=(14, 7))
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)
        
        # --- 1. DESSIN DE LA PELOUSE (Bas réaliste) ---
        # Dégradé pour le sol
        ground_rect = patches.Rectangle((-200, -100), 1000, 100, facecolor=grass_color, alpha=0.8, zorder=1)
        ax.add_patch(ground_rect)
        ax.axhline(0, color=grass_line, lw=3, alpha=0.3, zorder=2) # Ligne de but
        
        # --- 2. DESSIN DU FILET (Amélioré) ---
        # Utilisation d'une grille plus dense et bleutée pour l'effet de profondeur
        for x_net in np.linspace(0, 600, 31):
            ax.plot([x_net, x_net], [0, 250], color='#2a3547', lw=0.5, alpha=0.2, zorder=1)
        for y_net in np.linspace(0, 250, 16):
            ax.plot([0, 600], [y_net, y_net], color='#2a3547', lw=0.5, alpha=0.2, zorder=1)

        # --- 3. DESSIN DE LA CAGE (Poteaux 3D RÉALISTES - Pas de barre au sol) ---
        # Ombre portée au sol
        shadow_ground = patches.Rectangle((-15, -8), 630, 15, facecolor='black', alpha=0.15, zorder=3)
        ax.add_patch(shadow_ground)
        
        # Structure en U inversé (Gauche -> Haut -> Droite) pour éviter la barre au sol
        goal_x = [0, 0, 600, 600]
        goal_y = [0, 250, 250, 0]
        
        # Ombre de la structure pour le relief
        ax.plot([x-4 for x in goal_x], [y-4 for y in goal_y], color='black', lw=15, alpha=0.2, solid_capstyle='round', zorder=4)
        
        # Poteaux et barre (Blanc pur épais)
        ax.plot(goal_x, goal_y, color=post_color, lw=14, solid_capstyle='round', zorder=6)
        
        # Reflet sur le dessus de la barre transversale
        ax.plot([4, 596], [250, 250], color='white', lw=2, alpha=0.7, zorder=7)
        
        # Bouchons en bas des poteaux (pour l'ancrage)
        ax.scatter([0, 600], [0, 0], color=post_color, s=110, zorder=6)
        
        # --- 4. ZONES DE TIR SUBTILES ---
        for x_line in [200, 400]:
            ax.plot([x_line, x_line], [0, 250], color='#00ff88', linestyle=':', alpha=0.08, linewidth=1, zorder=4)
        for y_line in [83.3, 166.7]:
            ax.plot([0, 600], [y_line, y_line], color='#00ff88', linestyle=':', alpha=0.08, linewidth=1, zorder=4)
        
        # --- 5. PLOTTING DES IMPACTS (Effet 3D) ---
        colors = {'goal': '#00ff88', 'saved': '#ffcc00', 'missed': '#ff3366', 'post': '#cccccc'}
        
        for _, shot in shots.iterrows():
            y_opta, z_opta = shot['y_goal'], shot['z_goal']
            stype = str(shot['type']).lower()
            
            pixelX = (1 - (y_opta - 45) / 10) * 600
            pixelY = (z_opta / 36) * 250
            
            # Détermination style
            if 'goal' in stype:
                c, s, label, alpha = colors['goal'], 500, 'But ✅', 1.0
                # Halo lumineux pour les buts
                ax.scatter(pixelX, pixelY, color=c, s=s*2.5, alpha=0.15, zorder=9, edgecolors='none')
            elif 'saved' in stype:
                c, s, label, alpha = colors['saved'], 350, 'Arrêt 👐', 0.9
            elif 'post' in stype or 'woodwork' in stype:
                c, s, label, alpha = colors['post'], 300, 'Poteau 🥅', 1.0
            else:
                c, s, label, alpha = colors['missed'], 250, 'Hors-cadre ❌', 0.7
                
            # Ombre portée de la balle
            ax.scatter(pixelX+2, pixelY-2, color='black', s=s, alpha=0.3, zorder=10)
            
            # La balle elle-même avec bordure lumineuse
            ax.scatter(pixelX, pixelY, color=c, s=s, edgecolors='white', linewidth=1.5, zorder=11, label=label, alpha=alpha)
            
            # Point central blanc (reflet)
            ax.scatter(pixelX, pixelY, color='white', s=s/8, alpha=0.5, zorder=12)

        # --- 6. FINITION ---
        ax.set_xlim(-80, 680)
        ax.set_ylim(-40, 360) # Un peu plus d'espace en bas pour la pelouse
        ax.set_aspect('equal')
        ax.axis('off')
        
        # Titres Premium
        main_title, sub_label = _get_title_info(df)
        title_text = main_title.upper()
        ax.text(300, 335, title_text, color='white', fontsize=26, fontweight='bold', ha='center', fontfamily='Arial')
        ax.text(300, 305, f"{sub_label} · {len(shots)} tentatives".strip(' ·'), color='#70757e', fontsize=14, ha='center', fontstyle='italic')

        # Légende
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            by_label = dict(zip(labels, handles))
            legend = ax.legend(by_label.values(), by_label.keys(), loc='lower center', 
                               bbox_to_anchor=(0.5, -0.05), ncol=len(by_label), frameon=False)
            plt.setp(legend.get_texts(), color='#dee6ea', fontsize=11)
            
        return fig, None
    except Exception as e:
        import traceback
        return None, f"Erreur vue cage : {str(e)}\n{traceback.format_exc()}"

def plot_vertical_shot_map(df):
    """
    Vertical view focused on ALL Offensive Actions: 
    Passes, Carries, TakeOns, Shot Creation, and Shots.
    """
    try:
        from mplsoccer import VerticalPitch
        import matplotlib.pyplot as plt
    except ImportError:
        return None, "Le module 'mplsoccer' n'est pas installé."

    try:
        if df is None or df.empty:
            return None, "Pas de données."

        bg_color = '#1a1d23'
        line_color = '#c7d5cc'
        
        # --- Identification des types spéciaux ---
        def is_true(series):
            return series.astype(str).str.lower() == 'true'

        df_c = df.copy()
        for col in ['assist', 'adv_assist', 'keyPass', 'adv_keyPass', 'adv_key_pass', 'bigChanceCreated', 'adv_big_chance_created']:
            if col in df_c.columns:
                df_c[col] = df_c[col].fillna(False)

        # Big Chances Created
        bcc_mask = pd.Series(False, index=df_c.index)
        for col in ['bigChanceCreated', 'adv_big_chance_created']:
            if col in df_c.columns: bcc_mask |= (df_c[col] == True)
        
        # Assists
        assist_mask = pd.Series(False, index=df_c.index)
        for col in ['assist', 'adv_assist']:
            if col in df_c.columns: assist_mask |= (df_c[col] == True)
            
        # Key Passes
        kp_mask = pd.Series(False, index=df_c.index)
        for col in ['keyPass', 'adv_keyPass', 'adv_key_pass']:
            if col in df_c.columns: kp_mask |= (df_c[col] == True)

        # Ensure numeric coordinates
        for c in ['x', 'y', 'endX', 'endY']:
            if c in df_c.columns:
                df_c[c] = pd.to_numeric(df_c[c], errors='coerce')

        has_ends = "endX" in df_c.columns and "endY" in df_c.columns

        # Shots
        shot_types = ['Goal', 'SavedShot', 'MissedShots', 'ShotOnPost', 'Shot']
        all_shots = df_c[df_c['type'].astype(str).str.contains('|'.join(shot_types), case=False, na=False)].copy()
        
        # Passes
        is_pass = df_c['type'].astype(str) == 'Pass'
        passes_normal = df_c[is_pass & ~assist_mask & ~kp_mask & ~bcc_mask].copy()
        passes_assist = df_c[is_pass & assist_mask].copy()
        passes_kp = df_c[is_pass & kp_mask & ~assist_mask].copy()
        passes_bcc = df_c[is_pass & bcc_mask].copy()

        # Carries
        carries = df_c[df_c['type'].astype(str) == 'Carry'].copy()
        
        # TakeOns
        takeons = df_c[df_c['type'].astype(str) == 'TakeOn'].copy()

        # Vertical Pitch
        pitch = VerticalPitch(pitch_type='custom', pitch_length=105, pitch_width=68,
                              half=True, pitch_color=bg_color, line_color=line_color,
                              pad_top=2, line_zorder=2)
        
        fig, axs = pitch.grid(endnote_height=0.03, endnote_space=0, figheight=12,
                              title_height=0.1, title_space=0, axis=False,
                              grid_height=0.82)
        fig.set_facecolor(bg_color)
        ax = axs['pitch']

        # --- DRAWING ---
        
        # 1. Normal Construction Passes (Subtle)
        if has_ends and not passes_normal.empty:
            pn = passes_normal.dropna(subset=['endX', 'endY'])
            if not pn.empty:
                pitch.lines(pn.x, pn.y, pn.endX, pn.endY,
                            lw=4, transparent=True, comet=True, color='#ad993c',
                            alpha=0.15, ax=ax, label='Construction', zorder=3)

        # 2. Key Passes
        if has_ends and not passes_kp.empty:
            pk = passes_kp.dropna(subset=['endX', 'endY'])
            if not pk.empty:
                pitch.lines(pk.x, pk.y, pk.endX, pk.endY,
                            lw=6, transparent=True, comet=True, color='#f1c40f',
                            alpha=0.6, ax=ax, label='Passes Clés', zorder=4)

        # 3. Assists
        if has_ends and not passes_assist.empty:
            pa = passes_assist.dropna(subset=['endX', 'endY'])
            if not pa.empty:
                pitch.lines(pa.x, pa.y, pa.endX, pa.endY,
                            lw=10, transparent=True, comet=True, color='#e67e22',
                            alpha=0.8, ax=ax, label='Dernière Passe (Assist)', zorder=5)

        # 4. Big Chances Created
        if has_ends and not passes_bcc.empty:
            pb = passes_bcc.dropna(subset=['endX', 'endY'])
            if not pb.empty:
                pitch.lines(pb.x, pb.y, pb.endX, pb.endY,
                            lw=8, transparent=True, comet=True, color='#00d9ff',
                            alpha=0.9, ax=ax, label='Big Chance créée', zorder=6)
                pitch.scatter(pb.endX, pb.endY, s=100, color='#00d9ff', edgecolors='white', ax=ax, zorder=7)

        # 5. Carries — Progressive gradient arrows
        if has_ends and not carries.empty:
            carries_valid = carries.dropna(subset=['endX', 'endY']).copy()
            if not carries_valid.empty:
                carries_valid['dx'] = carries_valid['endX'] - carries_valid['x']
                
                prog_carries = carries_valid[carries_valid['dx'] > 10]
                other_carries = carries_valid[carries_valid['dx'] <= 10]
                
                if not prog_carries.empty:
                    pitch.lines(prog_carries.x, prog_carries.y, prog_carries.endX, prog_carries.endY,
                                lw=3, transparent=True, comet=True, color='#00d9ff', 
                                alpha=0.5, ax=ax, zorder=4, label='Conduites Progressives')
                    # Flèches
                    for _, row in prog_carries.iterrows():
                        ax.annotate('', xy=(row['endY'], row['endX']), xytext=(row['y'], row['x']),
                                    arrowprops=dict(arrowstyle='-|>', color='#00d9ff', lw=2.5, alpha=1.0, mutation_scale=25),
                                    zorder=5)
                
                if not other_carries.empty:
                    pitch.lines(other_carries.x, other_carries.y, other_carries.endX, other_carries.endY,
                                lw=2, transparent=True, comet=True, color='#ffffff', 
                                alpha=0.15, ax=ax, zorder=3, label='Autres Conduites')

        # 6. TakeOns
        if not takeons.empty:
            takeons_valid = takeons.dropna(subset=['x', 'y'])
            if not takeons_valid.empty:
                to_success = takeons_valid[takeons_valid['outcomeType'].astype(str) == 'Successful']
                to_fail = takeons_valid[takeons_valid['outcomeType'].astype(str) != 'Successful']
                if not to_success.empty:
                    pitch.scatter(to_success.x, to_success.y, s=200, marker='D',
                                  edgecolors='white', linewidths=1.5, c='#e74c3c', zorder=8, 
                                  label='Dribble Réussi', ax=ax, alpha=0.9)
                if not to_fail.empty:
                    pitch.scatter(to_fail.x, to_fail.y, s=120, marker='D',
                                  edgecolors='white', linewidths=1, c='#c0392b', zorder=7, 
                                  label='Dribble Raté', ax=ax, alpha=0.4)

        # 7. Shots
        if not all_shots.empty:
            goals = all_shots[all_shots['type'].astype(str).str.contains('Goal', case=False, na=False)]
            saved = all_shots[all_shots['type'].astype(str).str.contains('SavedShot', case=False, na=False)]
            missed = all_shots[~all_shots.index.isin(goals.index) & ~all_shots.index.isin(saved.index)]
            
            if not goals.empty:
                pitch.scatter(goals.x, goals.y, s=800, marker='football', 
                              edgecolors='#2ecc71', linewidths=3, c='white', zorder=10, label='BUT ✅', ax=ax)
            if not saved.empty:
                pitch.scatter(saved.x, saved.y, s=500, marker='o', 
                              edgecolors='#f1c40f', linewidths=2, c=bg_color, hatch='ooo', zorder=9, label='Tir Cadré (Arrêté)', ax=ax)
            if not missed.empty:
                pitch.scatter(missed.x, missed.y, s=400, marker='x', 
                              edgecolors='#e74c3c', linewidths=2, c='#e74c3c', alpha=0.6, zorder=8, label='Tir Non-Cadré / Bloqué', ax=ax)

        # --- Stats summary ---
        n_total = len(df)
        n_pass_total = len(df_c[is_pass])
        n_carry = len(carries)
        n_takeon = len(takeons)
        n_shots = len(all_shots)
        
        stats_parts = []
        if n_pass_total > 0: stats_parts.append(f"{n_pass_total} passes")
        if n_carry > 0: stats_parts.append(f"{n_carry} conduites")
        if n_takeon > 0: stats_parts.append(f"{n_takeon} dribbles")
        if n_shots > 0: stats_parts.append(f"{n_shots} tirs")
        subtitle = " · ".join(stats_parts) if stats_parts else f"{n_total} actions"

        # 8. Titles
        main_title, sub_label = _get_title_info(df)
        
        axs['title'].text(0.5, 0.75, main_title, color='#dee6ea', va='center', ha='center', fontsize=36, fontweight='bold')
        if sub_label:
            axs['title'].text(0.5, 0.5, sub_label, color='#aaaaaa', va='center', ha='center', fontsize=20)
        axs['title'].text(0.5, 0.2, f"FOCUS OFFENSIF · {subtitle}", color='#888888', va='center', ha='center', fontsize=16)
        
        axs['endnote'].text(1, 0.5, 'Generated by ClipMaker Analytics', va='center', ha='right', fontsize=14, color='#454a54', fontstyle='italic')

        # Legend — deduplicated
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            by_label = dict(zip(labels, handles))
            ncol = min(4, len(by_label))
            legend = ax.legend(by_label.values(), by_label.keys(), facecolor=bg_color, handlelength=4, 
                               edgecolor='None', loc='lower center', bbox_to_anchor=(0.5, -0.05), ncol=ncol)
            plt.setp(legend.get_texts(), color='#dee6ea', fontsize=13)

        return fig, None
    except Exception as e:
        import traceback
        return None, f"Erreur vue offensive : {str(e)}\n{traceback.format_exc()}"
