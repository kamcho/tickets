# Metrolinks — What to ask the ISP (missing info)

Ask the ISP / network team only for what we still need to finish billing + auto cut/restore.  
Fill the Answer column. Send back to the software team.

---

## 1. Routers

| # | Ask them | Answer |
|---|----------|--------|
| 1.1 | How many MikroTik routers terminate customer PPPoE? | |
| 1.2 | Name + location of each router | |
| 1.3 | Which router is the default for new customers? | |
| 1.4 | Who decides which tower a new customer goes on? | |

---

## 2. How our server reaches each router

| # | Ask them | Answer |
|---|----------|--------|
| 2.1 | API IP or hostname for each router | |
| 2.2 | Reachable from the public internet? (yes/no) | |
| 2.3 | If no — VPN type (WireGuard / OpenVPN / Tailscale / other)? | |
| 2.4 | Who sets up VPN to our DigitalOcean droplet? | |
| 2.5 | Must we whitelist the droplet public IP? | |
| 2.6 | HTTPS or HTTP for API? Port? | |

---

## 3. API access (create a dedicated user, e.g. billing)

| # | Ask them | Answer |
|---|----------|--------|
| 3.1 | API username | |
| 3.2 | API password (share on a secure channel) | |
| 3.3 | Can this user read/write PPP secrets? | |
| 3.4 | Can this user kick active PPP sessions? | |
| 3.5 | Is REST / www-ssl enabled on each router? | |

---

## 4. PPPoE naming and speed profiles

| # | Ask them | Answer |
|---|----------|--------|
| 4.1 | Current PPP username format (phone, account id, other)? | |
| 4.2 | OK to standardize usernames as phone 254… ? | |
| 4.3 | Who creates PPP secrets today — Winbox only, or OK if app creates? | |
| 4.4 | Exact PPP profile name for each speed below | |

| Plan / speed | Exact MikroTik profile name |
|--------------|-----------------------------|
| 10 Mbps | |
| 15 Mbps | |
| 20 Mbps | |
| 25 Mbps | |
| 30 Mbps | |
| 35 Mbps | |
| 40 Mbps | |
| Other | |

---

## 5. Cut / restore rules

| # | Ask them | Answer |
|---|----------|--------|
| 5.1 | On expiry: disable PPP secret + kick session — OK? | |
| 5.2 | On payment: enable secret again — OK? | |
| 5.3 | Cut at exact expiry time (to the second) — OK? | |
| 5.4 | Any grace period after expiry? (we assume 0) | |
| 5.5 | SMS on suspend / restore — OK? | |

---

## 6. Safe test account

| # | Ask them | Answer |
|---|----------|--------|
| 6.1 | Test PPP username we may suspend/restore | |
| 6.2 | Confirm it is not a paying customer | |
| 6.3 | Best time window for the live test | |
| 6.4 | Who do we call if a wrong customer gets cut? | |

---

## 7. Contacts

| # | Ask them | Answer |
|---|----------|--------|
| 7.1 | MikroTik admin name + phone / WhatsApp | |
| 7.2 | Escalation contact if API cut/restore fails | |

---

## Minimum we still need before go-live

- [ ] Every PPPoE router listed (name + API host)  
- [ ] Path from droplet → router (public or VPN)  
- [ ] API user + password with PPP rights  
- [ ] Exact profile names for 10–40 Mbps  
- [ ] PPP username format agreed (254… preferred)  
- [ ] One test PPP account for suspend/restore  
- [ ] Cut/restore rules confirmed (no surprise grace)  

---

## Short message you can send them

Please send us, for each MikroTik with customer PPPoE:

1. Router name + location  
2. API host/IP + port + HTTPS or HTTP  
3. How our cloud server will reach it (public or VPN)  
4. API username + password (secure channel)  
5. Confirm PPP secret + kick rights  
6. Exact PPP profile names for 10–40 Mbps  
7. PPP username format — is phone 254… OK?  
8. One test PPP account we can disable/enable  
9. Confirm: disable+kick on expiry, enable on payment, grace = 0  

Thank you — Metrolinks software team.
