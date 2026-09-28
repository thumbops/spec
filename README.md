# ThumbOps spec

Public contracts of [ThumbOps](https://github.com/thumbops): the protocol
between the in-cluster agent and the backend, and the runbook format.

| Path | Content |
| --- | --- |
| [`protocol/protocol.md`](protocol/protocol.md) | Agent–backend protocol v1 |
| [`protocol/openapi.yaml`](protocol/openapi.yaml) | The same protocol as an OpenAPI 3.1 contract |
| [`protocol/validate.py`](protocol/validate.py) | Checks the contract, its examples and recorded traffic |
| [`runbook/schema.md`](runbook/schema.md) | Runbook format and rules |
| [`runbook/runbook.schema.json`](runbook/runbook.schema.json) | Runbook JSON Schema |
| [`runbook/validate.py`](runbook/validate.py) | Validator for CI |

## Validating your runbooks

```
pip install -r runbook/requirements.txt
python3 runbook/validate.py path/to/runbooks/
```

It exits with code 1 if at least one runbook is invalid, so it can be used
directly in a pipeline.
