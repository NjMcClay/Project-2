# Diet Cloud Dashboard

Phase 2 project: Azure Function API (`/api/analyze`) plus a static dashboard that visualizes diet macro averages.

## Repository layout

| Folder | Owner (typical) | Contents |
|--------|-----------------|----------|
| `backend/` | Person 1 | Azure Functions Python app, CSV analysis, JSON response |
| `frontend/` | Person 2 | `index.html`, `style.css`, `app.js`, Chart.js dashboard |
| `docs/` | Person 3 | Architecture, Azure deployment notes, report screenshots |

## Quick local test

1. **Backend:** from `backend/`, run `func start` and open `http://localhost:7071/api/analyze` (JSON).
2. **Frontend:** from `frontend/`, run `python3 -m http.server 5500` and open `http://localhost:5500/index.html` (dashboard calls the local API).

## Cloud (Person 3)

After deploying the Function App and Static Web App, set `CLOUD_ANALYZE_URL` in `frontend/app.js` to your live `https://<your-function-app>.azurewebsites.net/api/analyze`. See `docs/DEPLOYMENT.md`.

## GitHub Actions

Workflows live in `.github/workflows/`. Configure repository secrets as described in `docs/GITHUB_ACTIONS.md`.
