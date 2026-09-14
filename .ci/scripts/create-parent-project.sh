#!/usr/bin/env bash
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
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  create-parent-project.sh

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
EOF
}

log() { printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Splits curl's `-w '\n%{http_code}'` output into the globals `status` and `body`.
# Parameter expansion rather than `head -n-1`, which is a GNU coreutils extension.
split_response() {
  local response="$1"
  status="${response##*$'\n'}"
  body="${response%$'\n'*}"
}

api() {
  curl -sS -H "X-Api-Key: ${DEPENDENCY_TRACK_API_KEY}" -w '\n%{http_code}' "$@"
}

main() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
  fi

  : "${DEPENDENCY_TRACK_HOST:?Set DEPENDENCY_TRACK_HOST (e.g. https://dtrack.example.com)}"
  : "${DEPENDENCY_TRACK_API_KEY:?Set DEPENDENCY_TRACK_API_KEY}"
  : "${PROJECT_NAME:?Set PROJECT_NAME}"
  : "${PROJECT_VERSION:?Set PROJECT_VERSION}"

  local status body payload uuid

  log "Ensuring collection project '${PROJECT_NAME}' @ '${PROJECT_VERSION}' exists"

  # Built with jq rather than string interpolation so a name containing quotes, slashes or
  # backslashes cannot break out of the JSON.
  # `classifier` is deliberately omitted: Dependency-Track nulls it whenever collectionLogic is
  # set, so passing one would be misleading.
  payload=$(jq -n \
    --arg name "${PROJECT_NAME}" \
    --arg version "${PROJECT_VERSION}" \
    --arg tags "${PROJECT_TAGS:-}" \
    '($tags | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0)) | unique) as $tagList
     | {
         name:            $name,
         version:         $version,
         isLatest:        true,
         collectionLogic: "AGGREGATE_DIRECT_CHILDREN"
       }
     + (if ($tagList | length) > 0 then { tags: ($tagList | map({ name: . })) } else {} end)')

  split_response "$(api -X PUT "${DEPENDENCY_TRACK_HOST}/api/v1/project" \
    -H 'Content-Type: application/json' -d "${payload}")"

  case "${status}" in
    201)
      log "Created collection project."
      uuid=$(jq -r '.uuid' <<<"${body}")
      ;;
    409)
      # Already exists: a re-run, or the sibling workflow racing us.
      log "Collection project already exists, looking it up."
      split_response "$(api -G "${DEPENDENCY_TRACK_HOST}/api/v1/project/lookup" \
        --data-urlencode "name=${PROJECT_NAME}" \
        --data-urlencode "version=${PROJECT_VERSION}")"
      [[ "${status}" == "200" ]] \
        || die "Lookup of '${PROJECT_NAME}' @ '${PROJECT_VERSION}' returned HTTP ${status}: ${body}"
      uuid=$(jq -r '.uuid' <<<"${body}")
      ;;
    *)
      printf '%s\n' "${body}" >&2
      die "Unexpected HTTP ${status} creating collection project"
      ;;
  esac

  [[ -n "${uuid}" && "${uuid}" != "null" ]] \
    || die "Could not determine the UUID of '${PROJECT_NAME}' @ '${PROJECT_VERSION}'"

  log "Project UUID:    ${uuid}"
  log "Project name:    ${PROJECT_NAME}"
  log "Project version: ${PROJECT_VERSION}"

  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "uuid=${uuid}" >>"${GITHUB_OUTPUT}"
  fi
}

main "$@"
