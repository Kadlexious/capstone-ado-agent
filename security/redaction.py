"""
Security screen para el ADO Portfolio Agent.
==============================================

Concepto del curso que demuestra: Dia 4 - Vibe Coding Agent Security and
Evaluation. Este modulo es puro Python (sin dependencias de ADK), pensado
para correr ANTES de que cualquier texto proveniente de Azure DevOps
(titulos de Epic, comentarios, descripciones) llegue al LLM de analisis de
riesgo o a los logs.

Dos responsabilidades, igual que el "security_screen" node del codelab
"Vibecode an ADK 2.0 Ambient Agent":

1. `redact_pii(text)`  -> enmascara PII/secretos (emails, PATs de ADO,
   numeros de tarjeta) antes de que el texto se use en un prompt o se loguee.
2. `detect_prompt_injection(text)` -> heuristica para detectar intentos de
   manipular al agente desde dentro de un campo de texto de ADO (por
   ejemplo, un titulo de Epic o un comentario) para que ignore las reglas de
   negocio (umbrales de riesgo) o se salte la revision humana.

Ambas funciones son deterministicas y se prueban con pytest en
`tests/test_security.py` sin necesidad de llamar a ningun LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Patrones de PII / secretos -------------------------------------------------

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
ADO_PAT_PATTERN = re.compile(r"\b[A-Za-z0-9]{52}\b")
CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
PHONE_PATTERN = re.compile(r"\b\+?\d{1,3}[ -]?\(?\d{2,4}\)?[ -]?\d{3,4}[ -]?\d{3,4}\b")


def redact_pii(text: str) -> str:
    """Enmascara emails, PATs de ADO, numeros de tarjeta y telefonos.

    Se aplica siempre antes de pasar texto libre proveniente de ADO (titulo,
    descripcion, comentarios de un work item) al LLM de analisis de riesgo,
    y antes de escribir ese texto en cualquier log.
    """
    if not text:
        return text
    redacted = ADO_PAT_PATTERN.sub("[REDACTED_TOKEN]", text)
    redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)
    redacted = CREDIT_CARD_PATTERN.sub("[REDACTED_CARD]", redacted)
    redacted = PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
    return redacted


# --- Deteccion de prompt injection ----------------------------------------------

# Frases que intentan forzar al agente a saltarse las reglas de negocio
# (umbral de riesgo, revision humana) directamente desde un campo de texto
# de Azure DevOps. Se revisa en minusculas y sin acentos para tolerar
# variaciones simples.
INJECTION_PATTERNS = [
    r"ignore (all|every|previous) (rules?|instructions?)",
    r"bypass (the )?(review|approval|threshold|rules?)",
    r"mark (this|it) as (on.?track|green|approved|low.?risk)",
    r"do not (escalate|flag|notify|report) (this|it)",
    r"disregard (the )?(budget|schedule|risk) (rules?|threshold)",
    r"auto.?approve",
    r"you are now (in )?(admin|developer) mode",
    r"system prompt",
]

_INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


@dataclass
class InjectionCheckResult:
    is_suspicious: bool
    matched_patterns: list[str]


def detect_prompt_injection(text: str) -> InjectionCheckResult:
    """Revisa un texto libre de ADO en busca de intentos de manipular al
    agente para que se salte las reglas de negocio o la revision humana.

    No usa un LLM: es una heuristica de regex determinista y rapida, pensada
    para actuar como el "pre-LLM security screen" del workflow -- si detecta
    algo sospechoso, el nodo de seguridad debe enrutar directo a revision
    humana y NUNCA dejar que ese texto llegue al LLM de analisis de riesgo.
    """
    if not text:
        return InjectionCheckResult(is_suspicious=False, matched_patterns=[])

    matches = [m.group(0) for m in _INJECTION_REGEX.finditer(text)]
    return InjectionCheckResult(is_suspicious=bool(matches), matched_patterns=matches)


def security_screen(epic: dict) -> dict:
    """Aplica el screening completo a un Epic obtenido del MCP de ADO.

    Devuelve un dict enriquecido con:
      - `title_clean`: titulo con PII redactada, listo para el LLM.
      - `security_flag`: True si se detecto un intento de prompt injection.
      - `security_reasons`: lista de patrones detectados (para el log de
        auditoria / para mostrarle al humano en la revision).

    Este es el equivalente, para este proyecto, al nodo `security_screen`
    del codelab "Vibecode an ADK 2.0 Ambient Agent" (Dia 4).
    """
    raw_title = epic.get("title", "") or ""
    injection = detect_prompt_injection(raw_title)

    return {
        **epic,
        "title_clean": redact_pii(raw_title),
        "security_flag": injection.is_suspicious,
        "security_reasons": injection.matched_patterns,
    }
