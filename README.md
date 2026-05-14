# Membra API

**Membra API is the future centralized control-plane API for MEMBRA Labs and the MEMBRA Proof Network.**

It defines the source-of-truth backend contract for owners, advertisers, campaigns, assets, creatives, media kits, QR/NFC tracking, proof events, payout states, and audit records.

## Company Context

- Company: **MEMBRA Labs**
- Flagship product: **MEMBRA Proof Network**
- Module: **Membra API**
- Category: central control plane, shared backend contract, proof-commerce source of truth

## One-Line Thesis

Membra API turns owners, surfaces, campaigns, kits, scans, proof records, and reward states into one coherent physical media network.

## Product Role

`Membra_ads` currently contains the first working API scaffold.

This repo should become the canonical shared backend contract once the suite is consolidated.

## Core Resources

- owners
- advertisers
- ad assets
- campaigns
- creatives
- placements
- media kits
- QR tags
- NFC tags
- proof events
- tracking events
- payment states
- reward states
- audit events
- claims and disputes
- vendor orders

## MVP Endpoints

```text
GET  /v1/health
POST /v1/owners
POST /v1/advertisers
POST /v1/ad-assets
POST /v1/campaigns
POST /v1/media-kits
POST /v1/proof-events
POST /v1/proof-events/{proof_id}/review
GET  /v1/campaigns
GET  /v1/proof-reports/{campaign_id}
GET  /r/{qr_id}
GET  /n/{nfc_id}
```

## Integration Points

| Repo | API Relationship |
|---|---|
| `overandor/Membra_ads` | first backend implementation and commercial workflow |
| `overandor/membra-qr-gateway` | dashboard consumer |
| `overandor/Membra_mobile` | owner proof and campaign-offer consumer |
| `overandor/Membra_admin-` | operator console consumer |
| `overandor/Membra_proofbook` | proof/audit verification sink |
| `overandor/Membra_wallet` | funding, reward, payout state boundary |
| `overandor/Membra_vendor_adapters` | vendor fulfillment action layer |
| `overandor/Membra_kpi` | reporting and export consumer |

## Non-Negotiable API Rules

1. MEMBRA is the control plane.
2. Frontends do not call vendor APIs directly.
3. QR and NFC destinations route through MEMBRA first.
4. Reward release depends on approved proof and payment state.
5. Every state change should be audit logged.
6. Sensitive information must not be exposed in public responses.
7. Demo data must be labeled as demo data.
8. No payout mutation should occur without authorization and audit trail.

## Productization Priority

This repo should be implemented after `Membra_ads` stabilizes. The cleanest path is to migrate or mirror the working `Membra_ads` FastAPI API into this repo as the canonical backend.

## Current Stage

Backend control-plane namespace and API charter. Not yet the canonical implementation.