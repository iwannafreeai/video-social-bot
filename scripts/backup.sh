#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-video-social-bot}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH="${BACKUP_DIR}/${PROJECT_NAME}-${TIMESTAMP}"
DATA_VOLUME="${DATA_VOLUME:-${PROJECT_NAME}_app-data}"
STORAGE_VOLUME="${STORAGE_VOLUME:-${PROJECT_NAME}_app-storage}"

mkdir -p "${BACKUP_PATH}"

docker run --rm \
  -v "${DATA_VOLUME}:/data:ro" \
  -v "${BACKUP_PATH}:/backup" \
  alpine tar czf /backup/app-data.tgz -C /data .

docker run --rm \
  -v "${STORAGE_VOLUME}:/storage:ro" \
  -v "${BACKUP_PATH}:/backup" \
  alpine tar czf /backup/app-storage.tgz -C /storage .

cat > "${BACKUP_PATH}/manifest.txt" <<EOF
project=${PROJECT_NAME}
created_at=${TIMESTAMP}
data_volume=${DATA_VOLUME}
storage_volume=${STORAGE_VOLUME}
EOF

echo "Backup written to ${BACKUP_PATH}"
