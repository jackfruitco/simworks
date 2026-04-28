# Billing Product Catalog

This document describes the backend source of truth for MedSim billing product identity.

## Canonical internal product codes

The backend accepts only these internal `product_code` values for base access entitlements:

- `chatlab_go`
- `chatlab_plus`
- `trainerlab_go`
- `trainerlab_plus`
- `medsim_one`
- `medsim_one_plus`

These codes live in [catalog.py](../../SimWorks/apps/billing/catalog.py).

## `plan_code` vs `product_code`

- `Entitlement.product_code` is internal-only and must always be one of the canonical codes above.
- `SeatAllocation.product_code` and `SeatAssignment.product_code` also use canonical internal product codes.
- `Subscription.plan_code` remains provider-facing for now.
  Stripe subscriptions store the Stripe price/plan code.
  Apple subscriptions store the Apple product ID.
- Provider-facing identifiers must never be copied directly into `Entitlement.product_code`.

## Provider mapping rules

- Apple product IDs map to canonical internal products in `apps.billing.catalog`.
- Stripe plan or price codes map to canonical internal products in `apps.billing.catalog`.
- Stripe Checkout price and promo coupon settings use `{product_code}:{interval}` keys, for
  example:

  ```bash
  BILLING_STRIPE_PRICE_PLAN_MAP='{"medsim_one:monthly":"price_...", "chatlab_go:monthly":"price_..."}'
  BILLING_STRIPE_PROMO_COUPON_MAP='{"medsim_one:monthly":"coupon_...", "chatlab_go:monthly":"coupon_..."}'
  ```

  Fixed-amount Stripe coupons must be configured per MVP product because one global fixed
  discount can be incorrect across differently priced products. `BILLING_STRIPE_PROMO_COUPON_ID`
  is supported only as a legacy/global fallback when a product-specific coupon map entry is
  missing.
- Product-to-lab capability rules also live in the catalog. Use helpers such as
  `product_includes_lab(...)` or `product_codes_for_lab(...)` instead of hardcoding
  product lists in lab-specific access code.
- Billing ingestion validates the provider identifier first, stores the provider-facing identifier on `Subscription.plan_code`, then reconciles entitlements with the mapped internal `product_code`.
- Legacy aliases such as `chatlab` and `trainerlab` are tolerated only for normalization and read-path hardening. New writes must use canonical internal codes.

## First-pass entitlement rules

- Base product access only.
- `feature_code` must be blank.
- `limit_code` must be blank.
- `limit_value` must be null.
- Access snapshots emit stable base-product entries only:
  `products[product_code]["enabled"] = true`

Malformed or legacy rows are skipped in snapshot generation so bootstrap/login paths stay stable even before data cleanup is complete.

## Personal-account auto-seat rule

- Seat-gated products are defined in the catalog.
- When the current account is a personal account, the owning user automatically satisfies one seat for seat-gated products.
- Personal-account owners do not need explicit `SeatAllocation` and `SeatAssignment` rows to consume that one seat.
- Organization or shared accounts still require normal seat allocation and seat assignment behavior.

## Safe manual or demo access grants

Use [grant_demo_product_access](../../SimWorks/apps/billing/services/entitlements.py) for base-product grants in scripts, tests, or support flows.

Behavior:

- validates the canonical product code
- creates only a base entitlement row
- uses user scope plus portability for a personal-account owner
- uses account scope for shared accounts

Django admin also uses catalog-backed product selects and blocks feature or limit grant entry for this first pass.
