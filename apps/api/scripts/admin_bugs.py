"""Admin CLI for testnet bug reports. Reads the admin token from infra/.env.

Usage (from apps/api):
  uv run python scripts/admin_bugs.py list
  uv run python scripts/admin_bugs.py verify <bug-id>
  uv run python scripts/admin_bugs.py reject <bug-id>

Override the API with FUTUREROOTS_TESTNET_API (default api-testnet.futureroots.app).
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

API = os.environ.get("FUTUREROOTS_TESTNET_API", "https://api-testnet.futureroots.app")

env_path = Path(__file__).resolve().parents[3] / "infra" / ".env"
m = re.search(r"^TESTNET_ADMIN_TOKEN=(.+)$", env_path.read_text(), re.M)
if not m:
    sys.exit("TESTNET_ADMIN_TOKEN not found in infra/.env")
TOKEN = m.group(1).strip()


def call(path, body=None, method="GET"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json", "X-Admin-Token": TOKEN},
        method=method,
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def cmd_list():
    bugs = call("/testnet/bugs/pending")
    if not bugs:
        print("No pending bug reports.")
        return
    print(f"{len(bugs)} pending report(s):\n")
    for b in bugs:
        print(f"  id:       {b['id']}")
        print(f"  from:     {b['reporter']}  ({b['wallet_address']})")
        print(f"  title:    {b['title']}")
        print(f"  details:  {b['body']}")
        print(f"  filed:    {b['created_at']}")
        print(f"  verify:   uv run python scripts/admin_bugs.py verify {b['id']}\n")


def cmd_decide(decision, bug_id):
    r = call(f"/testnet/bugs/{bug_id}/verify", {"decision": decision}, method="POST")
    verb = "verified (+250 to the reporter)" if decision == "verified" else "rejected"
    print(f"Report {r['id']} {verb}. Status: {r['status']}.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "verify", "reject"):
        sys.exit(__doc__)
    if sys.argv[1] == "list":
        cmd_list()
    else:
        if len(sys.argv) < 3:
            sys.exit("Provide a bug id.")
        cmd_decide("verified" if sys.argv[1] == "verify" else "rejected", sys.argv[2])
