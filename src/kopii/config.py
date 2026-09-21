"""Strict JSON configuration and lazy adapter construction."""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from kopii.detectors import CombinedDetector
from kopii.detectors.rules import DictionaryDetector, RuleDetector
from kopii.pipeline import Pipeline
from kopii.policies import Policy
from kopii.resolvers.csv import CsvResolver
from kopii.schemas import Detector

if TYPE_CHECKING:
    from kopii.context import ContextPipeline
    from kopii.embeddings import HttpEmbedder


def check_keys(config: dict[str, Any], allowed: set[str]) -> None:
    """Catch misspelled settings instead of silently reverting to defaults."""
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")


def load_config(path: Path) -> dict[str, Any]:
    """Load a JSON object; paths are relative to its containing directory."""
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object")
    return config


def create_detector(config: dict[str, Any]) -> Detector:
    """Construct a detector; no model is downloaded by importing the package."""
    kind = config.get("kind")
    if kind == "rules":
        check_keys(config, {"kind"})
        return RuleDetector()
    if kind == "dictionary":
        check_keys(config, {"kind", "names"})
        return DictionaryDetector(config["names"])
    if kind == "combined":
        check_keys(config, {"kind", "detectors"})
        return CombinedDetector([create_detector(item) for item in config["detectors"]])
    arguments = {key: value for key, value in config.items() if key != "kind"}
    if kind == "huggingface":
        from kopii.detectors.huggingface import HuggingFaceDetector

        return HuggingFaceDetector(**arguments)
    if kind == "gliner":
        from kopii.detectors.gliner import GlinerDetector

        return GlinerDetector(**arguments)
    raise ValueError("Unknown detector kind")


def create_pipeline(config: dict[str, Any], base: Path) -> Pipeline:
    """Resolve file references relative to config; keys are read from environment."""
    check_keys(config, {"detector", "policy", "resolver"})
    policy_config = dict(config.get("policy", {}))
    check_keys(policy_config, {"actions", "default_action", "key_env"})
    key_env = policy_config.pop("key_env", None)
    key: Optional[bytes] = None
    if key_env:
        value = os.environ.get(key_env)
        if not value:
            raise ValueError("Configured pseudonym key environment variable is missing")
        key = value.encode()
    policy = Policy(key=key, **policy_config)
    resolver = None
    if "resolver" in config:
        resolver_config = config["resolver"]
        check_keys(resolver_config, {"kind", "path", "level"})
        if resolver_config["kind"] != "csv":
            raise ValueError("Built-in resolver kind must be csv")
        resolver = CsvResolver(base / resolver_config["path"], resolver_config.get("level", "team"))
    return Pipeline(create_detector(config["detector"]), policy, resolver)


def create_context_pipeline(config: dict[str, Any], base: Path) -> "ContextPipeline":
    """Build configurable private fields; no organization column names are implicit."""
    from kopii.context import ContextField, ContextPipeline
    from kopii.resolvers.attributes import AttributeResolver

    check_keys(config, {"detector", "fields"})
    fields = {}
    for field, definition in config.get("fields", {}).items():
        check_keys(definition, {"entity_label", "resolver"})
        resolver = definition["resolver"]
        check_keys(resolver, {"kind", "path", "key", "value", "ambiguity_fields"})
        if resolver["kind"] != "csv_attributes":
            raise ValueError("Context configuration supports csv_attributes resolvers")
        fields[field] = ContextField(
            AttributeResolver.from_csv(
                base / resolver["path"],
                key=resolver["key"],
                value=resolver["value"],
                ambiguity_fields=resolver.get("ambiguity_fields", []),
            ),
            definition.get("entity_label", "PERSON_NAME"),
        )
    return ContextPipeline(create_detector(config["detector"]), fields)


def create_embedder(config: dict[str, Any]) -> "HttpEmbedder":
    """Read service settings explicitly, keeping endpoint and key values out of JSON."""
    from kopii.embeddings import HttpEmbedder

    check_keys(
        config,
        {
            "endpoint_env",
            "api_key_env",
            "model",
            "deployment_revision",
            "document_prefix",
            "query_prefix",
            "batch_size",
            "timeout_seconds",
        },
    )
    if not config.get("model") or config["model"].startswith("REPLACE_"):
        raise ValueError("Configure an actual deployed embedding model")
    return HttpEmbedder(
        os.environ[config["endpoint_env"]],
        config["model"],
        api_key=os.environ[config["api_key_env"]] if config.get("api_key_env") else None,
        document_prefix=config.get("document_prefix", ""),
        query_prefix=config.get("query_prefix", ""),
        batch_size=config.get("batch_size", 32),
        timeout=config.get("timeout_seconds", 60),
    )
