import azure.functions as func
import io
import logging
import csv
import json
import os
import time

from azure.storage.blob import BlobClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


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

    # Allow dashboard on Azure Static Web Apps (and localhost) to call this API from the browser.
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
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