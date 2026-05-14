from __future__ import annotations

import datetime as dt
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

APP_NAME = os.getenv('APP_NAME', 'Membra API')
APP_VERSION = '0.1.0'
DB_PATH = Path(os.getenv('APP_DB_PATH', 'membra_api.db'))
QR_BASE_URL = os.getenv('QR_BASE_URL', 'http://localhost:8000/r')
NFC_BASE_URL = os.getenv('NFC_BASE_URL', 'http://localhost:8000/n')
PROOF_REVIEW_REQUIRED = os.getenv('PROOF_REVIEW_REQUIRED', 'true').lower() == 'true'
ALLOW_REWARD_RELEASE = os.getenv('ALLOW_REWARD_RELEASE', 'false').lower() == 'true'

app = FastAPI(title=APP_NAME, version=APP_VERSION)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:16]}'


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS owners (id TEXT PRIMARY KEY, email TEXT, display_name TEXT, status TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS advertisers (id TEXT PRIMARY KEY, email TEXT, company_name TEXT, status TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, owner_id TEXT, asset_type TEXT, title TEXT, city TEXT, status TEXT, verification_status TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, advertiser_id TEXT, title TEXT, destination_url TEXT, budget_cents INTEGER, status TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS media_kits (id TEXT PRIMARY KEY, campaign_id TEXT, asset_id TEXT, kit_type TEXT, qr_id TEXT, nfc_id TEXT, status TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS proof_events (id TEXT PRIMARY KEY, campaign_id TEXT, owner_id TEXT, asset_id TEXT, media_kit_id TEXT, proof_type TEXT, evidence_url TEXT, status TEXT, review_notes TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS tracking_events (id TEXT PRIMARY KEY, campaign_id TEXT, qr_id TEXT, nfc_id TEXT, event_type TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS reward_states (id TEXT PRIMARY KEY, campaign_id TEXT, owner_id TEXT, proof_event_id TEXT, status TEXT, amount_cents INTEGER, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, actor_id TEXT, event_type TEXT, metadata TEXT, created_at TEXT);
        ''')


@app.on_event('startup')
def startup() -> None:
    init_db()


class OwnerCreate(BaseModel):
    email: Optional[str] = None
    display_name: str = 'Membra Owner'


class AdvertiserCreate(BaseModel):
    email: Optional[str] = None
    company_name: str = 'Membra Advertiser'


class AssetCreate(BaseModel):
    owner_id: str
    asset_type: str
    title: str
    city: Optional[str] = None


class CampaignCreate(BaseModel):
    advertiser_id: str
    title: str
    destination_url: str
    budget_cents: int = 0


class MediaKitCreate(BaseModel):
    campaign_id: str
    asset_id: Optional[str] = None
    kit_type: str = 'qr_sticker'


class ProofCreate(BaseModel):
    campaign_id: str
    owner_id: Optional[str] = None
    asset_id: Optional[str] = None
    media_kit_id: Optional[str] = None
    proof_type: str = 'install_photo'
    evidence_url: Optional[str] = None


class ProofReview(BaseModel):
    status: str = Field(..., description='approved, rejected, disputed')
    review_notes: Optional[str] = None


@app.get('/v1/health')
def health() -> dict[str, Any]:
    return {'ok': True, 'app': APP_NAME, 'version': APP_VERSION, 'reward_release_enabled': ALLOW_REWARD_RELEASE}


@app.post('/v1/owners')
def create_owner(payload: OwnerCreate) -> dict[str, Any]:
    oid = new_id('owner')
    ts = now_iso()
    with db() as conn:
        conn.execute('INSERT INTO owners VALUES (?, ?, ?, ?, ?, ?)', (oid, payload.email, payload.display_name, 'active', ts, ts))
    return {'owner_id': oid, 'status': 'active'}


@app.post('/v1/advertisers')
def create_advertiser(payload: AdvertiserCreate) -> dict[str, Any]:
    aid = new_id('adv')
    ts = now_iso()
    with db() as conn:
        conn.execute('INSERT INTO advertisers VALUES (?, ?, ?, ?, ?, ?)', (aid, payload.email, payload.company_name, 'active', ts, ts))
    return {'advertiser_id': aid, 'status': 'active'}


@app.post('/v1/ad-assets')
def create_asset(payload: AssetCreate) -> dict[str, Any]:
    asset_id = new_id('asset')
    ts = now_iso()
    with db() as conn:
        conn.execute('INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (asset_id, payload.owner_id, payload.asset_type, payload.title, payload.city, 'pending', 'unverified', ts, ts))
    return {'asset_id': asset_id, 'status': 'pending'}


@app.post('/v1/ad-assets/{asset_id}/verify')
def verify_asset(asset_id: str) -> dict[str, Any]:
    with db() as conn:
        if not conn.execute('SELECT id FROM assets WHERE id=?', (asset_id,)).fetchone():
            raise HTTPException(404, 'asset not found')
        conn.execute('UPDATE assets SET status=?, verification_status=?, updated_at=? WHERE id=?', ('available', 'verified', now_iso(), asset_id))
    return {'asset_id': asset_id, 'status': 'available', 'verification_status': 'verified'}


@app.post('/v1/campaigns')
def create_campaign(payload: CampaignCreate) -> dict[str, Any]:
    campaign_id = new_id('camp')
    ts = now_iso()
    with db() as conn:
        conn.execute('INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (campaign_id, payload.advertiser_id, payload.title, payload.destination_url, payload.budget_cents, 'draft', ts, ts))
    return {'campaign_id': campaign_id, 'status': 'draft'}


@app.post('/v1/campaigns/{campaign_id}/fund')
def fund_campaign(campaign_id: str) -> dict[str, Any]:
    with db() as conn:
        if not conn.execute('SELECT id FROM campaigns WHERE id=?', (campaign_id,)).fetchone():
            raise HTTPException(404, 'campaign not found')
        conn.execute('UPDATE campaigns SET status=?, updated_at=? WHERE id=?', ('funded', now_iso(), campaign_id))
    return {'campaign_id': campaign_id, 'status': 'funded'}


@app.post('/v1/media-kits')
def create_media_kit(payload: MediaKitCreate) -> dict[str, Any]:
    kit_id = new_id('kit')
    qr_id = new_id('qr')
    nfc_id = new_id('nfc') if 'nfc' in payload.kit_type.lower() else None
    ts = now_iso()
    with db() as conn:
        conn.execute('INSERT INTO media_kits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (kit_id, payload.campaign_id, payload.asset_id, payload.kit_type, qr_id, nfc_id, 'qr_generated', ts, ts))
    return {'media_kit_id': kit_id, 'qr_id': qr_id, 'nfc_id': nfc_id, 'qr_url': f'{QR_BASE_URL}/{qr_id}'}


@app.post('/v1/proof-events')
def create_proof(payload: ProofCreate) -> dict[str, Any]:
    proof_id = new_id('proof')
    status = 'submitted' if PROOF_REVIEW_REQUIRED else 'approved'
    ts = now_iso()
    with db() as conn:
        conn.execute('INSERT INTO proof_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (proof_id, payload.campaign_id, payload.owner_id, payload.asset_id, payload.media_kit_id, payload.proof_type, payload.evidence_url, status, None, ts, ts))
    return {'proof_id': proof_id, 'status': status}


@app.post('/v1/proof-events/{proof_id}/review')
def review_proof(proof_id: str, payload: ProofReview) -> dict[str, Any]:
    if payload.status not in {'approved', 'rejected', 'disputed'}:
        raise HTTPException(400, 'invalid status')
    with db() as conn:
        row = conn.execute('SELECT * FROM proof_events WHERE id=?', (proof_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'proof not found')
        conn.execute('UPDATE proof_events SET status=?, review_notes=?, updated_at=? WHERE id=?', (payload.status, payload.review_notes, now_iso(), proof_id))
    return {'proof_id': proof_id, 'status': payload.status}


@app.get('/r/{qr_id}')
def qr_redirect(qr_id: str) -> RedirectResponse:
    with db() as conn:
        kit = conn.execute('SELECT * FROM media_kits WHERE qr_id=?', (qr_id,)).fetchone()
        if not kit:
            raise HTTPException(404, 'QR not found')
        campaign = conn.execute('SELECT * FROM campaigns WHERE id=?', (kit['campaign_id'],)).fetchone()
        if not campaign:
            raise HTTPException(404, 'campaign not found')
        conn.execute('INSERT INTO tracking_events VALUES (?, ?, ?, ?, ?, ?)', (new_id('track'), campaign['id'], qr_id, None, 'qr_scan', now_iso()))
    return RedirectResponse(campaign['destination_url'])


@app.get('/v1/campaigns')
def list_campaigns() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute('SELECT * FROM campaigns ORDER BY created_at DESC LIMIT 100').fetchall()
    return {'campaigns': [dict(row) for row in rows]}


@app.get('/v1/proof-reports/{campaign_id}')
def proof_report(campaign_id: str) -> dict[str, Any]:
    with db() as conn:
        proofs = conn.execute('SELECT * FROM proof_events WHERE campaign_id=? ORDER BY created_at DESC', (campaign_id,)).fetchall()
        events = conn.execute('SELECT * FROM tracking_events WHERE campaign_id=? ORDER BY created_at DESC', (campaign_id,)).fetchall()
    return {'campaign_id': campaign_id, 'proof_events': [dict(r) for r in proofs], 'tracking_events': [dict(r) for r in events]}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
