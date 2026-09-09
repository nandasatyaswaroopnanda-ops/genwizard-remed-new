#!/usr/bin/env bash
# ==============================================================================
# Genwizard ITSM — Package Minimal Add-On for Existing Application Stack
# ==============================================================================
# Packages ONLY the runtime files required to install and run nexus-itsm-core
# alongside an existing enterprise stack. Excludes tests, docs, dev files, etc.
# ==============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${APP_DIR}"

OUTPUT_TAR="nexus-itsm-addon.tar.gz"
OUTPUT_ATR="nexus-itsm-addon.atr.gz"

echo "==> Creating clean, minimal runtime package for server deployment..."

# Make sure scripts are executable
chmod +x install-existing-app.sh scripts/bootstrap_external_im.py

# Create a temporary staging directory to guarantee zero unnecessary files
STAGE_DIR=$(mktemp -d /tmp/nexus-itsm-stage.XXXXXX)
trap 'rm -rf "${STAGE_DIR}"' EXIT

# Copy ONLY runtime components
cp -r backend "${STAGE_DIR}/"
cp -r frontend "${STAGE_DIR}/"
cp -r identity_service "${STAGE_DIR}/"
cp -r scripts "${STAGE_DIR}/"
cp Dockerfile "${STAGE_DIR}/"
cp requirements.txt "${STAGE_DIR}/"
cp docker-compose.existing-app-addon.yml "${STAGE_DIR}/"
cp install-existing-app.sh "${STAGE_DIR}/"
cp README.md "${STAGE_DIR}/" 2>/dev/null || true
cp .dockerignore "${STAGE_DIR}/" 2>/dev/null || true

# Clean any python bytecode, DS_Store, or non-runtime files inside the stage
find "${STAGE_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${STAGE_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true
find "${STAGE_DIR}" -type f -name ".DS_Store" -delete 2>/dev/null || true
rm -f "${STAGE_DIR}/identity_service/Dockerfile" 2>/dev/null || true
rm -f "${STAGE_DIR}/scripts/security-scan.sh" 2>/dev/null || true
rm -rf "${STAGE_DIR}/frontend/static" 2>/dev/null || true

# Archive strictly the staged files
tar -czf "${APP_DIR}/${OUTPUT_TAR}" -C "${STAGE_DIR}" .
cp "${APP_DIR}/${OUTPUT_TAR}" "${APP_DIR}/${OUTPUT_ATR}"

echo "================================================================================"
echo "✓ Successfully created clean deployment packages:"
echo "  - ${OUTPUT_TAR} ($(du -sh "${OUTPUT_TAR}" | cut -f1))"
echo "  - ${OUTPUT_ATR} ($(du -sh "${OUTPUT_ATR}" | cut -f1))"
echo ""
echo "Contents included (runtime only):"
tar -ztvf "${OUTPUT_TAR}" | awk '{print "  " $6}' | sort | head -25
echo "  ... (only backend, frontend, identity_service, scripts, Dockerfile, compose)"
echo ""
echo "Excluded: tests/, docs/, dev compose, cache, .env, and temp files."
echo "================================================================================"
