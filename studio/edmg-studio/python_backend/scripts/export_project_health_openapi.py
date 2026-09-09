from __future__ import annotations

import json
import re
from typing import Any

from edmg_studio_backend.app import app


ROUTE = "/v1/projects/{project_id}/health"
REFERENCE = re.compile(r"^#/components/schemas/([^/]+)$")


def referenced_schemas(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and (match := REFERENCE.match(reference)):
            names.add(match.group(1))
        for child in value.values():
            names.update(referenced_schemas(child))
    elif isinstance(value, list):
        for child in value:
            names.update(referenced_schemas(child))
    return names


def project_health_openapi() -> dict[str, Any]:
    source = app.openapi()
    operation = source["paths"][ROUTE]
    all_schemas = source.get("components", {}).get("schemas", {})
    pending = list(referenced_schemas(operation))
    selected: dict[str, Any] = {}
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        schema = all_schemas[name]
        selected[name] = schema
        pending.extend(referenced_schemas(schema) - selected.keys())
    return {
        "openapi": source["openapi"],
        "info": source["info"],
        "paths": {ROUTE: operation},
        "components": {"schemas": dict(sorted(selected.items()))},
    }


if __name__ == "__main__":
    print(json.dumps(project_health_openapi(), sort_keys=True))
