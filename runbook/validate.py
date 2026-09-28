#!/usr/bin/env python3
"""Valida i runbook ThumbOps: JSON Schema piu' controlli semantici.

Uso:
    python3 validate.py runbooks/            # tutti i .yaml/.yml nella cartella
    python3 validate.py a.yaml b.yaml        # file singoli

Esce con codice 1 se almeno un runbook non e' valido (utile in CI).
Dipendenze: pip install -r requirements.txt (jsonschema >= 4.18, pyyaml)
"""
import json
import re
import sys
from pathlib import Path

import yaml

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit("serve jsonschema >= 4.18: pip install -r requirements.txt")

SCHEMA_PATH = Path(__file__).with_name("runbook.schema.json")
MIN_COOLDOWN_SECONDS = 60
UNITS = {"s": 1, "m": 60, "h": 3600}


def duration_seconds(value):
    match = re.fullmatch(r"(\d+)([smh])", value)
    return int(match.group(1)) * UNITS[match.group(2)]


def semantic_errors(doc):
    """Regole che JSON Schema non esprime bene."""
    errors = []
    spec = doc.get("spec", {})
    action = spec.get("action", {})

    if action.get("type") == "scale":
        params = action.get("params", {})
        if params.get("min", 0) > params.get("max", 0):
            errors.append("spec.action.params: min non puo' essere maggiore di max")

    cooldown = spec.get("cooldown")
    if cooldown and duration_seconds(cooldown) < MIN_COOLDOWN_SECONDS:
        errors.append(f"spec.cooldown: minimo {MIN_COOLDOWN_SECONDS // 60}m, trovato {cooldown}")

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
            print(f"ERRORE {path}: YAML non valido: {exc}")
            failed += 1
            continue

        errors = []
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
            location = ".".join(str(p) for p in err.absolute_path) or "(radice)"
            errors.append(f"{location}: {err.message}")
        if not errors:
            errors.extend(semantic_errors(doc))
            name = doc["metadata"]["name"]
            if name in names:
                errors.append(f"metadata.name '{name}' gia' usato in {names[name]}")
            else:
                names[name] = path

        if errors:
            failed += 1
            print(f"ERRORE {path}")
            for line in errors:
                print(f"  - {line}")
        else:
            print(f"OK     {path}")

    print(f"\n{failed} runbook non validi" if failed else "\nTutti i runbook sono validi")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
