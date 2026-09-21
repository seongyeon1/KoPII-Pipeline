"""Public API for detection and policy-driven text processing."""

from kopii.context import ContextField, ContextPipeline, PreparedDocument
from kopii.pipeline import Pipeline
from kopii.policies import Policy
from kopii.retrieval import SearchDocument, SearchHit, SearchIndex
from kopii.schemas import Entity, ProcessingResult

__all__ = [
    "Entity",
    "Pipeline",
    "Policy",
    "ProcessingResult",
    "ContextField",
    "ContextPipeline",
    "PreparedDocument",
    "SearchDocument",
    "SearchHit",
    "SearchIndex",
]
__version__ = "0.2.0"
