# Metrolinks — MikroTik / network info checklist

Use this document when collecting details from the **network / MikroTik team** (NOC, router admin, or ISP engineer).  
Fill one copy **per physical router** where noted. Return answers to the billing/app team so we can finish Phase 4 (auto disconnect / restore).

**App context (for the network team):**  
Our Django billing system on DigitalOcean will call each MikroTik’s **RouterOS REST API** over HTTPS to:

- disable / enable **PPPoE secrets** when a subscription expires or is paid  
- kick active PPP sessions immediately on cut  
- optionally provision new PPP users  

The app does **not** replace Winbox. It only automates suspend/restore at the exact billing expiry time.

---

## 1. Contact & ownership

| # | Question | Answer |
|---|----------|--------|
| 1.1 | Who owns MikroTik admin (name + phone/WhatsApp)? | |
| 1.2 | Who should we call if API cut/restore fails in production? | |
| 1.3 | Preferred hours for a live cut/restore test? | |
| 1.4 | Escalation if a customer is wrongly suspended? | |

---

## 2. How many routers?

| # | Question | Answer |
|---|----------|--------|
| 2.1 | How many MikroTik routers terminate customer PPPoE today? | |
| 2.2 | List each router **name** (e.g. Tower A, HQ Core, Sector 3): | |
| 2.3 | Is one router the **default** for new customers? Which? | |
| 2.4 | How do you decide which tower/router a new customer uses? | |

> We store each router in the app DB and link every customer PPPoE account to **one** router.

---

## 3. Per-router sheet (copy for each router)

**Router friendly name:** _______________________

### 3.1 Identity & location

| # | Question | Answer |
|---|----------|--------|
| 3.1.1 | Site / tower / location description | |
| 3.1.2 | Approx. customers on this router | |
| 3.1.3 | RouterOS version (e.g. 7.x) | |
| 3.1.4 | Device model (optional) | |

### 3.2 Reachability from the cloud (DigitalOcean)

Our billing server is a **DigitalOcean droplet** (public cloud). It must reach this router’s REST API.

| # | Question | Answer |
|---|----------|--------|
| 3.2.1 | Management IP or hostname for API | |
| 3.2.2 | Is that address reachable from the **public internet**? (yes/no) | |
| 3.2.3 | If **no**, is it only on LAN / private network? | |
| 3.2.4 | If private: can you provide a **VPN** to the droplet? (WireGuard / OpenVPN / Tailscale / other) | |
| 3.2.5 | If VPN: who sets it up, and what IP will the droplet use to reach the router? | |
| 3.2.6 | Must we **whitelist** the droplet’s public IP on the firewall? | |
| 3.2.7 | Droplet public IP to whitelist (billing team fills once known): | |

### 3.3 REST API protocol

| # | Question | Answer |
|---|----------|--------|
| 3.3.1 | HTTPS or HTTP for `/rest/...`? (we prefer **HTTPS**) | |
| 3.3.2 | API port (443 / 80 / other)? | |
| 3.3.3 | Is **www-ssl** / REST API enabled on this router? | |
| 3.3.4 | Self-signed certificate? (yes/no — we can skip verify on private nets) | |
| 3.3.5 | Example base URL you expect, e.g. `https://10.0.0.1` | |

### 3.4 API user (create on the MikroTik — not a public “register” site)

Create a dedicated user for the billing app (recommended name: `billing`).

| # | Question | Answer |
|---|----------|--------|
| 3.4.1 | API username | |
| 3.4.2 | API password (share securely — not in WhatsApp group if possible) | |
| 3.4.3 | User group / rights include PPP secrets read/write? | |
| 3.4.4 | Rights include PPP **active** read + delete (kick session)? | |
| 3.4.5 | Confirm this user is **not** a full admin if you want least privilege | |

**Minimum rights needed:**

- `/ppp/secret` — read, write (disable/enable, create/update)  
- `/ppp/active` — read, delete (kick)  
- `/system/resource` — read (health check)  

### 3.5 PPPoE naming & profiles on **this** router

| # | Question | Answer |
|---|----------|--------|
| 3.5.1 | PPP username format today (e.g. phone `2547…`, account id, other) | |
| 3.5.2 | OK to standardize on **phone as `254XXXXXXXXX`**? | |
| 3.5.3 | Who creates PPP secrets today — manual Winbox, or OK if app auto-creates? | |
| 3.5.4 | List **exact** PPP profile names on this router (must match spelling): | |

Fill the profile table:

| Plan / speed (billing) | MikroTik PPP profile name (exact) |
|------------------------|-----------------------------------|
| 10 Mbps | |
| 15 Mbps | |
| 20 Mbps | |
| 25 Mbps | |
| 30 Mbps | |
| 35 Mbps | |
| 40 Mbps | |
| Other: | |

| # | Question | Answer |
|---|----------|--------|
| 3.5.5 | Default profile if speed unknown | |
| 3.5.6 | Any customers on Hotspot instead of PPPoE on this box? (we are PPPoE-only for now) | |

### 3.6 Cut / restore behaviour (confirm)

| # | Question | Answer (yes/no/notes) |
|---|----------|------------------------|
| 3.6.1 | On expiry: **disable** PPP secret + **kick** active session — OK? | |
| 3.6.2 | On payment: **enable** secret again — OK? | |
| 3.6.3 | Cut at **exact** expiry second (billing clock) — OK? | |
| 3.6.4 | Grace period after expiry before cut? (we currently use **0**) | |
| 3.6.5 | SMS to customer on suspend/restore — OK with billing team? | |

### 3.7 Safe test account on this router

| # | Question | Answer |
|---|----------|--------|
| 3.7.1 | Test PPP username we may suspend/restore | |
| 3.7.2 | Test password (if needed) | |
| 3.7.3 | Confirm test user is **not** a live paying customer | |
| 3.7.4 | Best time window for the test | |

---

## 4. Multi-router operations

| # | Question | Answer |
|---|----------|--------|
| 4.1 | If a customer moves tower, who updates which router they belong to? | |
| 4.2 | Do any customers have secrets on **more than one** router? (should be no) | |
| 4.3 | Shared profile names across all routers, or different per site? | |
| 4.4 | Any central RADIUS, or local PPP secrets only? (we assume **local secrets**) | |

---

## 5. Security & change control

| # | Question | Answer |
|---|----------|--------|
| 5.1 | OK to store API passwords in our app database (Django admin only)? | |
| 5.2 | Prefer you rotate API password on a schedule? How often? | |
| 5.3 | Must all API access be VPN-only (recommended)? | |
| 5.4 | Logging: OK if we log suspend/restore actions with customer id? | |

---

## 6. What billing/app team will configure (for awareness)

Once this form is filled, we will:

1. Add each router in **Django Admin → Network routers** (`api_host`, user, password, SSL, default flag).  
2. Link each customer **Network service account** to the correct router.  
3. Run Celery + Redis on the droplet so disconnect fires at exact `expires_at`.  
4. Test suspend/restore on the **test PPP user** before any live cut.

**We still need from hosting (not MikroTik team):** Redis, Celery worker, VPN if required, hourly billing cron.

---

## 7. Minimum to go live (checklist)

Before production auto-disconnect:

- [ ] Every PPPoE router listed with API host + user + password  
- [ ] HTTPS (or agreed HTTP on VPN) working from droplet  
- [ ] VPN / firewall path confirmed  
- [ ] PPP username format agreed (`254…` preferred)  
- [ ] Profile names match billing plans exactly  
- [ ] One successful suspend + restore on a **test** user  
- [ ] Default router marked for new customers  

---

## 8. Quick copy-paste summary for WhatsApp / email

Please send us, **for each MikroTik that has customer PPPoE**:

1. Router name + location  
2. API host/IP + port + HTTPS or HTTP  
3. How the droplet will reach it (public / VPN — details)  
4. API username + password (secure channel)  
5. Confirm PPP rights (secret + kick active)  
6. Exact PPP profile names for 10–40 Mbps  
7. PPP username format (is phone `254…` OK?)  
8. One test PPP account we can disable/enable  
9. Confirm: disable+kick on expiry, enable on payment, no grace  

Thank you — Metrolinks billing / software team.
