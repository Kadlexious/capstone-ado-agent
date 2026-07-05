# app/config.py

# Umbrales de negocio (no cambiar sin aprobación humana explícita)
THRESHOLD_ON_TRACK = 95.0
THRESHOLD_AT_RISK = 100.0

def get_risk_level(consumption_pct: float) -> str:
    """Calcula el nivel de riesgo determinista basado en el porcentaje de consumo
    de horas de un Epic.
    """
    if consumption_pct < THRESHOLD_ON_TRACK:
        return "on_track"
    elif consumption_pct <= THRESHOLD_AT_RISK:
        return "at_risk"
    else:
        return "critical"
