#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup-directory>" >&2
  exit 64
fi

BACKUP_PATH="$1"
PROJECT_NAME="${PROJECT_NAME:-video-social-bot}"
DATA_VOLUME="${DATA_VOLUME:-${PROJECT_NAME}_app-data}"
STORAGE_VOLUME="${STORAGE_VOLUME:-${PROJECT_NAME}_app-storage}"

if [[ ! -f "${BACKUP_PATH}/app-data.tgz" || ! -f "${BACKUP_PATH}/app-storage.tgz" ]]; then
  echo "Backup directory must contain app-data.tgz and app-storage.tgz" >&2
  exit 66
fi

echo "Restoring into ${DATA_VOLUME} and ${STORAGE_VOLUME}."
echo "Stop the app first with: docker compose down"
read -r -p "Continue? Type 'yes' to restore: " confirmation
if [[ "${confirmation}" != "yes" ]]; then
  echo "Restore cancelled."
  exit 0
fi

docker run --rm \
  -v "${DATA_VOLUME}:/data" \
  -v "${BACKUP_PATH}:/backup:ro" \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/app-data.tgz -C /data"

docker run --rm \
  -v "${STORAGE_VOLUME}:/storage" \
  -v "${BACKUP_PATH}:/backup:ro" \
  alpine sh -c "rm -rf /storage/* && tar xzf /backup/app-storage.tgz -C /storage"

echo "Restore complete. Start the app with: docker compose up -d"
