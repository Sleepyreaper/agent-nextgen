Local prototype run instructions

1) Create and activate the virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2) Install Python dependencies

```bash
pip install -r requirements.txt
```

3) Run the quick structure tests

```bash
python test_agent_models.py
```

4) Run the Flask app locally (development mode)

```bash
export FLASK_APP=app.py
export FLASK_ENV=development
python -m flask run --port=5000
```

5) Quick health check (after server running)

```bash
curl http://127.0.0.1:5000/health
```

Notes:
- If you don't have a Postgres database configured, the app will fall back to an in-memory SQLite database for local prototype runs.
- Provide production secrets via environment variables or Azure Key Vault as documented in `src/config.py`.
