"""End-to-end smoke test against a LOCAL `wrangler dev` (never production).

    cd backend && npm run db:local && npm run seed:local && npm run dev
    uv run python backend/smoke_test.py   # then wipe: see README in this folder

Local dev passes the CF-Connecting-IP header through, which lets this test simulate
different networks. In production Cloudflare sets that header itself.
"""

import re
import sys
from pathlib import Path

import requests

B = "http://localhost:8787/v1"
seed = (Path(__file__).parent / "seed" / "places.sql").read_text()
P1, P2 = re.findall(r"'(dohmh:\d+)'", seed)[:2]
tok = lambda i: f"device-token-{i:04d}-abcdefgh"  # noqa: E731
fails = []


def post(path, body, ip):
    r = requests.post(B + path, json=body, headers={"CF-Connecting-IP": ip}, timeout=10)
    return r.status_code


def listed():
    return [p["place_id"] for p in requests.get(B + "/public", timeout=10).json()["places"]]


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


check("starts empty", listed() == [])
for i in range(2):
    post("/report", {"place_id": P1, "outcome": "refused", "device_token": tok(i)}, f"10.0.0.{i}")
check("2 refusals not listed", P1 not in listed())
post("/report", {"place_id": P1, "outcome": "refused", "device_token": tok(2)}, "10.0.0.2")
check("3 independent refusals listed", P1 in listed())
for i in range(3, 6):
    post("/report", {"place_id": P2, "outcome": "refused", "device_token": tok(i)}, "10.0.9.9")
check("3 devices on one network not listed", P2 not in listed())
post("/dispute", {"place_id": P1, "device_token": tok(50)}, "10.0.1.1")
check("dispute withholds listing", P1 not in listed())
check(
    "unknown place rejected",
    post(
        "/report",
        {"place_id": "dohmh:999999999999", "outcome": "refused", "device_token": tok(7)},
        "10.0.2.1",
    )
    == 404,
)
check(
    "bad outcome rejected",
    post("/report", {"place_id": P1, "outcome": "violation", "device_token": tok(7)}, "10.0.2.1")
    == 400,
)
check(
    "bad token rejected",
    post("/report", {"place_id": P1, "outcome": "refused", "device_token": "x"}, "10.0.2.1") == 400,
)
codes = [
    post(
        "/confirm",
        {"restroom_id": "nyc:abcdef1234", "kind": "clean", "device_token": tok(200 + i)},
        "10.2.2.2",
    )
    for i in range(45)
]
check("rate limit at 41st write", 429 in codes and codes.index(429) == 40)
check("raw tables not exposed", requests.get(B + "/reports", timeout=10).status_code == 404)
sys.exit(1 if fails else 0)
