# MEMBRA Protocol

Version: 0.1
Status: working protocol for the Membra multi-repo system

## Purpose

This document defines the shared language, identifiers, state machines, event names, and repo boundaries for the Membra ecosystem.

Membra is a proof, placement, payout, and permission network for verified local media inventory: windows, vehicles, wearables, QR tags, NFC tags, proof events, campaign analytics, and owner payouts.

## Master invariant

No verified owner -> no asset.

No verified asset -> no campaign match.

No approved creative -> no media kit.

No certified QR or NFC identity -> no placement.

No proof photo plus location plus campaign time match -> no payout eligibility.

No audit event -> no trusted state change.

No Membra gateway redirect -> no analytics.

## System of record

`overandor/Membra_api` is the system of record for shared entities, auth, permissions, owner records, advertiser records, assets, campaigns, placements, proof records, payout states, and analytics APIs.

Other repos may compute, review, hash, fulfill, or display data, but they should not silently create a conflicting source of truth.

## Repository boundaries

`overandor/Membra_api`: FastAPI backend, Postgres or Supabase schema, auth, campaign CRUD, owner CRUD, proof endpoints, analytics endpoints.

`overandor/Membra_ads`: campaign engine, media kit state machine, QR identity generation, placement workflow, payout eligibility logic.

`overandor/Membra_proofbook`: proof hashing, audit event ledger, proof verification, immutable proof snapshots.

`overandor/membra-qr-gateway`: public redirect gateway, QR scan tracking, NFC tap tracking, campaign analytics dashboard.

`overandor/Membra_admin-`: proof review UI, fraud review, campaign moderation, payout approval queue.

`overandor/Membra_wallet`: reward accounting boundary, payout eligibility, Stripe Connect preparation, owner balance ledger, wallet handoff flows.

`overandor/Membra_vendor_adapters`: Printify adapter, Printful adapter, manual fulfillment adapter, shipment webhook handlers.

`overandor/Membra_wear`: wearable catalog, hoodie/shirt/cap templates, QR placement generator, NFC garment templates.

`overandor/Membra_kpi`: campaign KPIs, owner engagement metrics, scan heatmaps, payout analytics.

`overandor/Membra_mobile`: owner onboarding app, proof uploads, QR scan verifier, media kit confirmation.

`overandor/Membra_contracts`: devnet proof anchors, audit hash contracts, simulated reward proofs, ProofBook verification.

`overandor/Membra_demo_data`: seeded demo campaigns, fake advertisers, fake owners, scan simulation events.

`overandor/Membra_investor_room-`: pitch deck, valuation map, screenshots, revenue model, roadmap.

`overandor/membra-relay`: async event queue, webhook relay, scan event streaming, proof event distribution.

## Global IDs

All services should use stable prefixed IDs.

`usr_` user

`own_` owner

`adv_` advertiser

`ast_` ad asset

`win_` window asset

`veh_` vehicle asset

`wear_` wearable asset

`cmp_` campaign

`crt_` creative

`off_` campaign offer

`plc_` placement

`kit_` media kit

`qr_` QR identity

`nfc_` NFC identity

`proof_` proof event

`scan_` QR scan

`tap_` NFC tap

`pay_` payment or reward record

`pout_` payout record

`aud_` audit event

`snap_` proof snapshot

## Canonical states

Owner states: `draft`, `pending_verification`, `verified`, `suspended`, `banned`.

Asset states: `draft`, `submitted`, `under_review`, `verified`, `rejected`, `paused`, `retired`.

Campaign states: `draft`, `creative_pending`, `creative_approved`, `funding_pending`, `funded`, `matching`, `live`, `paused`, `completed`, `cancelled`.

Creative states: `uploaded`, `review_pending`, `approved`, `rejected`, `revision_requested`.

Offer states: `generated`, `sent`, `accepted`, `declined`, `expired`, `withdrawn`.

Media kit states: `planned`, `generated`, `ordered`, `in_production`, `shipped`, `delivered`, `confirmed_received`, `installed`, `active`, `expired`, `lost`, `damaged`.

Placement states: `offered`, `accepted`, `kit_pending`, `proof_pending`, `active`, `proof_approved`, `proof_rejected`, `eligible_for_payout`, `paid`, `disputed`, `cancelled`.

Proof states: `submitted`, `auto_checked`, `review_pending`, `approved`, `rejected`, `hashed`, `archived`.

Payout states: `pending`, `eligible`, `held`, `approved`, `released`, `failed`, `reversed`.

## Canonical event names

Use lowercase dot-separated event names.

Examples:

`owner.created`

`owner.verified`

`asset.submitted`

`asset.verified`

`campaign.created`

`campaign.creative_approved`

`campaign.funded`

`offer.sent`

`offer.accepted`

`kit.generated`

`kit.ordered`

`kit.shipped`

`kit.delivered`

`placement.activated`

`proof.submitted`

`proof.approved`

`proof.rejected`

`proof.snapshot_created`

`qr.scanned`

`nfc.tapped`

`payout.eligible`

`payout.approved`

`payout.released`

`audit.recorded`

## Proof requirements

A proof event should include the campaign ID, placement ID, asset ID, owner ID, timestamp, proof type, media URL or storage key, location result, campaign window result, QR/NFC identity result when applicable, reviewer result, and audit event ID.

Proof does not become payout-eligible until it passes the required checks for that campaign and asset type.

## QR and NFC rule

Every QR code and NFC tag must resolve through `membra-qr-gateway` first. Direct advertiser links are not certified Membra placements because they bypass tracking, attribution, fraud checks, and analytics.

## Audit rule

Every meaningful state change must write an audit event. The audit event must identify actor, entity type, entity ID, previous state, new state, reason, timestamp, and source service.

## Payout rule

Payout eligibility is not the same as payout release. Eligibility is computed by proof and campaign rules. Release requires wallet or payout rail approval, risk checks, and audit logging.

## Data ownership rule

Core records belong in `Membra_api`. Derived metrics belong in `Membra_kpi`. Immutable proof snapshots belong in `Membra_proofbook`. Vendor fulfillment details belong in `Membra_vendor_adapters` but must report status back to the system of record.

## Compatibility rule

Every service must tolerate unknown future fields and must never break on additive protocol changes.
