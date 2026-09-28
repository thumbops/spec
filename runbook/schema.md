# Schema dei runbook

Sep 28, 2026 · @Simone Bernardello

## Struttura di un runbook

Un runbook autorizza una sola azione su un insieme di cluster e risorse, con limiti e regole di approvazione fissati in anticipo; tutto ciò che non è dichiarato è vietato.

Il formato riprende quello delle risorse Kubernetes (`apiVersion`, `kind`, `metadata`, `spec`), così chi lo scrive ritrova una struttura familiare e in futuro lo si potrà trasformare in una CRD senza cambiarlo.

```yaml
apiVersion: thumbops.mobiletechnologies.cloud/v1
kind: Runbook
metadata:
  name: payments-api-restart
  description: Riavvia payments-api quando i pod vanno in crash
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

Un file contiene un solo runbook. Il repository tipico ha una cartella per team (`runbooks/payments/`, `runbooks/platform/`), e il campo `owner` rende esplicito chi ne è responsabile.

## Campi

Sono obbligatori `metadata.name`, `spec.target.clusters`, `spec.action` e `spec.approval`; qualsiasi campo non elencato qui rende il runbook non valido.

| Campo | Obbligatorio | Valori ammessi |
| --- | --- | --- |
| `metadata.name` | Sì | Nome DNS minuscolo, max 63 caratteri, unico nel repository |
| `metadata.description` | No | Testo, max 200 caratteri; appare nell'app |
| `metadata.owner` | No | Team o persona responsabile |
| `spec.alerts[].match` | No | Etichette dell'alert da confrontare (es. `alertname`, `namespace`); max 20 regole. Senza alert, il runbook è disponibile solo dalla dashboard |
| `spec.target.clusters.matchLabels` | Sì | Etichette dei cluster registrati (es. `env: prod`) |
| `spec.target.namespace` | Per restart e scale | Nome del namespace |
| `spec.target.deployment` | Per restart e scale | Nome del deployment |
| `spec.target.nodes.matchLabels` | Per cordon, uncordon, drain | Etichette dei nodi su cui l'azione è ammessa |
| `spec.action.type` | Sì | `rollout-restart`, `scale`, `cordon`, `uncordon`, `drain` |
| `spec.action.params` | Per scale; facoltativo per drain | Scale: `min` e `max` repliche (0–1000). Drain: `timeoutSeconds` (30–3600, default 600), `deleteEmptyDirData` (default false) |
| `spec.approval` | Sì | `single` oppure `two-person` |
| `spec.cooldown` | No | Durata come `30s`, `10m`, `1h`; minimo 1 minuto |

Nello scale l'utente sceglie il numero di repliche nell'app, ma solo tra `min` e `max`. Nel drain, `deleteEmptyDirData` resta falso per default perché cancellare i volumi `emptyDir` può far perdere dati temporanei.

## Regole di validazione

La validazione ha due livelli: un JSON Schema (draft 2020-12) per struttura e valori, e pochi controlli semantici in codice per le regole che lo schema non esprime bene.

**Nello schema:**

- Nessun campo aggiuntivo in nessun punto, così un runbook non può contenere comandi o parametri non previsti.
- Lo schema dell'azione è scelto in base a `type`, così l'errore indica il campo sbagliato invece di un generico "nessuno schema corrisponde".
- Coerenza tra azione e bersaglio: restart e scale richiedono `namespace` e `deployment` e vietano `nodes`; cordon, uncordon e drain richiedono `nodes` e vietano `namespace` e `deployment`.
- Nomi e etichette seguono le regole di Kubernetes (nomi DNS, chiavi e valori delle label).

**Controlli semantici:**

- In `scale`, `min` non può superare `max`.
- `cooldown` non può essere inferiore a 1 minuto.
- `metadata.name` deve essere unico tra tutti i file validati insieme.

Casi usati per testare lo schema, tutti respinti con l'errore indicato:

| Caso | Errore restituito |
| --- | --- |
| Campo `command` aggiunto a un rollout-restart | `spec.action`: campo aggiuntivo non ammesso (`command`) |
| Azione `delete-namespace` | `spec.action.type`: valore non tra quelli ammessi |
| Scale su `nodes` invece che su un deployment | `spec.target`: mancano `namespace` e `deployment`, `nodes` non ammesso |
| Drain su un namespace | `spec.target`: manca `nodes`, `namespace` non ammesso |
| Scale con `min: 8`, `max: 3` e cooldown `10s` | Min maggiore di max; cooldown sotto il minimo |
| Nome `Payments_API` e approvazione `always` | Nome non valido; approvazione non tra quelle ammesse |
| Due file con lo stesso `metadata.name` | Nome già usato nel primo file |

Tre runbook validi (restart con doppia approvazione, scale con limiti, drain su nodi di staging) passano senza errori. Lo script esce con codice 1 quando almeno un runbook non è valido, quindi basta aggiungerlo alla pipeline.

## Dove avvengono i controlli

Lo stesso runbook viene controllato in tre punti, e ognuno blocca un tipo diverso di errore: nessuno dei tre si fida del precedente.

| Dove | Quando | Cosa controlla |
| --- | --- | --- |
| CI del repository | A ogni pull request | Schema e controlli semantici; il merge è bloccato se fallisce |
| Backend | Alla sincronizzazione dal repository e a ogni richiesta dall'app | Di nuovo lo schema (un runbook non valido viene scartato e segnalato); parametri scelti dall'utente entro i limiti; permessi dell'utente sul cluster; cooldown |
| Agente | Prima di eseguire | Policy locale del cluster: tipi di azione, namespace e limiti ammessi dal team che gestisce il cluster |

Il backend usa lo stesso file `runbook.schema.json` della CI, così le regole non possono divergere. Lo schema ha un `$id` versionato (`runbook-v1.json`): una modifica incompatibile richiederà `apiVersion: .../v2`, e il backend accetterà entrambe le versioni durante la transizione.

## Questioni aperte

- Servono selettori più espressivi di `matchLabels` (ad esempio `matchExpressions` con `In` e `NotIn`)? Per l'MVP bastano le uguaglianze.
- Un runbook su più deployment (ad esempio tutti quelli con una certa etichetta) invece di uno solo: utile, ma aumenta il raggio d'azione.
- Il repository dei runbook è uno per organizzazione o uno per team? Cambia come il backend gestisce nomi duplicati e permessi di modifica.
- Alcuni messaggi dello schema sono ancora tecnici (ad esempio "should not be valid under"): lo script può tradurli in italiano leggibile prima di mostrarli.
