# DocFlow architecture and data flow

## Module responsibilities

| Layer | Main files | Responsibility |
| --- | --- | --- |
| HTTP | `backend/app/api/routes/` | Parse JWT/path/query/body/header inputs and serialize responses |
| Schema/domain | `backend/app/models.py` | API contracts, enums, tables, constraints, and workflow vocabulary |
| Service | `backend/app/services/` | Tenant authorization, state transitions, concurrency checks, and transactions |
| Persistence | `backend/app/core/db.py`, Alembic | PostgreSQL engine/session and reproducible schema changes |
| Cache | `backend/app/core/cache.py` | Redis cache-aside access; failures degrade to PostgreSQL |
| Async work | `backend/app/workers/notifications.py` | Claim and deliver outbox notifications with bounded retry |
| Operations | `compose*.yml`, `.github/workflows/` | Repeatable local stack, isolated tests, and CI |

## Create and edit flow

1. FastAPI validates the JWT, organization UUID, body fields, and optional
   `Idempotency-Key` header.
2. The service confirms organization membership.
3. Creation writes the document, version 1, audit log, and idempotency record in
   one PostgreSQL transaction.
4. Editing locks the document row, verifies `expected_lock_version`, creates an
   immutable new version, increments the lock version, and invalidates Redis.
5. Reusing the same idempotency key and same payload returns the original
   document; a different payload returns HTTP 409.

## Approval flow

```text
draft --submit--> in_review --approve--> approved --archive--> archived
  ^                    |
  |                    +--reject-----> rejected --edit--> draft
  +------withdraw------+
```

- Illegal transitions return `409 INVALID_TRANSITION`.
- A submitter cannot approve their own document.
- An explicitly assigned reviewer must be a reviewer/admin/owner in the same
  organization.
- Every mutation checks `expected_lock_version`; stale clients receive 409
  instead of silently overwriting newer work.

## Consistency and failure handling

- PostgreSQL is the source of truth. Business changes and audit records share
  the same transaction.
- Review submission also inserts a notification outbox row in that transaction.
  The worker sends email later, so an SMTP outage cannot roll back an already
  accepted submission.
- Worker rows use `FOR UPDATE SKIP LOCKED`, allowing multiple workers without
  processing the same row simultaneously.
- Redis only accelerates reads. Cache errors are logged and ignored; mutations
  invalidate the affected key.
- Tests run only when the database name is `app_test`, preventing accidental
  cleanup of development data.

## Deliberate boundaries

- DocFlow is a modular monolith: one deployable backend keeps transactions and
  local development simple while modules retain clear ownership.
- Offset pagination is sufficient for this first production-ready version. A
  cursor can replace it when datasets and write rates make deep offsets costly.
- Notification delivery is at-least-once. A downstream provider idempotency key
  would be added before supporting non-idempotent notification channels.
- The bundled template frontend remains available, but DocFlow's assessed scope
  is the backend API and its operational reliability.
