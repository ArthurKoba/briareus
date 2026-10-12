#!/usr/bin/env python3
"""Read-only domain DB ownership inventory. This tool cannot provision/DDL or read secrets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    path=Path(__file__).resolve().parent/'config/owner-databases.json'
    data=json.loads(path.read_text())
    assert data['provisioning_status']=='automatic_on_data_start_pending_live_observation'
    assert len(data['initial'])==5
    if args.json:
        print(json.dumps(data,indent=2))
    else:
        print('AUTO BOOTSTRAP OWNER DATABASES — LIVE STATUS UNVERIFIED')
        for row in data['initial']:
            print(f"{row['owner']}: database={row['database']} source_user={row['role_env']} secret_source={row['secret_env']}")
        print('PostgreSQL creates the five DBs at start; each ASGI owner runs Alembic automatically')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
