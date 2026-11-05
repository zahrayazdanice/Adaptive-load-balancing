"""Discrete-event simulator for comparing load-balancing policies."""
from .engine import simulate
from .metrics import summarize
from .policies import LABELS, POLICIES
from .scenarios import Scenario, get_scenario, main_scenarios

__all__ = ["simulate", "summarize", "LABELS", "POLICIES", "Scenario", "get_scenario", "main_scenarios"]
__version__ = "1.0.0"
