import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_risk_level

def test_on_track():
    assert get_risk_level(0.0) == "on_track"
    assert get_risk_level(94.9) == "on_track"

def test_at_risk():
    assert get_risk_level(95.0) == "at_risk"
    assert get_risk_level(97.0) == "at_risk"
    assert get_risk_level(100.0) == "at_risk"

def test_critical():
    assert get_risk_level(100.1) == "critical"
    assert get_risk_level(150.0) == "critical"
