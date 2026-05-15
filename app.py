"""MEMBRA API — canonical gateway for the proof-of-reality network.

This service normalizes shared objects used by MEMBRA repos and now ingests
canonical MEMBRA OS event envelopes from producer modules such as Membra_kpi.

It is intentionally settlement-safe: it records eligibility and audit state,
but it does not move money by itself.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

APP_NAME = "MEMBRA API Gateway"
APP_VERSION = "1.1.0"
DB_PATH = Path(os.getenv("APP_DB_PATH", "/tmp/membra_api.sqlite3"))
MEMBRA_EVENT_SECRET = os.getenv("MEMBRA_EVENT_SECRET", "")
api = FastAPI(title=APP_NAME, version=APP_VERSION)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def verify_event_signature(event: dict[str, Any]) -> bool:
    if not MEMBRA_EVENT_SECRET:
        return True
    supplied = event.get("signature") or ""
    unsigned = dict(event)
    unsigned["signature"] = None
    expected = "hmac_sha256:" + hmac.new(MEMBRA_EVENT_SECRET.encode("utf-8"), canonical(unsigned).encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY,email TEXT,display_name TEXT,role TEXT,status TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS assets(asset_id TEXT PRIMARY KEY,owner_id TEXT,asset_type TEXT,title TEXT,location_scope TEXT,consent_scope TEXT,status TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS listings(listing_id TEXT PRIMARY KEY,asset_id TEXT,listing_type TEXT,price_usd REAL,availability TEXT,status TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS campaigns(campaign_id TEXT PRIMARY KEY,advertiser_id TEXT,title TEXT,budget_usd REAL,status TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS relay_jobs(relay_id TEXT PRIMARY KEY,requester_id TEXT,pickup_node TEXT,dropoff_node TEXT,mode TEXT,status TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS proof_events(proof_id TEXT PRIMARY KEY,subject_type TEXT,subject_id TEXT,proof_type TEXT,evidence_url TEXT,metadata_json TEXT,proof_hash TEXT,status TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS wallet_events(ledger_event_id TEXT PRIMARY KEY,user_id TEXT,subject_type TEXT,subject_id TEXT,amount_usd REAL,event_type TEXT,status TEXT,metadata_json TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS payout_eligibility(payout_event_id TEXT PRIMARY KEY,user_id TEXT,subject_type TEXT,subject_id TEXT,eligible_amount_usd REAL,eligibility_reason TEXT,status TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS events(
          event_id TEXT PRIMARY KEY,
          event_type TEXT,
          source_module TEXT,
          subject_type TEXT,
          subject_id TEXT,
          owner_id TEXT,
          correlation_id TEXT,
          causation_id TEXT,
          risk_level TEXT,
          proof_hash TEXT,
          signature TEXT,
          payload_json TEXT,
          status TEXT,
          created_at TEXT,
          ingested_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_subject ON events(subject_type, subject_id);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_owner ON events(owner_id);
        """)


init_db()


class UserIn(BaseModel):
    email: str
    display_name: str = "MEMBRA User"
    role: str = "owner"


class AssetIn(BaseModel):
    owner_id: str
    asset_type: str
    title: str
    location_scope: str = "local"
    consent_scope: str = "permissioned listing and proof metadata only"


class ListingIn(BaseModel):
    asset_id: str
    listing_type: str = "access"
    price_usd: float = Field(default=0, ge=0)
    availability: str = "manual approval required"


class CampaignIn(BaseModel):
    advertiser_id: str
    title: str
    budget_usd: float = Field(default=0, ge=0)


class RelayIn(BaseModel):
    requester_id: str
    pickup_node: str
    dropoff_node: str
    mode: str = "local_delivery"


class ProofIn(BaseModel):
    subject_type: str
    subject_id: str
    proof_type: str = "photo_timestamp_metadata"
    evidence_url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class WalletEventIn(BaseModel):
    user_id: str
    subject_type: str
    subject_id: str
    amount_usd: float = 0
    event_type: str = "payout_hold"
    status: str = "recorded_not_settled"
    metadata: dict[str, Any] = Field(default_factory=dict)


class MembraEventIn(BaseModel):
    event_id: str
    event_type: str
    source_module: str
    subject_type: str
    subject_id: str
    owner_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    created_at: str
    consent_scope: str | None = None
    risk_level: str = "normal"
    payload: dict[str, Any] = Field(default_factory=dict)
    proof_hash: str | None = None
    signature: str | None = None


def project_event(event: MembraEventIn) -> list[dict[str, Any]]:
    """Project selected canonical events into API tables.

    Projection is intentionally conservative and idempotent-ish. Raw event payloads
    remain the source of truth in the events table.
    """
    actions: list[dict[str, Any]] = []
    payload = event.payload or {}
    with db() as conn:
        if event.event_type == "photo_analyzed":
            proof_id = new_id("proof")
            proof_hash = event.proof_hash or digest(event.model_dump())
            conn.execute(
                "INSERT OR IGNORE INTO proof_events VALUES(?,?,?,?,?,?,?,?,?)",
                (proof_id, event.subject_type, event.subject_id, "photo_analyzed_event", "", json.dumps(payload, default=str), proof_hash, "event_ingested_pending_review", now()),
            )
            actions.append({"table": "proof_events", "id": proof_id})
        elif event.event_type == "visibility_confirmed":
            listing_id = event.subject_id
            price = float(payload.get("eligible_amount_usd") or payload.get("price_usd") or 0)
            conn.execute(
                "INSERT OR IGNORE INTO wallet_events VALUES(?,?,?,?,?,?,?,?,?)",
                (new_id("ledger"), event.owner_id or "owner_unknown", "listing", listing_id, price, "visibility_confirmed", "recorded_not_settled", json.dumps(payload, default=str), now()),
            )
            actions.append({"table": "wallet_events", "id": listing_id})
        elif event.event_type == "payout_eligibility_created":
            payout_id = new_id("payout")
            amount = float(payload.get("eligible_amount_usd") or 0)
            conn.execute(
                "INSERT OR IGNORE INTO payout_eligibility VALUES(?,?,?,?,?,?,?,?)",
                (payout_id, event.owner_id or "owner_unknown", event.subject_type, event.subject_id, amount, "event_ingested", "eligible_pending_external_settlement", now()),
            )
            actions.append({"table": "payout_eligibility", "id": payout_id})
    return actions


@api.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "app": APP_NAME, "version": APP_VERSION, "doctrine": "proof records eligibility; external rails settle money"}


@api.get("/api/ready")
def ready() -> dict[str, Any]:
    with db() as conn:
        event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    warnings = [] if MEMBRA_EVENT_SECRET else ["MEMBRA_EVENT_SECRET not configured; signed event verification is permissive"]
    return {"ok": True, "event_count": event_count, "warnings": warnings}


@api.post("/api/events/ingest")
def ingest_event(data: MembraEventIn) -> dict[str, Any]:
    event = data.model_dump()
    if not verify_event_signature(event):
        raise HTTPException(401, "invalid event signature")
    with db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO events(event_id,event_type,source_module,subject_type,subject_id,owner_id,correlation_id,causation_id,risk_level,proof_hash,signature,payload_json,status,created_at,ingested_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (data.event_id, data.event_type, data.source_module, data.subject_type, data.subject_id, data.owner_id, data.correlation_id, data.causation_id, data.risk_level, data.proof_hash, data.signature, json.dumps(event, default=str), "ingested", data.created_at, now()),
        )
    projections = project_event(data)
    return {"ok": True, "event_id": data.event_id, "projections": projections}


@api.get("/api/events")
def list_events() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY ingested_at DESC LIMIT 500").fetchall()
    return {"events": [dict(row) for row in rows]}


@api.post("/api/users")
def create_user(data: UserIn) -> dict[str, Any]:
    user_id = new_id("usr")
    row = {"user_id": user_id, "email": data.email, "display_name": data.display_name, "role": data.role, "status": "active", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", tuple(row.values()))
    return row


@api.post("/api/assets")
def create_asset(data: AssetIn) -> dict[str, Any]:
    asset_id = new_id("asset")
    row = {"asset_id": asset_id, "owner_id": data.owner_id, "asset_type": data.asset_type, "title": data.title, "location_scope": data.location_scope, "consent_scope": data.consent_scope, "status": "registered_pending_verification", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?)", tuple(row.values()))
    return row


@api.post("/api/listings")
def create_listing(data: ListingIn) -> dict[str, Any]:
    listing_id = new_id("lst")
    row = {"listing_id": listing_id, "asset_id": data.asset_id, "listing_type": data.listing_type, "price_usd": data.price_usd, "availability": data.availability, "status": "draft_permission_required", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO listings VALUES(?,?,?,?,?,?,?)", tuple(row.values()))
    return row


@api.post("/api/campaigns")
def create_campaign(data: CampaignIn) -> dict[str, Any]:
    campaign_id = new_id("cmp")
    row = {"campaign_id": campaign_id, "advertiser_id": data.advertiser_id, "title": data.title, "budget_usd": data.budget_usd, "status": "draft_pending_funding_and_approval", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,?)", tuple(row.values()))
    return row


@api.post("/api/relay-jobs")
def create_relay_job(data: RelayIn) -> dict[str, Any]:
    relay_id = new_id("relay")
    row = {"relay_id": relay_id, "requester_id": data.requester_id, "pickup_node": data.pickup_node, "dropoff_node": data.dropoff_node, "mode": data.mode, "status": "draft_pending_agent_acceptance", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO relay_jobs VALUES(?,?,?,?,?,?,?)", tuple(row.values()))
    return row


@api.post("/api/proofs")
def create_proof(data: ProofIn) -> dict[str, Any]:
    proof_id = new_id("proof")
    payload = data.model_dump()
    proof_hash = digest(payload)
    row = {"proof_id": proof_id, "subject_type": data.subject_type, "subject_id": data.subject_id, "proof_type": data.proof_type, "evidence_url": data.evidence_url, "metadata_json": json.dumps(data.metadata, default=str), "proof_hash": proof_hash, "status": "submitted_pending_review", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO proof_events VALUES(?,?,?,?,?,?,?,?,?)", tuple(row.values()))
    return row


@api.post("/api/wallet-events")
def create_wallet_event(data: WalletEventIn) -> dict[str, Any]:
    ledger_event_id = new_id("ledger")
    row = {"ledger_event_id": ledger_event_id, "user_id": data.user_id, "subject_type": data.subject_type, "subject_id": data.subject_id, "amount_usd": data.amount_usd, "event_type": data.event_type, "status": data.status, "metadata_json": json.dumps(data.metadata, default=str), "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO wallet_events VALUES(?,?,?,?,?,?,?,?,?)", tuple(row.values()))
    return row


@api.post("/api/payout-eligibility/from-proof/{proof_id}")
def create_payout_eligibility(proof_id: str, user_id: str, amount_usd: float = 0) -> dict[str, Any]:
    with db() as conn:
        proof = conn.execute("SELECT * FROM proof_events WHERE proof_id=?", (proof_id,)).fetchone()
    if not proof:
        raise HTTPException(404, "proof not found")
    payout_event_id = new_id("payout")
    row = {"payout_event_id": payout_event_id, "user_id": user_id, "subject_type": proof["subject_type"], "subject_id": proof["subject_id"], "eligible_amount_usd": amount_usd, "eligibility_reason": f"proof_submitted:{proof_id}", "status": "eligible_pending_external_settlement", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO payout_eligibility VALUES(?,?,?,?,?,?,?,?)", tuple(row.values()))
    return row


@api.get("/api/{table}")
def list_table(table: str) -> dict[str, Any]:
    allowed = {"users", "assets", "listings", "campaigns", "relay_jobs", "proof_events", "wallet_events", "payout_eligibility", "events"}
    if table not in allowed:
        raise HTTPException(404, "unknown table")
    order_col = "ingested_at" if table == "events" else "created_at"
    with db() as conn:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT 250").fetchall()
    return {table: [dict(r) for r in rows]}


app = api

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))
