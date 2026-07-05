# Contexto del proyecto y estandares de codigo seguro
## ADO Portfolio Risk Agent - Capstone "Agents for Business"

Este archivo se carga automaticamente por Antigravity/ADK como contexto
persistente del proyecto (patron ensenado en el codelab "Vibecode and Secure
an AI Agent Lifecycle with Antigravity and TDD", Dia 4 del curso).

## Que hace este agente

Un workflow ADK 2.0 que consulta el estado de consumo de horas de Epics de
Azure DevOps (via el MCP server `ado-devops-portfolio`), clasifica el riesgo
de presupuesto/cronograma con un LLM, y pausa para revision humana
(human-in-the-loop) cuando un Epic esta en riesgo o critico, antes de generar
un briefing ejecutivo con la skill `ado-risk-briefing`.

## Paved roads (patrones obligatorios)

1. **Nunca llamar a Azure DevOps directamente desde el grafo.** Todo acceso a
   ADO pasa por las herramientas del MCP server `ado-devops-portfolio`
   (`get_portfolio_status`, `get_epic_detail`). Esto centraliza el manejo del
   PAT y la redaccion de secretos en un solo lugar.
2. **Todo texto libre de ADO (titulo, descripcion) pasa por
   `security.redaction.security_screen()` antes de llegar a cualquier
   `LlmAgent`.** No hay excepciones, incluso si el dato "parece" limpio.
3. **Si `security_flag` es `true` para un Epic, ese Epic NUNCA llega al nodo
   de analisis de riesgo por LLM.** Se enruta directo al nodo human-in-the-loop
   con la razon de seguridad adjunta.
4. **El PAT de Azure DevOps y cualquier API key viven en variables de entorno
   (`.env`, nunca hardcodeadas).** Ver `.env.example`.
5. **Toda herramienta de agente valida sus parametros con un esquema Pydantic**
   en vez de parsear dicts/strings sueltos.
6. **No usar `run_command` ni ejecucion de shell dentro del grafo del agente**
   salvo que este explicitamente aprobado en `hooks.json`.

## Pre-Commit Remediation Loop

Si un `git commit` falla por un hook (pre-commit / Semgrep), trata la falla
como una tarea de refactor: corrige el problema senalado, vuelve a correr
`pytest`, y solo entonces reintenta el commit. No uses `--no-verify` para
saltarte el hook.

## TDD Planning Gate

Durante la fase de Plan, todo `implementation_plan.md` que Antigravity genere
para este proyecto DEBE incluir una seccion **"Security Boundaries &
Assertions"** que identifique explicitamente:
- Que pasa si el texto de un Epic contiene un intento de prompt injection.
- Que pasa si el PAT de ADO es invalido o expira.
- Que pasa si el LLM de analisis de riesgo devuelve una clasificacion fuera
  del enum esperado (`on_track` / `at_risk` / `critical`).
- Que un Epic clasificado `at_risk` o `critical` JAMAS se auto-aprueba ni se
  auto-cierra sin pasar por `RequestInput` (human-in-the-loop).

## Umbrales de negocio (no cambiar sin aprobacion humana explicita)

- `on_track`: consumption_pct < 80
- `at_risk`: 80 <= consumption_pct <= 100
- `critical`: consumption_pct > 100, O `security_flag == true`

Estos umbrales viven en codigo (`app/config.py`), nunca se le pide al LLM que
los "recuerde" o los aplique de memoria.
