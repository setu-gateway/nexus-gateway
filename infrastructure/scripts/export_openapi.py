#!/usr/bin/env python
"""Exports the gateway's live FastAPI OpenAPI schema to a JSON file.

Schema generation is derived purely from route/Pydantic definitions, so this needs
no database or Redis connection - safe to run in CI or locally.
"""

import json
import sys
from pathlib import Path

from apps.gateway.main import app


def main() -> None:
    output_path = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    schema = app.openapi()
    output_path.write_text(json.dumps(schema, indent=2))
    print(f"Wrote OpenAPI schema ({len(schema.get('paths', {}))} paths) to {output_path}")


if __name__ == "__main__":
    main()
