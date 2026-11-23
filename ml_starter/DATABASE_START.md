# Application database startup (separate from ML datasets)

Repository: https://github.com/tanish19078/posify
Current backend setup: https://github.com/tanish19078/posify/blob/main/docs/DATABASE.md
Detector contract: https://github.com/tanish19078/posify/blob/main/docs/DETECTOR_CONTRACT.md

No hosted PostgreSQL URL is created yet. For local development with Docker:

```bash
git clone https://github.com/tanish19078/posify.git
cd posify
export POSIFY_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export POSIFY_DB_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
mkdir -p models
docker compose up --build
```

The existing stack starts PostgreSQL, runs migrations, then starts the API and
analysis worker. API docs: http://127.0.0.1:8000/docs. Authorize with the generated
API token. PostgreSQL is internal to the Compose network, not exposed as a public
DB URL. Containers connect to `db:5432`, database/user `posify` and the generated
password. Keep your environment values available for later starts.

SQLite is also supported for a quick local backend without Docker; see the repo
README. Docker configuration has not been run on the assistant's host. PostgreSQL
and SQLite API paths passed CI. Individual-user/site permissions remain pending;
the development instance token grants broad access.

You do not need PostgreSQL to train YOLO in Colab. Train on image/label files, then
send the exported ONNX bundle back for backend integration.
