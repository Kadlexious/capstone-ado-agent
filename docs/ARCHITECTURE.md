# Arquitectura - ADO Portfolio Risk Agent

## Problema de negocio

Los leads de una tribu de DevOps (ej. Medios de Pago / Interdin-Diners)
revisan manualmente, epic por epic, si el consumo de horas en Azure DevOps
esta alineado con el presupuesto y el cronograma. Es un trabajo repetitivo,
propenso a error humano, y que no escala cuando hay muchos Epics activos en
paralelo. Ademas, cualquier automatizacion que lea texto libre de tickets
(titulos, comentarios) queda expuesta a datos sensibles (PII) o incluso a
manipulacion deliberada del texto para "engañar" al sistema.

## Solucion

Un agente ADK 2.0 que automatiza la primera pasada de este triage:
consulta el portafolio, calcula el riesgo, y solo pide tiempo humano cuando
de verdad hace falta (Epics en riesgo o con contenido sospechoso), en vez de
para cada Epic.

```
                     ┌─────────────────────┐
   area_path  ─────► │  fetch_portfolio     │  (MCP: ado-devops-portfolio)
                     │  (funcion, sin LLM)  │
                     └──────────┬──────────┘
                                │ lista de epics
                                ▼
                     ┌─────────────────────┐
                     │  security_screen     │  redact_pii() +
                     │  (funcion, sin LLM)  │  detect_prompt_injection()
                     └──────────┬──────────┘
                       ┌────────┴────────┐
              limpios  │                 │  security_flag = true
                       ▼                 │
             ┌───────────────────┐       │
             │ clasificar umbral │       │
             │  (config.py)      │       │
             └─────────┬─────────┘       │
        on_track       │ at_risk/        │
        (< 80%)        │ critical        │
             │         ▼                 │
             │  ┌───────────────┐        │
             │  │ risk_analysis  │       │
             │  │ (LlmAgent)     │       │
             │  └───────┬───────┘        │
             │          ▼                ▼
             │   ┌──────────────────────────┐
             │   │ human_review (RequestInput)│
             │   └──────────────┬───────────┘
             │                  ▼
             │        ┌───────────────────┐
             │        │  draft_briefing    │  skill: ado-risk-briefing
             │        │  (LlmAgent + skill)│
             │        └─────────┬─────────┘
             └──────────────────┼─────────────┐
                                 ▼             ▼
                          ┌─────────────────────────┐
                          │     final_summary        │
                          └─────────────────────────┘
```

## Mapeo a conceptos del curso

| Concepto (dia del curso) | Donde se aplica |
|---|---|
| ADK 2.0 graph workflow, multi-nodo (Dia 3) | `app/agent.py`: `fetch_portfolio` -> `security_screen` -> ruteo condicional -> `risk_analysis` (LLM) -> `RequestInput` -> `draft_briefing` -> `final_summary` |
| Servidores MCP (Dia 2) | `mcp_server/ado_devops_mcp.py`: servidor MCP real con las herramientas `get_portfolio_status` y `get_epic_detail`, autenticado con PAT via Basic Auth |
| Agent Skills (Dia 3) | `.agents/skills/ado-risk-briefing/SKILL.md`: se carga solo cuando hay datos de riesgo que resumir (progressive disclosure) |
| Seguridad y evaluacion (Dia 4) | `security/redaction.py` (PII + prompt injection, con 9 tests unitarios pasando), `.agents/CONTEXT.md` (paved roads + TDD planning gate), human-in-the-loop obligatorio para riesgo alto |
| (Opcional) Produccion (Dia 5) | Paso 7 de `PROMPTS_FOR_ANTIGRAVITY.md`: deploy a Agent Runtime |

## Por que "Agents for Business"

Resuelve un problema real de gestion de portafolios de proyectos (consumo de
horas vs. presupuesto), reduce el tiempo de un lead de tribu en revision
manual, y demuestra valor de negocio medible: menos horas de revision
manual, deteccion temprana de sobrecostos, y una capa de seguridad que
protege contra manipulacion de datos y fuga de informacion sensible - un
requisito no negociable al automatizar sobre datos corporativos reales.

## Decisiones de diseño y por que

- **El MCP server es de solo lectura.** Deliberado: un agente de este tipo
  nunca deberia poder escribir/cerrar Epics en ADO automaticamente; solo
  informa y sugiere.
- **Los umbrales de riesgo viven en codigo, no en el prompt del LLM.** Un
  LLM puede alucinar o ser manipulado; un `if consumption_pct > 100` no.
- **El LLM nunca ve texto sin pasar por `security_screen` primero.** Esto
  es upstream de cualquier prompt injection posible desde un titulo o
  comentario de ADO.
- **Human-in-the-loop es obligatorio para riesgo alto, no opcional.** El
  agente acelera el triage, pero la decision de escalar sigue siendo
  humana - alineado con el pilar de "Effective Trust" del whitepaper de
  seguridad del Dia 4.
