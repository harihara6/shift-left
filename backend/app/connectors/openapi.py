"""Reading an OpenAPI (or Swagger 2) document into the few facts Feature Kickoff checks.

Deterministic on purpose: an operation exists if the spec lists it, and is deprecated if the spec
says so. Nothing here asks a model what an API probably does.
"""

import json
from dataclasses import dataclass, field

import yaml

METHODS = ("get", "put", "post", "delete", "patch", "options", "head", "trace")


class SpecUnreadable(ValueError):
    """The document isn't OpenAPI we can read. Reported as not checked, never as a pass."""


@dataclass
class Spec:
    title: str = ""
    version: str = ""
    operations: list[str] = field(default_factory=list)
    deprecated: list[str] = field(default_factory=list)
    security: list[str] = field(default_factory=list)
    servers: list[str] = field(default_factory=list)


def parse(text: str) -> Spec:
    try:
        doc = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecUnreadable(f"Not valid JSON or YAML: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("paths"), dict):
        raise SpecUnreadable("No `paths` object, so this isn't an OpenAPI document")

    spec = Spec()
    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    spec.title, spec.version = str(info.get("title", "")), str(info.get("version", ""))
    for path, item in doc["paths"].items():
        if not isinstance(item, dict):
            continue
        for method in METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            name = f"{method.upper()} {path}"
            spec.operations.append(name)
            if operation.get("deprecated") is True:
                spec.deprecated.append(name)

    # OpenAPI 3 keeps schemes under components; Swagger 2 at the top level.
    schemes = (doc.get("components") or {}).get("securitySchemes") or doc.get("securityDefinitions") or {}
    for name, scheme in schemes.items() if isinstance(schemes, dict) else []:
        if isinstance(scheme, dict):
            kind = scheme.get("type", "")
            detail = scheme.get("scheme") or ", ".join(sorted((scheme.get("flows") or {}).keys()))
            spec.security.append(f"{name}: {kind}{f' ({detail})' if detail else ''}")
    spec.servers = [s["url"] for s in doc.get("servers") or [] if isinstance(s, dict) and s.get("url")]
    if not spec.servers and doc.get("host"):
        spec.servers = [f"{(doc.get('schemes') or ['https'])[0]}://{doc['host']}{doc.get('basePath', '')}"]
    return spec
