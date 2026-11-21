# Multi-ISP (multi-vendor) — v1

One deployed app serves **many ISPs**. Each vendor has isolated customers, tickets, plans, towers, and spend.

## Model

- **`Vendor`** — ISP company (`name`, `slug`, contact fields)
- **`MyUser.vendor`** — staff & customers belong to an ISP (nullable only for platform super-admins)
- **Scoped models** — `Ticket`, `TicketCategory`, `NetworkRouter`, `Plan`, `Expenditure` carry `vendor_id`

## Runtime

- **`VendorMiddleware`** sets `request.vendor` from logged-in user or `DEFAULT_VENDOR_SLUG` (`metrolinks` default)
- Views use helpers in `core/tenancy.py` (`scoped_tickets`, `scoped_customers`, etc.)
- **Django Admin** → **ISP vendors** to add a new ISP

## After deploy

```bash
python manage.py migrate
python manage.py seed_default_vendor
```

Assigns existing rows to the default Metrolinks vendor.

## Adding a second ISP

1. Admin → ISP vendors → Add (name + slug, e.g. `acme-fiber`)
2. Create staff users with that **vendor** selected (v1: set via Django admin on user)
3. Customers/tickets/plans created while logged in as that staff user stay in that vendor

## Roles

| Who | How | Access |
|-----|-----|--------|
| **Platform super-admin** | `is_superuser=True` (optional: no vendor) | All vendors — **ISP vendors** in sidebar |
| **Tenant Admin** | `role=Admin` + `vendor` set, **not** superuser | Own ISP only — users, customers, billing |
| Staff / agents | Receptionist / Field Agent + vendor | Own ISP only |

New tenant Admins must **not** be given Django superuser. Only platform staff get **Platform super-admin** when creating users.

## Not in v1 yet

- Per-vendor M-Pesa / Ujumbe credentials in DB
- Subdomain `tickets.{slug}.domain` (partial host parsing exists)
- Vendor self-signup UI
- Per-vendor email/phone uniqueness (emails still globally unique)