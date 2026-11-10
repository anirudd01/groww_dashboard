"""Deploy the public dashboards to Railway, optionally pushing the local database to the server.

    python deploy/railway_deploy.py              # code only; the server keeps its database
    python deploy/railway_deploy.py --push-db    # code + this machine's data/market.db

``--push-db`` treats the local database as the truth: the server's database is replaced by a
cleaned copy of it on the next start (deploy/railway/start.sh). Whatever the server wrote since
the last push (e.g. the Dhan movers it recorded itself) is overwritten. The copy leaves out the
Dhan journal tables and every saved broker session (see deploy/stage_public.py).

How it works: deploy/stage_public.py builds the bundle in a temporary folder outside the repo,
scans it for .env values, and this script uploads it with ``railway up``. The upload uses the
project token in ``RAILWAY_PULSE_PROJECT_TOKEN`` (.env), which can deploy only to the
pulse-dashboards project. No secret is printed.

Needs the Railway CLI (``npm i -g @railway/cli``).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_ID = "4fcb8e29-2e76-42f2-b313-2860f975c61a"  # pulse-dashboards / dashboards
PUBLIC_URL = "https://market-pulse-dashboard.up.railway.app"
TOKEN_ENV = "RAILWAY_PULSE_PROJECT_TOKEN"


def read_env(name: str) -> str:
    with open(os.path.join(REPO, ".env"), encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--push-db", action="store_true", help="replace the server's database with this machine's")
    args = parser.parse_args()

    token = os.getenv(TOKEN_ENV) or read_env(TOKEN_ENV)
    if not token:
        sys.exit(f"{TOKEN_ENV} is not set in .env")
    railway = shutil.which("railway") or shutil.which("railway.cmd")
    if not railway:
        sys.exit("Railway CLI not found: npm i -g @railway/cli")

    work = tempfile.mkdtemp(prefix="pulse-deploy-")
    bundle = os.path.join(work, "bundle")
    try:
        stage = [sys.executable, os.path.join(REPO, "deploy", "stage_public.py"), bundle]
        if args.push_db:
            stage.append("--seed")
        if subprocess.run(stage).returncode:
            return 1

        # Only the project token: an account token in the environment would take precedence.
        env = {k: v for k, v in os.environ.items() if not k.startswith("RAILWAY_")}
        env["RAILWAY_TOKEN"] = token
        print("uploading", "code + database" if args.push_db else "code only", "...", flush=True)
        if subprocess.run([railway, "up", "--service", SERVICE_ID, "--ci"], cwd=bundle, env=env).returncode:
            print("railway up failed", file=sys.stderr)
            return 1
        print(f"deployed: {PUBLIC_URL}")
        if args.push_db:
            print("The server installs the pushed database as it starts; its log says 'Installing pushed database'.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
