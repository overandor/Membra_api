# MEMBRA API Authority Backend Blueprint

`Membra_api` is the canonical backend for rights-aware physical-world monetization.

It must own the truth for:

- Auth
- Tenants
- Asset deeds
- Permission grants
- Listing authority
- Activation gates
- Review workflow
- ProofBook writer
- Revocation engine
- Event bus
- Vector memory
- KPI orchestration

## Core rule

No listing, ad, QR target, wallet entitlement, KPI product, or on-chain anchor may be activated unless `Membra_api` verifies authority.

## Authority chain

```text
Tenant
→ User
→ Asset deed
→ Permission grant
→ Listing authority
→ Admin review
→ Activation gate
→ ProofBook event
→ Optional contract anchor
```

## Activation gate requirements

A listing may activate only when all conditions are true:

1. `tenant_id` is present and scoped.
2. user belongs to the tenant.
3. asset deed exists.
4. deed is not disputed, restricted, or revoked.
5. permission grant exists.
6. permission scope covers the requested monetization use.
7. listing authority exists.
8. admin review status is approved.
9. no active dispute blocks the asset/listing.
10. latest ProofBook chain verification passes.

## Canonical tables

The first production schema should include:

- `tenants`
- `users`
- `asset_deeds`
- `permission_grants`
- `listing_authority`
- `review_decisions`
- `revocations`
- `proofbook_events`
- `event_outbox`
- `vector_memory`
- `kpi_observations`

## Repo responsibilities

### Membra_api

Owns the state machine and activation gate.

### Membra_proofbook

Owns immutable event verification, replay, lineage, and audit exports.

### Membra_contracts

Anchors verified hashes only. It does not prove ownership by itself.

## Non-negotiable production rules

- No mock production auth.
- No listing activation without authority.
- No cross-tenant data leakage.
- No contract anchor without ProofBook hash.
- No wallet entitlement without approved authority.
- No KPI monetization score without durable listing/deed records.
- No silent provider failures.
