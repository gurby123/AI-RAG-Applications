import io
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st
from docx import Document
from docx.shared import Pt
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


@dataclass
class OllamaConfig:
    base_url: str
    model: str
    temperature: float = 0.2
    num_ctx: int = 8192
    connect_timeout: float = 10.0
    read_timeout: float = 120.0
    max_retries: int = 2


class OllamaClient:
    def __init__(self, config: OllamaConfig) -> None:
        self.config = config
        self.session = requests.Session()
        retry_strategy = Retry(
            total=self.config.max_retries,
            connect=self.config.max_retries,
            read=self.config.max_retries,
            backoff_factor=0.8,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type((requests.RequestException,)))
    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        endpoint = self.config.base_url.rstrip("/") + "/api/generate"
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": self.config.num_ctx,
            },
        }
        if system:
            payload["system"] = system
        response = self.session.post(
            endpoint,
            json=payload,
            timeout=(self.config.connect_timeout, self.config.read_timeout),
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "")

    def test_connection(self) -> Dict[str, Any]:
        """Check connectivity and available models via /api/tags."""
        endpoint = self.config.base_url.rstrip("/") + "/api/tags"
        response = self.session.get(
            endpoint,
            timeout=(self.config.connect_timeout, min(self.config.read_timeout, 10.0)),
        )
        response.raise_for_status()
        return response.json()


def extract_first_json_block(text: str) -> Optional[str]:
    """Extract the first top-level JSON object or array from a string in a robust way."""
    # Prefer fenced code blocks
    code_block_match = re.search(r"```(?:json)?\n([\s\S]*?)\n```", text)
    if code_block_match:
        candidate = code_block_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass

    # Fallback: scan for first balanced object or array
    for open_char, close_char in [("{", "}"), ("[", "]")]:
        depth = 0
        start_idx: Optional[int] = None
        for idx, ch in enumerate(text):
            if ch == open_char:
                if depth == 0:
                    start_idx = idx
                depth += 1
            elif ch == close_char and depth > 0:
                depth -= 1
                if depth == 0 and start_idx is not None:
                    block = text[start_idx : idx + 1]
                    try:
                        json.loads(block)
                        return block
                    except Exception:
                        return None
    return None


def read_docx_text(file_bytes: bytes) -> str:
    buffer = io.BytesIO(file_bytes)
    document = Document(buffer)
    paragraphs = [p.text for p in document.paragraphs]
    text = "\n".join([p for p in paragraphs if p and p.strip()])
    return text.strip()


def chunk_text(text: str, max_chars: int = 3000, overlap: int = 300) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p and p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    def flush_chunk() -> None:
        nonlocal current, current_len
        if current:
            chunk = "\n\n".join(current).strip()
            if chunk:
                chunks.append(chunk)
        current = []
        current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len + 2 <= max_chars:
            current.append(para)
            current_len += para_len + 2
        else:
            flush_chunk()
            # start new with overlap from previous
            if chunks and overlap > 0:
                tail = chunks[-1]
                tail_overlap = tail[-min(len(tail), overlap) :]
                current.append(tail_overlap)
                current_len = len(tail_overlap)
            current.append(para)
            current_len += para_len
    flush_chunk()
    # Final trim
    return [c.strip() for c in chunks if c.strip()]


def call_analysis_for_chunk(client: OllamaClient, chunk_text_value: str) -> Dict[str, Any]:
    system = (
        "You are a senior corporate strategy analyst."
        " Extract facts, make cautious deductions, and identify internal and external factors."
        " Be precise and concise. Output valid minified JSON only."
    )
    prompt = (
        "From the following business context chunk, extract: facts, deductions, risk/opportunity factors,"
        " and early insights relevant to corporate strategy."
        "\n\nReturn strict JSON with keys: facts (string[]), deductions (string[]),"
        " factors (object with internal: string[], external: string[]), insights (string[])."
        " Avoid duplication and keep items atomic."
        f"\n\nCHUNK:\n{chunk_text_value}"
    )
    try:
        response_text = client.generate(prompt=prompt, system=system)
    except (requests.Timeout, requests.ConnectionError, requests.RequestException) as e:
        return {
            "facts": [],
            "deductions": [],
            "factors": {"internal": [], "external": []},
            "insights": [],
            "_error": f"request_failed: {e}",
        }
    json_block = extract_first_json_block(response_text) or response_text
    try:
        parsed = json.loads(json_block)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object")
        return parsed
    except Exception:
        return {
            "facts": [],
            "deductions": [],
            "factors": {"internal": [], "external": []},
            "insights": [],
            "_raw": response_text,
        }


def aggregate_chunk_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    def normalize_item(text_item: str) -> str:
        return re.sub(r"\s+", " ", text_item.strip()).strip().rstrip(".;")

    def dedupe(items: List[str]) -> List[str]:
        seen = set()
        unique: List[str] = []
        for item in items:
            norm = normalize_item(item).casefold()
            if norm and norm not in seen:
                seen.add(norm)
                unique.append(item.strip())
        return unique

    all_facts: List[str] = []
    all_deductions: List[str] = []
    internal_factors: List[str] = []
    external_factors: List[str] = []
    insights: List[str] = []
    raw_responses: List[str] = []

    for r in results:
        all_facts.extend(r.get("facts", []) or [])
        all_deductions.extend(r.get("deductions", []) or [])
        f = r.get("factors", {}) or {}
        internal_factors.extend(f.get("internal", []) or [])
        external_factors.extend(f.get("external", []) or [])
        insights.extend(r.get("insights", []) or [])
        raw = r.get("_raw")
        if isinstance(raw, str) and raw.strip():
            raw_responses.append(raw.strip())

    aggregated = {
        "facts": dedupe(all_facts),
        "deductions": dedupe(all_deductions),
        "factors": {
            "internal": dedupe(internal_factors),
            "external": dedupe(external_factors),
        },
        "insights": dedupe(insights),
        "_raw": raw_responses,
    }
    return aggregated


def synthesize_strategy_plan(client: OllamaClient, aggregated: Dict[str, Any]) -> Dict[str, Any]:
    system = (
        "You are a chief strategy officer creating a 3-year strategic plan."
        " Provide a pragmatic, metrics-driven, and actionable plan."
        " Output valid minified JSON only."
    )
    guidance = (
        "Return strict JSON with keys: organization_name (string), vision (string), mission (string),"
        " values (string[]), strategic_themes (string[]), three_year_goals (object[] with: name, description, metrics string[]),"
        " initiatives (object[] with: goal_name, name, description, owner, resources string[], risks string[]),"
        " year_plan (object with year_1, year_2, year_3 each with objectives: object[] {name, description, kpis string[], timeline, owner}),"
        " action_plans (object[] with: objective_name, actions string[], owner, timeline, dependencies string[])."
    )
    context = json.dumps(aggregated, ensure_ascii=False)
    prompt = (
        f"Use the aggregated facts, deductions, factors, and insights to draft a 3-year corporate strategy.\n{guidance}\n\n"
        f"AGGREGATED_CONTEXT:\n{context}"
    )
    response_text = client.generate(prompt=prompt, system=system)
    json_block = extract_first_json_block(response_text) or response_text
    try:
        parsed = json.loads(json_block)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object for plan")
        return parsed
    except Exception:
        return {
            "organization_name": "Organization",
            "vision": "",
            "mission": "",
            "values": [],
            "strategic_themes": [],
            "three_year_goals": [],
            "initiatives": [],
            "year_plan": {"year_1": {"objectives": []}, "year_2": {"objectives": []}, "year_3": {"objectives": []}},
            "action_plans": [],
            "_raw": response_text,
        }


def add_heading(document: Document, text: str, level: int = 1) -> None:
    paragraph = document.add_heading(text, level=level)
    for run in paragraph.runs:
        run.font.size = Pt(14 if level >= 2 else 16)


def add_bulleted_list(document: Document, items: List[str]) -> None:
    for item in items:
        if not item:
            continue
        paragraph = document.add_paragraph(item)
        paragraph.style = "List Bullet"


def build_docx_from_plan(plan: Dict[str, Any], aggregated: Dict[str, Any]) -> bytes:
    doc = Document()

    title = plan.get("organization_name") or "Strategic Plan"
    doc.add_heading(title, level=0)
    doc.add_paragraph("Three-Year Strategic Plan")
    doc.add_page_break()

    add_heading(doc, "Vision")
    doc.add_paragraph(plan.get("vision", ""))

    add_heading(doc, "Mission")
    doc.add_paragraph(plan.get("mission", ""))

    values = plan.get("values", []) or []
    if values:
        add_heading(doc, "Corporate Values", level=2)
        add_bulleted_list(doc, values)

    themes = plan.get("strategic_themes", []) or []
    if themes:
        add_heading(doc, "Strategic Themes", level=2)
        add_bulleted_list(doc, themes)

    goals = plan.get("three_year_goals", []) or []
    if goals:
        add_heading(doc, "Three-Year Goals", level=2)
        for goal in goals:
            doc.add_paragraph(goal.get("name", "Goal"), style="List Number")
            if goal.get("description"):
                doc.add_paragraph(goal["description"]) 
            metrics = goal.get("metrics", []) or []
            if metrics:
                doc.add_paragraph("Metrics:")
                add_bulleted_list(doc, metrics)

    initiatives = plan.get("initiatives", []) or []
    if initiatives:
        add_heading(doc, "Strategic Initiatives", level=2)
        for init in initiatives:
            name = init.get("name", "Initiative")
            goal_name = init.get("goal_name")
            header = f"{name}"
            if goal_name:
                header += f" (Goal: {goal_name})"
            doc.add_paragraph(header, style="List Number")
            if init.get("description"):
                doc.add_paragraph(init["description"]) 
            if init.get("owner"):
                doc.add_paragraph(f"Owner: {init['owner']}")
            if init.get("resources"):
                doc.add_paragraph("Resources:")
                add_bulleted_list(doc, init.get("resources", []))
            if init.get("risks"):
                doc.add_paragraph("Risks:")
                add_bulleted_list(doc, init.get("risks", []))

    year_plan = plan.get("year_plan", {}) or {}
    for year_key, year_title in [("year_1", "Year 1"), ("year_2", "Year 2"), ("year_3", "Year 3")]:
        year = year_plan.get(year_key, {}) or {}
        objectives = year.get("objectives", []) or []
        if objectives:
            add_heading(doc, f"Objectives - {year_title}", level=2)
            for obj in objectives:
                doc.add_paragraph(obj.get("name", "Objective"), style="List Number")
                if obj.get("description"):
                    doc.add_paragraph(obj["description"]) 
                if obj.get("kpis"):
                    doc.add_paragraph("KPIs:")
                    add_bulleted_list(doc, obj.get("kpis", []))
                if obj.get("timeline"):
                    doc.add_paragraph(f"Timeline: {obj['timeline']}")
                if obj.get("owner"):
                    doc.add_paragraph(f"Owner: {obj['owner']}")

    action_plans = plan.get("action_plans", []) or []
    if action_plans:
        add_heading(doc, "Action Plans", level=2)
        for ap in action_plans:
            doc.add_paragraph(ap.get("objective_name", "Objective"), style="List Number")
            if ap.get("actions"):
                doc.add_paragraph("Actions:")
                add_bulleted_list(doc, ap.get("actions", []))
            if ap.get("owner"):
                doc.add_paragraph(f"Owner: {ap['owner']}")
            if ap.get("timeline"):
                doc.add_paragraph(f"Timeline: {ap['timeline']}")
            if ap.get("dependencies"):
                doc.add_paragraph("Dependencies:")
                add_bulleted_list(doc, ap.get("dependencies", []))

    add_heading(doc, "Appendix: Analysis Summary", level=2)
    facts = aggregated.get("facts", [])
    deductions = aggregated.get("deductions", [])
    internal = aggregated.get("factors", {}).get("internal", [])
    external = aggregated.get("factors", {}).get("external", [])
    insights = aggregated.get("insights", [])

    if facts:
        doc.add_paragraph("Facts:")
        add_bulleted_list(doc, facts)
    if deductions:
        doc.add_paragraph("Deductions:")
        add_bulleted_list(doc, deductions)
    if internal:
        doc.add_paragraph("Internal Factors:")
        add_bulleted_list(doc, internal)
    if external:
        doc.add_paragraph("External Factors:")
        add_bulleted_list(doc, external)
    if insights:
        doc.add_paragraph("Insights:")
        add_bulleted_list(doc, insights)

    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


def run_app() -> None:
    st.set_page_config(page_title="3-Year Strategic Plan Generator", layout="wide")
    st.title("Strategic Plan Generator (3-Year)")
    st.caption("Analyze your business context to draft vision, mission, values, goals, initiatives, objectives, and action plans.")

    with st.sidebar:
        st.header("Model Configuration")
        default_base = st.session_state.get("ollama_base", "http://192.168.2.200:11434")
        default_model = st.session_state.get("ollama_model", "llama3.1")
        base_url = st.text_input("Ollama Base URL", value=default_base, help="Example: http://192.168.2.200:11434")
        model = st.text_input("Model", value=default_model, help="Example: llama3.1")
        temperature = st.slider("Temperature", 0.0, 1.0, 0.2, 0.05)
        num_ctx = st.select_slider("Context Tokens (approx)", options=[2048, 4096, 8192, 12288, 16384], value=8192)
        connect_timeout = st.number_input("Connect timeout (s)", min_value=1.0, max_value=60.0, value=10.0, step=1.0)
        read_timeout = st.number_input("Read timeout (s)", min_value=10.0, max_value=600.0, value=180.0, step=10.0)
        max_retries = st.slider("HTTP retries", 0, 5, 2)
        st.session_state["ollama_base"] = base_url
        st.session_state["ollama_model"] = model

        st.divider()
        st.header("Chunking")
        max_chars = st.slider("Max chars per chunk", 1000, 6000, 3000, 250)
        overlap = st.slider("Overlap chars", 0, 1000, 300, 50)

    st.subheader("Input Business Context")
    uploaded = st.file_uploader("Upload .docx (optional)", type=["docx"], accept_multiple_files=False)
    text_input = st.text_area("Or paste your business details / problems / aspirations", height=220, placeholder="Describe your business, market, challenges, aspirations, constraints, stakeholders, offerings, geographies, timelines...")

    collected_texts: List[str] = []
    if uploaded is not None:
        try:
            doc_text = read_docx_text(uploaded.read())
            if doc_text:
                collected_texts.append(doc_text)
        except Exception as e:
            st.error(f"Failed to read DOCX: {e}")
    if text_input and text_input.strip():
        collected_texts.append(text_input.strip())

    if st.button("Analyze and Generate Plan", type="primary"):
        if not collected_texts:
            st.warning("Please upload a DOCX or provide text input.")
            st.stop()

        full_text = "\n\n".join(collected_texts).strip()
        st.info("Chunking input and contacting the model. This may take a few minutes for long inputs.")

        chunks = chunk_text(full_text, max_chars=max_chars, overlap=overlap)
        st.write(f"Identified {len(chunks)} chunk(s).")

        client = OllamaClient(
            OllamaConfig(
                base_url=base_url,
                model=model,
                temperature=temperature,
                num_ctx=int(num_ctx),
                connect_timeout=float(connect_timeout),
                read_timeout=float(read_timeout),
                max_retries=int(max_retries),
            )
        )

        # Connection test before heavy calls
        try:
            meta = client.test_connection()
            available_models = [m.get("name") for m in meta.get("models", [])] if isinstance(meta, dict) else []
            if available_models and model not in available_models:
                st.warning(f"Model '{model}' not in available models: {available_models}")
        except Exception as e:
            st.error(f"Failed to connect to Ollama at {base_url}: {e}")
            st.stop()

        progress = st.progress(0.0, text="Analyzing chunks...")
        per_chunk_results: List[Dict[str, Any]] = []
        total = max(1, len(chunks))
        for idx, ch in enumerate(chunks, start=1):
            result = call_analysis_for_chunk(client, ch)
            per_chunk_results.append(result)
            progress.progress(min(1.0, idx / total), text=f"Analyzed chunk {idx}/{total}")
        progress.empty()

        aggregated = aggregate_chunk_results(per_chunk_results)

        st.subheader("Aggregated Analysis")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Facts**")
            st.write(aggregated.get("facts", []))
            st.markdown("**Internal Factors**")
            st.write(aggregated.get("factors", {}).get("internal", []))
        with col2:
            st.markdown("**Deductions**")
            st.write(aggregated.get("deductions", []))
            st.markdown("**External Factors**")
            st.write(aggregated.get("factors", {}).get("external", []))
        st.markdown("**Insights**")
        st.write(aggregated.get("insights", []))

        st.subheader("Synthesis: Strategic Plan")
        with st.spinner("Synthesizing plan..."):
            plan = synthesize_strategy_plan(client, aggregated)

        st.markdown("**Vision**")
        st.write(plan.get("vision", ""))
        st.markdown("**Mission**")
        st.write(plan.get("mission", ""))

        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Values**")
            st.write(plan.get("values", []))
        with cols[1]:
            st.markdown("**Strategic Themes**")
            st.write(plan.get("strategic_themes", []))

        st.markdown("**Three-Year Goals**")
        st.write(plan.get("three_year_goals", []))
        st.markdown("**Initiatives**")
        st.write(plan.get("initiatives", []))
        st.markdown("**Year Plan**")
        st.write(plan.get("year_plan", {}))

        docx_bytes = build_docx_from_plan(plan, aggregated)
        st.download_button(
            label="Download Strategic Plan (.docx)",
            data=docx_bytes,
            file_name=f"strategic_plan_{(plan.get('organization_name') or 'organization').lower().replace(' ', '_')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


if __name__ == "__main__":
    run_app()

