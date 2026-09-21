"""Strict JSON configuration and lazy adapter construction."""

import json
import os
from pathlib import Path
from typing import Any, Optional

from kopii.detectors import CombinedDetector
from kopii.detectors.rules import DictionaryDetector, RuleDetector
from kopii.pipeline import Pipeline
from kopii.policies import Policy
from kopii.resolvers.csv import CsvResolver
from kopii.schemas import Detector


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
