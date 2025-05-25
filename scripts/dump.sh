APP_NAME="casspea-v2"      # Your Heroku app name
DUMP_FILE="heroku_db_dump.dump"  # Local filename for the dump

echo "Capturing a new backup for app '$APP_NAME'..."
heroku pg:backups:capture --app "$APP_NAME"

echo "Downloading the latest backup..."
heroku pg:backups:download --app "$APP_NAME"

# The downloaded file is typically named 'latest.dump'. Rename it:
mv latest.dump "$DUMP_FILE"

echo "Database dump saved as '$DUMP_FILE'."