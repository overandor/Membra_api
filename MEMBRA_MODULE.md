# MEMBRA Module Contract — API

## Role

Canonical backend gateway for MEMBRA shared objects: users, assets, listings, campaigns, relay jobs, proofs, wallet events, and payout eligibility.

## System inputs

- owner/user records
- asset registrations
- listings
- campaign records
- relay job records
- proof records
- wallet ledger events

## System outputs

- normalized API objects
- shared table views
- payout eligibility records
- proof-to-eligibility transitions

## Health

```text
GET /api/health
```

## Replit role

`service`

Runs behind the main MEMBRA website or alongside `Membra_kpi` in a multi-module workspace.

## Production boundary

Records eligibility and audit state. Does not move money or custody funds.
