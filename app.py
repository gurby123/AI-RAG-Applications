import os
import io
from typing import List

import streamlit as st
import requests
from docx import Document

# Defaults (can be overridden in the UI sidebar or via env vars)
DEFAULT_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.2.200:11434")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:latest")

FRAMEWORKS = [
    "Reframing Thinking",
    "Delphi",
    "SCAMPER",
    "Blue Ocean",
    "Six Thinking Hats",
    "Balanced Scorecard",
    "McKinsey 7S",
    "Burke-Litwin",
    "TRIZ",
]

FRAMEWORK_DESCRIPTIONS = {
    "Reframing Thinking": "Challenge assumptions and reframe the problem from alternative perspectives.",
    "Delphi": "Iterative expert consensus via rounds of anonymous feedback.",
    "SCAMPER": "Substitute, Combine, Adapt, Modify, Put to another use, Eliminate, Reverse.",
    "Blue Ocean": "Create new market space by shifting value curves away from competition.",
    "Six Thinking Hats": "Parallel thinking: Facts, Feelings, Caution, Benefits, Creativity, Process.",
    "Balanced Scorecard": "Translate strategy into objectives across Financial, Customer, Internal, Learning.",
    "McKinsey 7S": "Align Strategy, Structure, Systems, Shared Values, Skills, Style, Staff.",
    "Burke-Litwin": "Diagnose org change via External Env., Leadership, Culture, Systems, etc.",
    "TRIZ": "Inventive problem solving using patterns of technical evolution and contradictions.",
}


def ollama_generate(host: str, model: str, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """Call Ollama's /api/generate endpoint for a single-turn completion."""
    url = f"{host.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": f"<|system|>\n{system_prompt}\n<|user|>\n{user_prompt}\n<|assistant|>",
        "stream": False,
        "options": {"temperature": temperature},
    }
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "").strip()


def build_vision_prompt(issue_text: str, selected_frameworks: List[str]) -> str:
    frameworks_block = "\n".join(
        f"- {fw}: {FRAMEWORK_DESCRIPTIONS.get(fw, '')}" for fw in selected_frameworks
    )
    return (
        "You are a strategy consultant. Given the business issues and the chosen frameworks, "
        "produce exactly 3 distinct vision statements as a numbered list (1., 2., 3.).\n\n"
        f"Business issues:\n{issue_text}\n\n"
        f"Frameworks to apply:\n{frameworks_block}\n\n"
        "Instructions:\n"
        "- Each vision statement must be ONE sentence only (<= 25 words).\n"
        "- Ensure each is meaningfully different.\n"
        "- Output ONLY the three numbered items, no preface or epilogue.\n"
    )


def parse_numbered_list(text: str) -> List[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    items: List[str] = []
    current: List[str] = []
    for ln in lines:
        if any(ln.startswith(prefix) for prefix in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            if current:
                items.append(" ".join(current).strip())
                current = []
            current.append(ln.split(".", 1)[1].strip())
        else:
            current.append(ln)
    if current:
        items.append(" ".join(current).strip())
    return [it for it in items if it]


def first_sentence(text: str) -> str:
    """Return text up to the first sentence terminator (.!?), inclusive; else the whole text."""
    for ch in ".!?":
        pass
    sentence_end = None
    for idx, ch in enumerate(text):
        if ch in ".!?":
            sentence_end = idx
            break
    return text[: sentence_end + 1].strip() if sentence_end is not None else text.strip()


def build_mission_goals_prompt(selected_vision: str, issue_text: str, selected_frameworks: List[str]) -> str:
    frameworks_block = ", ".join(selected_frameworks)
    return (
        "You are a strategy consultant. Based on the selected vision statement, "
        "draft a mission statement and at least 5 strategic goals.\n\n"
        f"Selected vision:\n{selected_vision}\n\n"
        f"Key business issues:\n{issue_text}\n\n"
        f"Framework lenses to reflect: {frameworks_block}.\n\n"
        "Output format:\n"
        "Mission: <one concise mission statement>\n"
        "Goals:\n"
        "1. <goal one>\n2. <goal two>\n3. <goal three>\n4. <goal four>\n5. <goal five>\n"
    )


def export_docx(issue_text: str, frameworks: List[str], visions: List[str], chosen_idx: int, mission: str, goals: List[str]) -> bytes:
    doc = Document()
    doc.add_heading('Strategy Synthesis', level=1)

    doc.add_heading('Business Issues', level=2)
    doc.add_paragraph(issue_text)

    doc.add_heading('Frameworks Applied', level=2)
    for fw in frameworks:
        doc.add_paragraph(fw, style='List Bullet')

    doc.add_heading('Vision Options', level=2)
    for i, v in enumerate(visions, start=1):
        p = doc.add_paragraph(f"{i}. {v}")
        if i - 1 == chosen_idx and p.runs:
            p.runs[0].bold = True

    doc.add_heading('Mission Statement', level=2)
    doc.add_paragraph(mission)

    doc.add_heading('Strategic Goals', level=2)
    for g in goals:
        doc.add_paragraph(g, style='List Number')

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def export_selected_docx(selected_vision: str, mission: str, goals: List[str]) -> bytes:
    doc = Document()
    doc.add_heading('Selected Strategy', level=1)

    doc.add_heading('Vision', level=2)
    doc.add_paragraph(selected_vision)

    doc.add_heading('Mission', level=2)
    doc.add_paragraph(mission)

    doc.add_heading('Goals', level=2)
    for g in goals:
        doc.add_paragraph(g, style='List Number')

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def extract_docx_text(file) -> str:
    """Extract text from a .docx file, including paragraphs and table cells."""
    try:
        doc = Document(file)
    except Exception:
        return ""
    chunks: List[str] = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            chunks.append(text)
    for table in getattr(doc, "tables", []):
        for row in table.rows:
            for cell in row.cells:
                text = cell.text.strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks)


st.set_page_config(page_title="Vision & Strategy Synthesizer", page_icon="🧠", layout="wide")

st.title("🧠 Vision & Strategy Synthesizer")

with st.sidebar:
    st.header("Model Settings")
    host_val = st.text_input("Ollama Host", value=DEFAULT_OLLAMA_HOST, key="ollama_host")
    model_val = st.text_input("Model", value=DEFAULT_OLLAMA_MODEL, key="ollama_model")
    temperature = st.slider("Temperature", 0.0, 1.5, 0.7, 0.1)

st.markdown("Enter your business issues, optionally upload a Word document, select frameworks, and generate strategic options.")

issue_text = st.text_area("Business issues / context", height=180, placeholder="Describe the current situation, constraints, and opportunities...")

uploaded = st.file_uploader("Upload Word document (.docx)", type=["docx"], accept_multiple_files=False)
if uploaded is not None:
    uploaded_text = extract_docx_text(uploaded)
    st.session_state["uploaded_issue_text"] = uploaded_text
    with st.expander("Preview uploaded document", expanded=False):
        if uploaded_text:
            st.write(uploaded_text[:4000])
        else:
            st.write("(No extractable text found)")

include_uploaded_default = bool(st.session_state.get("uploaded_issue_text"))
include_uploaded = st.checkbox("Include uploaded document text", value=include_uploaded_default, key="include_uploaded") if include_uploaded_default else False

cols = st.columns(3)
selected_frameworks: List[str] = []
for i, fw in enumerate(FRAMEWORKS):
    col = cols[i % 3]
    with col:
        if st.checkbox(fw, value=False, key=f"fw_{i}"):
            selected_frameworks.append(fw)

uploaded_text_state = st.session_state.get("uploaded_issue_text", "")
combined_issue_text = (issue_text or "")
if include_uploaded and uploaded_text_state:
    combined_issue_text = (combined_issue_text + ("\n\n" if combined_issue_text else "") + uploaded_text_state)

disable_generate = (not combined_issue_text) or (not selected_frameworks)
if st.button("Generate 3 one-sentence visions", type="primary", disabled=disable_generate):
    with st.spinner("Generating vision statements..."):
        try:
            prompt = build_vision_prompt(combined_issue_text, selected_frameworks)
            resp = ollama_generate(
                host=st.session_state.get("ollama_host", DEFAULT_OLLAMA_HOST),
                model=st.session_state.get("ollama_model", DEFAULT_OLLAMA_MODEL),
                system_prompt="You are a world-class strategy advisor.",
                user_prompt=prompt,
                temperature=temperature,
            )
            visions = parse_numbered_list(resp)
            if len(visions) < 3:
                visions = [ln.strip("-• ") for ln in resp.split("\n") if ln.strip()]
            visions = [first_sentence(v) for v in visions][:3]
            st.session_state["visions"] = visions
            st.session_state["issue_text"] = combined_issue_text
            st.session_state["frameworks"] = selected_frameworks
            st.session_state["model_settings"] = {
                "ollama_host": st.session_state.get("ollama_host", DEFAULT_OLLAMA_HOST),
                "ollama_model": st.session_state.get("ollama_model", DEFAULT_OLLAMA_MODEL),
                "temperature": temperature,
            }
            st.success(f"Generated {len(visions)} vision options.")
        except Exception as e:
            st.error(f"Failed to generate visions: {e}")

visions: List[str] = st.session_state.get("visions", [])
if visions:
    st.subheader("Vision Options")
    selected_idx = st.radio(
        "Select a preferred vision",
        options=list(range(len(visions))),
        format_func=lambda i: f"{i+1}. {visions[i]}",
        index=0,
        horizontal=False,
        key="vision_idx",
    )
    if st.button("Develop mission and goals", type="secondary"):
        with st.spinner("Drafting mission and goals..."):
            try:
                prompt = build_mission_goals_prompt(
                    selected_vision=visions[selected_idx],
                    issue_text=st.session_state.get("issue_text", ""),
                    selected_frameworks=st.session_state.get("frameworks", []),
                )
                resp = ollama_generate(
                    host=st.session_state.get("ollama_host", DEFAULT_OLLAMA_HOST),
                    model=st.session_state.get("ollama_model", DEFAULT_OLLAMA_MODEL),
                    system_prompt="You are a world-class strategy advisor.",
                    user_prompt=prompt,
                    temperature=temperature,
                )
                mission = ""
                goals: List[str] = []
                for line in resp.splitlines():
                    stripped = line.strip()
                    if stripped.lower().startswith("mission:"):
                        mission = stripped.split(":", 1)[1].strip()
                    elif stripped and stripped[0].isdigit() and stripped[1:2] == ".":
                        goals.append(stripped.split(".", 1)[1].strip())
                if not mission:
                    mission = resp.split("\n", 1)[0].strip()
                if len(goals) < 5:
                    goals = parse_numbered_list(resp)[:5]
                st.session_state["mission"] = mission
                st.session_state["goals"] = goals
                st.success("Mission and goals drafted.")
            except Exception as e:
                st.error(f"Failed to generate mission/goals: {e}")

mission = st.session_state.get("mission")
goals = st.session_state.get("goals", [])
if mission or goals:
    st.subheader("Results")
    if mission:
        st.markdown(f"**Mission:** {mission}")
    if goals:
        st.markdown("**Goals:**")
        for i, g in enumerate(goals, start=1):
            st.markdown(f"{i}. {g}")

    # Selected-only export
    selected_idx = st.session_state.get("vision_idx", 0)
    visions_list: List[str] = st.session_state.get("visions", [])
    selected_vision = visions_list[selected_idx] if visions_list else ""
    selected_content = export_selected_docx(
        selected_vision=selected_vision,
        mission=mission or "",
        goals=goals,
    )
    st.download_button(
        label="Download selected strategy.docx",
        data=selected_content,
        file_name="selected_strategy.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # Full analysis export
    full_content = export_docx(
        issue_text=st.session_state.get("issue_text", ""),
        frameworks=st.session_state.get("frameworks", []),
        visions=st.session_state.get("visions", []),
        chosen_idx=selected_idx,
        mission=mission or "",
        goals=goals,
    )
    st.download_button(
        label="Download full analysis.docx",
        data=full_content,
        file_name="analysis.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )