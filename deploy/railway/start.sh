#!/bin/sh
# Container entry point. /app/data is the Railway volume, so the database survives restarts and
# redeploys.
#
# A bundle built with a database (deploy/railway_deploy.py --push-db) carries seed/market.db.gz.part*
# and seed/SEED_ID. The seed is installed when the volume has no database, or when its SEED_ID
# differs from the one recorded at the last install (/app/data/.seed_id) - i.e. once per push.
# A restart, or a later deploy of the same image, finds the same id and leaves the volume alone;
# code-only deploys carry no seed at all.
set -e

DATA_DIR=/app/data
DB="$DATA_DIR/market.db"
mkdir -p "$DATA_DIR"

if [ -f /app/seed/SEED_ID ]; then
    NEW_ID=$(cat /app/seed/SEED_ID)
    OLD_ID=$(cat "$DATA_DIR/.seed_id" 2>/dev/null || true)
    if [ ! -s "$DB" ] || [ "$NEW_ID" != "$OLD_ID" ]; then
        echo "Installing pushed database $NEW_ID (replacing ${OLD_ID:-nothing})"
        cat /app/seed/market.db.gz.part* | gunzip > "$DB.incoming"
        rm -f "$DB-wal" "$DB-shm"
        mv "$DB.incoming" "$DB"
        echo "$NEW_ID" > "$DATA_DIR/.seed_id"
    else
        echo "Pushed database $NEW_ID is already installed"
    fi
elif [ ! -s "$DB" ]; then
    echo "Volume has no database and this deploy carries none - history pages will be empty"
fi

# The daily-jobs trigger (scripts/job_trigger.py), on the private network only. It runs only when
# JOB_TRIGGER_SECRET is set; if it dies, Streamlit carries on and the next cron call fails loudly.
if [ -n "$JOB_TRIGGER_SECRET" ]; then
    python scripts/job_trigger.py &
else
    echo "JOB_TRIGGER_SECRET is not set - the daily-jobs trigger is off"
fi

exec streamlit run pulse_dashboard.py \
    --server.port "${PORT:-8501}" \
    --server.address 0.0.0.0
