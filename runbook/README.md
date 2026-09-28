# Runbooks: schema and validation

- `runbook.schema.json`: JSON Schema (draft 2020-12) of a `thumbops.mobiletechnologies.cloud/v1` runbook
- `validate.py`: schema + semantic checks (min <= max, cooldown >= 1m, unique names)
- `examples/`: valid and invalid runbooks and a duplicate-name case
- `schema.md`: full description of the format

## Usage

    pip install -r requirements.txt   # jsonschema >= 4.18
    python3 validate.py path/to/runbooks/

It exits with code 1 if at least one runbook is invalid.

## GitHub Actions example

    - run: pip install -r runbook/requirements.txt
    - run: python3 runbook/validate.py runbooks/
