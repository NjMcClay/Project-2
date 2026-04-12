# Azure Function App settings

Add these app settings in the Azure Portal for the Function App.

## Required

- `AzureWebJobsStorage`
- `FUNCTIONS_WORKER_RUNTIME=python`

## Blob source

- `DIET_SOURCE_CONTAINER=diet-data`
- `DIET_SOURCE_BLOB_NAME=All_Diets.csv`

## Cleaned output blob

- `DIET_CLEAN_CONTAINER=diet-data`
- `DIET_CLEAN_BLOB_NAME=cleaned/All_Diets.cleaned.csv`

## Redis

- `REDIS_URL=rediss://<your-redis-name>.redis.cache.windows.net:6380/0`
- `REDIS_KEY=<your-redis-primary-key>`

## Cache keys

- `ANALYZE_CACHE_KEY=diet:analyze:v1`
- `ANALYZE_META_CACHE_KEY=diet:analyze:meta:v1`

## API protection

Leave blank for public routes, or set a shared secret:

- `API_SHARED_SECRET=<your-shared-secret>`

## CORS

- `CORS_ALLOWED_ORIGINS=https://lively-ocean-0a4dc570f.6.azurestaticapps.net,http://localhost:5500`

# Notes

- Upload `All_Diets.csv` to the source container after deployment so the blob trigger runs.
- `/api/analyze` reads Redis only.
- `/api/recipes` reads the cleaned CSV blob.
