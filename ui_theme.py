"""
ui_theme.py
===========
Constantes de thème (couleurs, styles CSS) et composants HTML réutilisables
pour l'interface ClipMaker SUAOL (Kinetic Analyst Design).
"""

import base64
import streamlit as st

# =============================================================================
# THEME CONSTANTS
# =============================================================================
ACCENT = "#DFFF00"      # Neon Chartreuse
ACCENT_2 = "#00FFA3"    # Spring Green
BG_BASE = "#050505"
BG_SURFACE = "rgba(19, 19, 19, 0.7)"
BG_BORDER = "rgba(255, 255, 255, 0.08)"
TEXT_PRIMARY = "#ffffff"
TEXT_MUTED = "#a0a0a0"


def load_logo_b64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except:
        return ""


def logo_header(title, subtitle, logo_path=None):
    logo_b64 = load_logo_b64(logo_path) if logo_path else None
    img = (
        f'<img src="data:image/png;base64,{logo_b64}" '
        f'style="width:50px;height:50px;object-fit:contain;filter:drop-shadow(0 0 15px rgba(223,255,0,0.3))"/>'
        if logo_b64
        else ""
    )
    return f"""<div class="header-main-container">
<div style='display:flex;align-items:center;gap:18px;margin-bottom:12px;'>
{img}
<div>
<div style="font-family:'JetBrains Mono', monospace; font-size:24px; font-weight:900; color:{ACCENT}; letter-spacing: -1px; text-transform:uppercase;">{title}</div>
<div style="font-family:'Inter', sans-serif; font-size:11px; color:{TEXT_MUTED}; text-transform:uppercase; letter-spacing:3px;">{subtitle}</div>
</div>
</div>
<div class="header-divider"></div>
</div>"""


def step_header(num, label):
    return f"""<div class='step-header-container'>
<div class='step-marker'>{num}</div>
<div class='step-label'>{label}</div>
</div>"""


def inject_global_css():
    """Injecte le CSS global premium de l'application."""
    st.markdown(
        f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;900&family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;700&display=swap');

:root {{
    --accent: {ACCENT};
    --accent-2: {ACCENT_2};
    --bg-base: {BG_BASE};
    --bg-surface: {BG_SURFACE};
    --bg-border: {BG_BORDER};
}}

/* Global layout & background */
.stApp {{
    background: radial-gradient(circle at 50% -20%, #1a1a1a 0%, #050505 100%) !important;
    background-attachment: fixed !important;
}}

html, body, [class*="css"] {{
    font-family: 'Outfit', sans-serif !important;
    color: #ffffff;
}}

[data-testid="stSidebar"] {{
    background: rgba(10, 10, 10, 0.8) !important;
    backdrop-filter: blur(20px) !important;
    border-right: 1px solid var(--bg-border) !important;
}}

/* Typography */
h1, h2, h3, h4, h5 {{
    font-family: 'Outfit', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    background: linear-gradient(135deg, #fff 30%, {TEXT_MUTED} 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 20px !important;
}}

/* Glassmorphism Containers */
div[data-testid="stExpander"], div[data-testid="column"] > div > div > div {{
    background: rgba(255, 255, 255, 0.03) !important;
    backdrop-filter: blur(10px) !important;
    border: 1px solid var(--bg-border) !important;
    border-radius: 12px !important;
    padding: 5px !important;
}}

/* Custom Headers */
.header-main-container {{
    margin-top: -30px;
    margin-bottom: 30px;
}}
.header-divider {{
    height: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent-2), transparent);
    border-radius: 4px;
    opacity: 0.6;
}}

.step-header-container {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin: 40px 0 20px 0;
    padding: 12px 20px;
    background: linear-gradient(90deg, rgba(223, 255, 0, 0.05) 0%, transparent 100%);
    border-left: 4px solid var(--accent);
    border-radius: 4px;
}}
.step-marker {{
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    background: var(--accent);
    border-radius: 50%;
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    font-weight: 900;
    color: #000;
    box-shadow: 0 0 15px rgba(223, 255, 0, 0.4);
}}
.step-label {{
    font-family: 'Outfit', sans-serif;
    font-size: 14px;
    font-weight: 600;
    color: #fff;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}}

/* Buttons Premium */
.stButton > button {{
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%) !important;
    color: #000 !important;
    border-radius: 8px !important;
    font-family: 'Outfit', sans-serif !important;
    font-weight: 700 !important;
    font-size: 13px !important;
    padding: 10px 24px !important;
    border: none !important;
    box-shadow: 0 4px 15px rgba(223, 255, 0, 0.2) !important;
    transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) !important;
}}
.stButton > button:hover, .stButton > button:active, .stButton > button:focus {{
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(223, 255, 0, 0.4) !important;
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%) !important;
    color: #000 !important;
    filter: brightness(1.1) !important;
}}
.stButton > button:active {{
    transform: translateY(0) !important;
}}

/* Special button for batch/basket */
.stButton > button[kind="secondary"] {{
    background: rgba(255, 255, 255, 0.05) !important;
    color: #fff !important;
    border: 1px solid var(--bg-border) !important;
    backdrop-filter: blur(5px);
}}
.stButton > button[kind="secondary"]:hover {{
    background: rgba(255, 255, 255, 0.1) !important;
    border-color: var(--accent) !important;
}}

/* Metrics Refined */
[data-testid="stMetric"] {{
    background: rgba(255, 255, 255, 0.02) !important;
    padding: 15px !important;
    border-radius: 12px !important;
    border: 1px solid var(--bg-border) !important;
}}
[data-testid="stMetricValue"] {{
    color: var(--accent) !important;
    font-family: 'Outfit', sans-serif !important;
    font-weight: 800 !important;
    font-size: 28px !important;
}}
[data-testid="stMetricLabel"] {{
    font-family: 'Inter', sans-serif !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
    color: {TEXT_MUTED} !important;
}}

/* Inputs */
.stTextInput input, .stSelectbox div[data-baseweb="select"] {{
    background: rgba(255, 255, 255, 0.05) !important;
    border: 1px solid var(--bg-border) !important;
    border-radius: 8px !important;
    color: #fff !important;
}}
.stTextInput input:focus {{
    border-color: var(--accent) !important;
    box-shadow: 0 0 10px rgba(223, 255, 0, 0.2) !important;
}}

/* Tabs premium styling */
.stTabs [data-baseweb="tab-list"] {{
    gap: 8px !important;
    background-color: transparent !important;
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 8px 8px 0 0 !important;
    background-color: rgba(255, 255, 255, 0.03) !important;
    padding: 10px 20px !important;
    color: {TEXT_MUTED} !important;
    border: 1px solid transparent !important;
    transition: all 0.3s ease !important;
}}
.stTabs [aria-selected="true"] {{
    background-color: rgba(223, 255, 0, 0.1) !important;
    color: var(--accent) !important;
    border: 1px solid var(--bg-border) !important;
    border-bottom: 2px solid var(--accent) !important;
}}

/* Dataframe Refinement */
.stDataFrame {{
    border-radius: 12px !important;
    overflow: hidden !important;
    border: 1px solid var(--bg-border) !important;
}}

/* Special Classes */
.stAlert {{
    background: rgba(255, 255, 255, 0.05) !important;
    border: 1px solid var(--bg-border) !important;
    border-radius: 12px !important;
    backdrop-filter: blur(5px);
}}

.tip-box {{
    background: linear-gradient(135deg, rgba(223, 255, 0, 0.05) 0%, rgba(0, 255, 163, 0.05) 100%);
    padding: 20px;
    border-radius: 12px;
    border: 1px solid rgba(223, 255, 0, 0.1);
    margin: 20px 0;
}}
.tip-box b {{
    color: var(--accent);
}}

.active-badge {{
    background: rgba(223, 255, 0, 0.1) !important;
    color: var(--accent) !important;
    padding: 4px 12px !important;
    border-radius: 20px !important;
    border: 1px solid rgba(223, 255, 0, 0.2) !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    display: inline-block;
    margin-right: 8px;
    margin-bottom: 8px;
}}

/* Scrollbar */
::-webkit-scrollbar {{
    width: 8px;
    height: 8px;
}}
::-webkit-scrollbar-track {{
    background: rgba(0,0,0,0.1);
}}
::-webkit-scrollbar-thumb {{
    background: rgba(255,255,255,0.1);
    border-radius: 10px;
}}
::-webkit-scrollbar-thumb:hover {{
    background: var(--accent);
}}

/* Global Stats Bar Styling (Build-Up) */
.cm-stats-bar {{
    display: flex;
    align-items: stretch;
    background: rgba(255, 255, 255, 0.03) !important;
    border-radius: 12px !important;
    overflow: hidden !important;
    border: 1px solid var(--bg-border) !important;
    margin-bottom: 20px !important;
}}
.cm-stats-cell {{
    flex: 1;
    padding: 18px 24px !important;
    text-align: center !important;
    border-right: 1px solid var(--bg-border) !important;
    transition: background 0.3s ease;
}}
.cm-stats-cell:hover {{
    background: rgba(255, 255, 255, 0.05) !important;
}}
.cm-stats-cell:last-child {{
    border-right: none !important;
}}
.cm-stats-label {{
    font-size: 10px !important;
    color: var(--accent) !important;
    text-transform: uppercase !important;
    letter-spacing: .2em !important;
    margin-bottom: 8px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 700 !important;
}}
.cm-stats-value {{
    font-size: 24px !important;
    font-weight: 900 !important;
    color: #ffffff !important;
    font-family: 'Outfit', sans-serif !important;
}}

/* Build-Up Sequence Cards */
.bu-card-container {{
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-bottom: 20px;
    max-height: 650px;
    overflow-y: auto;
    padding-right: 12px;
}}

/* Override buttons in list view */
div.stVerticalBlock > div > div > button.st-emotion-cache-1vt4ygl {{
    text-align: left !important;
    justify-content: flex-start !important;
    background: rgba(255, 255, 255, 0.02) !important;
    border-left: 3px solid transparent !important;
    color: #ffffff !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 11px !important;
    height: auto !important;
    padding: 12px 18px !important;
    line-height: 1.5 !important;
    border-radius: 8px !important;
}}

div.stVerticalBlock > div > div > button:hover {{
    border-left-color: var(--accent) !important;
    background: rgba(255, 255, 255, 0.05) !important;
}}

/* Active sequence styling */
div.bu-selected-card > div > div > button {{
    background: linear-gradient(90deg, rgba(223, 255, 0, 0.1), transparent) !important;
    border-left: 4px solid var(--accent) !important;
    border-top: 1px solid rgba(223, 255, 0, 0.1) !important;
    border-bottom: 1px solid rgba(223, 255, 0, 0.1) !important;
    border-right: 1px solid rgba(223, 255, 0, 0.1) !important;
    font-weight: 700 !important;
    box-shadow: inset 0 0 20px rgba(223, 255, 0, 0.05) !important;
}}

/* Animations */
@keyframes fadeIn {{
    from {{ opacity: 0; transform: translateY(10px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}
.stApp > div {{
    animation: fadeIn 0.6s ease-out;
}}

.neon-title {{
    font-family: 'Outfit', sans-serif;
    font-weight: 900;
    font-size: 42px;
    background: linear-gradient(135deg, #fff 0%, {ACCENT} 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-shadow: 0 10px 30px rgba(223, 255, 0, 0.2);
}}

.footer {{
    margin-top: 60px;
    padding: 20px;
    text-align: center;
    font-size: 10px;
    color: {TEXT_MUTED};
    letter-spacing: 2px;
    text-transform: uppercase;
    opacity: 0.6;
}}
</style>""",
        unsafe_allow_html=True,
    )
