#!/usr/bin/env python3
# shamelessly LLM generated ;)
# Creates, or locates, the Dependency-Track "collection" project for one release:
#
#   <repo> @ <version>                          collection, AGGREGATE_DIRECT_CHILDREN
#   ├── <repo> - linux-amd64 image @ <version>    (uploaded by docker.yml)
#   ├── <repo> - linux-arm64 image @ <version>    (uploaded by docker.yml)
#   └── <repo> - source @ <version>               (uploaded by sbom.yml)
#
# Collection projects hold no components of their own; they derive their metrics from their
# children. AGGREGATE_DIRECT_CHILDREN rolls up every direct child findings.
#
# PUT /api/v1/project returns 201 on create and 409 when the project already
# exists, in which case it is looked up instead.
# Safe to re-run, and safe to run concurrently another workflow.
#
# Writes `uuid` to $GITHUB_OUTPUT under GitHub Actions, and always logs it.
#
# Stdlib only; no third-party dependencies.
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

USAGE = """\
Usage:
  create-parent-project.py

Required env:
  DEPENDENCY_TRACK_HOST     Dependency-Track base URL, including scheme
                            (e.g. https://dtrack.example.com)
  DEPENDENCY_TRACK_API_KEY  API key with VIEW_PORTFOLIO and PORTFOLIO_MANAGEMENT_CREATE
  PROJECT_NAME              Collection project name (e.g. element-hq/sygnal)
  PROJECT_VERSION           Release version (e.g. v1.0.0, latest, develop)

Optional env:
  PROJECT_TAGS              Comma-separated tags for the collection project itself
                            (e.g. element-hq/sygnal,element-hq). Blank entries are dropped
                            and duplicates collapsed.
"""


def log(message: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{now}] {message}")


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def require_env(name: str, hint: str) -> str:
    value = os.environ.get(name)
    if not value:
        die(f"Set {name} ({hint})")
    return value


def parse_tags(raw: str) -> list[dict[str, str]]:
    """Split a comma-separated list, stripping whitespace, dropping blank
    entries and collapsing duplicates (matches the previous jq `unique`)."""
    tags = sorted({tag.strip() for tag in raw.split(",") if tag.strip()})
    return [{"name": tag} for tag in tags]


# Identifies this script to the Dependency-Track API, e.g. for server-side logs.
# GITHUB_SHA is set under GitHub Actions to the commit being built; falls back to
# "unknown" so local/manual runs still send a well-formed header.
def user_agent() -> str:
    return f"sygnal-ci/{os.environ.get('GITHUB_SHA', 'unknown')} (+https://github.com/element-hq/sygnal)"


def request(
    method: str,
    host: str,
    path: str,
    api_key: str,
    *,
    params: dict[str, str] | None = None,
    payload: bytes | None = None,
) -> tuple[int, bytes]:
    """Returns (status, body). Non-2xx responses are returned, not raised."""
    url = host.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method, data=payload)
    req.add_header("X-Api-Key", api_key)
    req.add_header("User-Agent", user_agent())
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(USAGE, end="")
        return

    host = require_env(
        "DEPENDENCY_TRACK_HOST", "e.g. https://dtrack.example.com"
    )
    api_key = require_env("DEPENDENCY_TRACK_API_KEY", "")
    name = require_env("PROJECT_NAME", "")
    version = require_env("PROJECT_VERSION", "")

    log(f"Ensuring collection project '{name}' @ '{version}' exists")

    # Built with json.dumps rather than string interpolation so a name containing
    # quotes, slashes or backslashes cannot break out of the JSON.
    # `classifier` is deliberately omitted: Dependency-Track nulls it whenever
    # collectionLogic is set, so passing one would be misleading.
    payload: dict[str, object] = {
        "name": name,
        "version": version,
        "isLatest": True,
        # TODO: Enable later. Not available in our current version of DependencyTrack.
        # "collectionLogic": "AGGREGATE_DIRECT_CHILDREN",
    }
    tags = parse_tags(os.environ.get("PROJECT_TAGS", ""))
    if tags:
        payload["tags"] = tags

    status, body = request(
        "PUT", host, "/api/v1/project", api_key,
        payload=json.dumps(payload).encode("utf-8"),
    )

    if status == 201:
        log("Created collection project.")
        uuid = json.loads(body).get("uuid")
    elif status == 409:
        # Already exists: a re-run, or the sibling workflow racing us.
        log("Collection project already exists, looking it up.")
        status, body = request(
            "GET", host, "/api/v1/project/lookup", api_key,
            params={"name": name, "version": version},
        )
        if status != 200:
            die(
                f"Lookup of '{name}' @ '{version}' returned HTTP {status}: "
                f"{body.decode('utf-8', errors='replace')}"
            )
        uuid = json.loads(body).get("uuid")
    else:
        print(body.decode("utf-8", errors="replace"), file=sys.stderr)
        die(f"Unexpected HTTP {status} creating collection project")

    if not uuid:
        die(f"Could not determine the UUID of '{name}' @ '{version}'")

    log(f"Project UUID:    {uuid}")
    log(f"Project name:    {name}")
    log(f"Project version: {version}")

    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as output_file:
            print(f"uuid={uuid}", file=output_file)


if __name__ == "__main__":
    main()
