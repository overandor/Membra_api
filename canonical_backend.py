"""MEMBRA canonical backend.

Production-oriented control plane for tenants, API auth, deeds, listings,
ProofBook events, and admin review.

Run:
    uvicorn canonical_backend:app --host 0.0.0.0 --port 8000

Security model:
- API keys are tenant scoped.
- Deeds establish listing authority.
- Listings can only be created against active deeds.
- Public visibility requires admin approval.
- ProofBook entries use an immutable tenant-scoped hash chain.
- This service records eligibility and authority; it does not settle money.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

APP_NAME = "MEMBRA Canonical API"
APP_VERSION = "0.1.0"
DB_PATH = Path(os.getenv("MEMBRA_API_DB", "./data/membra_api.db"))
ADMIN_TOKEN_SHA256 = os.getenv("ADMIN_TOKEN_SHA256", "")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_NAME, version=APP_VERSION)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def hash_payload(payload: dict[str, Any]) -> str:
    return sha256_text(canonical_json(payload))


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tenants(
            tenant_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS api_keys(
            key_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            label TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users(
            user_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            email TEXT,
            display_name TEXT,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deeds(
            deed_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            title TEXT NOT NULL,
            authority_scope TEXT NOT NULL,
            consent_scope TEXT NOT NULL,
            location_hint TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS listings(
            listing_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            deed_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            listing_type TEXT NOT NULL,
            price_low REAL DEFAULT 0,
            price_high REAL DEFAULT 0,
            pricing_unit TEXT DEFAULT 'unit',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proofbook_entries(
            proof_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            previous_hash TEXT,
            chain_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_reviews(
            review_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT,
            operator TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_deeds_tenant ON deeds(tenant_id,status);
        CREATE INDEX IF NOT EXISTS idx_listings_tenant ON listings(tenant_id,status);
        CREATE INDEX IF NOT EXISTS idx_proofbook_tenant ON proofbook_entries(tenant_id,created_at);
        """)


init_db()


class TenantIn(BaseModel):
    name: str = Field(min_length=1)


class TenantContext(BaseModel):
    tenant_id: str
    key_id: str | None = None


class UserIn(BaseModel):
    email: str | None = None
    display_name: str = "MEMBRA User"
    role: Literal["owner", "advertiser", "admin", "operator"] = "owner"


class DeedIn(BaseModel):
    owner_user_id: str
    asset_type: str
    title: str
    authority_scope: str = "owner_controls_visibility"
    consent_scope: str = "permissioned listing and proof metadata only"
    location_hint: str | None = None


class ListingIn(BaseModel):
    deed_id: str
    title: str
    description: str = ""
    listing_type: str
    price_low: float = 0
    price_high: float = 0
    pricing_unit: str = "unit"


class ProofIn(BaseModel):
    subject_type: str
    subject_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "recorded"


class ReviewIn(BaseModel):
    subject_type: str
    subject_id: str
    decision: Literal["approve", "request_evidence", "restrict", "reject"]
    reason: str = ""
    operator: str = "system"


def require_admin(x_admin_token: str | None = Header(None)) -> None:
    if not ADMIN_TOKEN_SHA256:
        raise HTTPException(503, "ADMIN_TOKEN_SHA256 is not configured")
    if not x_admin_token or not hmac.compare_digest(sha256_text(x_admin_token), ADMIN_TOKEN_SHA256):
        raise HTTPException(401, "invalid admin token")


def tenant_from_key(x_api_key: str | None = Header(None)) -> TenantContext:
    if not x_api_key:
        raise HTTPException(401, "X-API-Key required")
    key_hash = sha256_text(x_api_key)
    with db() as conn:
        row = conn.execute("SELECT key_id, tenant_id FROM api_keys WHERE key_hash=? AND status='active'", (key_hash,)).fetchone()
    if not row:
        raise HTTPException(401, "invalid API key")
    return TenantContext(tenant_id=row["tenant_id"], key_id=row["key_id"])


def last_chain_hash(tenant_id: str) -> str | None:
    with db() as conn:
        row = conn.execute("SELECT chain_hash FROM proofbook_entries WHERE tenant_id=? ORDER BY created_at DESC LIMIT 1", (tenant_id,)).fetchone()
    return row["chain_hash"] if row else None


def write_proof(tenant_id: str, subject_type: str, subject_id: str, event_type: str, payload: dict[str, Any], status: str = "recorded") -> dict[str, Any]:
    proof_id = new_id("proof")
    created_at = now()
    payload_hash = hash_payload(payload)
    previous = last_chain_hash(tenant_id)
    chain_hash = hash_payload({"tenant_id": tenant_id, "proof_id": proof_id, "payload_hash": payload_hash, "previous_hash": previous, "created_at": created_at})
    row = {
        "proof_id": proof_id,
        "tenant_id": tenant_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event_type": event_type,
        "payload_json": canonical_json(payload),
        "payload_hash": payload_hash,
        "previous_hash": previous,
        "chain_hash": chain_hash,
        "status": status,
        "created_at": created_at,
    }
    with db() as conn:
        conn.execute("INSERT INTO proofbook_entries VALUES(?,?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
    return row


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "app": APP_NAME, "version": APP_VERSION, "database": "connected"}


@app.post("/api/admin/tenants")
def create_tenant(data: TenantIn, _: None = Depends(require_admin)) -> dict[str, Any]:
    tenant_id = new_id("tenant")
    api_key = "mk_" + secrets.token_urlsafe(32)
    key_id = new_id("key")
    with db() as conn:
        conn.execute("INSERT INTO tenants VALUES(?,?,?,?)", (tenant_id, data.name, "active", now()))
        conn.execute("INSERT INTO api_keys VALUES(?,?,?,?,?,?)", (key_id, tenant_id, sha256_text(api_key), "default", "active", now()))
    return {"tenant_id": tenant_id, "name": data.name, "api_key_once": api_key}


@app.post("/api/users")
def create_user(data: UserIn, ctx: TenantContext = Depends(tenant_from_key)) -> dict[str, Any]:
    user_id = new_id("usr")
    row = {"user_id": user_id, "tenant_id": ctx.tenant_id, "email": data.email, "display_name": data.display_name, "role": data.role, "status": "active", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?)", tuple(row.values()))
    write_proof(ctx.tenant_id, "user", user_id, "user_created", row)
    return row


@app.post("/api/deeds")
def create_deed(data: DeedIn, ctx: TenantContext = Depends(tenant_from_key)) -> dict[str, Any]:
    with db() as conn:
        owner = conn.execute("SELECT user_id FROM users WHERE tenant_id=? AND user_id=? AND status='active'", (ctx.tenant_id, data.owner_user_id)).fetchone()
    if not owner:
        raise HTTPException(404, "owner user not found in tenant")
    deed_id = new_id("deed")
    row = {"deed_id": deed_id, "tenant_id": ctx.tenant_id, "owner_user_id": data.owner_user_id, "asset_type": data.asset_type, "title": data.title, "authority_scope": data.authority_scope, "consent_scope": data.consent_scope, "location_hint": data.location_hint, "status": "active", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO deeds VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
    write_proof(ctx.tenant_id, "deed", deed_id, "deed_created", row)
    return row


@app.post("/api/listings")
def create_listing(data: ListingIn, ctx: TenantContext = Depends(tenant_from_key)) -> dict[str, Any]:
    with db() as conn:
        deed = conn.execute("SELECT deed_id,status FROM deeds WHERE tenant_id=? AND deed_id=?", (ctx.tenant_id, data.deed_id)).fetchone()
    if not deed or deed["status"] != "active":
        raise HTTPException(403, "active deed required before listing")
    listing_id = new_id("lst")
    row = {"listing_id": listing_id, "tenant_id": ctx.tenant_id, "deed_id": data.deed_id, "title": data.title, "description": data.description, "listing_type": data.listing_type, "price_low": data.price_low, "price_high": data.price_high, "pricing_unit": data.pricing_unit, "status": "draft", "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO listings VALUES(?,?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
    write_proof(ctx.tenant_id, "listing", listing_id, "listing_drafted", row)
    return row


@app.post("/api/proofbook")
def create_proof(data: ProofIn, ctx: TenantContext = Depends(tenant_from_key)) -> dict[str, Any]:
    return write_proof(ctx.tenant_id, data.subject_type, data.subject_id, data.event_type, data.payload, data.status)


@app.get("/api/proofbook")
def list_proofbook(ctx: TenantContext = Depends(tenant_from_key)) -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM proofbook_entries WHERE tenant_id=? ORDER BY created_at DESC LIMIT 500", (ctx.tenant_id,)).fetchall()
    return {"proofbook_entries": [dict(r) for r in rows]}


@app.get("/api/proofbook/verify")
def verify_chain(ctx: TenantContext = Depends(tenant_from_key)) -> dict[str, Any]:
    with db() as conn:
        entries = [dict(r) for r in conn.execute("SELECT * FROM proofbook_entries WHERE tenant_id=? ORDER BY created_at ASC", (ctx.tenant_id,)).fetchall()]
    previous = None
    for entry in entries:
        expected = hash_payload({"tenant_id": entry["tenant_id"], "proof_id": entry["proof_id"], "payload_hash": entry["payload_hash"], "previous_hash": previous, "created_at": entry["created_at"]})
        if entry["previous_hash"] != previous or entry["chain_hash"] != expected:
            return {"ok": False, "failed_proof_id": entry["proof_id"]}
        previous = entry["chain_hash"]
    return {"ok": True, "entry_count": len(entries), "last_chain_hash": previous}


@app.post("/api/admin/reviews")
def admin_review(data: ReviewIn, tenant_id: str, _: None = Depends(require_admin)) -> dict[str, Any]:
    review_id = new_id("review")
    row = {"review_id": review_id, "tenant_id": tenant_id, "subject_type": data.subject_type, "subject_id": data.subject_id, "decision": data.decision, "reason": data.reason, "operator": data.operator, "created_at": now()}
    with db() as conn:
        conn.execute("INSERT INTO admin_reviews VALUES(?,?,?,?,?,?,?,?)", tuple(row.values()))
        if data.subject_type == "listing" and data.decision == "approve":
            conn.execute("UPDATE listings SET status='approved' WHERE tenant_id=? AND listing_id=?", (tenant_id, data.subject_id))
        elif data.subject_type == "listing" and data.decision in {"reject", "restrict"}:
            conn.execute("UPDATE listings SET status=? WHERE tenant_id=? AND listing_id=?", (data.decision, tenant_id, data.subject_id))
    write_proof(tenant_id, data.subject_type, data.subject_id, f"admin_{data.decision}", row)
    return row


@app.get("/api/{table}")
def list_table(table: str, ctx: TenantContext = Depends(tenant_from_key)) -> dict[str, Any]:
    allowed = {"users", "deeds", "listings", "admin_reviews"}
    if table not in allowed:
        raise HTTPException(404, "unknown table")
    with db() as conn:
        rows = conn.execute(f"SELECT * FROM {table} WHERE tenant_id=? ORDER BY created_at DESC LIMIT 500", (ctx.tenant_id,)).fetchall()
    return {table: [dict(r) for r in rows]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
