# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from typing import List, Dict, Any, AsyncGenerator
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from google.adk.workflow import Workflow, START, node, Edge
from google.adk.agents import LlmAgent
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from google.genai import types

from security.redaction import security_screen as run_screen
from app.config import get_risk_level

# Cargar variables de entorno
load_dotenv()

# --- Esquemas Pydantic para I/O y Estado -----------------------------------------

class WorkflowInput(BaseModel):
    area_path: str = Field(..., description="Area Path de Azure DevOps a inspeccionar (ej. 'Tribu Medios de Pago').")

class EpicRisk(BaseModel):
    epic_id: int = Field(..., description="ID del Epic en Azure DevOps")
    risk_level: str = Field(..., description="Nivel de riesgo ('at_risk' o 'critical')")
    rationale: str = Field(..., description="Breve explicación del riesgo")

class EpicRiskAnalysis(BaseModel):
    analyses: List[EpicRisk] = Field(..., description="Lista de análisis de riesgo por Epic")

class WorkflowOutput(BaseModel):
    on_track: List[Dict[str, Any]] = []
    approved: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    security_incidents: List[Dict[str, Any]] = []

class WorkflowState(BaseModel):
    on_track_epics: List[Dict[str, Any]] = []
    risky_epics: List[Dict[str, Any]] = []
    flagged_epics: List[Dict[str, Any]] = []
    analysis_results: Dict[str, Any] = {}
    approved_epics: List[Dict[str, Any]] = []
    rejected_epics: List[Dict[str, Any]] = []
    review_index: int = 0
    briefings: Dict[str, str] = {}

# --- Inicialización del MCP Toolset ----------------------------------------------

def get_mcp_toolset() -> McpToolset:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_path = os.path.abspath(os.path.join(current_dir, "..", "mcp_server", "ado_devops_mcp.py"))
    
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python",
                args=[mcp_path],
                env={
                    "ADO_ORG": os.environ.get("ADO_ORG", ""),
                    "ADO_PROJECT": os.environ.get("ADO_PROJECT", ""),
                    "ADO_PAT": os.environ.get("ADO_PAT", ""),
                }
            ),
            timeout=60.0
        )
    )

mcp_toolset = get_mcp_toolset()

# --- Definición de Nodos de Función del Grafo ------------------------------------

def _parse_text_or_json(text: str) -> str:
    text = text.strip()
    try:
        import json
        data = json.loads(text)
        if isinstance(data, dict) and "area_path" in data:
            return data["area_path"]
    except Exception:
        pass
    return text

def extract_area_path(node_input: Any) -> str:
    if hasattr(node_input, "area_path"):
        return getattr(node_input, "area_path")
    if isinstance(node_input, dict):
        if "area_path" in node_input:
            return node_input["area_path"]
        parts = node_input.get("parts", [])
        if parts and isinstance(parts, list):
            item = parts[0]
            text = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
            return _parse_text_or_json(text)
    if hasattr(node_input, "parts"):
        parts = getattr(node_input, "parts", [])
        if parts:
            part = parts[0]
            text = getattr(part, "text", "") or ""
            return _parse_text_or_json(text)
    if isinstance(node_input, str):
        return _parse_text_or_json(node_input)
    if hasattr(node_input, "model_dump"):
        try:
            dump = node_input.model_dump()
            parts = dump.get("parts", [])
            if parts:
                item = parts[0]
                text = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
                return _parse_text_or_json(text)
        except Exception:
            pass
    return str(node_input)

@node
async def fetch_portfolio(ctx: Context, node_input: Any) -> dict:
    """Nodo 1: Obtiene el listado de Epics bajo el Area Path de ADO."""
    area_path = extract_area_path(node_input)
    tools = await mcp_toolset.get_tools()
    get_portfolio_status_tool = next(t for t in tools if t.name == "get_portfolio_status")
    
    tool_ctx = ToolContext(invocation_context=ctx.get_invocation_context())
    res = await get_portfolio_status_tool.run_async(
        args={"area_path": area_path},
        tool_context=tool_ctx
    )
    
    # Extract the actual dictionary from McpTool return structure
    if isinstance(res, dict) and "content" in res:
        content = res["content"]
        if isinstance(content, list) and len(content) > 0:
            text = content[0].get("text", "")
            try:
                import json
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
                
    return res

@node
def security_screen(node_input: Any) -> dict:
    """Nodo 2: Limpia PII de títulos y detecta inyección de prompts."""
    epics = node_input.get("epics", []) or []
    screened_epics = [run_screen(epic) for epic in epics]
    return {"epics": screened_epics}

@node
def threshold_routing(node_input: Any) -> Event:
    """Nodo 3: Enruta epics a on_track, risky o flagged en base a seguridad e inversión."""
    epics = node_input.get("epics", []) or []
    on_track_epics = []
    risky_epics = []
    flagged_epics = []
    
    for epic in epics:
        if epic.get("security_flag"):
            flagged_epic = dict(epic)
            flagged_epic["risk_level"] = "critical"
            flagged_epic["rationale"] = f"Alerta de seguridad: prompt injection detectado en título: {epic.get('security_reasons', [])}"
            flagged_epics.append(flagged_epic)
        else:
            consumption_pct = epic.get("consumption_pct", 0.0)
            risk = get_risk_level(consumption_pct)
            clean_epic = dict(epic)
            clean_epic["risk_level"] = risk
            
            if risk == "on_track":
                clean_epic["rationale"] = "Bajo consumo de horas (dentro de lo planeado)."
                on_track_epics.append(clean_epic)
            else:
                risky_epics.append(clean_epic)
                
    if len(risky_epics) > 0:
        route = "has_risk"
    elif len(flagged_epics) > 0:
        route = "has_flagged"
    else:
        route = "no_risk"
        
    state_delta = {
        "on_track_epics": on_track_epics,
        "risky_epics": risky_epics,
        "flagged_epics": flagged_epics
    }
    
    return Event(output=risky_epics, route=route, state=state_delta)

# --- Nodo 4: risk_analysis (LlmAgent) --------------------------------------------

risk_analysis = LlmAgent(
    name="risk_analysis",
    model="gemini-3.1-flash-lite",
    instruction=(
        "Eres un analista de riesgos de portafolios experto. "
        "Analiza la lista de Epics en formato JSON. Para cada Epic, determina por qué está en riesgo "
        "(at_risk o critical) basándose en el consumo y estado. "
        "Devuelve una lista estructurada con el ID del Epic, el nivel de riesgo y la justificación (rationale) breve en español."
    ),
    output_schema=EpicRiskAnalysis,
    output_key="analysis_results"
)

# --- Nodo 5: human_review (RequestInput) -----------------------------------------

@node(rerun_on_resume=True)
async def human_review(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    """Nodo 5: Pausa para revisión humana de epics at_risk, critical o flagged."""
    flagged_epics = ctx.state.get("flagged_epics", []) or []
    risky_epics = ctx.state.get("risky_epics", []) or []
    
    # Resolver racional de riesgo desde la salida del LLM
    analyses = []
    if isinstance(node_input, dict) and "analyses" in node_input:
        analyses = node_input["analyses"]
    else:
        state_results = ctx.state.get("analysis_results")
        if isinstance(state_results, dict):
            analyses = state_results.get("analyses", []) or []
            
    rationale_map = {item.get("epic_id"): item.get("rationale") for item in analyses}
    
    # Enriquecer risky_epics con los análisis del LLM
    enriched_risky = []
    for epic in risky_epics:
        epic_copy = dict(epic)
        epic_id = epic_copy.get("id")
        epic_copy["rationale"] = rationale_map.get(epic_id, "Revisión requerida por consumo de horas.")
        enriched_risky.append(epic_copy)
        
    epics_to_review = []
    epics_to_review.extend(flagged_epics)
    epics_to_review.extend(enriched_risky)
    
    approved_epics = ctx.state.setdefault("approved_epics", [])
    rejected_epics = ctx.state.setdefault("rejected_epics", [])
    
    current_index = ctx.state.get("review_index", 0)
    
    while current_index < len(epics_to_review):
        epic = epics_to_review[current_index]
        epic_id = epic.get("id")
        interrupt_id = f"review_epic_{epic_id}"
        
        if not ctx.resume_inputs or interrupt_id not in ctx.resume_inputs:
            msg = (
                f"=== REVISIÓN REQUERIDA ===\n"
                f"Epic ID: {epic_id}\n"
                f"Título: {epic.get('title_clean')}\n"
                f"Horas: Planeadas={epic.get('hours_planned')}, Completadas={epic.get('hours_completed')}, Restantes={epic.get('hours_remaining')}\n"
                f"Riesgo / Razón: {epic.get('risk_level', 'critical')} - {epic.get('rationale')}\n\n"
                f"¿Desea enviar una alerta ejecutiva para este Epic? Responda 'aprobar' o 'rechazar'."
            )
            yield RequestInput(interrupt_id=interrupt_id, message=msg)
            return
            
        user_response = ctx.resume_inputs[interrupt_id].strip().lower()
        if user_response in ["si", "sí", "aprobar", "aprobado", "yes", "approve", "approved"]:
            epic_decision = dict(epic)
            epic_decision["human_decision"] = "approved"
            approved_epics.append(epic_decision)
        else:
            epic_decision = dict(epic)
            epic_decision["human_decision"] = "rejected"
            rejected_epics.append(epic_decision)
            
        current_index += 1
        ctx.state["review_index"] = current_index
        
    yield Event(output={
        "approved": approved_epics,
        "rejected": rejected_epics
    }, state={
        "approved_epics": approved_epics,
        "rejected_epics": rejected_epics
    })

# --- Nodo 5: draft_briefing -------------------------------------------------------

def load_briefing_skill_instructions() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    skill_path = os.path.abspath(os.path.join(current_dir, "..", ".agents", "skills", "ado-risk-briefing", "SKILL.md"))
    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
            return content.strip()
    except Exception as e:
        return "Redacta un briefing ejecutivo corto (3-5 bullets) sobre el riesgo de presupuesto/cronograma..."

@node
async def draft_briefing(ctx: Context, node_input: Any) -> Event:
    """Nodo 5: Genera el briefing ejecutivo para cada Epic aprobado usando la skill ado-risk-briefing."""
    import json
    from google.genai import Client
    
    approved_epics = ctx.state.get("approved_epics", []) or []
    if not approved_epics:
        return Event(output={"briefings": {}}, state={"briefings": {}})
        
    instructions = load_briefing_skill_instructions()
    briefings = {}
    
    client = Client()
    for epic in approved_epics:
        prompt = (
            f"Basándote en las instrucciones de la skill, redacta el briefing ejecutivo para este Epic:\n"
            f"{json.dumps(epic, indent=2)}\n"
        )
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=instructions,
                temperature=0.2,
            )
        )
        briefings[str(epic.get("id"))] = response.text.strip()
        
    return Event(output={"briefings": briefings}, state={"briefings": briefings})


# --- Nodo 6: final_summary -------------------------------------------------------

@node
def final_summary(ctx: Context, node_input: Any) -> Event:
    """Nodo 6: Genera el resumen final estructurado y un reporte Markdown."""
    on_track = ctx.state.get("on_track_epics", []) or []
    approved = ctx.state.get("approved_epics", []) or []
    rejected = ctx.state.get("rejected_epics", []) or []
    
    normal_approved = [e for e in approved if not e.get("security_flag")]
    normal_rejected = [e for e in rejected if not e.get("security_flag")]
    security_incidents = [e for e in approved + rejected if e.get("security_flag")]
    
    # Crear reporte Markdown
    lines = ["# Resumen de Análisis de Riesgo de Portafolio\n"]
    
    if on_track:
        lines.append("## Epics En Curso (Sin Riesgo / On Track)")
        lines.append("| ID | Título | Consumo % | Estado |")
        lines.append("| --- | --- | --- | --- |")
        for epic in on_track:
            lines.append(f"| {epic.get('id')} | {epic.get('title_clean')} | {epic.get('consumption_pct')}% | {epic.get('state')} |")
        lines.append("")
        
    if normal_approved:
        lines.append("## Alertas Aprobadas para Envío (Briefing Ejecutivo)")
        briefings = ctx.state.get("briefings", {}) or {}
        for epic in normal_approved:
            epic_id = epic.get("id")
            briefing = briefings.get(str(epic_id)) or briefings.get(int(epic_id))
            if briefing:
                lines.append(briefing)
                lines.append("")
            else:
                lines.append(f"- Epic {epic_id} - {epic.get('title_clean')} ({epic.get('consumption_pct')}% de consumo) - Sin briefing generado.")
        lines.append("")
        
    if normal_rejected:
        lines.append("## Alertas Rechazadas")
        lines.append("| ID | Título | Consumo % | Razón / Riesgo |")
        lines.append("| --- | --- | --- | --- |")
        for epic in normal_rejected:
            lines.append(f"| {epic.get('id')} | {epic.get('title_clean')} | {epic.get('consumption_pct')}% | {epic.get('risk_level')} - {epic.get('rationale')} |")
        lines.append("")

    if security_incidents:
        lines.append("## Incidentes de Seguridad Detectados")
        briefings = ctx.state.get("briefings", {}) or {}
        for epic in security_incidents:
            epic_id = epic.get("id")
            reasons = epic.get("security_reasons", [])
            reasons_str = ", ".join(reasons) if reasons else "Patrón sospechoso detectado"
            decision = "Aprobado para escalación" if epic.get("human_decision") == "approved" else "Rechazado"
            
            lines.append(f"### Epic {epic_id} - [Texto sospechoso detectado]")
            lines.append(f"- **Razón del bloqueo**: {reasons_str}")
            lines.append(f"- **Decisión del revisor humano**: {decision}")
            
            briefing = briefings.get(str(epic_id)) or briefings.get(int(epic_id))
            if briefing and epic.get("human_decision") == "approved":
                lines.append("- **Briefing Ejecutivo generado**:")
                lines.append(briefing)
            lines.append("")
        
    summary_text = "\n".join(lines)
    
    output_data = {
        "on_track": on_track,
        "approved": normal_approved,
        "rejected": normal_rejected,
        "security_incidents": security_incidents
    }
    
    content = types.Content(role='model', parts=[types.Part.from_text(text=summary_text)])
    return Event(output=output_data, content=content)

# --- Construcción del Grafo ------------------------------------------------------

root_agent = Workflow(
    name="ado_portfolio_workflow",
    edges=[
        ('START', fetch_portfolio),
        (fetch_portfolio, security_screen),
        (security_screen, threshold_routing),
        Edge(from_node=threshold_routing, to_node=risk_analysis, route="has_risk"),
        Edge(from_node=threshold_routing, to_node=human_review, route="has_flagged"),
        Edge(from_node=threshold_routing, to_node=final_summary, route="no_risk"),
        (risk_analysis, human_review),
        (human_review, draft_briefing),
        (draft_briefing, final_summary),
    ],
    output_schema=WorkflowOutput,
    state_schema=WorkflowState,
)

app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)
