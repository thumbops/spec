# Agent–backend protocol

Sep 25, 2026 · @Simone Bernardello

This document explains the protocol in prose. The machine-readable contract is [`openapi.yaml`](openapi.yaml) (OpenAPI 3.1): the two must stay in sync, and `python3 protocol/validate.py` checks the contract, its examples and, with `--traffic`, recorded agent–backend exchanges.

## Principles

The agent always opens the connections, over HTTPS to the backend: the cluster exposes nothing and no inbound ports need to be opened.

- **Authentication**: a bootstrap token only for registration, then mTLS with one certificate per cluster. The certificate CN is the `cluster_id`, so calls do not repeat it in the path.
- **Format**: JSON, timestamps in RFC 3339 UTC, IDs as UUIDs.
- **Versioning**: `/v1` prefix in the path. The agent sends its own version on every call (`User-Agent: thumbops-agent/1.2.0`) and the backend states the minimum supported version.
- **Base URL**: `https://agent.thumbops.mobiletechnologies.cloud/v1`.

The reverse proxy (Caddy or Traefik) verifies the client certificate and passes the CN to the service in an internal header. The service accepts that header only from the proxy, never directly from outside.

| Endpoint | Method | Authentication | Frequency |
| --- | --- | --- | --- |
| `/v1/register` | POST | Bootstrap token | Once |
| `/v1/agent/certificate` | POST | mTLS | Before the certificate expires |
| `/v1/agent/heartbeat` | PUT | mTLS | Every 60 s |
| `/v1/agent/actions` | GET | mTLS | Continuous, long polling |
| `/v1/agent/actions/{id}/claim` | POST | mTLS | For every action received |
| `/v1/agent/actions/{id}/result` | POST | mTLS | When execution ends |
| `/v1/agent/status` | PUT | mTLS | Every 60 s and on request |

## Registration and certificate

The agent generates its own private key, which never leaves the cluster: the backend only signs a CSR.

1. A cluster is created in the backend from the app or the CLI, which returns a single-use bootstrap token valid for 1 hour.
2. The token is put in a Secret and the agent is installed (Helm chart).
3. At startup the agent generates an Ed25519 key and calls `POST /v1/register`; once registered it saves key and certificate together in a Secret.
4. The backend invalidates the token and returns the signed certificate.

Request (`Authorization: Bearer <bootstrap token>`):

```json
{
  "csr": "-----BEGIN CERTIFICATE REQUEST-----...",
  "agent_version": "0.1.0",
  "kubernetes_version": "v1.34.3",
  "cluster_uid": "<uid of the kube-system namespace>"
}
```

Response:

```json
{
  "cluster_id": "8c1f0e7a-...",
  "certificate": "-----BEGIN CERTIFICATE-----...",
  "ca_chain": "-----BEGIN CERTIFICATE-----...",
  "expires_at": "2026-10-25T10:00:00Z"
}
```

The `cluster_uid` lets the backend recognize the same cluster if the agent is reinstalled. The certificate lasts 30 days; when less than a third is left, the agent sends a new CSR to `POST /v1/agent/certificate`, authenticating with the still valid one. Revoking a cluster in the backend makes the certificate unusable on the next call.

**New registration.** The agent keeps, next to key and certificate, the SHA-256 of the bootstrap token it registered with (never the token itself). At startup it registers again, with a new key, when the mounted token differs from that one: after a `401` (cluster revoked, certificate expired) the fix is a new token from the app and a restart of the agent. The previous identity is replaced only after the new registration succeeds, and the same token never triggers a second registration. The backend recognizes the cluster from the `cluster_uid`.

Renewal happens only while the certificate is still valid. If the agent cannot reach the backend for the whole last third of the validity (agent stopped, network or backend down for more than 10 days), the certificate expires and can no longer be renewed: a new registration is needed. A certificate that is expired, revoked or signed by a CA the backend does not know is rejected by the reverse proxy already during the TLS handshake, so the agent receives a TLS alert rather than a `401`: it treats it as a `401` (see "Errors and retries").

## Heartbeat

Every 60 seconds the agent calls `PUT /v1/agent/heartbeat`; after 3 minutes without a heartbeat the backend marks the cluster as offline and shows it in the app.

Request:

```json
{
  "agent_version": "0.1.0",
  "kubernetes_version": "v1.34.3",
  "nodes": { "ready": 6, "total": 6 },
  "permissions": {
    "rollout-restart": true,
    "scale": true,
    "cordon": false,
    "uncordon": false,
    "drain": false
  },
  "last_action_id": "3b2d..."
}
```

The `permissions` block has one entry per action type and is the result of a `SelfSubjectAccessReview` made by the agent: the app can thus disable in advance the actions that would fail for lack of RBAC.

The backend never answers `426` to a heartbeat: an agent that is no longer supported keeps sending heartbeats (see "Errors and retries").

Response:

```json
{
  "server_time": "2026-09-25T10:00:00Z",
  "poll": { "interval_seconds": 0, "wait_seconds": 20 },
  "min_agent_version": "0.1.0"
}
```

With `poll` the backend tunes polling without having to upgrade the agent. `server_time` lets the agent correct skewed clocks when it checks action deadlines.

## Receiving actions

The agent uses long polling: the request stays open for up to 20 seconds, and an approved action usually arrives in under a second.

As soon as it receives a response, the agent reopens the request immediately. Reverse proxy and service must have timeouts longer than the wait, for example 30 seconds. Through the heartbeat's `poll` block the backend can reduce `wait_seconds` or switch to plain polling, for example if part of the service ended up on a platform that charges for waiting time.

Call: `GET /v1/agent/actions?wait=20`. Response `204` if nothing is there when the wait ends, otherwise `200`:

```json
{
  "actions": [
    {
      "action_id": "3b2d...",
      "type": "scale",
      "params": {
        "namespace": "payments",
        "deployment": "payments-api",
        "replicas": 6
      },
      "runbook": "payments/scale-api@4f2a91c",
      "requested_by": "u_123",
      "approved_by": ["u_456"],
      "expires_at": "2026-09-25T10:02:00Z"
    }
  ]
}
```

In the MVP the list contains at most one action. `runbook` names the file and Git commit the action comes from, for auditing. `expires_at` is set to 2 minutes after approval: an action left in the queue while the agent was offline is no longer run.

Parameters per action type, already resolved by the backend from the runbook and the user's choices:

| Action | Parameters |
| --- | --- |
| `rollout-restart` | `namespace`, `deployment` |
| `scale` | `namespace`, `deployment`, `replicas` (already checked to be between the runbook's `min` and `max`) |
| `cordon`, `uncordon` | `node` |
| `drain` | `node`, `timeout_seconds` (default 600), `delete_emptydir_data` (default false). The agent never evicts its own pod: it is skipped like DaemonSet pods and reported in the result (`details.agent_pod_left`); the node is cordoned, so the agent moves at its next restart. |

In the runbook the drain fields are called `timeoutSeconds` and `deleteEmptyDirData`, as in Kubernetes resources; in the protocol they follow the snake\_case convention of the other messages.

## Execution and results

Before running, the agent claims the action with `POST /v1/agent/actions/{id}/claim`; only a successful claim authorizes execution.

The claim responds `200` (empty body) if the action is still valid, `404` if the action is unknown, `409` if it has already been claimed, `410` if it has expired or been canceled; in every case other than `200` the agent discards the action. When done, the agent sends `POST /v1/agent/actions/{id}/result`:

```json
{
  "status": "succeeded",
  "started_at": "2026-09-25T10:00:12Z",
  "finished_at": "2026-09-25T10:00:14Z",
  "message": "payments/payments-api scaled from 3 to 6 replicas",
  "details": { "previous_replicas": 3, "replicas": 6 }
}
```

`status` is `succeeded`, `failed` (Kubernetes API error) or `rejected` (the agent refused the action, see the next section). For a restart, the result arrives when the rollout has started, not when it has completed; rollout status is a possible later improvement.

**Progress.** A long action (today only `drain`) reports its progress while it runs with `POST /v1/agent/actions/{id}/progress`:

```json
{
  "updated_at": "2026-09-30T10:03:12Z",
  "message": "draining worker-3: 14 pods evicted, 2 remaining",
  "details": {
    "evicted": 14,
    "remaining": 2,
    "blocked": [{ "pod": "payments/api-7f9c", "reason": "PodDisruptionBudget" }]
  }
}
```

`details` depends on the action type; for `drain`, `blocked` lists at most 20 pods the agent cannot evict yet. The agent sends the first progress right after the cordon, then whenever the counts change (at most once every 5 seconds) and at least every 30 seconds. Progress is never retried: the next one is newer. The only exception is the first progress of a resumed drain (see **Resume**).

The backend answers `200` (empty body), stores the progress for the dashboard and renews the action's lease (see the states below). `409` or `410` mean the backend no longer tracks the action (expired or cancelled): the agent stops it, with no further evictions, leaves the node cordoned and sends no result. `404` means the backend does not support progress: the agent stops sending it for that action and goes on (except for a resumed drain, see **Resume**).

**Resume.** When the drain starts, the agent writes the annotation `thumbops.mobiletechnologies.cloud/drain-in-progress` on the node, in the same patch as the cordon, with the `action_id`, the start time and the parameters. If the agent restarts, it finds the annotation and resumes the drain with the time left, without a new claim: it sends progress and the result for the same `action_id`, which the backend accepts while the action is `claimed`. A resumed drain is first checked against the current local policy: if the policy rejects it, the agent sends a `rejected` result and removes the annotation, leaving the node as it is. Then the resumed drain changes nothing until its first progress is accepted (`200`): the agent sends it before re-asserting the cordon, and tries it up to three times on a network error or a `5xx`. `404`, `409` or `410` to it, or repeated failures, make the agent abandon the drain: it removes the annotation, leaves the node as it is and sends no result. The annotation is removed in the patch that writes the result, when the backend answers `409`/`410` to a progress, and when the user uncordons the node through an `uncordon` action. On `401` (or a rejected certificate) the agent stops, keeps the annotation and sends no result: the drain is resumed after a new registration.

| State | Set by | Meaning |
| --- | --- | --- |
| `requested` | Backend | Requested from the app, waiting for approval if needed |
| `approved` | Backend | Ready, visible to the agent until `expires_at` |
| `claimed` | Agent (claim) | Running |
| `succeeded` / `failed` / `rejected` | Agent (result) | Finished |
| `expired` | Backend | Not claimed before the deadline, or claimed and then 5 minutes without a result or a progress (each progress renews the lease) |
| `cancelled` | Backend | Canceled by the user before the claim, or while it runs (the next progress gets `410`) |

Every state change produces an audit log entry and a notification to the user who requested the action.

## Errors, idempotency and defense in depth

The agent does not blindly trust the backend: it runs only actions that its own local policy also allows, so a compromised backend cannot do anything outside those limits.

**Local policy.** A ConfigMap managed by the cluster team lists the allowed action types, namespaces and limits (for example `scale` up to 20 replicas at most). An action outside the policy is rejected with `status: rejected`. On top of that, the agent's ServiceAccount has RBAC limited to the verbs it needs.

**Idempotency.** Every action is identified by `action_id`. The agent annotates the modified resource with `thumbops.mobiletechnologies.cloud/last-action-id`: if it finds that ID already there, it does not repeat the action and sends the result again. This covers the case where the agent restarts between execution and sending the result.

In the prototype the annotation with the ID and a second annotation with the result (`thumbops.mobiletechnologies.cloud/last-action-result`) are written in the same patch that applies the change, so a change can never exist without the trace that makes it idempotent. The drain is the exception: it is made of several steps. It marks the node with the `drain-in-progress` annotation in the cordon patch and writes the result annotations, removing the in-progress one, only at the end; repeating it on an already drained node has no effect.

**Errors and retries.**

| Code | Meaning | Agent behavior |
| --- | --- | --- |
| `401`, or a TLS alert rejecting the certificate | Certificate invalid or expired, or cluster revoked | Stops and logs it with the cause; a new registration is needed (new bootstrap token, see "New registration") |
| `409` / `410` | Action already claimed or expired | Discards it; for a progress, stops the action (see Progress) |
| `426` (polling only) | Agent version no longer supported | Continues with the heartbeat only and reports that an upgrade is needed |
| `429` / `5xx` | Rate limit or backend error | Retries with exponential backoff and jitter, up to 60 s (except progress, which is never retried) |

Sending the `result` is retried until it succeeds, keeping the result in memory and in the resource annotation. The backend answers `200` with an empty body; `400`, `409` and `410` stop the retries.

Error responses carry a short human-readable text body, which the agent logs but never parses. Receivers ignore unknown JSON fields, so adding an optional field is a compatible change.

The TLS alerts equivalent to a `401` are the ones a server uses to reject the client certificate (RFC 8446, §6.2): `bad_certificate`, `unsupported_certificate`, `certificate_revoked`, `certificate_expired`, `certificate_unknown`, `unknown_ca`, `certificate_required`. Other network and TLS errors, including a server certificate the agent does not recognize, are temporary and are retried with backoff.

**Certificate change.** The client certificate is presented only at the TLS handshake, and with long polling the connection to the backend is never idle. After registration and after every renewal the agent must therefore open new connections, otherwise it keeps presenting no certificate or the old one. The prototype does this, and a test covers it.

## Cluster status

Every 60 seconds the agent sends a compact status summary with `PUT /v1/agent/status`; the backend answers `204` and keeps the latest summary of each cluster for the dashboard.

The agent collects the data with client-go informers (watch), without querying the API server on every cycle. If metrics-server is in the cluster, it adds real CPU and memory usage; otherwise the `used` fields are `null`.

```json
{
  "collected_at": "2026-09-28T10:00:00Z",
  "resources": {
    "cpu": { "allocatable_m": 23520, "requested_m": 15800, "used_m": null },
    "memory": { "allocatable_mib": 92160, "requested_mib": 61440, "used_mib": null }
  },
  "nodes": {
    "total": 6, "ready": 5, "cordoned": 1,
    "items": [
      {
        "name": "ip-10-0-1-12",
        "ready": false,
        "unschedulable": false,
        "conditions": ["MemoryPressure"],
        "cpu": { "allocatable_m": 3920, "requested_m": 3100 },
        "memory": { "allocatable_mib": 15360, "requested_mib": 12288 }
      }
    ]
  },
  "workloads": {
    "unhealthy_pods": [
      { "namespace": "payments", "name": "payments-api-7d9f-x2k", "reason": "CrashLoopBackOff", "restarts": 14 }
    ],
    "degraded_deployments": [
      { "namespace": "payments", "name": "payments-api", "ready": 1, "desired": 3 }
    ]
  },
  "truncated": false
}
```

**Size limits.** The node list is complete up to 100 nodes; beyond that, the agent sends only the nodes with problems plus the aggregates. Pods and deployments with problems are limited to the first 20 each, sorted by severity. When something is cut, `truncated` is `true` and the app shows it.

**On-demand refresh.** When the user asks for a refresh from the app, the response of `GET /v1/agent/actions` includes `"status_requested": true`. The agent sends a new summary right away; with long polling the data arrives within a couple of seconds.

**Excluded namespaces.** The agent's local policy can list namespaces to exclude (`status.exclude_namespaces`): their pods and deployments are never sent to the backend.

**Permissions.** For the status the agent uses a read-only ClusterRole (`get`, `list`, `watch`) on nodes, pods, events and deployments, plus `get` on the `metrics.k8s.io` metrics. It is separate from the role used for actions, so the agent can also be installed for the dashboard only.

## Open questions

- Merge heartbeat and polling into a single call to halve the requests, or keep them separate for simplicity?
- Where does the CA that signs agent certificates live: AWS Private CA (fixed monthly cost) or a self-managed CA with the key in KMS?
