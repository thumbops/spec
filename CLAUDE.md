# ThumbOps spec

Repository **pubblico** `thumbops/spec`: i contratti di ThumbOps. È l'unica
fonte di verità per il protocollo agente–backend e per il formato dei runbook;
agente e backend li seguono, i clienti usano il validatore nella loro CI.

ThumbOps permette di eseguire dal telefono solo azioni pre-approvate su cluster
Kubernetes. Il contesto completo del progetto è nel repository privato
`../platform` (`CLAUDE.md` e `docs/progetto.md`), se presente sul disco.

## Struttura

```
protocol/protocollo.md     protocollo agente–backend v1, in prosa
protocol/openapi.yaml      da scrivere: stessa specifica in OpenAPI 3.1
runbook/schema.md          formato e regole dei runbook
runbook/runbook.schema.json JSON Schema (draft 2020-12)
runbook/validate.py        validazione: schema + controlli semantici
runbook/examples/          runbook validi, non validi, nomi duplicati
```

## Comandi

```
pip install -r runbook/requirements.txt   # serve jsonschema >= 4.18 (draft 2020-12)
python3 runbook/validate.py runbook/examples/valid       # deve uscire con 0
python3 runbook/validate.py runbook/examples/invalid     # deve uscire con 1, un errore per file
python3 runbook/validate.py runbook/examples/duplicate   # deve segnalare il nome duplicato
```

## Regole

- **Contratti versionati.** Il repository si rilascia con tag semver. Una
  modifica incompatibile al protocollo richiede `/v2`; allo schema dei runbook,
  `apiVersion: .../v2` e un nuovo `$id`. Il backend accetta entrambe le
  versioni durante la transizione.
- **Consumatori da aggiornare.** Se cambi un contratto, elenca nella modifica
  cosa va aggiornato: i tipi Go in `../agent/internal/protocol/types.go`, il
  backend finto `../agent/internal/mockbackend`, i tipi generati in `../platform`.
- `additionalProperties: false` ovunque nello schema: un runbook non deve poter
  contenere campi non previsti, ad esempio comandi arbitrari.
- Lo schema dell'azione si sceglie con `if`/`then` su `type`, non con `oneOf`,
  così gli errori indicano il campo sbagliato.
- Le regole che lo schema non esprime bene (min ≤ max, cooldown minimo, nomi
  unici) stanno in `validate.py`; il backend deve replicarle.
- Ogni regola nuova ha un esempio in `runbook/examples/invalid/`.
- Repository pubblico: niente materiale interno (modello di business, piani,
  marchio), che va in `../platform`.

## Convenzioni

Italiano per documentazione e messaggi; inglese per identificatori e campi. JSON
del protocollo in `snake_case`, YAML dei runbook in `camelCase`, prefisso
`thumbops.mobiletechnologies.cloud/` per annotazioni ed etichette.

## Prossimi passi

1. Scrivere `protocol/openapi.yaml` a partire da `protocol/protocollo.md`, con
   esempi validi; controllare che l'agente attuale sia conforme.
2. Test automatici (pytest) sugli esempi dei runbook.
3. GitHub Action riutilizzabile per validare i runbook nella CI dei clienti.
4. Tradurre in italiano leggibile i messaggi tecnici di `jsonschema`.
5. Aggiungere il file `LICENSE` (Apache 2.0).
