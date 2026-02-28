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
