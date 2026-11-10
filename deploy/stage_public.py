"""Build the bundle for the public Railway app: only what the public pages need, nothing personal.

    python deploy/stage_public.py <out_dir>            # code only (every deploy after the first)
    python deploy/stage_public.py <out_dir> --seed     # + a cleaned database for the first boot

Then deploy from <out_dir> (``railway up`` there), never from the repo root.

What goes in is an allowlist (COPY_DIRS / COPY_FILES minus EXCLUDE), so a new personal file in the
repo stays out by default. Left out on purpose:

  - .env, every Groww/Dhan report (.xlsx), the generated insight pages (data/*.html), context.md,
    docs/, scripts/, strategies/ and tests/
  - the personal pages and their code: the Dhan trade journal (apps/dhan_journal_dashboard.py,
    market/dhan_journal.py), the Dhan API explorer, order placement (market/dhan_orders.py) and the
    old Groww portfolio apps (apps/app.py, apps/fno_dashboard.py)

``--seed`` copies data/market.db (read-only; the original is not touched), then drops the Dhan
journal tables (fills, ledger, trip tags), deletes every saved broker session and lock from
runtime_state / state_locks, vacuums so the deleted bytes are really gone, gzips it and splits it
into parts for upload. deploy/railway/start.sh unpacks it into the Railway volume on first boot.

Last, every file in the bundle is scanned for each value in .env. Any hit deletes nothing but
exits with an error, so the bundle must not be deployed.
"""

import argparse
import gzip
import hashlib
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(REPO, "deploy", "railway")

COPY_FILES = ["pulse_dashboard.py", "requirements.txt",
              # The unattended daily jobs and their trigger (deploy/railway/start.sh). Named one by one:
              # scripts/ also holds the personal insight scripts, which must never ship.
              "scripts/daily.py", "scripts/job_trigger.py", "scripts/jobs/__init__.py", "scripts/jobs/common.py",
              "scripts/jobs/dhan_daily.py", "scripts/jobs/groww_intraday.py", "scripts/jobs/dhan_movers.py",
              # The auction recorder (docs/PLAN_PRE_MARKET.md), started through the trigger's /capture.
              "scripts/debug/capture_auctions.py"]
COPY_DIRS = ["apps", "market", "ui", "utils", "groww_api"]
EXCLUDE = {
    "apps/dhan_journal_dashboard.py",
    "apps/dhan_api_explorer.py",
    "apps/app.py",
    "apps/fno_dashboard.py",
    "market/dhan_journal.py",
    "market/dhan_orders.py",
}

PRIVATE_TABLES = ("dhan_fills", "dhan_ledger", "dhan_trip_tags")
#: Local backups that only make the upload bigger: the Kite-adjusted daily history kept when
#: daily_bars switched to Dhan's raw candles (2026-11-08).
LOCAL_ONLY_TABLES = ("daily_bars_kite",)
#: The only runtime_state row that may ship: the clock offset. Everything else is a broker session
#: (live tokens) or the journal's sync marker.
KEEP_STATE = ("clock_offset",)
PART_BYTES = 40 * 1024 * 1024


def copy_code(out: str) -> None:
    for name in COPY_FILES:
        os.makedirs(os.path.dirname(os.path.join(out, name)), exist_ok=True)
        shutil.copy2(os.path.join(REPO, name), os.path.join(out, name))
    for top in COPY_DIRS:
        for root, dirs, files in os.walk(os.path.join(REPO, top)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if not name.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(root, name), REPO).replace(os.sep, "/")
                if rel in EXCLUDE:
                    continue
                dest = os.path.join(out, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(os.path.join(REPO, rel), dest)

    shutil.copy2(os.path.join(DEPLOY, "Dockerfile"), os.path.join(out, "Dockerfile"))
    shutil.copy2(os.path.join(DEPLOY, "railway.json"), os.path.join(out, "railway.json"))
    os.makedirs(os.path.join(out, ".streamlit"), exist_ok=True)
    shutil.copy2(os.path.join(DEPLOY, "streamlit_config.toml"), os.path.join(out, ".streamlit", "config.toml"))
    # A shell script with Windows line endings fails in the Linux container ("not found").
    with open(os.path.join(DEPLOY, "start.sh"), "rb") as f:
        script = f.read().replace(b"\r\n", b"\n")
    with open(os.path.join(out, "start.sh"), "wb") as f:
        f.write(script)


def build_seed(out: str) -> None:
    seed_dir = os.path.join(out, "seed")
    os.makedirs(seed_dir, exist_ok=True)
    db = os.path.join(seed_dir, "market.db")
    src = sqlite3.connect(f"file:{os.path.join(REPO, 'data', 'market.db')}?mode=ro", uri=True)
    dst = sqlite3.connect(db)
    src.backup(dst)
    src.close()
    for table in PRIVATE_TABLES + LOCAL_ONLY_TABLES:
        dst.execute(f'DROP TABLE IF EXISTS "{table}"')
    marks = ",".join("?" * len(KEEP_STATE))
    dst.execute(f"DELETE FROM runtime_state WHERE name NOT IN ({marks})", KEEP_STATE)
    dst.execute("DELETE FROM state_locks")
    dst.commit()
    dst.execute("PRAGMA journal_mode=DELETE")
    dst.execute("VACUUM")
    left = [r[0] for r in dst.execute("SELECT name FROM runtime_state")]
    tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    dst.close()
    assert not set(PRIVATE_TABLES) & set(tables), tables
    assert set(left) <= set(KEEP_STATE), left
    print(f"seed: tables {', '.join(tables)}; runtime_state rows {left}")

    gz = db + ".gz"
    with open(db, "rb") as f, gzip.open(gz, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g, 16 * 1024 * 1024)
    os.remove(db)
    digest = hashlib.sha256()
    with open(gz, "rb") as f:
        part = 0
        while chunk := f.read(PART_BYTES):
            digest.update(chunk)
            with open(f"{gz}.part{part:02d}", "wb") as p:
                p.write(chunk)
            part += 1
    os.remove(gz)
    # Identifies this push; start.sh installs a seed only when its id is new to the volume.
    with open(os.path.join(seed_dir, "SEED_ID"), "w", newline="\n") as f:
        f.write(f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{digest.hexdigest()[:12]}\n")
    print(f"seed: {part} parts of at most {PART_BYTES // 2**20} MB")


def env_secrets() -> dict:
    """Every value in .env long enough to be a secret, by name."""
    found = {}
    path = os.path.join(REPO, ".env")
    if not os.path.exists(path):
        return found
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if len(value) >= 6:
                found[key.strip()] = value.encode()
    return found


def scan(out: str) -> list:
    """(file, env var name) for every .env value found in the bundle. Seed parts are scanned joined."""
    secrets = env_secrets()
    hits = []
    seed_blob = b""
    for root, _, files in os.walk(out):
        for name in files:
            path = os.path.join(root, name)
            with open(path, "rb") as f:
                data = f.read()
            if ".part" in name:
                seed_blob += data
                continue
            hits += [(os.path.relpath(path, out), key) for key, value in secrets.items() if value in data]
    if seed_blob:
        raw = gzip.decompress(seed_blob)
        hits += [("seed/market.db", key) for key, value in secrets.items() if value in raw]
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir", help="empty or missing folder to write the bundle to")
    parser.add_argument("--seed", action="store_true", help="include a cleaned copy of data/market.db")
    args = parser.parse_args()

    out = os.path.abspath(args.out_dir)
    if os.path.commonpath([out, REPO]) == REPO:
        sys.exit("Write the bundle outside the repo, so it can't be committed by accident.")
    if os.path.exists(out) and os.listdir(out):
        sys.exit(f"{out} is not empty.")
    os.makedirs(out, exist_ok=True)

    copy_code(out)
    if args.seed:
        build_seed(out)

    hits = scan(out)
    if hits:
        for path, key in hits:
            print(f"SECRET FOUND: value of {key} in {path}", file=sys.stderr)
        return 1
    count = sum(len(files) for _, _, files in os.walk(out))
    print(f"bundle: {count} files in {out}; no .env value found in any of them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
