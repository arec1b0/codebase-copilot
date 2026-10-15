"""Create local credentials once without overwriting existing configuration."""

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    destination = ROOT / ".env"
    content = (
        f"POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
        f"QDRANT_API_KEY={secrets.token_hex(32)}\n"
        "POSTGRES_PORT=15432\n"
        "QDRANT_PORT=6333\n"
        "PHOENIX_PORT=6006\n"
        "PHOENIX_GRPC_PORT=4317\n"
    )
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    except FileExistsError:
        print("Existing .env preserved.")
    else:
        print("Created .env with independent local credentials.")


if __name__ == "__main__":
    main()
