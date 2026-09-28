# ThumbOps spec

**Public** repository `thumbops/spec`: the ThumbOps contracts. It is the single
source of truth for the agent–backend protocol and the runbook format; agent
and backend follow them, customers use the validator in their CI.

ThumbOps lets you run only pre-approved actions on Kubernetes clusters from
your phone. The full project context is in the private repository
`../platform` (`CLAUDE.md` and `docs/project.md`), if present on disk.

## Layout

```
protocol/protocol.md        agent–backend protocol v1, in prose
protocol/openapi.yaml       the same protocol as a machine-readable contract (OpenAPI 3.1)
protocol/validate.py        checks the contract, its examples and recorded traffic
runbook/schema.md           runbook format and rules
runbook/runbook.schema.json JSON Schema (draft 2020-12)
runbook/validate.py         validation: schema + semantic checks
runbook/examples/           valid, invalid and duplicate-name runbooks
```

## Commands

```
pip install -r runbook/requirements.txt   # needs jsonschema >= 4.18 (draft 2020-12)
python3 runbook/validate.py runbook/examples/valid       # must exit with 0
python3 runbook/validate.py runbook/examples/invalid     # must exit with 1, one error per file
python3 runbook/validate.py runbook/examples/duplicate   # must report the duplicate name

pip install -r protocol/requirements.txt
python3 protocol/validate.py                             # contract and examples, must exit with 0
python3 protocol/validate.py --traffic exchanges.jsonl   # also recorded agent–backend traffic
```

## Rules

- **Versioned contracts.** The repository is released with semver tags. An
  incompatible change to the protocol requires `/v2`; to the runbook schema,
  `apiVersion: .../v2` and a new `$id`. The backend accepts both versions
  during the transition.
- **Consumers to update.** If you change a contract, list in the change what
  must be updated: the Go types in `../agent/internal/protocol/types.go`, the
  mock backend `../agent/internal/mockbackend`, the generated types in `../platform`.
- `protocol.md` and `openapi.yaml` describe the same protocol: change them
  together. Protocol schemas do not forbid unknown fields (receivers ignore
  them, so adding an optional field stays compatible); the `--traffic` check
  still reports fields the contract does not declare.
- `additionalProperties: false` everywhere in the runbook schema: a runbook must not be
  able to contain unexpected fields, for example arbitrary commands.
- The action schema is chosen with `if`/`then` on `type`, not with `oneOf`,
  so errors point to the wrong field.
- The rules the schema does not express well (min ≤ max, minimum cooldown,
  unique names) live in `validate.py`; the backend must replicate them.
- Every new rule has an example in `runbook/examples/invalid/`.
- Public repository: no internal material (business model, plans, brand),
  which belongs in `../platform`.

## Conventions

English for everything written into the repository: documentation, messages,
commit messages and PR descriptions. Protocol JSON in `snake_case`, runbook
YAML in `camelCase`, `thumbops.mobiletechnologies.cloud/` prefix for
annotations and labels.

## Next steps

Done: `protocol/openapi.yaml`, checked against 87 exchanges recorded between
the current agent and its mock backend (registration, renewal, heartbeat,
polling with `200`/`204`/`426`, claims including a `409`, results including a
`503` retry): all conform.

1. Automated tests (pytest) on the runbook examples and on `protocol/validate.py`.
2. CI (GitHub Actions) running both validators; in the agent's CI, record
   traffic against the mock backend and check it with `--traffic`.
3. Reusable GitHub Action to validate runbooks in customers' CI.
4. Rewrite the technical `jsonschema` messages into readable ones.
5. Add the `LICENSE` file (Apache 2.0).
