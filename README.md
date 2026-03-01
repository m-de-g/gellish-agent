# gellish-agent

## Backend Quickstart
1. `cd backend`
2. Ensure `.env` at repo root has:
   - `DATABASE_URL=...`
   - `OPENAI_API_KEY=...` (required for `provider=openai`)
   - `OPENAI_MODEL=gpt-4.1-mini` (optional override)
3. Run the API: `uvicorn app.main:app --reload`

Try ingestion:
```bash
curl -X POST http://127.0.0.1:8000/documents/paste \\
  -H 'Content-Type: application/json' \\
  -d '{"text":"Hello world. Second sentence?"}'
```

Translate with stub provider:
```bash
curl -X POST http://127.0.0.1:8000/translate/document/1 \\
  -H 'Content-Type: application/json' \\
  -d '{"provider":"stub"}'
```

Translate with OpenAI provider:
```bash
curl -X POST http://127.0.0.1:8000/translate/document/1 \\
  -H 'Content-Type: application/json' \\
  -d '{
    "provider":"openai",
    "openai":{"model":"gpt-4.1-mini","temperature":0.0,"seed":7},
    "max_sentences":5
  }'
```

Resumable translation (translate one sentence at a time):
```bash
curl -X POST http://127.0.0.1:8000/translate/document/1 \\
  -H 'Content-Type: application/json' \\
  -d '{
    "provider":"stub",
    "start_sentence_index":0,
    "max_sentences":1
  }'
```
The response includes `next_sentence_index` and `is_complete`. Call again with:
`"start_sentence_index": <next_sentence_index>` and optionally `"translation_run_id": <id>`
to continue the same run without duplicating already translated sentence IR/expressions.

Provider failures are captured per sentence and do not fail the whole HTTP request. The
response contains `aborted_reason` when the run is stopped early (for example `auth` or
`quota` errors from the provider).

List provisional concept UIDs for a translation run:
```bash
curl -X GET http://127.0.0.1:8000/translation-runs/1/provisionals
```

Batch-promote provisionals for a translation run:
```bash
curl -X POST http://127.0.0.1:8000/translation-runs/1/promote-provisionals \\
  -H 'Content-Type: application/json' \\
  -d '{
    "mapping": {
      "provisional:toaster": {"new_uid":"concept:toaster","pref_label":"toaster","definition":null},
      "provisional:lever": {"new_uid":"concept:lever","pref_label":"lever"}
    },
    "auto_generate_missing": false
  }'
```
