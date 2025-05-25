#!/bin/bash
# Script to restore a local PostgreSQL database in the Docker Compose 'db' container
# using the dump file produced by the Heroku pg:backups process.
# This version stops the 'web' container to avoid connection conflicts during the restore.
#
# Requirements:
#   - docker-compose must be running (e.g. use `docker-compose up -d`)
#   - The dump file (heroku_db_dump.dump) must exist in the project root.

DUMP_FILE="heroku_db_dump.dump"

if [ ! -f "$DUMP_FILE" ]; then
    echo "Error: Dump file '$DUMP_FILE' not found. Please run the dump script first."
    exit 1
fi

echo "Stopping the web container to avoid connection conflicts..."
docker compose stop web

echo "Restoring database from '$DUMP_FILE' into the local PostgreSQL container..."
# Use pg_restore (from the official postgres image) to load the dump.
cat "$DUMP_FILE" | docker compose exec -T db pg_restore -U postgres_user -d postgres_db --clean --no-owner

echo "Starting the web container..."
docker compose start web

echo "Database restore completed."