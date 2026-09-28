# Protocollo agente–backend

Sep 25, 2026 · @Simone Bernardello

## Principi

È sempre l'agente ad avviare le connessioni, in HTTPS verso il backend: il cluster non espone nulla e non serve aprire porte in ingresso.

- **Autenticazione**: token di bootstrap solo per la registrazione, poi mTLS con un certificato per cluster. Il CN del certificato è il `cluster_id`, quindi le chiamate non lo ripetono nel percorso.
- **Formato**: JSON, timestamp in RFC 3339 UTC, ID in UUID.
- **Versioning**: prefisso `/v1` nel percorso. L'agente invia la propria versione in ogni chiamata (`User-Agent: thumbops-agent/1.2.0`) e il backend indica la versione minima supportata.
- **Base URL**: `https://agent.thumbops.mobiletechnologies.cloud/v1`.

Il reverse proxy (Caddy o Traefik) verifica il certificato client e passa il CN al servizio in un header interno. Il servizio accetta quell'header solo dal proxy, mai direttamente dall'esterno.

| Endpoint | Metodo | Autenticazione | Frequenza |
| --- | --- | --- | --- |
| `/v1/register` | POST | Token di bootstrap | Una volta |
| `/v1/agent/certificate` | POST | mTLS | Prima della scadenza del certificato |
| `/v1/agent/heartbeat` | PUT | mTLS | Ogni 60 s |
| `/v1/agent/actions` | GET | mTLS | Continua, in long polling |
| `/v1/agent/actions/{id}/claim` | POST | mTLS | Per ogni azione ricevuta |
| `/v1/agent/actions/{id}/result` | POST | mTLS | A fine esecuzione |
| `/v1/agent/status` | PUT | mTLS | Ogni 60 s e su richiesta |

## Registrazione e certificato

L'agente genera da sé la chiave privata, che non lascia mai il cluster: il backend firma solo una CSR.

1. Dall'app o dalla CLI si crea un cluster nel backend, che restituisce un token di bootstrap monouso valido 1 ora.
2. Il token viene messo in un Secret e l'agente viene installato (Helm chart).
3. All'avvio l'agente genera una chiave Ed25519, la salva in un Secret e chiama `POST /v1/register`.
4. Il backend invalida il token e restituisce il certificato firmato.

Richiesta (`Authorization: Bearer <token di bootstrap>`):

```json
{
  "csr": "-----BEGIN CERTIFICATE REQUEST-----...",
  "agent_version": "0.1.0",
  "kubernetes_version": "v1.34.3",
  "cluster_uid": "<uid del namespace kube-system>"
}
```

Risposta:

```json
{
  "cluster_id": "8c1f0e7a-...",
  "certificate": "-----BEGIN CERTIFICATE-----...",
  "ca_chain": "-----BEGIN CERTIFICATE-----...",
  "expires_at": "2026-10-25T10:00:00Z"
}
```

Il `cluster_uid` serve a riconoscere lo stesso cluster se l'agente viene reinstallato. Il certificato dura 30 giorni; quando ne resta meno di un terzo, l'agente invia una nuova CSR a `POST /v1/agent/certificate` autenticandosi con quello ancora valido. Revocare un cluster dal backend rende il certificato inutilizzabile alla chiamata successiva.

## Heartbeat

Ogni 60 secondi l'agente chiama `PUT /v1/agent/heartbeat`; dopo 3 minuti senza heartbeat il backend segna il cluster come offline e lo mostra nell'app.

Richiesta:

```json
{
  "agent_version": "0.1.0",
  "kubernetes_version": "v1.34.3",
  "nodes": { "ready": 6, "total": 6 },
  "permissions": {
    "rollout-restart": true,
    "scale": true,
    "cordon-drain": false
  },
  "last_action_id": "3b2d..."
}
```

Il blocco `permissions` è il risultato di una `SelfSubjectAccessReview` fatta dall'agente: l'app può così disabilitare in anticipo le azioni che fallirebbero per mancanza di RBAC.

Risposta:

```json
{
  "server_time": "2026-09-25T10:00:00Z",
  "poll": { "interval_seconds": 0, "wait_seconds": 20 },
  "min_agent_version": "0.1.0"
}
```

Con `poll` il backend regola il polling senza dover aggiornare l'agente. `server_time` permette all'agente di correggere gli orologi sfasati quando controlla le scadenze delle azioni.

## Ricezione delle azioni

L'agente fa long polling: la richiesta resta aperta fino a 20 secondi e un'azione approvata arriva in genere in meno di un secondo.

Appena riceve una risposta, l'agente riapre subito la richiesta. Reverse proxy e servizio devono avere timeout superiori all'attesa, ad esempio 30 secondi. Tramite il blocco `poll` dell'heartbeat il backend può ridurre `wait_seconds` o passare al polling semplice, ad esempio se una parte del servizio finisse su una piattaforma che fa pagare il tempo di attesa.

Chiamata: `GET /v1/agent/actions?wait=20`. Risposta `204` se allo scadere dell'attesa non c'è nulla, altrimenti `200`:

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

Nell'MVP la lista contiene al massimo un'azione. `runbook` indica il file e il commit Git da cui deriva l'azione, per l'audit. `expires_at` è fissato a 2 minuti dall'approvazione: un'azione rimasta in coda mentre l'agente era offline non viene più eseguita.

Parametri per tipo di azione, già risolti dal backend a partire dal runbook e dalle scelte dell'utente:

| Azione | Parametri |
| --- | --- |
| `rollout-restart` | `namespace`, `deployment` |
| `scale` | `namespace`, `deployment`, `replicas` (già verificato tra `min` e `max` del runbook) |
| `cordon`, `uncordon` | `node` |
| `drain` | `node`, `timeout_seconds` (default 600), `delete_emptydir_data` (default false) |

Nel runbook i campi del drain si chiamano `timeoutSeconds` e `deleteEmptyDirData`, come nelle risorse Kubernetes; nel protocollo seguono la convenzione snake\_case del resto dei messaggi.

## Esecuzione ed esiti

Prima di eseguire, l'agente prende in carico l'azione con `POST /v1/agent/actions/{id}/claim`; solo una presa in carico riuscita autorizza l'esecuzione.

Il claim risponde `200` se l'azione è ancora valida, `409` se è già stata presa in carico, `410` se è scaduta o annullata. Al termine l'agente invia `POST /v1/agent/actions/{id}/result`:

```json
{
  "status": "succeeded",
  "started_at": "2026-09-25T10:00:12Z",
  "finished_at": "2026-09-25T10:00:14Z",
  "message": "payments-api scalato da 3 a 6 repliche",
  "details": { "previous_replicas": 3, "replicas": 6 }
}
```

`status` vale `succeeded`, `failed` (errore dell'API Kubernetes) o `rejected` (l'agente ha rifiutato l'azione, vedi la sezione successiva). Per il restart, l'esito arriva quando il rollout è partito, non quando è completato; lo stato del rollout è un possibile miglioramento successivo.

| Stato | Chi lo imposta | Significato |
| --- | --- | --- |
| `requested` | Backend | Richiesta dall'app, in attesa di approvazione se serve |
| `approved` | Backend | Pronta, visibile all'agente fino a `expires_at` |
| `claimed` | Agente (claim) | In esecuzione |
| `succeeded` / `failed` / `rejected` | Agente (result) | Conclusa |
| `expired` | Backend | Non presa in carico entro la scadenza, oppure claim senza risultato entro 5 minuti |
| `cancelled` | Backend | Annullata dall'utente prima del claim |

Ogni cambio di stato genera una riga nell'audit log e una notifica all'utente che ha richiesto l'azione.

## Errori, idempotenza e difesa in profondità

L'agente non si fida ciecamente del backend: esegue solo azioni ammesse anche dalla propria policy locale, così un backend compromesso non può fare nulla fuori da quei limiti.

**Policy locale.** Un ConfigMap gestito dal team del cluster elenca tipi di azione, namespace e limiti ammessi (ad esempio `scale` al massimo a 20 repliche). Un'azione fuori policy viene rifiutata con `status: rejected`. A questo si aggiunge il ServiceAccount dell'agente, con RBAC limitato ai soli verbi necessari.

**Idempotenza.** Ogni azione è identificata da `action_id`. L'agente annota la risorsa modificata con `thumbops.mobiletechnologies.cloud/last-action-id`: se trova già quell'ID, non ripete l'azione e invia di nuovo l'esito. Questo copre il caso in cui l'agente si riavvia tra l'esecuzione e l'invio del risultato.

Nel prototipo l'annotazione con l'ID e una seconda annotazione con l'esito (`thumbops.mobiletechnologies.cloud/last-action-result`) vengono scritte nella stessa patch che applica la modifica, quindi non può esistere una modifica senza la traccia che la rende idempotente. Il drain fa eccezione: è composto da più passi e scrive l'annotazione solo alla fine, ma ripeterlo su un nodo già svuotato non ha effetti.

**Errori e ritentativi.**

| Codice | Significato | Comportamento dell'agente |
| --- | --- | --- |
| `401` | Certificato non valido o cluster revocato | Si ferma e lo segnala nei log; serve una nuova registrazione |
| `409` / `410` | Azione già presa o scaduta | La scarta |
| `426` | Versione dell'agente non più supportata | Continua solo con l'heartbeat e segnala l'aggiornamento |
| `429` / `5xx` | Limite di richieste o errore del backend | Ritenta con backoff esponenziale e jitter, fino a 60 s |

L'invio del `result` viene ritentato finché riesce, conservando l'esito in memoria e nell'annotazione della risorsa.

**Cambio di certificato.** Il certificato client si presenta solo all'handshake TLS, e con il long polling la connessione verso il backend non resta mai inattiva. Dopo la registrazione e dopo ogni rinnovo l'agente deve quindi aprire nuove connessioni, altrimenti continua a presentarsi senza certificato o con quello vecchio. Il prototipo lo fa, e un test lo verifica.

## Stato del cluster

Ogni 60 secondi l'agente invia un riepilogo compatto dello stato con `PUT /v1/agent/status`; il backend conserva l'ultimo riepilogo di ogni cluster per la dashboard.

L'agente raccoglie i dati con gli informer di client-go (watch), senza interrogare l'API server a ogni ciclo. Se nel cluster c'è metrics-server, aggiunge l'uso reale di CPU e memoria; altrimenti i campi `used` sono `null`.

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

**Limiti di dimensione.** L'elenco dei nodi è completo fino a 100 nodi; oltre, l'agente invia solo i nodi con problemi più gli aggregati. Pod e deployment con problemi sono limitati ai primi 20 ciascuno, ordinati per gravità. Quando qualcosa viene tagliato, `truncated` vale `true` e l'app lo segnala.

**Aggiornamento su richiesta.** Quando l'utente chiede un refresh dall'app, la risposta di `GET /v1/agent/actions` include `"status_requested": true`. L'agente invia subito un nuovo riepilogo; con il long polling il dato arriva in un paio di secondi.

**Namespace esclusi.** La policy locale dell'agente può elencare namespace da escludere (`status.exclude_namespaces`): i loro pod e deployment non vengono mai inviati al backend.

**Permessi.** Per lo stato l'agente usa un ClusterRole in sola lettura (`get`, `list`, `watch`) su nodi, pod, eventi e deployment, più `get` sulle metriche di `metrics.k8s.io`. È separato dal ruolo usato per le azioni, così si può installare l'agente anche solo per la dashboard.

## Questioni aperte

- Unire heartbeat e polling in una sola chiamata per dimezzare le richieste, o tenerli separati per semplicità?
- Il drain può durare minuti: serve un esito intermedio (`progress`) o basta un timeout più lungo per quel tipo di azione?
- Dove vive la CA che firma i certificati degli agenti: AWS Private CA (costo fisso mensile) o una CA gestita in proprio con la chiave in KMS?
