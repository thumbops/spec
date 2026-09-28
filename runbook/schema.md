# Runbook schema

Sep 28, 2026 · @Simone Bernardello

## Structure of a runbook

A runbook authorizes a single action on a set of clusters and resources, with limits and approval rules fixed in advance; anything not declared is forbidden.

The format follows Kubernetes resources (`apiVersion`, `kind`, `metadata`, `spec`), so whoever writes it finds a familiar structure, and in the future it can become a CRD without changes.

```yaml
apiVersion: thumbops.mobiletechnologies.cloud/v1
kind: Runbook
metadata:
  name: payments-api-restart
  description: Restart payments-api when its pods crash
  owner: team-payments
spec:
  alerts:
    - match: { alertname: KubePodCrashLooping, namespace: payments }
  target:
    clusters:
      matchLabels: { env: prod }
    namespace: payments
    deployment: payments-api
  action:
    type: rollout-restart
  approval: two-person
  cooldown: 10m
```

A file contains a single runbook. A typical repository has one directory per team (`runbooks/payments/`, `runbooks/platform/`), and the `owner` field makes explicit who is responsible for it.

## Fields

`metadata.name`, `spec.target.clusters`, `spec.action` and `spec.approval` are required; any field not listed here makes the runbook invalid.

| Field | Required | Allowed values |
| --- | --- | --- |
| `metadata.name` | Yes | Lowercase DNS name, max 63 characters, unique in the repository |
| `metadata.description` | No | Text, max 200 characters; shown in the app |
| `metadata.owner` | No | Responsible team or person |
| `spec.alerts[].match` | No | Alert labels to match (e.g. `alertname`, `namespace`); max 20 rules. Without alerts, the runbook is available only from the dashboard |
| `spec.target.clusters.matchLabels` | Yes | Labels of the registered clusters (e.g. `env: prod`) |
| `spec.target.namespace` | For restart and scale | Namespace name |
| `spec.target.deployment` | For restart and scale | Deployment name |
| `spec.target.nodes.matchLabels` | For cordon, uncordon, drain | Labels of the nodes the action is allowed on |
| `spec.action.type` | Yes | `rollout-restart`, `scale`, `cordon`, `uncordon`, `drain` |
| `spec.action.params` | For scale; optional for drain | Scale: `min` and `max` replicas (0–1000). Drain: `timeoutSeconds` (30–3600, default 600), `deleteEmptyDirData` (default false) |
| `spec.approval` | Yes | `single` or `two-person` |
| `spec.cooldown` | No | Duration such as `30s`, `10m`, `1h`; minimum 1 minute |

For scale the user picks the number of replicas in the app, but only between `min` and `max`. For drain, `deleteEmptyDirData` is false by default because deleting `emptyDir` volumes can lose temporary data.

## Validation rules

Validation has two levels: a JSON Schema (draft 2020-12) for structure and values, and a few semantic checks in code for the rules the schema does not express well.

**In the schema:**

- No additional fields anywhere, so a runbook cannot contain unexpected commands or parameters.
- The action schema is chosen based on `type`, so the error names the wrong field instead of a generic "no schema matches".
- Consistency between action and target: restart and scale require `namespace` and `deployment` and forbid `nodes`; cordon, uncordon and drain require `nodes` and forbid `namespace` and `deployment`.
- Names and labels follow the Kubernetes rules (DNS names, label keys and values).

**Semantic checks:**

- In `scale`, `min` cannot exceed `max`.
- `cooldown` cannot be less than 1 minute.
- `metadata.name` must be unique across all the files validated together.

Cases used to test the schema, all rejected with the error shown:

| Case | Error returned |
| --- | --- |
| `command` field added to a rollout-restart | `spec.action`: additional field not allowed (`command`) |
| `delete-namespace` action | `spec.action.type`: value not among the allowed ones |
| Scale on `nodes` instead of a deployment | `spec.target`: `namespace` and `deployment` missing, `nodes` not allowed |
| Drain on a namespace | `spec.target`: `nodes` missing, `namespace` not allowed |
| Scale with `min: 8`, `max: 3` and cooldown `10s` | Min greater than max; cooldown below the minimum |
| Name `Payments_API` and approval `always` | Invalid name; approval not among the allowed ones |
| Two files with the same `metadata.name` | Name already used in the first file |

Three valid runbooks (restart with two-person approval, scale with limits, drain on staging nodes) pass without errors. The script exits with code 1 when at least one runbook is invalid, so it can simply be added to the pipeline.

## Where the checks happen

The same runbook is checked in three places, and each one blocks a different kind of error: none of the three trusts the previous one.

| Where | When | What it checks |
| --- | --- | --- |
| Repository CI | On every pull request | Schema and semantic checks; the merge is blocked if they fail |
| Backend | When syncing from the repository and on every request from the app | The schema again (an invalid runbook is discarded and reported); user-chosen parameters within the limits; the user's permissions on the cluster; cooldown |
| Agent | Before running | The cluster's local policy: action types, namespaces and limits allowed by the team that runs the cluster |

The backend uses the same `runbook.schema.json` file as the CI, so the rules cannot diverge. The schema has a versioned `$id` (`runbook-v1.json`): an incompatible change will require `apiVersion: .../v2`, and the backend will accept both versions during the transition.

## Open questions

- Are selectors more expressive than `matchLabels` needed (for example `matchExpressions` with `In` and `NotIn`)? For the MVP equality is enough.
- A runbook on several deployments (for example all those with a given label) instead of a single one: useful, but it widens the blast radius.
- Is there one runbook repository per organization or one per team? It changes how the backend handles duplicate names and edit permissions.
- Some schema messages are still technical (for example "should not be valid under"): the script could rewrite them into readable messages before showing them.
