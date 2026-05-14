# Membra API

Central MEMBRA control-plane API for owners, advertisers, campaigns, assets, media kits, proof events, QR/NFC tracking, and payout logic.

## One-line thesis

Membra API is the source-of-truth backend that turns owners, surfaces, campaigns, kits, scans, proof records, and reward states into one coherent physical media network.

## Role in the ecosystem

- `Membra_ads` defines the ad network product wedge.
- `Membra_api` owns the production backend contract.
- `membra-qr-gateway` consumes this API for dashboards.
- `Membra_mobile` consumes this API for owner proof workflows.
- `Membra_proofbook` verifies records created by this API.
- `Membra_wallet` coordinates payment and reward state.
- `Membra_vendor_adapters` handles fulfillment rails.

## Core resources

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

## Non-negotiable API rules

1. Membra is the control plane.
2. Frontends do not call vendor APIs directly.
3. QR and NFC destinations route through Membra first.
4. Reward release depends on approved proof and payment state.
5. Every state change should be audit logged.
6. Sensitive information must not be exposed in public responses.

## MVP endpoints

```text
GET  /v1/health
POST /v1/owners
POST /v1/advertisers
POST /v1/ad-assets
POST /v1/campaigns
POST /v1/media-kits
POST /v1/proof-events
GET  /v1/campaigns
GET  /v1/proof-reports/{campaign_id}
GET  /r/{qr_id}
GET  /n/{nfc_id}
```

## Current stage

Backend control-plane scaffold. Next step is to connect it to the existing `Membra_ads` API starter and make this the canonical shared backend.
