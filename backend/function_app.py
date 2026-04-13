import csv
import hashlib
import hmac
import io
import json
import logging
import math
import os
import secrets
import time
import urllib.parse
import urllib.request
from typing import Any

import azure.functions as func
import jwt
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
import redis

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


SOURCE_CONTAINER = os.getenv("DIET_SOURCE_CONTAINER", "diet-data")
SOURCE_BLOB_NAME = os.getenv("DIET_SOURCE_BLOB_NAME", "All_Diets.csv")

CLEAN_CONTAINER = os.getenv("DIET_CLEAN_CONTAINER", SOURCE_CONTAINER)
CLEAN_BLOB_NAME = os.getenv("DIET_CLEAN_BLOB_NAME", "cleaned/All_Diets.cleaned.csv")

ANALYZE_CACHE_KEY = os.getenv("ANALYZE_CACHE_KEY", "diet:analyze:v1")
META_CACHE_KEY = os.getenv("ANALYZE_META_CACHE_KEY", "diet:analyze:meta:v1")

AZURE_STORAGE_CONNECTION_STRING = os.getenv("AzureWebJobsStorage", "")
REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_KEY = os.getenv("REDIS_KEY", "")
API_SHARED_SECRET = os.getenv("API_SHARED_SECRET", "").strip()
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_ISSUER = os.getenv("JWT_ISSUER", "diet-dashboard")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "diet-dashboard-users")
JWT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", "86400"))
USERS_TABLE = os.getenv("USERS_TABLE", "users")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "").strip()
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "").strip()
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI", "").strip()
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() != "false"

blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
table_service = TableServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)


def get_redis_client() -> redis.Redis:
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL is not configured.")
    return redis.Redis.from_url(
        REDIS_URL,
        password=REDIS_KEY or None,
        decode_responses=True,
    )


def _access_control_allow_origin(req: func.HttpRequest) -> str:
    origin = (req.headers.get("Origin") or "").strip()

    if CORS_ALLOWED_ORIGINS:
        allowed = [o.strip() for o in CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
        if "*" in allowed:
            return "*"
        if origin in allowed:
            return origin

    if origin.startswith("https://") and origin.endswith(".azurestaticapps.net"):
        return origin
    if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
        return origin

    return "*"


def _cors_headers(req: func.HttpRequest) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": _access_control_allow_origin(req),
        "Access-Control-Allow-Methods": "GET,POST,HEAD,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-API-Key",
    }


def _json_response(req: func.HttpRequest, payload: dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload),
        mimetype="application/json",
        status_code=status_code,
        headers=_cors_headers(req),
    )


def _options_or_head(req: func.HttpRequest) -> func.HttpResponse | None:
    headers = _cors_headers(req)
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=headers)
    if req.method == "HEAD":
        return func.HttpResponse(status_code=200, headers=headers)
    return None


def _unauthorized(req: func.HttpRequest, message: str = "Unauthorized") -> func.HttpResponse:
    return _json_response(req, {"error": message}, status_code=401)


def _require_api_secret(req: func.HttpRequest) -> func.HttpResponse | None:
    """
    Optional protection hook.
    If API_SHARED_SECRET is empty, routes stay public.
    If set, accept either:
      Authorization: Bearer <secret>
      X-API-Key: <secret>
    """
    if not API_SHARED_SECRET:
        return None

    auth_header = (req.headers.get("Authorization") or "").strip()
    api_key = (req.headers.get("X-API-Key") or "").strip()

    bearer_secret = ""
    if auth_header.lower().startswith("bearer "):
        bearer_secret = auth_header[7:].strip()

    if bearer_secret == API_SHARED_SECRET or api_key == API_SHARED_SECRET:
        return None

    return _unauthorized(req)


def _users_table_client():
    table = table_service.create_table_if_not_exists(table_name=USERS_TABLE)
    return table


def _password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def _password_verify(password: str, stored_hash: str) -> bool:
    try:
        algo, salt, expected = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200000).hex()
    return hmac.compare_digest(digest, expected)


def _jwt_issue(user: dict[str, Any]) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not configured.")
    now = int(time.time())
    payload = {
        "sub": user["userId"],
        "email": user["email"],
        "name": user["name"],
        "provider": user.get("provider", "local"),
        "iat": now,
        "exp": now + JWT_TTL_SECONDS,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _jwt_decode(token: str) -> dict[str, Any]:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not configured.")
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer=JWT_ISSUER, audience=JWT_AUDIENCE)


def _extract_bearer_token(req: func.HttpRequest) -> str:
    auth = (req.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _require_user(req: func.HttpRequest) -> tuple[dict[str, Any] | None, func.HttpResponse | None]:
    if not AUTH_REQUIRED:
        return ({"sub": "anonymous", "email": "", "name": "Anonymous", "provider": "none"}, None)
    token = _extract_bearer_token(req)
    if not token:
        return (None, _json_response(req, {"error": "Missing Authorization bearer token."}, status_code=401))
    try:
        claims = _jwt_decode(token)
        return (claims, None)
    except Exception:
        return (None, _json_response(req, {"error": "Invalid or expired token."}, status_code=401))


def _state_sign(value: str) -> str:
    if not JWT_SECRET:
        return value
    sig = hmac.new(JWT_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}.{sig}"


def _state_verify(signed_value: str) -> str | None:
    if not JWT_SECRET:
        return signed_value
    if "." not in signed_value:
        return None
    value, sig = signed_value.rsplit(".", 1)
    expected = hmac.new(JWT_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    return value


def _auth_provider_enabled() -> bool:
    return bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET and GITHUB_REDIRECT_URI)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_diet(value: Any) -> str:
    return _normalize_text(value).lower()


def _write_blob_text(container: str, blob_name: str, content: str) -> None:
    blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
    blob_client.upload_blob(content.encode("utf-8"), overwrite=True)


def _read_cleaned_rows() -> list[dict[str, Any]]:
    blob_client = blob_service.get_blob_client(container=CLEAN_CONTAINER, blob=CLEAN_BLOB_NAME)
    raw = blob_client.download_blob().readall().decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw))
    rows: list[dict[str, Any]] = []

    for row in reader:
        rows.append(
            {
                "recipe_id": int(row["recipe_id"]),
                "recipe_name": row["recipe_name"],
                "diet_type": row["diet_type"],
                "protein_g": float(row["protein_g"]),
                "carbs_g": float(row["carbs_g"]),
                "fat_g": float(row["fat_g"]),
                "calories": float(row["calories"]),
                "keyword_text": row["keyword_text"],
            }
        )

    return rows


def _clean_rows_from_source(raw_csv_bytes: bytes) -> list[dict[str, Any]]:
    text = raw_csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    cleaned: list[dict[str, Any]] = []

    for idx, row in enumerate(reader, start=1):
        recipe_name = _normalize_text(
            row.get("Recipe_name")
            or row.get("Recipe")
            or row.get("Name")
            or row.get("recipe_name")
        )
        diet_type = _clean_diet(
            row.get("Diet_type")
            or row.get("Diet")
            or row.get("diet_type")
        )

        protein_g = _safe_float(row.get("Protein(g)") or row.get("Protein"))
        carbs_g = _safe_float(row.get("Carbs(g)") or row.get("Carbs"))
        fat_g = _safe_float(row.get("Fat(g)") or row.get("Fat"))

        if not recipe_name or not diet_type:
            continue

        calories = round((protein_g * 4) + (carbs_g * 4) + (fat_g * 9), 2)
        keyword_text = f"{recipe_name} {diet_type}".lower()

        cleaned.append(
            {
                "recipe_id": idx,
                "recipe_name": recipe_name,
                "diet_type": diet_type,
                "protein_g": round(protein_g, 2),
                "carbs_g": round(carbs_g, 2),
                "fat_g": round(fat_g, 2),
                "calories": calories,
                "keyword_text": keyword_text,
            }
        )

    return cleaned


def _cleaned_rows_to_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = [
        "recipe_id",
        "recipe_name",
        "diet_type",
        "protein_g",
        "carbs_g",
        "fat_g",
        "calories",
        "keyword_text",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _build_analyze_payload(rows: list[dict[str, Any]], source_blob_name: str) -> dict[str, Any]:
    grouped: dict[str, dict[str, float]] = {}

    for row in rows:
        diet = row["diet_type"]
        if diet not in grouped:
            grouped[diet] = {
                "protein_sum": 0.0,
                "carbs_sum": 0.0,
                "fat_sum": 0.0,
                "count": 0.0,
            }

        grouped[diet]["protein_sum"] += row["protein_g"]
        grouped[diet]["carbs_sum"] += row["carbs_g"]
        grouped[diet]["fat_sum"] += row["fat_g"]
        grouped[diet]["count"] += 1

    labels = sorted(grouped.keys())
    protein: list[float] = []
    carbs: list[float] = []
    fat: list[float] = []

    for diet in labels:
        count = grouped[diet]["count"] or 1
        protein.append(round(grouped[diet]["protein_sum"] / count, 2))
        carbs.append(round(grouped[diet]["carbs_sum"] / count, 2))
        fat.append(round(grouped[diet]["fat_sum"] / count, 2))

    return {
        "macrosByDiet": {
            "labels": labels,
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
        },
        "meta": {
            "sourceBlob": source_blob_name,
            "cleanedBlob": CLEAN_BLOB_NAME,
            "rowCount": len(rows),
            "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }


def _cache_analyze_payload(payload: dict[str, Any]) -> None:
    client = get_redis_client()
    client.set(ANALYZE_CACHE_KEY, json.dumps(payload))
    client.set(META_CACHE_KEY, json.dumps(payload.get("meta", {})))


def _run_preprocess(source_blob_name: str) -> dict[str, Any]:
    started = time.time()
    source_blob = blob_service.get_blob_client(container=SOURCE_CONTAINER, blob=source_blob_name)
    raw_csv = source_blob.download_blob().readall()
    cleaned_rows = _clean_rows_from_source(raw_csv)

    cleaned_csv = _cleaned_rows_to_csv(cleaned_rows)
    _write_blob_text(CLEAN_CONTAINER, CLEAN_BLOB_NAME, cleaned_csv)

    analyze_payload = _build_analyze_payload(cleaned_rows, source_blob_name)
    _cache_analyze_payload(analyze_payload)

    duration_ms = int((time.time() - started) * 1000)
    return {
        "ok": True,
        "sourceBlob": source_blob_name,
        "cleanedBlob": CLEAN_BLOB_NAME,
        "cleanedRows": len(cleaned_rows),
        "cacheKey": ANALYZE_CACHE_KEY,
        "durationMs": duration_ms,
    }


def _get_user_by_email(email: str) -> dict[str, Any] | None:
    table = _users_table_client()
    key = email.strip().lower()
    try:
        entity = table.get_entity(partition_key="USER", row_key=key)
        return dict(entity)
    except Exception:
        return None


def _upsert_user(email: str, name: str, provider: str, password_hash: str = "", oauth_id: str = "") -> dict[str, Any]:
    table = _users_table_client()
    email_norm = email.strip().lower()
    user_id = oauth_id or email_norm
    entity = {
        "PartitionKey": "USER",
        "RowKey": email_norm,
        "email": email_norm,
        "name": name.strip() or email_norm,
        "provider": provider,
        "passwordHash": password_hash,
        "oauthId": oauth_id,
        "createdAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "userId": user_id,
    }
    table.upsert_entity(entity=entity, mode="Merge")
    return entity


@app.blob_trigger(
    arg_name="inputblob",
    path="%DIET_SOURCE_CONTAINER%/%DIET_SOURCE_BLOB_NAME%",
    connection="AzureWebJobsStorage",
)
def preprocess_diet_blob(inputblob: func.InputStream) -> None:
    logging.info(
        "Blob trigger fired for %s (size=%s bytes)",
        inputblob.name,
        inputblob.length,
    )

    started = time.time()
    raw_csv = inputblob.read()
    cleaned_rows = _clean_rows_from_source(raw_csv)

    cleaned_csv = _cleaned_rows_to_csv(cleaned_rows)
    _write_blob_text(CLEAN_CONTAINER, CLEAN_BLOB_NAME, cleaned_csv)

    analyze_payload = _build_analyze_payload(cleaned_rows, inputblob.name)
    _cache_analyze_payload(analyze_payload)

    duration_ms = int((time.time() - started) * 1000)
    logging.info(
        "Preprocessing completed. cleaned_rows=%s, cleaned_blob=%s, cache_key=%s, duration_ms=%s",
        len(cleaned_rows),
        CLEAN_BLOB_NAME,
        ANALYZE_CACHE_KEY,
        duration_ms,
    )


@app.route(route="preprocess", methods=["GET", "POST", "HEAD", "OPTIONS"])
def preprocess(req: func.HttpRequest) -> func.HttpResponse:
    short_circuit = _options_or_head(req)
    if short_circuit:
        return short_circuit

    _, auth_required_error = _require_user(req)
    if auth_required_error:
        return auth_required_error

    auth_error = _require_api_secret(req)
    if auth_error:
        return auth_error

    source_blob_name = _normalize_text(req.params.get("blob")) or SOURCE_BLOB_NAME
    try:
        result = _run_preprocess(source_blob_name)
        logging.info(
            "Manual preprocess completed. source_blob=%s cleaned_blob=%s cleaned_rows=%s duration_ms=%s",
            result["sourceBlob"],
            result["cleanedBlob"],
            result["cleanedRows"],
            result["durationMs"],
        )
        return _json_response(req, result)
    except Exception as exc:
        logging.exception("Manual preprocess failed: %s", exc)
        return _json_response(req, {"error": "Manual preprocess failed."}, status_code=500)


@app.route(route="auth/register", methods=["POST", "OPTIONS"])
def auth_register(req: func.HttpRequest) -> func.HttpResponse:
    short_circuit = _options_or_head(req)
    if short_circuit:
        return short_circuit
    try:
        body = req.get_json()
    except ValueError:
        return _json_response(req, {"error": "Invalid JSON body."}, status_code=400)

    name = _normalize_text(body.get("name"))
    email = _normalize_text(body.get("email")).lower()
    password = _normalize_text(body.get("password"))
    if not email or "@" not in email:
        return _json_response(req, {"error": "Valid email is required."}, status_code=400)
    if len(password) < 8:
        return _json_response(req, {"error": "Password must be at least 8 characters."}, status_code=400)
    if _get_user_by_email(email):
        return _json_response(req, {"error": "Email already exists."}, status_code=409)

    user = _upsert_user(email=email, name=name or email.split("@")[0], provider="local", password_hash=_password_hash(password))
    token = _jwt_issue(user)
    return _json_response(req, {"token": token, "user": {"email": user["email"], "name": user["name"], "provider": user["provider"]}})


@app.route(route="auth/login", methods=["POST", "OPTIONS"])
def auth_login(req: func.HttpRequest) -> func.HttpResponse:
    short_circuit = _options_or_head(req)
    if short_circuit:
        return short_circuit
    try:
        body = req.get_json()
    except ValueError:
        return _json_response(req, {"error": "Invalid JSON body."}, status_code=400)

    email = _normalize_text(body.get("email")).lower()
    password = _normalize_text(body.get("password"))
    user = _get_user_by_email(email)
    if not user:
        return _json_response(req, {"error": "Invalid credentials."}, status_code=401)
    if user.get("provider") != "local":
        return _json_response(req, {"error": "Use social login for this account."}, status_code=400)
    if not _password_verify(password, user.get("passwordHash", "")):
        return _json_response(req, {"error": "Invalid credentials."}, status_code=401)

    token = _jwt_issue(user)
    return _json_response(req, {"token": token, "user": {"email": user["email"], "name": user["name"], "provider": user["provider"]}})


@app.route(route="auth/me", methods=["GET", "OPTIONS"])
def auth_me(req: func.HttpRequest) -> func.HttpResponse:
    short_circuit = _options_or_head(req)
    if short_circuit:
        return short_circuit
    claims, error = _require_user(req)
    if error:
        return error
    return _json_response(req, {"user": {"email": claims.get("email"), "name": claims.get("name"), "provider": claims.get("provider")}})


@app.route(route="auth/github/start", methods=["GET", "OPTIONS"])
def auth_github_start(req: func.HttpRequest) -> func.HttpResponse:
    short_circuit = _options_or_head(req)
    if short_circuit:
        return short_circuit
    if not _auth_provider_enabled():
        return _json_response(req, {"error": "GitHub OAuth is not configured."}, status_code=503)
    return_to = _normalize_text(req.params.get("returnTo")) or req.headers.get("Origin") or ""
    state_raw = json.dumps({"nonce": secrets.token_urlsafe(12), "returnTo": return_to})
    state = _state_sign(state_raw)
    params = urllib.parse.urlencode(
        {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": GITHUB_REDIRECT_URI,
            "scope": "read:user user:email",
            "state": state,
        }
    )
    return _json_response(req, {"url": f"https://github.com/login/oauth/authorize?{params}"})


@app.route(route="auth/github/callback", methods=["GET"])
def auth_github_callback(req: func.HttpRequest) -> func.HttpResponse:
    code = _normalize_text(req.params.get("code"))
    state = _normalize_text(req.params.get("state"))
    state_raw = _state_verify(state)
    if not code or not state_raw:
        return func.HttpResponse("OAuth callback missing required parameters.", status_code=400)
    try:
        state_obj = json.loads(state_raw)
    except json.JSONDecodeError:
        return func.HttpResponse("OAuth state is invalid.", status_code=400)
    return_to = _normalize_text(state_obj.get("returnTo"))
    if not return_to:
        return_to = "https://lively-ocean-0a4dc570f.6.azurestaticapps.net"

    token_req = urllib.request.Request(
        "https://github.com/login/oauth/access_token",
        data=urllib.parse.urlencode(
            {
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GITHUB_REDIRECT_URI,
            }
        ).encode("utf-8"),
        headers={"Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(token_req, timeout=15) as resp:
        token_data = json.loads(resp.read().decode("utf-8"))
    access_token = _normalize_text(token_data.get("access_token"))
    if not access_token:
        return func.HttpResponse("GitHub token exchange failed.", status_code=400)

    user_req = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}", "User-Agent": "diet-dashboard"},
        method="GET",
    )
    with urllib.request.urlopen(user_req, timeout=15) as resp:
        gh_user = json.loads(resp.read().decode("utf-8"))
    email = _normalize_text(gh_user.get("email"))
    if not email:
        email_req = urllib.request.Request(
            "https://api.github.com/user/emails",
            headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}", "User-Agent": "diet-dashboard"},
            method="GET",
        )
        with urllib.request.urlopen(email_req, timeout=15) as resp:
            emails = json.loads(resp.read().decode("utf-8"))
        primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
        if not primary:
            primary = next((e for e in emails if e.get("verified")), None)
        email = _normalize_text((primary or {}).get("email"))
    if not email:
        return func.HttpResponse("GitHub account email is not available.", status_code=400)

    name = _normalize_text(gh_user.get("name") or gh_user.get("login") or email.split("@")[0])
    user = _upsert_user(email=email, name=name, provider="github", oauth_id=str(gh_user.get("id") or email))
    token = _jwt_issue(user)
    dest = f"{return_to}{'&' if '?' in return_to else '?'}token={urllib.parse.quote(token)}&name={urllib.parse.quote(user['name'])}"
    return func.HttpResponse(status_code=302, headers={"Location": dest})


@app.route(route="analyze", methods=["GET", "HEAD", "OPTIONS"])
def analyze(req: func.HttpRequest) -> func.HttpResponse:
    short_circuit = _options_or_head(req)
    if short_circuit:
        return short_circuit

    _, auth_required_error = _require_user(req)
    if auth_required_error:
        return auth_required_error

    auth_error = _require_api_secret(req)
    if auth_error:
        return auth_error

    started = time.time()

    try:
        client = get_redis_client()
        cached = client.get(ANALYZE_CACHE_KEY)
        if not cached:
            return _json_response(
                req,
                {
                    "error": "Analyze cache is empty. Upload or re-upload All_Diets.csv to trigger preprocessing."
                },
                status_code=503,
            )

        payload = json.loads(cached)
        payload["executionTimeMs"] = int((time.time() - started) * 1000)
        payload["source"] = "redis"
        return _json_response(req, payload)

    except Exception as exc:
        logging.exception("Failed to read analyze payload from Redis: %s", exc)
        return _json_response(req, {"error": "Failed to read cached analysis."}, status_code=500)


@app.route(route="recipes", methods=["GET", "HEAD", "OPTIONS"])
def recipes(req: func.HttpRequest) -> func.HttpResponse:
    short_circuit = _options_or_head(req)
    if short_circuit:
        return short_circuit

    _, auth_required_error = _require_user(req)
    if auth_required_error:
        return auth_required_error

    auth_error = _require_api_secret(req)
    if auth_error:
        return auth_error

    try:
        page = max(1, int(req.params.get("page", "1")))
        page_size = min(100, max(1, int(req.params.get("pageSize", "10"))))
    except ValueError:
        return _json_response(req, {"error": "page and pageSize must be integers."}, status_code=400)

    diet = _clean_diet(req.params.get("diet"))
    keyword = _normalize_text(req.params.get("q")).lower()

    try:
        rows = _read_cleaned_rows()
    except Exception as exc:
        logging.exception("Failed to read cleaned CSV: %s", exc)
        return _json_response(
            req,
            {"error": "Cleaned dataset is unavailable. Trigger preprocessing first."},
            status_code=503,
        )

    filtered = rows

    if diet:
        filtered = [row for row in filtered if row["diet_type"] == diet]

    if keyword:
        filtered = [row for row in filtered if keyword in row["keyword_text"]]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]

    total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 0

    response = {
        "items": [
            {
                "recipeId": row["recipe_id"],
                "recipeName": row["recipe_name"],
                "dietType": row["diet_type"],
                "proteinG": row["protein_g"],
                "carbsG": row["carbs_g"],
                "fatG": row["fat_g"],
                "calories": row["calories"],
            }
            for row in page_items
        ],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
        "filters": {
            "diet": diet or None,
            "q": keyword or None,
        },
        "source": "cleaned_blob",
    }

    return _json_response(req, response)