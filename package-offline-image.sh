#!/usr/bin/env bash
# ==============================================================================
# Build & Export Genwizard ITSM Docker Image for Air-Gapped / Offline Environments
# ==============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAG="nexus-itsm-core:latest"
OUTPUT_FILE="$APP_DIR/nexus-itsm-core-image.tar.gz"

echo "==> Building Docker image: ${IMAGE_TAG}..."
docker build -t "${IMAGE_TAG}" -f "$APP_DIR/Dockerfile" "$APP_DIR"

echo "==> Exporting pre-built image to ${OUTPUT_FILE}..."
docker save "${IMAGE_TAG}" | gzip > "${OUTPUT_FILE}"

echo "================================================================================"
echo "✓ Pre-built image saved to: ${OUTPUT_FILE}"
echo "✓ Size: $(du -sh "${OUTPUT_FILE}" | cut -f1)"
echo "You can copy this file to your destination server alongside nexus-itsm-addon.tar.gz"
echo "install-existing-app.sh will automatically detect and load it without building!"
echo "================================================================================"
