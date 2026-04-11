# Azure deployment (Person 3 checklist)

For **GitHub Actions** (automated deploys), see [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md).

Use your instructor’s naming rules if they differ. Below is a minimal, repeatable order of operations.

## 1. Create Azure resources

Create in the Azure Portal (or Azure CLI):

| Resource | Example name | Notes |
|----------|--------------|--------|
| Resource group | `diet-analysis-rg` | One group for the whole project |
| Storage account | `dietsstorageXXXX` | Globally unique; supports blobs |
| Blob container | e.g. `diets` | Private or public read, per assignment |
| Function App | `diet-analyze-func` | Python, Consumption or Flex (per course) |
| Static Web App | `diet-dashboard-swa` | Connects to this GitHub repo (or manual deploy) |

## 2. Upload the dataset

1. In the Storage Account, open **Containers** → your container (e.g. `diets`).
2. Upload **`All_Diets.csv`** (same file as in `backend/`).
3. Note the **blob name** (usually `All_Diets.csv`).

## 3. Configure the Function App (backend)

### Application settings

In the Function App → **Configuration** → **Application settings**, add:

| Name | Example / notes |
|------|-----------------|
| `AzureWebJobsStorage` | Often already set to the storage connection string |
| `FUNCTIONS_WORKER_RUNTIME` | `python` |
| `DIET_BLOB_CONTAINER` | Your container name, e.g. `diets` |
| `DIET_BLOB_NAME` | Optional; defaults to `All_Diets.csv` |

The function uses the storage connection string (`AzureWebJobsStorage` or `DIET_BLOB_CONNECTION_STRING`) plus `DIET_BLOB_CONTAINER` to download the CSV from Blob Storage. If `DIET_BLOB_CONTAINER` is **not** set, local runs still use the file `backend/All_Diets.csv`.

Deploy `backend/` using your course’s method (VS Code Azure extension, `func azure functionapp publish`, or GitHub Actions).

### Function URL

After deployment, copy the HTTPS URL for the `analyze` function, for example:

`https://diet-analyze-func.azurewebsites.net/api/analyze`

Test in the browser or with:

```bash
curl -s "https://YOUR-FUNCTION-APP.azurewebsites.net/api/analyze"
```

You should see JSON with `macrosByDiet` and `executionTimeMs`.

## 4. CORS (required for browser dashboard)

The Static Web App origin (e.g. `https://your-app.azurestaticapps.net`) must be allowed to call the Function origin.

In **Function App** → **API** → **CORS**, add your Static Web App URL (scheme + host, no path). Save and restart if prompted.

## 5. Deploy the frontend (Static Web App)

Deploy the contents of **`frontend/`** (not the whole repo root, unless your workflow is configured that way).

### Connect frontend to cloud backend

In `frontend/app.js`, set **`CLOUD_ANALYZE_URL`** to your deployed function URL:

```javascript
const CLOUD_ANALYZE_URL =
  "https://YOUR-FUNCTION-APP.azurewebsites.net/api/analyze";
```

Behavior:

- Opening the dashboard from **`localhost`** still uses `http://localhost:7071/api/analyze` for local testing.
- Opening the dashboard from **Azure Static Web Apps** uses `CLOUD_ANALYZE_URL`.

Optional override for debugging:

`https://your-static-app.azurestaticapps.net/index.html?functionUrl=https://.../api/analyze`

## 6. Deliverables to capture

- Function App URL returning JSON
- Static Web App URL showing charts
- Blob container screenshot with `All_Diets.csv`
- GitHub repository link

See `screenshots/README.md` for a screenshot checklist.
