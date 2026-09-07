#!/usr/bin/env bash
# Fail a release if the built image or Python requirements contain known high/critical CVEs.
set -euo pipefail

IMAGE="${1:-nexus-itsm:local-verified}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required to scan ${IMAGE}." >&2
  exit 1
fi

echo "Scanning Python dependencies with pip-audit…"
docker run --rm -v "$(pwd):/src:ro" -w /src python:3.12-slim-bookworm sh -ec \
  'pip install --no-cache-dir pip-audit >/dev/null && pip-audit -r requirements.txt'

echo "Scanning ${IMAGE} with Docker Scout (requires Docker login)…"
docker scout cves --only-severity high,critical --exit-code --only-fixed "$IMAGE"
