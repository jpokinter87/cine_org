"""
Package CLI pour la reparation interactive des symlinks casses.

Reexporte les classes principales pour preserver la compatibilite
des imports existants (from src.adapters.cli.repair_helpers import ...).
"""

from .auto_repair import AutoRepair
from .custom_search import CandidateDisplay, CustomSearch, RepairSummary
from .helpers import display_broken_link_info, extract_series_name
from .interactive_repair import InteractiveRepair
from .title_resolver import TitleResolver

__all__ = [
    "AutoRepair",
    "CandidateDisplay",
    "CustomSearch",
    "InteractiveRepair",
    "RepairSummary",
    "TitleResolver",
    "display_broken_link_info",
    "extract_series_name",
]
