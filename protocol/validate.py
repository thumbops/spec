#!/usr/bin/env python3
"""Check the agent–backend OpenAPI contract, and optionally real traffic against it.

Usage:
    python3 validate.py                      # the spec and all its examples
    python3 validate.py --traffic log.jsonl  # also recorded agent–backend exchanges

Each line of a traffic file is one exchange:
    {"method": "PUT", "path": "/v1/agent/heartbeat", "status": 200,
     "user_agent": "thumbops-agent/0.1.0", "request": {...}, "response": {...}}
`request` and `response` are the decoded JSON bodies, or null when empty or
not JSON. Fields not declared in the contract are reported as errors, so
drift between agent, backend and spec shows up.

Exits with code 1 if anything is invalid (useful in CI).
Dependencies: pip install -r requirements.txt
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from openapi_spec_validator import validate as validate_openapi
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012
except ImportError:
    sys.exit("missing dependencies: pip install -r requirements.txt")

SPEC_PATH = Path(__file__).with_name("openapi.yaml")
BASE = "urn:thumbops:openapi"
METHODS = ("get", "put", "post", "delete", "patch")


class Contract:
    def __init__(self, doc):
        self.doc = doc
        self.registry = Registry().with_resource(BASE, DRAFT202012.create_resource(doc))

    def resolve(self, node):
        """Follow local $refs ('#/...') to the referenced object."""
        while isinstance(node, dict) and "$ref" in node and node["$ref"].startswith("#/"):
            target = self.doc
            for part in node["$ref"][2:].split("/"):
                target = target[part]
            node = target
        return node

    def errors(self, schema, value, where):
        """Schema errors for value, with $refs resolved against the whole document."""
        wrapper = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": BASE + "#" + pointer_of(self.doc, schema)}
        validator = Draft202012Validator(wrapper, registry=self.registry, format_checker=FormatChecker())
        out = []
        for err in sorted(validator.iter_errors(value), key=lambda e: list(e.absolute_path)):
            loc = ".".join(str(p) for p in err.absolute_path) or "(root)"
            out.append(f"{where}: {loc}: {err.message}")
        return out

    def undeclared(self, schema, value, where):
        """Fields present in value but not declared anywhere in schema."""
        schema = self.resolve(schema)
        out = []
        if isinstance(value, dict) and isinstance(schema, dict):
            if "additionalProperties" in schema or "propertyNames" in schema:
                return out
            props = dict(schema.get("properties", {}))
            for sub in schema.get("allOf", []):
                props.update(self.resolve(sub).get("properties", {}))
            if not props:
                return out  # free-form object, e.g. Result.details
            for key, val in value.items():
                if key not in props:
                    out.append(f"{where}: undeclared field {key!r}")
                else:
                    out.extend(self.undeclared(props[key], val, f"{where}.{key}"))
        elif isinstance(value, list) and isinstance(schema, dict) and "items" in schema:
            for i, item in enumerate(value):
                out.extend(self.undeclared(schema["items"], item, f"{where}[{i}]"))
        return out

    def operations(self):
        for path, item in self.doc["paths"].items():
            for method in METHODS:
                if method in item:
                    yield path, method, item[method]

    def match(self, method, path):
        for template, meth, op in self.operations():
            regex = "^" + re.sub(r"\{[^/]+\}", "[^/]+", template) + "$"
            if meth == method.lower() and re.match(regex, path):
                return template, op
        return None, None


_POINTERS = {}


def pointer_of(doc, node):
    """JSON pointer of node inside doc (nodes are found by identity)."""
    if not _POINTERS:
        def walk(obj, ptr):
            _POINTERS[id(obj)] = ptr
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, f"{ptr}/{str(k).replace('~', '~0').replace('/', '~1')}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    walk(v, f"{ptr}/{i}")
        walk(doc, "")
    return _POINTERS[id(node)]


def check_examples(c):
    errors = []
    for path, method, op in c.operations():
        name = f"{method.upper()} {path}"
        params = [c.resolve(p) for p in op.get("parameters", [])]
        for p in params:
            if "example" in p:
                errors += c.errors(p["schema"], p["example"], f"{name} parameter {p['name']} example")
        body = op.get("requestBody", {}).get("content", {}).get("application/json")
        if body and "example" in body:
            errors += c.errors(body["schema"], body["example"], f"{name} request example")
        for status, resp in op["responses"].items():
            media = c.resolve(resp).get("content", {}).get("application/json")
            if media and "example" in media:
                errors += c.errors(media["schema"], media["example"], f"{name} {status} example")
    return errors


def response_for(op, status):
    responses = op["responses"]
    return responses.get(str(status)) or responses.get(f"{str(status)[0]}XX")


def check_traffic(c, path):
    errors = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        ex = json.loads(line)
        name = f"{path}:{n} {ex['method']} {ex['path']} -> {ex['status']}"
        template, op = c.match(ex["method"], ex["path"].split("?")[0])
        if op is None:
            errors.append(f"{name}: no such operation in the contract")
            continue
        for p in (c.resolve(p) for p in op.get("parameters", [])):
            if p["in"] == "header" and p["name"] == "User-Agent":
                errors += c.errors(p["schema"], ex.get("user_agent", ""), f"{name} User-Agent")
        body = op.get("requestBody", {}).get("content", {}).get("application/json")
        if body:
            if ex.get("request") is None:
                errors.append(f"{name}: request body missing")
            else:
                errors += c.errors(body["schema"], ex["request"], f"{name} request")
                errors += c.undeclared(body["schema"], ex["request"], f"{name} request")
        resp = response_for(op, ex["status"])
        if resp is None:
            errors.append(f"{name}: status {ex['status']} not documented for {template}")
            continue
        media = c.resolve(resp).get("content", {}).get("application/json")
        if media:
            errors += c.errors(media["schema"], ex.get("response"), f"{name} response")
            errors += c.undeclared(media["schema"], ex.get("response"), f"{name} response")
        elif ex.get("response") is not None and "content" not in c.resolve(resp):
            errors.append(f"{name}: body not allowed for status {ex['status']}")
    return errors


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--traffic", action="append", default=[], help="JSON Lines file of recorded exchanges")
    args = parser.parse_args(argv)

    doc = yaml.safe_load(SPEC_PATH.read_text())
    try:
        validate_openapi(doc)
    except Exception as exc:  # the validator raises several exception types
        print(f"ERROR  {SPEC_PATH.name}: not a valid OpenAPI 3.1 document: {exc}")
        return 1
    contract = Contract(doc)

    errors = check_examples(contract)
    for traffic in args.traffic:
        errors += check_traffic(contract, traffic)

    for e in errors:
        print(f"ERROR  {e}")
    print(f"\n{len(errors)} error(s)" if errors else "\nContract and examples are valid" + (", traffic conforms" if args.traffic else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
