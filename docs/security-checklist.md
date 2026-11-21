# Metrolinks — Billing / ISP security checklist

Use this when hardening the billing app, M-Pesa paths, and MikroTik cut/restore.  
Fill Answer / Done as you go. Software + hosting + network owners should each complete their sections.

App context:  
This system holds customer phones, payment references, and the power to suspend/restore internet. Treat production like money + network control from day one. DDoS protection is mostly at the edge (Cloudflare + firewall), not inside Django alone.

---

## 1. Edge / DDoS (hosting)

| # | Measure | Done (yes/no) | Notes |
|---|---------|---------------|-------|
| 1.1 | Site behind Cloudflare (or equivalent) with proxy ON | | |
| 1.2 | Origin droplet firewall: only Cloudflare IPs (or VPN) can reach 80/443 | | |
| 1.3 | SSH not open to 0.0.0.0 — key auth + allowlist or VPN only | | |
| 1.4 | Winbox / MikroTik API / RouterOS ports not on the public internet | | |
| 1.5 | WAF / bot protection enabled for login and payment URLs | | |
| 1.6 | Rate limit at nginx (or Cloudflare) for /login, STK, webhooks | | |

---

## 2. Django app hardening

| # | Measure | Done (yes/no) | Notes |
|---|---------|---------------|-------|
| 2.1 | DEBUG=False in production | | |
| 2.2 | Strong SECRET_KEY (not in git) | | |
| 2.3 | ALLOWED_HOSTS locked to real domains | | |
| 2.4 | CSRF_TRUSTED_ORIGINS set for HTTPS hosts | | |
| 2.5 | HTTPS only (SECURE_SSL_REDIRECT, secure cookies, HSTS) | | |
| 2.6 | Billing pages: Admin + Receptionist only | | |
| 2.7 | No public unauthenticated suspend/restore APIs | | |
| 2.8 | Rate limit login + STK initiate in app or proxy | | |
| 2.9 | Dependencies patched; unused apps/endpoints removed | | |

---

## 3. Secrets and access

| # | Measure | Done (yes/no) | Notes |
|---|---------|---------------|-------|
| 3.1 | .env never committed; .env.example has placeholders only | | |
| 3.2 | M-Pesa Consumer Key / Secret / Passkey in env only | | |
| 3.3 | MikroTik API password not shared in WhatsApp groups | | |
| 3.4 | 2FA on DigitalOcean, Cloudflare, GitHub, Safaricom portal | | |
| 3.5 | DB user is least privilege (not root for the app) | | |
| 3.6 | Staff accounts: strong passwords; disable leavers quickly | | |

---

## 4. M-Pesa / payments

| # | Measure | Done (yes/no) | Notes |
|---|---------|---------------|-------|
| 4.1 | Callback URL is HTTPS on production domain only | | |
| 4.2 | Callback handler validates amount + reference | | |
| 4.3 | Payment apply is idempotent (retries do not double-credit) | | |
| 4.4 | Manual payment path remains for cash / failed STK | | |
| 4.5 | Who recorded a manual payment is logged | | |
| 4.6 | Do not log full secrets or raw passkeys | | |

---

## 5. MikroTik / network control

| # | Measure | Done (yes/no) | Notes |
|---|---------|---------------|-------|
| 5.1 | Router API only over VPN or private management net | | |
| 5.2 | Dedicated API user (e.g. billing) — not full admin | | |
| 5.3 | Rights limited to PPP secret + kick active (+ health read) | | |
| 5.4 | Short API timeouts; retries queued (never block STK callback) | | |
| 5.5 | Auto-cut disabled until test suspend/restore succeeds | | |
| 5.6 | Test PPP account is not a paying customer | | |
| 5.7 | Escalation contact if a wrong customer is suspended | | |

---

## 6. Audit and safety of cut/restore

| # | Measure | Done (yes/no) | Notes |
|---|---------|---------------|-------|
| 6.1 | Every suspend/restore logged (customer, actor, time, result) | | |
| 6.2 | Staff Suspend / Restore buttons require staff auth | | |
| 6.3 | Cut policy in writing (grace = 0 unless ISP agrees otherwise) | | |
| 6.4 | SMS on suspend/restore only after ISP + billing agree | | |
| 6.5 | Failed MikroTik call does not mark invoice wrongly | | |

---

## 7. Data protection

| # | Measure | Done (yes/no) | Notes |
|---|---------|---------------|-------|
| 7.1 | Backups exist and restore was tested once | | |
| 7.2 | Phone numbers normalized; avoid logging full PII dumps | | |
| 7.3 | Redis / Celery not exposed publicly | | |
| 7.4 | Admin and customer portals use HTTPS | | |

---

## 8. Monitoring

| # | Measure | Done (yes/no) | Notes |
|---|---------|---------------|-------|
| 8.1 | Alerts on 5xx spike / site down | | |
| 8.2 | Alerts on STK / callback failures | | |
| 8.3 | Alerts on suspend job / MikroTik unreachable | | |
| 8.4 | Who gets the alert (name + WhatsApp/email) | | |

---

## 9. Ownership (who does what)

| # | Area | Owner name | Phone / WhatsApp |
|---|------|------------|------------------|
| 9.1 | Cloudflare / DNS / WAF | | |
| 9.2 | Droplet firewall / SSH | | |
| 9.3 | Django / billing app | | |
| 9.4 | M-Pesa Daraja | | |
| 9.5 | MikroTik / VPN | | |
| 9.6 | Incident escalation | | |

---

## 10. Minimum before production billing + auto-cut

- [ ] Cloudflare + origin lockdown (section 1)  
- [ ] Django production settings (section 2)  
- [ ] Secrets out of git; 2FA on critical accounts (section 3)  
- [ ] M-Pesa callback safe + idempotent (section 4)  
- [ ] MikroTik API on VPN; least-privilege user (section 5)  
- [ ] Suspend/restore audit log (section 6)  
- [ ] One successful test cut/restore  
- [ ] Monitoring contacts filled (section 8)  

---

## 11. Priority order (do in this sequence)

1. Cloudflare + origin firewall  
2. MikroTik on VPN only + weak API user  
3. Django HTTPS / ALLOWED_HOSTS / CSRF / DEBUG=False  
4. Rate limits on login + payment endpoints  
5. Audit logs for suspend/restore  
6. Then enable auto-cut at expires_at  

---

## Short message for the team

Security bar for Metrolinks billing:

1. Edge: Cloudflare + lock origin  
2. App: DEBUG off, HTTPS, host/CSRF locked, staff-only billing  
3. Secrets: env only, 2FA everywhere that matters  
4. Money: validate + idempotent M-Pesa callbacks  
5. Network: MikroTik API not public; billing user only; VPN  
6. Safety: audit every cut/restore; test account first  
7. Watch: alerts on down / STK fail / router unreachable  

Thank you — Metrolinks software team.
