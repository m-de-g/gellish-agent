# gellish-agent

## Backend Quickstart
1. `cd backend`
2. Ensure `.env` at repo root has `DATABASE_URL` set.
3. Run the API: `uvicorn app.main:app --reload`

Try ingestion:
```bash
curl -X POST http://127.0.0.1:8000/documents/paste \\
  -H 'Content-Type: application/json' \\
  -d '{"text":"Hello world. Second sentence?"}'
```
