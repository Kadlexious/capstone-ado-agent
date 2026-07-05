"""
ADO DevOps Portfolio MCP Server
================================

Servidor MCP (Model Context Protocol) que expone el estado de un portafolio
de Azure DevOps (horas presupuestadas vs. consumidas, avance por etapa) como
herramientas que un agente (Antigravity / ADK) puede invocar.

Reutiliza el mismo patrón de autenticación (PAT vía Basic Auth) y de consulta
(WIQL + workitemsbatch) que ya usas en tu skill `ado-executive-report`, para
que el comportamiento sea consistente entre ambos.

Concepto del curso que demuestra: Día 2 - Agent Tools & Interoperability (MCP).

Como se usa desde Antigravity / Antigravity CLI / ADK
------------------------------------------------------
1. Instala dependencias:
     pip install "mcp[cli]" requests
2. Agrega el servidor a tu configuracion MCP (~/.gemini/config/mcp_config.json):

    {
      "mcpServers": {
        "ado-devops-portfolio": {
          "command": "python3",
          "args": ["/ruta/completa/a/ado_devops_mcp.py"],
          "env": {
            "ADO_ORG": "Interdin",
            "ADO_PROJECT": "Tribu Medios de Pago",
            "ADO_PAT": "<tu PAT>"
          }
        }
      }
    }

3. En Antigravity, Settings -> Customizations -> Installed MCP Servers -> Refresh.
4. Prueba con un prompt como:
     "Usa la herramienta ado-devops-portfolio para revisar el estado del
      Epic 12345 en Interdin y dime si algun Epic esta en riesgo de presupuesto."

Notas de seguridad
-------------------
- El PAT se lee de una variable de entorno, nunca se hardcodea ni se expone
  en las respuestas de las herramientas (ver `_redact` mas abajo).
- Las herramientas son de solo lectura (GET / WIQL POST de consulta). No hay
  ninguna operacion de escritura contra Azure DevOps.
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass, field
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ado-devops-portfolio")

API_VERSION = "7.0"
PAT_PATTERN = re.compile(r"[A-Za-z0-9]{52}")  # forma tipica de un PAT de ADO


def _redact(text: str) -> str:
    """Evita que un PAT (o algo con esa forma) se filtre en logs o respuestas."""
    return PAT_PATTERN.sub("[REDACTED_TOKEN]", text or "")


@dataclass
class AdoClient:
    org: str
    pat: str
    project: str | None = None
    base: str = field(init=False)
    headers: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.base = f"https://dev.azure.com/{self.org}"
        auth = base64.b64encode(f":{self.pat}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        }

    def _get(self, url: str) -> dict[str, Any]:
        resp = requests.get(url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(url, headers=self.headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def query_epics_under(self, area_path: str) -> list[int]:
        """WIQL: todos los Epics activos bajo un Area Path dado."""
        project_segment = requests.utils.quote(self.project) if self.project else ""
        wiql = {
            "query": (
                "SELECT [System.Id] FROM WorkItems "
                "WHERE [System.WorkItemType] = 'Epic' "
                "AND [System.State] <> 'Closed' "
                f"AND [System.AreaPath] UNDER '{area_path}'"
            )
        }
        url = f"{self.base}/{project_segment}/_apis/wit/wiql?api-version={API_VERSION}"
        result = self._post(url, wiql)
        return [wi["id"] for wi in result.get("workItems", [])]

    def get_work_items_batch(self, ids: list[int], fields: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        url = f"{self.base}/_apis/wit/workitemsbatch?api-version={API_VERSION}"
        out: list[dict[str, Any]] = []
        page_size = 200
        for i in range(0, len(ids), page_size):
            page = ids[i : i + page_size]
            body = {"ids": page, "fields": fields}
            result = self._post(url, body)
            out.extend(result.get("value", []))
        return out

    def get_descendant_ids(self, work_item_id: int) -> list[int]:
        """WIQL recursivo (WorkItemLinks + MODE Recursive): todos los
        descendientes de un work item (User Stories, Tasks, etc.)."""
        project_segment = requests.utils.quote(self.project) if self.project else ""
        wiql = {
            "query": (
                "SELECT [System.Id] FROM WorkItemLinks "
                f"WHERE ([Source].[System.Id] = {work_item_id}) "
                "AND ([System.Links.LinkType] = 'System.LinkTypes.Hierarchy-Forward') "
                "MODE (Recursive)"
            )
        }
        url = f"{self.base}/{project_segment}/_apis/wit/wiql?api-version={API_VERSION}"
        result = self._post(url, wiql)
        ids: set[int] = set()
        for rel in result.get("workItemRelations", []):
            target = rel.get("target")
            if target:
                ids.add(target["id"])
        return sorted(ids)

    def get_task_hours_rollup(self, epic_id: int) -> dict[str, float]:
        """Suma OriginalEstimate/Completed/Remaining Work de todas las Tasks bajo un Epic."""
        descendant_ids = self.get_descendant_ids(epic_id)
        if not descendant_ids:
            return {"estimate": 0.0, "completed": 0.0, "remaining": 0.0}
        items = self.get_work_items_batch(
            descendant_ids,
            ["System.WorkItemType",
             "Microsoft.VSTS.Scheduling.OriginalEstimate",
             "Microsoft.VSTS.Scheduling.CompletedWork",
             "Microsoft.VSTS.Scheduling.RemainingWork"],
        )
        estimate = 0.0
        completed = 0.0
        remaining = 0.0
        for wi in items:
            f = wi.get("fields", {})
            if f.get("System.WorkItemType") == "Task":
                estimate += float(f.get("Microsoft.VSTS.Scheduling.OriginalEstimate", 0) or 0)
                completed += float(f.get("Microsoft.VSTS.Scheduling.CompletedWork", 0) or 0)
                remaining += float(f.get("Microsoft.VSTS.Scheduling.RemainingWork", 0) or 0)
        return {"estimate": estimate, "completed": completed, "remaining": remaining}


def _client_from_env(org: str | None, project: str | None, pat: str | None) -> AdoClient:
    org = org or os.environ.get("ADO_ORG")
    project = project or os.environ.get("ADO_PROJECT")
    pat = pat or os.environ.get("ADO_PAT")
    if not org or not pat:
        raise ValueError(
            "Faltan credenciales de Azure DevOps. Define ADO_ORG y ADO_PAT "
            "como variables de entorno, o pasalas explicitamente a la herramienta."
        )
    return AdoClient(org=org, pat=pat, project=project)


# Campos estandar que usamos para calcular consumo vs. presupuesto.
# Ajusta estos nombres si tu proceso de ADO usa campos custom distintos
# (por ejemplo los que ya usas en el widget "CONSUMO REAL vs PRESUPUESTO").
PORTFOLIO_FIELDS = [
    "System.Id",
    "System.Title",
    "System.State",
    "System.AreaPath",
    "Microsoft.VSTS.Scheduling.OriginalEstimate",
    "Microsoft.VSTS.Scheduling.CompletedWork",
    "Microsoft.VSTS.Scheduling.RemainingWork",
]


@mcp.tool()
def get_portfolio_status(
    area_path: str,
    org: str | None = None,
    project: str | None = None,
    pat: str | None = None,
) -> dict[str, Any]:
    """Devuelve el estado de consumo de horas de todos los Epics activos bajo
    un Area Path de Azure DevOps: horas estimadas, completadas, restantes y
    el porcentaje de consumo. Usalo como primer paso antes de pedir un
    analisis de riesgo.

    Args:
        area_path: Area Path de ADO a inspeccionar (ej. "Interdin\\Tribu Medios de Pago").
        org: Organizacion de ADO. Si se omite, se toma de la variable de entorno ADO_ORG.
        project: Proyecto de ADO (opcional).
        pat: Personal Access Token. Si se omite, se toma de ADO_PAT.
    """
    try:
        client = _client_from_env(org, project, pat)
        epic_ids = client.query_epics_under(area_path)
        items = client.get_work_items_batch(epic_ids, PORTFOLIO_FIELDS)

        epics = []
        for wi in items:
            f = wi.get("fields", {})
            epic_estimate = float(f.get("Microsoft.VSTS.Scheduling.OriginalEstimate", 0) or 0)
            rollup = client.get_task_hours_rollup(wi.get("id"))
            completed = rollup["completed"]
            remaining = rollup["remaining"]
            tasks_estimate = rollup["estimate"]
            planned_total = tasks_estimate or epic_estimate or (completed + remaining)
            consumption_pct = round((completed / planned_total) * 100, 1) if planned_total else 0.0
            epics.append(
                {
                    "id": wi.get("id"),
                    "title": _redact(f.get("System.Title", "")),
                    "state": f.get("System.State"),
                    "hours_planned": planned_total,
                    "hours_completed": completed,
                    "hours_remaining": remaining,
                    "consumption_pct": consumption_pct,
                }
            )
        return {"area_path": area_path, "epic_count": len(epics), "epics": epics}
    except requests.HTTPError as exc:
        detail = _redact(exc.response.text[:500]) if exc.response is not None else ""
        return {
            "error": f"HTTP {exc.response.status_code if exc.response is not None else '?'} consultando Azure DevOps.",
            "detail": detail,
        }
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def get_epic_detail(
    epic_id: int,
    org: str | None = None,
    project: str | None = None,
    pat: str | None = None,
) -> dict[str, Any]:
    """Devuelve el detalle de un Epic puntual de Azure DevOps (titulo, estado,
    horas). Usalo cuando el analisis de riesgo necesite profundizar en un
    Epic especifico antes de escalarlo a revision humana.

    Args:
        epic_id: ID numerico del Epic en Azure DevOps.
        org: Organizacion de ADO (opcional, usa ADO_ORG si se omite).
        project: Proyecto de ADO (opcional).
        pat: Personal Access Token (opcional, usa ADO_PAT si se omite).
    """
    try:
        client = _client_from_env(org, project, pat)
        items = client.get_work_items_batch([epic_id], PORTFOLIO_FIELDS)
        if not items:
            return {"error": f"No se encontro el Epic {epic_id}."}
        f = items[0].get("fields", {})
        rollup = client.get_task_hours_rollup(epic_id)
        return {
            "id": epic_id,
            "title": _redact(f.get("System.Title", "")),
            "state": f.get("System.State"),
            "area_path": f.get("System.AreaPath"),
            "hours_estimate": rollup['estimate'] or f.get('Microsoft.VSTS.Scheduling.OriginalEstimate'),
            "hours_completed": rollup["completed"],
            "hours_remaining": rollup["remaining"],
        }
    except requests.HTTPError as exc:
        detail = _redact(exc.response.text[:500]) if exc.response is not None else ""
        return {
            "error": f"HTTP {exc.response.status_code if exc.response is not None else '?'} consultando Azure DevOps.",
            "detail": detail,
        }
    except ValueError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run()
