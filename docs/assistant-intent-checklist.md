# Metrolinks — Assistant intent / phone lookup checklist

Use this document when testing or signing off the support assistant’s intent layer (web chat and WhatsApp).  
Fill answers during UAT. Return to the software team so we can confirm phone lookups and ticket searches no longer fail.

App context:  
The assistant must classify the user’s intent before calling OpenAI. For clear cases (phone number, ticket ID, “my tickets”) it queries the database directly and replies in plain text. OpenAI is only used for greetings, create-ticket wording, and general chat.

The failure we are fixing: assistant asks for a phone → user sends a number → empty reply, wrong “no tickets”, or AI service error.

---

## 1. Environment under test

| # | Question | Answer |
|---|----------|--------|
| 1.1 | Environment (local / staging / production)? | |
| 1.2 | Date of test | |
| 1.3 | Tester name | |
| 1.4 | Channel tested (web / WhatsApp / both)? | |
| 1.5 | Browser or device (if web) | |
| 1.6 | OPENAI_API_KEY configured on this env? (yes/no) | |

---

## 2. Known test customer (fill before chat tests)

Use a real customer who already has at least one ticket.

| # | Question | Answer |
|---|----------|--------|
| 2.1 | Customer display name | |
| 2.2 | Phone as stored in DB (prefer 254…) | |
| 2.3 | Same person also has 07… form? (yes/no + number) | |
| 2.4 | How many tickets should appear? | |
| 2.5 | Example open ticket ID (TKT-XXXXXXXX) | |
| 2.6 | Duplicate customer rows for this phone? (yes/no) | |

> If tickets are missing in chat but exist in admin, note the phone formats and customer IDs below for the software team.

| Customer ID | Phone on that row | Ticket count |
|-------------|-------------------|--------------|
| | | |
| | | |

---

## 3. Intent behaviour checks

For each row: run the chat turn, then mark Pass / Fail and note what the bot actually replied.

### 3.1 Provide phone (after assistant asked)

| # | Step | Pass / Fail | Notes |
|---|------|-------------|-------|
| 3.1.1 | Say: how many tickets do I have (or my tickets) | | |
| 3.1.2 | Bot asks for phone number | | |
| 3.1.3 | Reply with 254… form of test customer | | |
| 3.1.4 | Bot lists tickets (count matches 2.4) | | |
| 3.1.5 | No blank message / no AI service error | | |

### 3.2 Provide phone (message is only a number)

| # | Step | Pass / Fail | Notes |
|---|------|-------------|-------|
| 3.2.1 | New chat (or clear context) | | |
| 3.2.2 | Send only the phone: 0712… or 2547… | | |
| 3.2.3 | Bot lists tickets for that phone | | |
| 3.2.4 | Spaced number works (e.g. 0712 345 678) | | |

### 3.3 Ticket ID lookup

| # | Step | Pass / Fail | Notes |
|---|------|-------------|-------|
| 3.3.1 | Paste ticket ID from 2.5 | | |
| 3.3.2 | Bot returns status, priority, link | | |
| 3.3.3 | Link opens on the correct host (not localhost) | | |
| 3.3.4 | No AI service error | | |

### 3.4 Ticket list / count language

| # | User message | Pass / Fail | Notes |
|---|--------------|-------------|-------|
| 3.4.1 | my tickets | | |
| 3.4.2 | any open tickets? | | |
| 3.4.3 | how many tickets do I have | | |
| 3.4.4 | check ticket status | | |

### 3.5 Create ticket

| # | Step | Pass / Fail | Notes |
|---|------|-------------|-------|
| 3.5.1 | Say: I want to open a ticket / report an issue | | |
| 3.5.2 | Bot continues create flow (categories / details) | | |
| 3.5.3 | Ticket is created or duplicate handled correctly | | |

### 3.6 Greeting / general

| # | Step | Pass / Fail | Notes |
|---|------|-------------|-------|
| 3.6.1 | hi / hello gets a short welcome | | |
| 3.6.2 | Unrelated question still gets a sensible reply | | |

---

## 4. Phone format matrix

Same customer, different inputs. Expected: same ticket list every time.

| # | Input sent in chat | Pass / Fail | Tickets shown (count) |
|---|--------------------|-------------|------------------------|
| 4.1 | 2547XXXXXXXXX | | |
| 4.2 | 07XXXXXXXXX | | |
| 4.3 | +2547XXXXXXXXX | | |
| 4.4 | 254 7XX XXX XXX (spaces) | | |
| 4.5 | 07XX XXX XXX (spaces) | | |
| 4.6 | Invalid junk (e.g. 123) — bot explains, does not crash | | |

---

## 5. Channel parity

| # | Question | Answer (yes/no/notes) |
|---|----------|------------------------|
| 5.1 | Web chat: phone-after-ask works | |
| 5.2 | WhatsApp: same phone-after-ask works | |
| 5.3 | Web and WhatsApp show same tickets for same phone | |
| 5.4 | Sidebar (web) updates after ticket list / lookup | |

---

## 6. Failure capture (fill only if something fails)

| # | Question | Answer |
|---|----------|--------|
| 6.1 | Exact user message that failed | |
| 6.2 | Exact bot reply (copy/paste) | |
| 6.3 | Time of failure (approx) | |
| 6.4 | Conversation / session id if known | |
| 6.5 | Screenshot attached? (yes/no) | |
| 6.6 | Customer ID(s) involved | |

---

## 7. Engineering sign-off (software team)

Confirm code path before calling UAT complete.

| # | Check | Done (yes/no) |
|---|-------|---------------|
| 7.1 | core/assistant/intent.py present (classifier) | |
| 7.2 | core/assistant/direct.py present (direct DB replies) | |
| 7.3 | agent.py wires: classify → try_direct_reply → else OpenAI | |
| 7.4 | CREATE_TICKET forces create_support_ticket on first OpenAI round | |
| 7.5 | customer_lookup merges 07… / 254… duplicates | |
| 7.6 | Unit tests for intent + direct phone path green | |
| 7.7 | Deployed / workers restarted on this environment | |

---

## 8. Minimum to go live (checklist)

Before production sign-off:

- [ ] Section 2 filled with a real customer who has tickets  
- [ ] 3.1 phone-after-ask pass  
- [ ] 3.3 ticket ID lookup pass  
- [ ] Section 4: at least 254… and 07… both pass  
- [ ] No blank replies on phone turns  
- [ ] No “AI service” error on phone / ticket ID turns  
- [ ] Ticket links use production host  
- [ ] WhatsApp smoke test pass (if WhatsApp is live)  
- [ ] Section 7 engineering checks all yes  

---

## 9. Quick copy-paste summary for WhatsApp / email

Please confirm for the assistant intent fix:

1. Env tested + date + tester  
2. Test customer name + phone(s) + expected ticket count  
3. Phone after “share your number” — pass or fail  
4. 07… and 254… both return the same tickets — pass or fail  
5. Paste TKT-… — pass or fail  
6. Any failure: exact message + bot reply  
7. Web only or WhatsApp too  

Thank you — Metrolinks software team.
