# ThumbOps spec

Contratti pubblici di [ThumbOps](https://github.com/thumbops): il protocollo tra
l'agente nel cluster e il backend, e il formato dei runbook.

| Percorso | Contenuto |
| --- | --- |
| [`protocol/protocollo.md`](protocol/protocollo.md) | Protocollo agente–backend v1 |
| [`runbook/schema.md`](runbook/schema.md) | Formato e regole dei runbook |
| [`runbook/runbook.schema.json`](runbook/runbook.schema.json) | JSON Schema dei runbook |
| [`runbook/validate.py`](runbook/validate.py) | Validatore per la CI |

## Validare i propri runbook

```
pip install -r runbook/requirements.txt
python3 runbook/validate.py path/ai/runbook/
```

Esce con codice 1 se almeno un runbook non è valido, quindi si può usare
direttamente in una pipeline.
