import azure.functions as func
import io
import logging
import csv
import json
import os
import time

from azure.storage.blob import BlobClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _access_control_allow_origin(req: func.HttpRequest) -> str:
    """
    Browsers require Access-Control-Allow-Origin to echo a specific origin when
    credentials are involved; some setups also mis-handle '*'. Azure platform
    503 responses omit CORS headers entirely — fix the 503 (runtime/deploy),
    then this header applies to successful function responses.
    """
    origin = (req.headers.get("Origin") or "").strip()
    extra = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if extra:
        parts = [o.strip() for o in extra.split(",") if o.strip()]
        if "*" in parts:
            return "*"
        allowed = frozenset(parts)
        if origin in allowed:
            return origin
        return "*"
    if origin.startswith("https://") and origin.endswith(".azurestaticapps.net"):
        return origin
    if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
        return origin
    return "*"


def _cors_headers(req: func.HttpRequest) -> dict:
    return {
        "Access-Control-Allow-Origin": _access_control_allow_origin(req),
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def _iter_diet_rows():
    """
    Local dev: read All_Diets.csv next to this file.
    Azure (Person 3): set app settings DIET_BLOB_CONTAINER (and optionally
    DIET_BLOB_NAME) so the function reads the uploaded CSV from Blob Storage.
    """
    container = os.environ.get("DIET_BLOB_CONTAINER")
    blob_name = os.environ.get("DIET_BLOB_NAME", "All_Diets.csv")
    conn = os.environ.get("AzureWebJobsStorage") or os.environ.get(
        "DIET_BLOB_CONNECTION_STRING"
    )

    if container and conn:
        blob = BlobClient.from_connection_string(
            conn, container_name=container, blob_name=blob_name
        )
        raw = blob.download_blob().readall().decode("utf-8")
        return csv.DictReader(io.StringIO(raw))

    csv_path = os.path.join(os.path.dirname(__file__), "All_Diets.csv")
    with open(csv_path, newline="", encoding="utf-8") as f:
        text = f.read()
    return csv.DictReader(io.StringIO(text))


@app.route(route="analyze")
def analyze(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")

    cors_headers = _cors_headers(req)
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers)

    start_time = time.time()

    averages = {}

    reader = _iter_diet_rows()
    for row in reader:
        diet_type = row["Diet_type"]

        if diet_type not in averages:
            averages[diet_type] = {
                "Protein": 0.0,
                "Carbs": 0.0,
                "Fat": 0.0,
                "count": 0,
            }

        averages[diet_type]["Protein"] += float(row["Protein(g)"])
        averages[diet_type]["Carbs"] += float(row["Carbs(g)"])
        averages[diet_type]["Fat"] += float(row["Fat(g)"])
        averages[diet_type]["count"] += 1

    for diet in averages:
        count = averages[diet]["count"]
        averages[diet]["Protein"] = round(averages[diet]["Protein"] / count, 2)
        averages[diet]["Carbs"] = round(averages[diet]["Carbs"] / count, 2)
        averages[diet]["Fat"] = round(averages[diet]["Fat"] / count, 2)
        del averages[diet]["count"]

    labels = list(averages.keys())
    protein = [averages[diet]["Protein"] for diet in labels]
    carbs = [averages[diet]["Carbs"] for diet in labels]
    fat = [averages[diet]["Fat"] for diet in labels]

    execution_time_ms = int((time.time() - start_time) * 1000)

    result = {
        "macrosByDiet": {
            "labels": labels,
            "protein": protein,
            "carbs": carbs,
            "fat": fat
        },
        "executionTimeMs": execution_time_ms
    }

    return func.HttpResponse(
        json.dumps(result),
        mimetype="application/json",
        status_code=200,
        headers=cors_headers,
    )