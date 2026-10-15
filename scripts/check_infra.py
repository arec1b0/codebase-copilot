"""Check readiness and persistence of the dedicated local development stack."""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "--project-directory",
    str(ROOT),
    "--env-file",
    str(ROOT / ".env"),
    "-f",
    str(ROOT / "deploy" / "compose.yaml"),
]


def load_environment() -> dict[str, str]:
    values = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in values:
            raise ValueError(".env must contain unique KEY=value lines.")
        values[key] = os.environ.get(key, value)
    for key in ("POSTGRES_PASSWORD", "QDRANT_API_KEY"):
        if not re.fullmatch(r"[a-f0-9]{64}", values.get(key, "")):
            raise ValueError(f"{key} must contain 64 lowercase hexadecimal characters.")
    for key in ("POSTGRES_PORT", "QDRANT_PORT", "PHOENIX_PORT", "PHOENIX_GRPC_PORT"):
        port = values.get(key, "")
        if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError(f"{key} must be a valid TCP port.")
    return values


def compose(*arguments: str, timeout: int = 30) -> str:
    completed = subprocess.run(
        [*COMPOSE, *arguments], capture_output=True, text=True, timeout=timeout, check=False
    )
    if completed.returncode:
        raise RuntimeError("Docker Compose operation failed; inspect stack status and logs.")
    return completed.stdout.strip()


def sql(statement: str, database: str = "copilot") -> str:
    return compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "--username=copilot",
        f"--dbname={database}",
        "--no-psqlrc",
        "--set=ON_ERROR_STOP=1",
        "--tuples-only",
        "--no-align",
        "--command",
        statement,
        timeout=10,
    )


def http(
    url: str,
    *,
    method: str = "GET",
    key: str | None = None,
    payload: dict[str, object] | None = None,
) -> bytes:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["api-key"] = key
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read()
        if not isinstance(body, bytes):
            raise RuntimeError("HTTP response did not contain bytes.")
        return body


def qdrant_result(body: bytes) -> dict[str, object]:
    parsed = json.loads(body)
    if not isinstance(parsed, dict) or parsed.get("status") != "ok":
        raise RuntimeError("Qdrant did not return a successful result.")
    result = parsed.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Qdrant result must be an object.")
    return cast(dict[str, object], result)


def wait_until_ready(qdrant: str, phoenix: str, key: str, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if sql("SELECT 1;") != "1":
                raise RuntimeError("PostgreSQL query failed.")
            http(f"{qdrant}/readyz")
            qdrant_result(http(f"{qdrant}/collections", key=key))
            http(f"{phoenix}/readyz")
            tables = sql(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';",
                database="phoenix",
            )
            if int(tables) < 1:
                raise RuntimeError("Phoenix database migrations are not ready.")
            return
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Stack readiness timed out; inspect stack status and logs."
                ) from None
            time.sleep(1)


def main() -> None:
    environment = load_environment()
    qdrant = f"http://127.0.0.1:{environment['QDRANT_PORT']}"
    phoenix = f"http://127.0.0.1:{environment['PHOENIX_PORT']}"
    key = environment["QDRANT_API_KEY"]
    wait_until_ready(qdrant, phoenix, key)
    print("PostgreSQL, Qdrant, and Phoenix readiness passed.")

    try:
        http(f"{qdrant}/collections")
    except urllib.error.HTTPError as error:
        if error.code not in (401, 403):
            raise RuntimeError("Unexpected unauthenticated Qdrant response.") from None
    else:
        raise RuntimeError("Qdrant accepted a request without its API key.")

    marker = uuid.uuid4().hex
    collection = f"infra_probe_{marker}"
    collection_url = f"{qdrant}/collections/{collection}"
    collection_created = False
    row_created = False
    try:
        sql(
            "CREATE SCHEMA IF NOT EXISTS infra_acceptance; "
            "CREATE TABLE IF NOT EXISTS infra_acceptance.probes "
            "(id text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now()); "
            f"INSERT INTO infra_acceptance.probes (id) VALUES ('{marker}');"
        )
        row_created = True
        http(
            collection_url,
            method="PUT",
            key=key,
            payload={"vectors": {"size": 2, "distance": "Cosine"}},
        )
        collection_created = True
        http(
            f"{collection_url}/points?wait=true",
            method="PUT",
            key=key,
            payload={"points": [{"id": 1, "vector": [1.0, 0.0], "payload": {"id": marker}}]},
        )
        print("Probe data written. Restarting the three infrastructure services.")
        compose("restart", "phoenix", "qdrant", "postgres", timeout=120)
        wait_until_ready(qdrant, phoenix, key)
        if sql(f"SELECT id FROM infra_acceptance.probes WHERE id='{marker}';") != marker:
            raise RuntimeError("PostgreSQL did not preserve the probe row after restart.")
        point = qdrant_result(http(f"{collection_url}/points/1", key=key))
        payload = point.get("payload")
        if not isinstance(payload, dict) or payload.get("id") != marker:
            raise RuntimeError("Qdrant did not preserve the probe point after restart.")
        print("Restart persistence passed for PostgreSQL and Qdrant.")
    finally:
        if collection_created:
            http(collection_url, method="DELETE", key=key)
        if row_created:
            sql(f"DELETE FROM infra_acceptance.probes WHERE id='{marker}';")

    print("STEP 2 ACCEPTANCE PASSED")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Infrastructure check failed: {error}", file=sys.stderr)
        sys.exit(1)
