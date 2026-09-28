#!/usr/bin/env python3
"""Validate ThumbOps runbooks: JSON Schema plus semantic checks.

Usage:
    python3 validate.py runbooks/            # every .yaml/.yml in the directory
    python3 validate.py a.yaml b.yaml        # single files

Exits with code 1 if at least one runbook is invalid (useful in CI).
Dependencies: pip install -r requirements.txt (jsonschema >= 4.18, pyyaml)
"""
import json
import re
import sys
from pathlib import Path

import yaml

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit("jsonschema >= 4.18 is required: pip install -r requirements.txt")

SCHEMA_PATH = Path(__file__).with_name("runbook.schema.json")
MIN_COOLDOWN_SECONDS = 60
UNITS = {"s": 1, "m": 60, "h": 3600}


def duration_seconds(value):
    match = re.fullmatch(r"(\d+)([smh])", value)
    return int(match.group(1)) * UNITS[match.group(2)]


def semantic_errors(doc):
    """Rules that JSON Schema does not express well."""
    errors = []
    spec = doc.get("spec", {})
    action = spec.get("action", {})

    if action.get("type") == "scale":
        params = action.get("params", {})
        if params.get("min", 0) > params.get("max", 0):
            errors.append("spec.action.params: min cannot be greater than max")

    cooldown = spec.get("cooldown")
    if cooldown and duration_seconds(cooldown) < MIN_COOLDOWN_SECONDS:
        errors.append(f"spec.cooldown: minimum {MIN_COOLDOWN_SECONDS // 60}m, found {cooldown}")

    return errors


def collect_files(args):
    files = []
    for arg in args:
        path = Path(arg)
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix in (".yaml", ".yml")))
        else:
            files.append(path)
    return files


def main(args):
    if not args:
        print(__doc__)
        return 2

    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
    names = {}
    failed = 0

    for path in collect_files(args):
        try:
            doc = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            print(f"ERROR  {path}: invalid YAML: {exc}")
            failed += 1
            continue

        errors = []
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
            location = ".".join(str(p) for p in err.absolute_path) or "(root)"
            errors.append(f"{location}: {err.message}")
        if not errors:
            errors.extend(semantic_errors(doc))
            name = doc["metadata"]["name"]
            if name in names:
                errors.append(f"metadata.name '{name}' already used in {names[name]}")
            else:
                names[name] = path

        if errors:
            failed += 1
            print(f"ERROR  {path}")
            for line in errors:
                print(f"  - {line}")
        else:
            print(f"OK     {path}")

    print(f"\n{failed} invalid runbook(s)" if failed else "\nAll runbooks are valid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
