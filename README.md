# ADO Portfolio Risk Agent — Capstone (Agents for Business)

Agente ADK 2.0 que hace triage automático del consumo de horas de Epics de
Azure DevOps: consulta el portafolio vía un servidor MCP propio, aplica
seguridad (PII + anti prompt-injection) antes de tocar cualquier LLM,
clasifica el riesgo por umbrales de negocio, y pausa para revisión humana
solo cuando hace falta — generando un briefing ejecutivo al final.

## Qué hay listo (ya escrito y probado)

| Archivo | Qué es | Estado |
|---|---|---|
| `mcp_server/ado_devops_mcp.py` | Servidor MCP real contra Azure DevOps (WIQL + workitemsbatch, mismo patrón que tu skill `ado-executive-report`) | ✅ Probado (imports + lógica de auth) |
| `security/redaction.py` | Redacción de PII + detección de prompt injection | ✅ 9/9 tests pasando |
| `tests/test_security.py` | Tests outcome-based del security screen | ✅ `pytest tests/test_security.py -v` |
| `.agents/skills/ado-risk-briefing/SKILL.md` | Agent Skill para redactar el briefing ejecutivo | ✅ Lista para usar |
| `.agents/CONTEXT.md` | Reglas de seguridad + umbrales de negocio (paved roads) | ✅ Lista |
| `docs/ARCHITECTURE.md` | Diagrama y justificación de diseño | ✅ Lista |
| `.env.example`, `pyproject.toml`, `.gitignore` | Config base del proyecto | ✅ Lista |

## Qué falta (por diseño — se hace en Antigravity, no a mano)

El grafo ADK (`app/agent.py`) **no** viene escrito de antemano: siguiendo la
filosofía del curso ("vibe coding"), se lo pides a Antigravity con prompts
específicos, para que genere código compatible con la versión exacta de
`google-adk` que tengas instalada. Sigue **`PROMPTS_FOR_ANTIGRAVITY.md`**
paso a paso — ahí está todo, en el mismo formato que los codelabs del curso.

## Orden de trabajo recomendado

1. Lee `docs/ARCHITECTURE.md` (5 min) para entender el diseño completo.
2. Copia `.env.example` a `.env` y completa tu API key de Gemini y tu PAT de ADO.
3. Corre los tests de seguridad para confirmar que todo funciona antes de tocar Antigravity:
   ```bash
   pip install -e .
   pytest tests/test_security.py -v
   ```
4. Abre esta carpeta en Antigravity IDE y sigue `PROMPTS_FOR_ANTIGRAVITY.md` de principio a fin.
5. Cuando tengas el agente corriendo en el Playground, graba tu video siguiendo `../video-script.md`.
6. Completa los `[placeholders]` de `../capstone-writeup.md` con tus datos reales y súbelo a Kaggle.

## Deadline

**Capstone Project: lunes 6 de julio de 2026, 11:59 PM PT.**

## Conceptos del curso cubiertos

Multi-agente/grafo ADK 2.0 · Servidores MCP · Agent Skills · Seguridad
(redacción PII + anti prompt-injection + human-in-the-loop) — ver el detalle
completo en `docs/ARCHITECTURE.md`.
