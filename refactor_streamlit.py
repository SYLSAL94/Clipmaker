import sys
import re

file_path = r"d:\Montage video football\ClipMaker SUAOL\app_streamlit.py"
with open(file_path, "r", encoding="utf-8") as f:
    orig_content = f.read()

# 1. Turbo Batch Dialog
turbo_pattern = re.compile(
    r'( +)batch_log_placeholder = st\.empty\(\)\n\s+batch_log_lines = \[f"<b>🚀 Démarrage du traitement Turbo.*?st\.balloons\(\)\n',
    re.DOTALL
)

def turbo_repl(m):
    indent = m.group(1)
    original_block = m.group(0).split('\n')
    
    # We strip the first group(1) from each line, then add 4 spaces
    new_block_lines = []
    for line in original_block:
        if line.startswith(indent):
            new_block_lines.append(indent + "    " + line[len(indent):])
        elif line == "":
            new_block_lines.append("")
        else:
            new_block_lines.append(indent + "    " + line)
            
    body = "\n".join(new_block_lines)
    
    dialog_def = f"{indent}@st.dialog(\"🚀 Turbo Batch en cours...\", width=\"large\")\n{indent}def process_turbo_dialog():\n"
    dialog_call = f"\n{indent}{indent}    if st.button(\"Fermer\", type=\"primary\", use_container_width=True):\n{indent}        st.rerun()\n{indent}process_turbo_dialog()\n"
    
    return dialog_def + body + dialog_call

content1 = turbo_pattern.sub(turbo_repl, orig_content)

# 2. Aggregate Batch Dialog
agg_pattern = re.compile(
    r'( +)# Setup logging area for parallel run\n\s+batch_log_lines = \[f"<b style=\'color:#00ff88;\'>DÉMARRAGE MULTI-ANALYSE.*?st\.balloons\(\)\n',
    re.DOTALL
)

def agg_repl(m):
    indent = m.group(1)
    original_block = m.group(0).split('\n')
    new_block_lines = []
    for line in original_block:
        if line.startswith(indent):
            new_block_lines.append(indent + "    " + line[len(indent):])
        elif line == "":
            new_block_lines.append("")
        else:
            new_block_lines.append(indent + "    " + line)
            
    body = "\n".join(new_block_lines)
    
    dialog_def = f"{indent}@st.dialog(\"🌐 Multi-Analyse (Aggregate) en cours...\", width=\"large\")\n{indent}def process_aggregate_dialog():\n"
    dialog_call = f"\n{indent}{indent}    if st.button(\"Fermer\", type=\"primary\", use_container_width=True):\n{indent}        st.rerun()\n{indent}process_aggregate_dialog()\n"
    
    return dialog_def + body + dialog_call
    
content2 = agg_pattern.sub(agg_repl, content1)

# 3. Single Action Run
single_pattern = re.compile(
    r'( +)log_queue = queue\.Queue\(\)\n\s+progress_queue = queue\.Queue\(\).*?progress_placeholder\.empty\(\)\n',
    re.DOTALL
)

def single_repl(m):
    indent = m.group(1)
    original_block = m.group(0).split('\n')
    new_block_lines = []
    for line in original_block:
        if line.startswith(indent):
            new_block_lines.append(indent + "    " + line[len(indent):])
        elif line == "":
            new_block_lines.append("")
        else:
            new_block_lines.append(indent + "    " + line)
            
    body = "\n".join(new_block_lines)
    
    dialog_def = f"{indent}@st.dialog(\"🎬 Progression du Rendu (ClipMaker)\", width=\"large\")\n{indent}def process_single_match_dialog():\n{indent}    st.markdown(\"### ⚙️ Traitement en cours...\")\n{indent}    progress_placeholder = st.empty()\n{indent}    log_placeholder = st.empty()\n"
    dialog_call = f"\n{indent}{indent}    st.success(\"✅ Traitement terminé !\")\n{indent}{indent}    if st.button(\"Fermer\", type=\"primary\", use_container_width=True):\n{indent}        st.rerun()\n{indent}process_single_match_dialog()\n"
    
    return dialog_def + body + dialog_call

content3 = single_pattern.sub(single_repl, content2)

if content3 != orig_content:
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content3)
    print("Replaced all correctly!")
else:
    print("Failed to replace!")
