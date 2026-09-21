"""Public API for detection and policy-driven text processing."""

from kopii.pipeline import Pipeline
from kopii.policies import Policy
from kopii.schemas import Entity, ProcessingResult

__all__ = ["Entity", "Pipeline", "Policy", "ProcessingResult"]
__version__ = "0.1.0"
