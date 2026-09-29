# OpenPango

An open-source agent harness for post-purchase ops at a small DTC store. Five agents own fulfillment exceptions, tracking, returns, carrier issues, and customer replies. Orders and carriers are mocked, so everything replays offline. Python 3.11, SQLite, zero runtime dependencies.

## One command

```bash
python -m openpango replay 1042-customs
```

Replays "order #1042 stuck in customs for 9 days" against a frozen clock and prints the recommended action plus the draft email:

```
DECISION
  exception  stuck_customs
  action     carrier_inquiry
  approval   none
  follow-up  2026-10-01

TOOL CALLS (immutable event log)
  #1   ops_lead        lookup_order
  #2   carrier_chaser  open_ticket
  #3   support_writer  draft_customer_email

DRAFT EMAIL  (guard: PASS)
  Hi Maya,

  Order #1042 is with DHL Express, tracking number JD014600006281.
  The latest scan, on Sep 23, 2026, reads: "Customs clearance delayed: awaiting documentation" (Toronto, ON).
  The package has been in customs processing for 9 days, since Sep 20, 2026.
  DHL Express has not provided an estimated delivery date, and we won't guess one.
  We have opened an inquiry with DHL Express. We will check with them again on Oct 1, 2026.
  ...
```

Also: `--json` for machine output, `--db run.sqlite` to keep the event log, `python -m openpango list` for all incidents.

```bash
python -m openpango eval     # score all 10 incidents, exit 1 on any miss
python -m openpango serve    # ops inbox at http://127.0.0.1:8000
python -m pytest -q          # needs: pip install pytest
```

## Product rules and where they are enforced

| Rule | Enforcement |
|---|---|
| Every action writes an immutable event log | `tools.py`: each tool writes state and one event in one transaction. `events` is hash-chained and SQLite triggers reject `UPDATE`/`DELETE`. `eventlog.verify_chain` detects tampering (the inbox shows chain status). |
| Refunds over $75 or lost packages need a human | `policy.approval_gate`, called inside `approve_refund`. Above the line it files an approval request and moves no money. Only the `human` actor can `decide_approval`. Exactly $75.00 auto-issues, $75.01 does not. |
| Emails cite tracking facts, never invent ETAs | Copy is built from `TrackingFacts` (`facts.py`). `guard.py` then checks every draft: ETA language, dates, numbers, and claims like "delivered" or "customs" must trace to carrier data. A failing draft is stored as `blocked`, never sendable. |
| Agents only use their own tools | `Ctx.tool()` checks `policy.AGENT_TOOLS`. `support_writer` cannot refund; `returns` cannot decide approvals. |
| Dashboard shows aging exceptions | `dashboard.py`: late, stuck customs, refused delivery, WISMO tickets, plus an "other" bucket (lost, undelivered dispute, never picked up). |

## Architecture

```
mocks/carrier.py   rates, labels, case numbers (deterministic)
incidents/*.json   10 fixtures: order, shipment, carrier events, expected outcome
replay.py          load fixture -> fresh DB -> frozen clock -> ops_lead.handle()
agents/
  ops_lead         routes: classify, call specialists, pick the one recommended action
  exceptions       read-only triage: late | stuck_customs | refused | lost | address_issue | ...
  carrier_chaser   carrier inquiries/claims/pickup chases, address fix (rerate + new label)
  returns          return window, refund vs human approval
  support_writer   picks the email template, drafts through the guarded tool
tools.py           lookup_order rerate_shipment issue_label approve_refund draft_customer_email open_ticket
                   (+ human-only decide_approval, send_draft)
facts.py guard.py templates.py drafters.py
evals/             scorers.py, run.py
server.py ui/      stdlib HTTP server + single-file inbox
```

Agents are deterministic policy code by default, so replays are byte-identical and CI needs no API key. `drafters.ClaudeDrafter` (`pip install openpango[llm]`, `--drafter llm`) lets a model write the email body instead; its output goes through the same guard, so a hallucinated ETA gets blocked and scores zero.

## The 10 incidents

| id | situation | expected next action | approval |
|---|---|---|---|
| `1042-customs` | stuck in customs 9 days | `carrier_inquiry` | none |
| `late-weather` | weather delay, carrier ETA passed | `carrier_inquiry` | none |
| `wismo-normal` | "where is my order", moving normally | `status_reply` | none |
| `refused-delivery` | refused at door, returning | `rts_followup` | none |
| `lost-package` | no scan 14 days, $120 refund asked | `escalate_for_approval` | pending |
| `damaged-refund` | damaged item, $40 | `auto_refund` | auto |
| `return-late` | return 45 days after delivery, $90 | `deny_return_escalate` | none |
| `address-failure` | address not found, customer sent fix | `reissue_label` | none |
| `delivered-not-received` | marked delivered, customer disagrees | `carrier_claim` | none |
| `label-never-picked-up` | label 6 days old, no pickup scan | `pickup_chase` | none |

## Eval harness

`python -m openpango eval` runs each incident on a fresh database and scores three things from 0 to 1. Scorers read the event log and DB, not the agent's self-report.

- **Correct next action**: exception type, action, exact write-tool sequence from the event log, approval state, ticket kind.
- **Correct customer copy**: required phrases present (tracking number, latest scan, the "no ETA" statement) and forbidden promises absent.
- **No invented facts**: re-runs the guard against facts rebuilt from the database. Tests include a drafter that lies, to prove the scorer catches it.

An incident passes at 1.0 on all three plus a valid log chain.

## Add an incident

Drop a JSON file in `openpango/incidents/` (copy one). Times are `ago_days` relative to the fixture clock. The `expected` block lists the exception, action, tool sequence, approval state, and required/forbidden copy. `$TRACKING` and `$PREVIOUS_TRACKING` are substituted in copy checks.

## Limits

Carriers, orders, and email delivery are mocks, and "send" only marks a draft sent. The schema is plain SQL but only SQLite is wired up; Postgres is not implemented. The address-fix path reads a structured `Corrected address:` line from the ticket, where a real system would extract it with a model. The guard is pattern-based, so it is a strong tripwire, not a proof.

MIT licensed.
