# ThumbOps spec

**Public** repository `thumbops/spec`: the ThumbOps contracts. It is the single
source of truth for the agent–backend protocol and the runbook format; agent
and backend follow them, customers use the validator in their CI.

ThumbOps lets you run only pre-approved actions on Kubernetes clusters from
your phone. The full project context is in the private repository
`../platform` (`CLAUDE.md` and `docs/progetto.md`), if present on disk.

## Layout

```
protocol/protocol.md        agent–backend protocol v1, in prose
protocol/openapi.yaml       to be written: the same specification in OpenAPI 3.1
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
```

## Rules

- **Versioned contracts.** The repository is released with semver tags. An
  incompatible change to the protocol requires `/v2`; to the runbook schema,
  `apiVersion: .../v2` and a new `$id`. The backend accepts both versions
  during the transition.
- **Consumers to update.** If you change a contract, list in the change what
  must be updated: the Go types in `../agent/internal/protocol/types.go`, the
  mock backend `../agent/internal/mockbackend`, the generated types in `../platform`.
- `additionalProperties: false` everywhere in the schema: a runbook must not be
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

1. Write `protocol/openapi.yaml` from `protocol/protocol.md`, with valid
   examples; check that the current agent conforms.
2. Automated tests (pytest) on the runbook examples.
3. Reusable GitHub Action to validate runbooks in customers' CI.
4. Rewrite the technical `jsonschema` messages into readable ones.
5. Add the `LICENSE` file (Apache 2.0).
