import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import numpy as np

def create_pitch_figure(width=105, height=68, show_grid=True):
    """Creates a Plotly figure with a football pitch background."""
    # Colors matching the 'Premium' aesthetic
    bg_color = '#0b0e14'
    line_color = '#454a54'
    grass_color = '#12161e'

    fig = go.Figure()

    # Main pitch rectangle
    fig.add_shape(type="rect", x0=0, y0=0, x1=width, y1=height,
                  line=dict(color=line_color, width=2), fillcolor=grass_color, layer="below")

    # Center line
    fig.add_shape(type="line", x0=width/2, y0=0, x1=width/2, y1=height,
                  line=dict(color=line_color, width=2), layer="below")

    # Center circle
    fig.add_shape(type="circle", x0=width/2 - 9.15, y0=height/2 - 9.15, 
                  x1=width/2 + 9.15, y1=height/2 + 9.15,
                  line=dict(color=line_color, width=2), layer="below")
    
    # Center spot
    fig.add_shape(type="circle", x0=width/2 - 0.2, y0=height/2 - 0.2, 
                  x1=width/2 + 0.2, y1=height/2 + 0.2,
                  line=dict(color=line_color, width=2), fillcolor=line_color, layer="below")

    # Six-yard boxes
    fig.add_shape(type="rect", x0=0, y0=height/2 - 9.16, x1=5.5, y1=height/2 + 9.16,
                  line=dict(color=line_color, width=2), layer="below")
    fig.add_shape(type="rect", x0=width-5.5, y0=height/2 - 9.16, x1=width, y1=height/2 + 9.16,
                  line=dict(color=line_color, width=2), layer="below")

    # Penalty areas
    fig.add_shape(type="rect", x0=0, y0=height/2 - 20.16, x1=16.5, y1=height/2 + 20.16,
                  line=dict(color=line_color, width=2), layer="below")
    fig.add_shape(type="rect", x0=width-16.5, y0=height/2 - 20.16, x1=width, y1=height/2 + 20.16,
                  line=dict(color=line_color, width=2), layer="below")

    # Goals
    fig.add_shape(type="rect", x0=-2, y0=height/2 - 3.66, x1=0, y1=height/2 + 3.66,
                  line=dict(color="white", width=2), layer="below")
    fig.add_shape(type="rect", x0=width, y0=height/2 - 3.66, x1=width+2, y1=height/2 + 3.66,
                  line=dict(color="white", width=2), layer="below")

    # --- TACTICAL GRID (18 ZONES) ---
    if show_grid:
        # Vertical Thirds
        for vx in [35, 70]:
            fig.add_shape(type="line", x0=vx, y0=0, x1=vx, y1=height,
                          line=dict(color=line_color, width=1, dash="dot"), layer="below")
        
        # Horizontal Channels (5 corridors)
        for vy in [13.6, 27.2, 40.8, 54.4]:
            fig.add_shape(type="line", x0=0, y0=vy, x1=width, y1=vy,
                          line=dict(color=line_color, width=1, dash="dot"), layer="below")
        
        # Half-space logic (often part of 18-zone systems)
        # We already have 4 horizontal lines creating 5 corridors.

    # Set axes properties
    fig.update_xaxes(range=[-5, width+5], showgrid=False, zeroline=False, visible=False)
    fig.update_yaxes(range=[-5, height+5], showgrid=False, zeroline=False, visible=False, scaleanchor="x", scaleratio=1)
    
    fig.update_layout(
        plot_bgcolor=bg_color,
        paper_bgcolor=bg_color,
        margin=dict(l=20, r=20, t=30, b=100),
        width=1000,
        height=750,
        dragmode='select',
        hovermode='closest',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.05,
            xanchor="center",
            x=0.5,
            font=dict(color="white")
        )
    )

    return fig

def add_concentration_annotations(fig, df, width=105, height=68):
    """Adds interactive concentration percentage traces to the pitch."""
    if df is None or df.empty:
        return fig
    
    total = len(df)
    
    # --- VERTICAL THIRDS (TOP PERCENTAGES) ---
    v_thirds = [
        ("Tier Défensif", 0, 35), ("Tier Central", 35, 70), ("Tier Offensif", 70, 105)
    ]
    for i, (name, x0, x1) in enumerate(v_thirds):
        count = len(df[(df['x'] >= x0) & (df['x'] < x1)])
        pct = (count / total * 100) if total > 0 else 0
        
        fig.add_trace(go.Scatter(
            x=[(x0 + x1) / 2], y=[height + 4],
            text=[f"<b>{pct:.0f}%</b>"],
            mode="text",
            showlegend=False,
            name=name,
            textfont=dict(color="white", size=17),
            hoverinfo="text",
            hovertext=f"Filtrer {name}",
            # Use a dict-like string or list for customdata to identify in Streamlit
            customdata=[f"zone_filter|x|{x0}|{x1}"]
        ))
        
        # Separator lines
        if i < 2:
            fig.add_shape(type="line", x0=x1, y0=height+1, x1=x1, y1=height+7,
                          line=dict(color="#454a54", width=1), xref="x", yref="y")

    # --- HORIZONTAL ZONES (SIDE PERCENTAGES) ---
    h_zones = [
        ("Bas", 0, 22.6), ("Milieu", 22.6, 45.3), ("Haut", 45.3, 68)
    ]
    for i, (name, y0, y1) in enumerate(h_zones):
        count = len(df[(df['y'] >= y0) & (df['y'] < y1)])
        pct = (count / total * 100) if total > 0 else 0
        
        fig.add_trace(go.Scatter(
            x=[-4], y=[(y0 + y1) / 2],
            text=[f"<b>{pct:.0f}%</b>"],
            mode="text",
            showlegend=False,
            name=name,
            textfont=dict(color="white", size=15),
            hoverinfo="text",
            hovertext=f"Filtrer {name}",
            customdata=[f"zone_filter|y|{y0}|{y1}"]
        ))
        if i < 2:
            fig.add_shape(type="line", x0=-7, y0=y1, x1=-1, y1=y1,
                          line=dict(color="#454a54", width=1), xref="x", yref="y")
            
    # --- CLICKABLE ZONE HUBS (NEW) ---
    # We add invisible large markers at the center of each of the 15 zones (3x5)
    # for easy "Click-only" filtering.
    # IMPORTANT: selectedpoints=[] prevents these from being captured by lasso/box select
    v_thirds = [(0, 35), (35, 70), (70, 105)]
    h_corridors = [(0, 13.6), (13.6, 27.2), (27.2, 40.8), (40.8, 54.4), (54.4, 68)]
    
    for vx0, vx1 in v_thirds:
        for vy0, vy1 in h_corridors:
            fig.add_trace(go.Scatter(
                x=[(vx0 + vx1) / 2], y=[(vy0 + vy1) / 2],
                mode='markers',
                marker=dict(size=40, color='rgba(0,0,0,0)'), # Invisible but clickable
                showlegend=False,
                hoverinfo='skip',
                selectedpoints=[],
                customdata=[f"zone_filter|both|{vx0}|{vx1}|{vy0}|{vy1}"],
                name="Zone Hub"
            ))
    
    return fig

def plot_interactive_pitch(df, show_grid=True, color_by_outcome=False, show_percentages=True, dragmode='select'):
    """Generates an interactive Plotly pitch with events."""
    if df is None or df.empty:
        fig = create_pitch_figure(show_grid=show_grid)
        fig.update_layout(dragmode=dragmode)
        return fig

    fig = create_pitch_figure(show_grid=show_grid)
    fig.update_layout(dragmode=dragmode)
    
    # Valid coordinates only
    df_valid = df.dropna(subset=['x', 'y']).copy()
    for c in ['x', 'y', 'endX', 'endY']:
        if c in df_valid.columns:
            df_valid[c] = pd.to_numeric(df_valid[c], errors='coerce')
    df_valid = df_valid.dropna(subset=['x', 'y'])

    # Outcome handling
    if 'outcomeType' not in df_valid.columns:
        df_valid['outcomeType'] = 'Unsuccessful' # Fallback
    
    # Add percentages if requested
    if show_percentages:
        fig = add_concentration_annotations(fig, df_valid)

    # Add custom data for click handling
    # We store the dataframe index to find the event back
    custom_data = df_valid.index.values

    # Color mapping for event types
    event_colors = {
        'Pass': '#00ff88',
        'Goal': '#f1c40f',
        'Shot': '#ff3366',
        'SavedShot': '#ffcc00',
        'Carry': '#00d9ff',
        'Tackle': '#3498db',
        'Interception': '#2ecc71'
    }
    
    def get_color(etype):
        for k, v in event_colors.items():
            if k.lower() in str(etype).lower():
                return v
        return '#95a5a6' # Default gray

    # Group by type for legend and consolidated handling
    all_types = df_valid['type'].unique()
    
    for etype in all_types:
        type_df = df_valid[df_valid['type'] == etype]
        marker_color = get_color(etype)
        
        # Determine symbol (skip custom symbols when coloring by outcome)
        symbol = "circle"
        if not color_by_outcome:
            if "Shot" in str(etype) or "Goal" in str(etype):
                symbol = "star"
            elif "Tackle" in str(etype):
                symbol = "x"

        # Check if this type usually has motion traits (Pass/Carry)
        is_motion = any(m in str(etype).lower() for m in ['pass', 'carry'])
        
        if is_motion and 'endX' in type_df.columns:
            # We add individual traces for motion events to link marker + line in hover
            first_of_type = True
            for idx, row in type_df.iterrows():
                if pd.isna(row['x']) or pd.isna(row['y']): continue
                
                # Check outcome for coloring/symbol override
                is_success = str(row.get('outcomeType')).lower() == 'successful'
                if color_by_outcome:
                    item_color = '#ff4b4b' if is_success else '#ffffff'
                    item_symbol = 'circle' if is_success else 'square'
                    item_name = 'Successful' if is_success else 'Unsuccessful'
                else:
                    item_color = marker_color
                    item_symbol = symbol
                    item_name = str(etype)

                has_end = pd.notna(row['endX']) and pd.notna(row['endY'])
                x_vals = [row['x'], row['endX']] if has_end else [row['x']]
                y_vals = [row['y'], row['endY']] if has_end else [row['y']]
                
                # Use dash for passes, solid for carries
                dash = 'dot' if 'pass' in str(etype).lower() else 'solid'
                
                fig.add_trace(go.Scatter(
                    x=x_vals,
                    y=y_vals,
                    mode='lines+markers' if has_end else 'markers',
                    name=item_name,
                    legendgroup=item_name,
                    showlegend=first_of_type,
                    line=dict(color=item_color, width=2, dash=dash),
                    marker=dict(
                        size=[12, 0] if has_end else [12],
                        color=item_color,
                        symbol=item_symbol,
                        line=dict(color='white' if is_success or not color_by_outcome else '#454a54', width=1)
                    ),
                    opacity=0.75 if is_success or not color_by_outcome else 0.5,
                    customdata=[idx, idx] if has_end else [idx],
                    hovertemplate=(
                        f"<b>%{{text}}</b> ({'Réussi' if is_success else 'Échec'})<br>"
                        "Action: " + str(etype) + "<br>"
                        "Position: (%{x}, %{y})<br>"
                        f"⏳ Temps: {int(row.get('minute', 0))}:{int(float(row.get('second', 0))):02d}<br>"
                        "⚔️ Adv.: " + str(row.get('oppositionTeamName', 'Inconnu')) + "<extra></extra>"
                    ),
                    text=[row['playerName'] if 'playerName' in type_df.columns else str(etype)] * (2 if has_end else 1)
                ))
                first_of_type = False
        else:
            # Grouped markers for non-motion events
            # If color_by_outcome, we need to split by outcome even for non-motion
            outcomes = type_df['outcomeType'].unique() if color_by_outcome else [None]
            is_success = True  # Default for non-outcome mode, prevents NameError
            
            for out in outcomes:
                if color_by_outcome:
                    is_success = str(out).lower() == 'successful'
                    item_df = type_df[type_df['outcomeType'] == out]
                    item_color = '#ff4b4b' if is_success else '#ffffff'
                    item_symbol = 'circle' if is_success else 'square'
                    item_name = 'Successful' if is_success else 'Unsuccessful'
                else:
                    item_df = type_df
                    item_color = marker_color
                    item_symbol = symbol
                    item_name = str(etype)

                if item_df.empty: continue

                fig.add_trace(go.Scatter(
                    x=item_df['x'],
                    y=item_df['y'],
                    mode='markers',
                    name=item_name,
                    legendgroup=item_name,
                    showlegend=True if color_by_outcome else True,
                    marker=dict(
                        size=12,
                        color=item_color,
                        symbol=item_symbol,
                        line=dict(color='white' if not color_by_outcome or is_success else '#454a54', width=1)
                    ),
                    customdata=np.stack([
                        item_df.index,
                        item_df.apply(lambda r: f"{int(r['minute'])}:{int(float(r['second'])):02d}", axis=1),
                        item_df['oppositionTeamName'].fillna('Inconnu')
                    ], axis=-1),
                    hovertemplate=(
                        "<b>%{text}</b><br>"
                        "Action: " + str(etype) + "<br>"
                        "Position: (%{x}, %{y})<br>"
                        "⏳ Temps: %{customdata[1]}<br>"
                        "⚔️ Adv.: %{customdata[2]}<extra></extra>"
                    ),
                    text=item_df['playerName'] if 'playerName' in item_df.columns else item_df['type']
                ))
                if not color_by_outcome: break # Only one loop if not coloring by outcome

    # Premium hoverlabel styling
    fig.update_layout(
        hoverlabel=dict(
            bgcolor="rgba(15, 15, 20, 0.95)",
            font_size=13,
            font_family="Inter, sans-serif",
            bordercolor="#454a54"
        )
    )

    return fig

def plot_tactical_sequence(chain_df, team_name=None, is_home=True):
    """Generates an interactive Plotly pitch for a tactical sequence (Build-Up)."""
    fig = create_pitch_figure()
    
    if chain_df is None or chain_df.empty:
        return fig

    # Colors for tactical visualization
    COLOR_PASS = '#00ff88'
    COLOR_CARRY = '#00d9ff'
    COLOR_OTHER = '#95a5a6'
    COLOR_PLAYER = '#ffffff'
    
    # Process coordinates
    df = chain_df.copy()
    for c in ['x', 'y', 'endX', 'endY']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    
    # Draw sequence steps
    steps = len(df)
    for i, (idx, row) in enumerate(df.iterrows()):
        step_num = i + 1
        x, y = row.get('x', 0), row.get('y', 0)
        ex, ey = row.get('endX'), row.get('endY')
        etype = str(row.get('type', '')).lower()
        player = str(row.get('playerName', 'Unknown'))
        
        # Determine color
        marker_color = COLOR_OTHER
        if 'pass' in etype: marker_color = COLOR_PASS
        elif 'carry' in etype or 'takeon' in etype: marker_color = COLOR_CARRY
        
        # Prepare coordinates for joint marker+line trace
        has_end = pd.notna(ex) and pd.notna(ey)
        x_coords = [x, ex] if has_end else [x]
        y_coords = [y, ey] if has_end else [y]
        
        # Symbols: circle at start, triangle at end if movement exists
        symbols = ['circle']
        sizes = [12]
        if has_end:
            symbols.append('triangle-right' if x < ex else 'triangle-left')
            sizes.append(10)
            
        fig.add_trace(go.Scatter(
            x=x_coords, y=y_coords,
            mode='lines+markers+text' if has_end else 'markers+text',
            name=f"Step {step_num}: {row.get('type')}",
            text=[str(step_num), ""] if has_end else [str(step_num)],
            textposition="top center",
            textfont=dict(color='white', size=11, family="JetBrains Mono"),
            line=dict(
                color=marker_color, 
                width=4 if 'pass' in etype else 2.5, 
                dash='solid' if 'pass' in etype else 'dash'
            ),
            marker=dict(
                size=sizes,
                color=marker_color,
                symbol=symbols,
                line=dict(color='white', width=1.5)
            ),
            hovertemplate=(
                f"<b>Step {step_num}: {row.get('type')}</b><br>"
                f"Joueur: {player}<br>"
                f"⚔️ Adv.: {row.get('oppositionTeamName', 'Inconnu')}<br>"
                f"⏳ Temps: {int(row.get('minute', 0))}:{int(float(row.get('second', 0))):02d}<br>"
                "<extra></extra>"
            )
        ))

    # Title and subtitle
    title = f"Build-Up Sequence: {team_name}" if team_name else "Build-Up Sequence"
    duration = f"{int(df.iloc[0]['minute'])}' -> {int(df.iloc[-1]['minute'])}'"
    
    fig.update_layout(
        title=dict(
            text=f"<b>{title}</b><br><span style='font-size:14px;color:#888'>{duration} · {steps} Actions</span>",
            x=0.05, y=0.95,
            font=dict(color='white', size=24)
        ),
        showlegend=False
    )
    
    return fig
