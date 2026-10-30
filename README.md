# HandOff

AI-powered meeting and work-handover tracker.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Health check: `GET /health`
