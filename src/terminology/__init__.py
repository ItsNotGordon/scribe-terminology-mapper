"""Terminology clients that talk to official NLM APIs.

No module in this package invents medical codes. Every candidate comes
from an authoritative search response and is then format-checked.
"""

from src.terminology.icd10 import Icd10Client
from src.terminology.rxnorm import RxNormClient

__all__ = ["Icd10Client", "RxNormClient"]
