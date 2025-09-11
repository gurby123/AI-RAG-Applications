THIS SHOULD BE A LINTER ERRORimport io
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
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
    read_timeout: float = 300.0
    max_retries: int = 2
    stream: bool = True
    num_predict: int = 1024


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
            "stream": bool(self.config.stream),
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.num_predict,
            },
        }
        if system:
            payload["system"] = system
        if not payload["stream"]:
            response = self.session.post(
                endpoint,
                json=payload,
                timeout=(self.config.connect_timeout, self.config.read_timeout),
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
        # Streaming mode: accumulate tokens
        response = self.session.post(
            endpoint,
            json=payload,
            timeout=(self.config.connect_timeout, self.config.read_timeout),
            stream=True,
        )
        response.raise_for_status()
        collected: List[str] = []
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            token = obj.get("response")
            if isinstance(token, str):
                collected.append(token)
            if obj.get("done") is True:
                break
        return "".join(collected)

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


def read_docx_text(uploaded_file) -> str:
    """Extracts text from a .docx file-like object or bytes, including tables."""
    try:
        doc = Document(uploaded_file if not isinstance(uploaded_file, (bytes, bytearray)) else io.BytesIO(uploaded_file))
        paragraph_texts = [p.text for p in doc.paragraphs]
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    paragraph_texts.append(cell.text)
        paragraph_text = "\n".join([t for t in paragraph_texts if t and t.strip()])
        return paragraph_text.strip()
    except Exception as exc:
        raise ValueError(f"Failed to read .docx: {exc}")


def chunk_text(text: str, max_chars: int = 3000, overlap: int = 300) -> List[str]:
    """Simple character-based chunking with overlap."""
    if not text:
        return []
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    chunks: List[str] = []
    start = 0
    end = max_chars
    while start < len(text):
        chunks.append(text[start:end])
        start = end - overlap
        if start < 0:
            start = 0
        end = start + max_chars
    return chunks


def call_analysis_for_chunk(client: OllamaClient, chunk_text_value: str) -> Dict[str, Any]:
    system = (
        "You are a senior corporate strategy analyst."
        " Extract factor rows with cautious deductions."
        " Be precise and concise. Output valid minified JSON only."
    )
    prompt = (
        "From the following business context CHUNK, produce factor rows, each with:"
        " name (string), facts (string[]), deductions (string[]), summary (string)."
        "\nOrganize as strict JSON under factor_tables with two objects: internal and external."
        "\ninternal has keys: customer_demographics, business_activities_cost, marketing, production_services, staff, leadership, operations, finance, technology, compliance, supply_chain."
        "\nexternal has keys: political, economic, social, technological, legal, environmental."
        "\nEach key is an array of row objects as described. Return only JSON."
        f"\n\nCHUNK:\n{chunk_text_value}"
    )
    try:
        response_text = client.generate(prompt=prompt, system=system)
    except (requests.Timeout, requests.ConnectionError, requests.RequestException) as e:
        return {
            "factor_tables": {"internal": {}, "external": {}},
            "_error": f"request_failed: {e}",
        }
    json_block = extract_first_json_block(response_text) or response_text
    try:
        parsed = json.loads(json_block)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object")
        # Normalize missing keys
        ft = parsed.get("factor_tables") or parsed
        if not isinstance(ft, dict):
            ft = {"internal": {}, "external": {}}
        return {"factor_tables": ft}
    except Exception:
        return {"factor_tables": {"internal": {}, "external": {}}, "_raw": response_text}


def aggregate_chunk_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    def normalize_text(text_item: str) -> str:
        return re.sub(r"\s+", " ", (text_item or "").strip()).strip().rstrip(".;")

    def merge_lists(a: List[str], b: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in (a or []) + (b or []):
            norm = normalize_text(item).casefold()
            if norm and norm not in seen:
                seen.add(norm)
                out.append(item.strip())
        return out

    def merge_row(existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        if not existing:
            existing = {"name": new.get("name") or "Factor", "facts": [], "deductions": [], "summary": ""}
        existing["facts"] = merge_lists(existing.get("facts", []), new.get("facts", []) or [])
        existing["deductions"] = merge_lists(existing.get("deductions", []), new.get("deductions", []) or [])
        # Prefer longer summary
        summaries = [existing.get("summary") or "", new.get("summary") or ""]
        existing["summary"] = max(summaries, key=lambda s: len(s))
        if not existing.get("name") and new.get("name"):
            existing["name"] = new.get("name")
        return existing

    def merge_groups(acc_groups: List[Dict[str, Any]], new_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_name: Dict[str, Dict[str, Any]] = {}
        for g in acc_groups or []:
            key = normalize_text(g.get("name", "")).casefold()
            by_name[key] = g
        for g in new_groups or []:
            key = normalize_text(g.get("name", "")).casefold()
            if key in by_name:
                by_name[key] = merge_row(by_name[key], g)
            else:
                by_name[key] = merge_row({}, g)
        return list(by_name.values())

    aggregated_ft: Dict[str, Dict[str, List[Dict[str, Any]]]] = {"internal": {}, "external": {}}
    raw_responses: List[str] = []

    for r in results:
        ft = (r.get("factor_tables") or {"internal": {}, "external": {}})
        if not isinstance(ft, dict):
            ft = {"internal": {}, "external": {}}
        for side in ("internal", "external"):
            section = ft.get(side) or {}
            # If the section is a list, treat as uncategorized
            if isinstance(section, list):
                merged = merge_groups(aggregated_ft[side].get("uncategorized", []) or [], section)
                if merged:
                    aggregated_ft[side]["uncategorized"] = merged
                continue
            if not isinstance(section, dict):
                continue
            # Merge all keys present, not only the expected ones
            for k, v in section.items():
                groups_list = v if isinstance(v, list) else []
                merged = merge_groups(aggregated_ft[side].get(k, []) or [], groups_list)
                if merged:
                    aggregated_ft[side][k] = merged
        raw = r.get("_raw")
        if isinstance(raw, str) and raw.strip():
            raw_responses.append(raw.strip())

    return {"factor_tables": aggregated_ft, "_raw": raw_responses}


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
        " action_plans (object[] with: objective_name, actions string[], owner, timeline, dependencies string[]),"
        " factor_tables (object with internal and external keys)."
        " internal: object with keys [customer_demographics, business_activities_cost, marketing, production_services, staff, leadership, operations, finance, technology, compliance, supply_chain] each as array of {name, facts string[], deductions string[], summary}."
        " external: object with keys [political, economic, social, technological, legal, environmental] (PESTLE) each as array of {name, facts string[], deductions string[], summary}."
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
            "factor_tables": {"internal": {}, "external": {}},
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

    # Factor tables (internal and external)
    factor_tables = plan.get("factor_tables", {}) or {}
    internal_ft = factor_tables.get("internal", {}) or {}
    external_ft = factor_tables.get("external", {}) or {}

    def add_factor_section(title: str, groups: List[Dict[str, Any]]) -> None:
        if not groups:
            return
        add_heading(doc, title, level=2)
        for group in groups:
            name = group.get("name") or "Factor"
            facts = group.get("facts", []) or []
            deductions = group.get("deductions", []) or []
            summary = group.get("summary") or ""
            if name:
                doc.add_paragraph(name, style="List Number")
            if facts:
                doc.add_paragraph("Facts:")
                add_bulleted_list(doc, facts)
            if deductions:
                doc.add_paragraph("Deductions:")
                add_bulleted_list(doc, deductions)
            if summary:
                doc.add_paragraph(f"Summary: {summary}")

    if internal_ft:
        add_heading(doc, "Internal Factors", level=2)
        for key, title in [
            ("customer_demographics", "Customer Demographics"),
            ("business_activities_cost", "Business Activities & Cost"),
            ("marketing", "Marketing"),
            ("production_services", "Production / Services"),
            ("staff", "Staff"),
            ("leadership", "Leadership"),
            ("operations", "Operations"),
            ("finance", "Finance"),
            ("technology", "Technology"),
            ("compliance", "Compliance"),
            ("supply_chain", "Supply Chain"),
            ("uncategorized", "Uncategorized"),
        ]:
            add_factor_section(title, internal_ft.get(key, []) or [])

    if external_ft:
        add_heading(doc, "External Factors (PESTLE)", level=2)
        for key, title in [
            ("political", "Political"),
            ("economic", "Economic"),
            ("social", "Social"),
            ("technological", "Technological"),
            ("legal", "Legal"),
            ("environmental", "Environmental"),
            ("uncategorized", "Uncategorized"),
        ]:
            add_factor_section(title, external_ft.get(key, []) or [])

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
        stream_mode = st.toggle("Stream responses", value=True)
        num_predict = st.slider("Max tokens to generate", 256, 4096, 1024, 128)
        st.session_state["ollama_base"] = base_url
        st.session_state["ollama_model"] = model

        st.divider()
        st.header("Chunking")
        max_chars = st.slider("Max chars per chunk", 200, 1200, 1200, 50)
        overlap = st.slider("Overlap chars", 0, 1000, 300, 50)

    st.subheader("Input Business Context")
    uploaded = st.file_uploader("Upload .docx (optional)", type=["docx"], accept_multiple_files=False)
    text_input = st.text_area("Or paste your business details / problems / aspirations", height=220, placeholder="Describe your business, market, challenges, aspirations, constraints, stakeholders, offerings, geographies, timelines...")

    collected_texts: List[str] = []
    if uploaded is not None:
        try:
            doc_text = read_docx_text(uploaded)
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
                stream=bool(stream_mode),
                num_predict=int(num_predict),
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

        st.subheader("Aggregated Factor Tables Preview")
        factor_tables = aggregated.get("factor_tables", {}) or {}
        internal_ft = factor_tables.get("internal", {}) or {}
        external_ft = factor_tables.get("external", {}) or {}

        def render_factor_group(title: str, groups: List[Dict[str, Any]]):
            if not groups:
                return
            st.markdown(f"### {title}")
            rows: List[Dict[str, Any]] = []
            for g in groups:
                rows.append(
                    {
                        "name": g.get("name"),
                        "facts": "; ".join(g.get("facts", []) or []),
                        "deductions": "; ".join(g.get("deductions", []) or []),
                        "summary": g.get("summary", ""),
                    }
                )
            if rows:
                df = pd.DataFrame(rows, columns=["name", "facts", "deductions", "summary"])
                st.dataframe(df, use_container_width=True)

        if internal_ft:
            st.markdown("#### Internal Factors")
            for key, title in [
                ("customer_demographics", "Customer Demographics"),
                ("business_activities_cost", "Business Activities & Cost"),
                ("marketing", "Marketing"),
                ("production_services", "Production / Services"),
                ("staff", "Staff"),
                ("leadership", "Leadership"),
                ("operations", "Operations"),
                ("finance", "Finance"),
                ("technology", "Technology"),
                ("compliance", "Compliance"),
                ("supply_chain", "Supply Chain"),
                ("uncategorized", "Uncategorized"),
            ]:
                render_factor_group(title, internal_ft.get(key, []) or [])

        if external_ft:
            st.markdown("#### External Factors (PESTLE)")
            for key, title in [
                ("political", "Political"),
                ("economic", "Economic"),
                ("social", "Social"),
                ("technological", "Technological"),
                ("legal", "Legal"),
                ("environmental", "Environmental"),
                ("uncategorized", "Uncategorized"),
            ]:
                render_factor_group(title, external_ft.get(key, []) or [])

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

        # Factor tables rendering
        st.markdown("**Factor Tables**")
        factor_tables = plan.get("factor_tables", {}) or {}
        internal_ft = factor_tables.get("internal", {}) or {}
        external_ft = factor_tables.get("external", {}) or {}

        def render_factor_group(title: str, groups: List[Dict[str, Any]]):
            if not groups:
                return
            st.markdown(f"### {title}")
            rows: List[Dict[str, Any]] = []
            for g in groups:
                rows.append(
                    {
                        "name": g.get("name"),
                        "facts": "; ".join(g.get("facts", []) or []),
                        "deductions": "; ".join(g.get("deductions", []) or []),
                        "summary": g.get("summary", ""),
                    }
                )
            if rows:
                df = pd.DataFrame(rows, columns=["name", "facts", "deductions", "summary"])
                st.dataframe(df, use_container_width=True)

        if internal_ft:
            st.markdown("#### Internal Factors")
            render_factor_group("Customer Demographics", internal_ft.get("customer_demographics", []) or [])
            render_factor_group("Business Activities & Cost", internal_ft.get("business_activities_cost", []) or [])
            render_factor_group("Marketing", internal_ft.get("marketing", []) or [])
            render_factor_group("Production / Services", internal_ft.get("production_services", []) or [])
            render_factor_group("Staff", internal_ft.get("staff", []) or [])
            render_factor_group("Leadership", internal_ft.get("leadership", []) or [])
            render_factor_group("Operations", internal_ft.get("operations", []) or [])
            render_factor_group("Finance", internal_ft.get("finance", []) or [])
            render_factor_group("Technology", internal_ft.get("technology", []) or [])
            render_factor_group("Compliance", internal_ft.get("compliance", []) or [])
            render_factor_group("Supply Chain", internal_ft.get("supply_chain", []) or [])

        if external_ft:
            st.markdown("#### External Factors (PESTLE)")
            render_factor_group("Political", external_ft.get("political", []) or [])
            render_factor_group("Economic", external_ft.get("economic", []) or [])
            render_factor_group("Social", external_ft.get("social", []) or [])
            render_factor_group("Technological", external_ft.get("technological", []) or [])
            render_factor_group("Legal", external_ft.get("legal", []) or [])
            render_factor_group("Environmental", external_ft.get("environmental", []) or [])

        docx_bytes = build_docx_from_plan(plan, aggregated)
        st.download_button(
            label="Download Strategic Plan (.docx)",
            data=docx_bytes,
            file_name=f"strategic_plan_{(plan.get('organization_name') or 'organization').lower().replace(' ', '_')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


if __name__ == "__main__":
    run_app()

