#!/bin/bash

set -euo pipefail

export DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-config.settings}
export BACKUP_CRON_ENABLE_CORE=${BACKUP_CRON_ENABLE_CORE:-true}
export BACKUP_CRON_ENABLE_FULL=${BACKUP_CRON_ENABLE_FULL:-true}
export BACKUP_CORE_CRON=${BACKUP_CORE_CRON:-"0 3 * * *"}
export BACKUP_FULL_CRON=${BACKUP_FULL_CRON:-"0 4 * * *"}

export -p > /tmp/medsim-backup-env.sh
chmod 0600 /tmp/medsim-backup-env.sh

{
  echo "SHELL=/bin/bash"
  echo "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  if [ "${BACKUP_CRON_ENABLE_CORE}" = "true" ]; then
    echo "${BACKUP_CORE_CRON} . /tmp/medsim-backup-env.sh; cd /app/SimWorks && python manage.py backup_database --mode core --upload r2 --encrypt --verify-upload >> /proc/1/fd/1 2>> /proc/1/fd/2"
  fi
  if [ "${BACKUP_CRON_ENABLE_FULL}" = "true" ]; then
    echo "${BACKUP_FULL_CRON} . /tmp/medsim-backup-env.sh; cd /app/SimWorks && python manage.py backup_database --mode full --upload r2 --encrypt --verify-upload >> /proc/1/fd/1 2>> /proc/1/fd/2"
  fi
} > /tmp/medsim-backup-crontab

crontab /tmp/medsim-backup-crontab
echo "Starting MedSim backup cron..."
exec cron -f
