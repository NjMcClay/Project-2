# GitHub Actions deployment

This repo includes two workflows under `.github/workflows/`:

| Workflow | Triggers | What it deploys |
|----------|----------|-----------------|
| `azure-static-web-apps.yml` | Push / PR to `main` when `frontend/` changes | Static site from `frontend/` |
| `azure-functions.yml` | Push to `main` when `backend/` changes | Python Function App from `backend/` |

Both support **manual runs**: GitHub → **Actions** → select the workflow → **Run workflow**.

If your default branch is not `main`, edit the `branches:` lists in each YAML file.

---

## 1. Static Web App (frontend)

### Create the resource (Azure Portal)

1. Create a **Static Web App** (deployment source: **GitHub**).
2. Connect your repository and branch (`main`).
3. Azure can generate a workflow automatically; you may **replace** it with this repo’s `azure-static-web-apps.yml`, or keep Azure’s file and align `app_location` / `skip_app_build` with ours.

### GitHub secret

| Secret name | Where to get it |
|-------------|------------------|
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | Azure Portal → your Static Web App → **Manage deployment token** (copy the token). |

In GitHub: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

The workflow uses plain static files: `app_location: frontend`, `skip_app_build: true`, `output_location: ""`.

---

## 2. Azure Functions (backend)

### Publish profile

1. Azure Portal → your **Function App** → **Get publish profile** (downloads a `.PublishSettings` file).
2. Open the file, copy **all** XML contents.

### GitHub secrets

| Secret name | Value |
|-------------|--------
| `AZURE_FUNCTIONAPP_NAME` | Function App **name** only (e.g. `diet-analyze-func`), not the full URL. |
| `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` | Full contents of the publish profile XML. |

The workflow sets **`scm-do-build-during-deployment: true`** so Azure can install Python dependencies from `backend/requirements.txt` during deploy.

### Application settings (Portal)

After the first successful deploy, confirm **Configuration** on the Function App includes any settings your code needs (for example `DIET_BLOB_CONTAINER` for blob-backed CSV). See [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 3. CORS (frontend calling the API)

After both URLs exist, allow your Static Web App origin on the **Function App** → **CORS**, and set **`CLOUD_ANALYZE_URL`** in `frontend/app.js` to your live `https://<app>.azurewebsites.net/api/analyze` before the next frontend deploy.

---

## 4. Troubleshooting

- **SWA workflow fails with missing token:** Add `AZURE_STATIC_WEB_APPS_API_TOKEN` or temporarily disable the workflow.
- **Functions deploy fails:** Confirm `AZURE_FUNCTIONAPP_NAME` matches the app name in Azure exactly; republish a fresh publish profile if the secret expired.
- **Wrong Python version:** Set the Function App’s **Python version** in Azure to match what you use locally (e.g. 3.11).
