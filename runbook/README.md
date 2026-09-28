# Runbook: schema e validazione

- `runbook.schema.json`: JSON Schema (draft 2020-12) di un runbook `thumbops.mobiletechnologies.cloud/v1`
- `validate.py`: schema + controlli semantici (min <= max, cooldown >= 1m, nomi unici)
- `examples/`: runbook validi, non validi e un caso di nome duplicato
- `schema.md`: descrizione completa del formato

## Uso

    pip install -r requirements.txt   # jsonschema >= 4.18
    python3 validate.py path/ai/runbook/

Esce con codice 1 se almeno un runbook non è valido.

## Esempio in GitHub Actions

    - run: pip install -r runbook/requirements.txt
    - run: python3 runbook/validate.py runbooks/
