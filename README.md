# DocFlow

DocFlow is a multi-tenant document approval backend. It turns document editing,
review, approval, notification, and auditing into one traceable workflow instead
of a collection of disconnected CRUD endpoints.

The repository is adapted from the MIT-licensed
[Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template).
DocFlow's domain model, organization RBAC, approval workflow, version control,
audit trail, Redis cache, notification outbox, idempotency, and isolated test
environment are project-specific additions.

## Core capabilities

- JWT authentication and secure password hashing
- Organization-level multi-tenancy with owner/admin/reviewer/member roles
- Document CRUD, keyword filtering, pagination, and immutable version history
- State machine: draft -> in_review -> approved/rejected, plus withdraw/archive
- Optimistic concurrency control through `lock_version`
- Idempotent document creation through the `Idempotency-Key` header
- Tenant-scoped audit logs for sensitive operations
- Redis cache-aside reads with fail-open degradation
- Transactional notification outbox and retrying background worker
- PostgreSQL migrations with Alembic upgrade and downgrade verification
- Request IDs, key-value request logs, and health checks
- Isolated Docker test database; tests refuse to use the development database

## Architecture

```text
Client
  -> Traefik
  -> FastAPI route (authentication + validation)
  -> service layer (tenant permission + state transition + transaction)
  -> PostgreSQL (business source of truth + audit + outbox)
  -> Redis (read cache, optional/fail-open)

Notification worker
  -> claims outbox row
  -> sends email
  -> records success or retry state
```

See [docs/architecture.md](docs/architecture.md) for the data flow, state
transitions, consistency strategy, and interview-oriented design decisions.

## Run locally

1. Copy `.env.example` to `.env` and replace all placeholder secrets.
2. Start the stack:

   ```powershell
   docker compose up -d --build
   ```

3. Apply migrations and bootstrap the initial administrator:

   ```powershell
   docker compose exec backend bash scripts/prestart.sh
   ```

4. Open:

   - API documentation: <http://localhost:8000/docs>
   - Mailpit: <http://localhost:8025>
   - Adminer: <http://localhost:8080>
   - Traefik dashboard: <http://localhost:8090>

## Verification

Run the backend against disposable PostgreSQL and Redis services:

```powershell
.\scripts\test-backend-isolated.ps1
```

The script validates Alembic upgrade/downgrade reversibility, runs the backend
test suite, then removes the disposable containers and volumes.

Lint the backend:

```powershell
docker compose run --rm --no-deps backend ruff check app tests
```

## Important API paths

- `POST /api/v1/login/access-token`
- `POST /api/v1/organizations/`
- `GET|POST /api/v1/organizations/{organization_id}/members`
- `GET|POST /api/v1/organizations/{organization_id}/documents/`
- `PATCH /api/v1/organizations/{organization_id}/documents/{document_id}`
- `POST .../{document_id}/submit|approve|reject|withdraw|archive`
- `GET /api/v1/organizations/{organization_id}/audit-logs/`
- `GET /api/v1/utils/health-check/`

## License

MIT. See [LICENSE](LICENSE).
