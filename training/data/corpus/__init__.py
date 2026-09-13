"""Authored SFT corpora, one module per persona family.

Kept out of `build_datasets.py` so the generator stays readable: the data is long, the
assembly logic is five lines.
"""

from .bard import BARD
from .bard import SYSTEM as BARD_SYSTEM
from .software import PAIRS
from .software import REVIEWER_EXTRA
from .software import TUTOR_EXTRA

__all__ = ["BARD", "BARD_SYSTEM", "PAIRS", "REVIEWER_EXTRA", "TUTOR_EXTRA"]
