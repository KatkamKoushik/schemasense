# SchemaSense 2.0 Disaster Recovery & Operational Runbook

This document specifies the operational runbooks, disaster recovery procedures, database backup and restoration protocols, versioned migration rollback mechanisms, and dual-mode outage mitigation for SchemaSense 2.0.

---

## 1. Architecture Resilience & Outage Mitigation

SchemaSense 2.0 operates under a strict **Dual-Mode Deployment Contract**:

```
+-----------------------------------------------------------------------------------+
|                                  SCHEMASENSE_MODE                                 |
+-----------------------------------------+-----------------------------------------+
|        simple (Developer / Streamlit)   |        advanced (Enterprise Platform)   |
+-----------------------------------------+-----------------------------------------+
| * Zero external daemon dependencies     | * Distributed Celery + Redis workers    |
| * Synchronous in-process task execution | * Durable PostgreSQL platform state     |
| * Local SQLite or in-memory checkpointer| * AsyncPostgresSaver LangGraph state    |
| * Optional Rust native acceleration     | * Conjunction double-lock SQLGuard      |
| * Never touches network task queues     | * FAILS FAST on broker/worker outages   |
+-----------------------------------------+-----------------------------------------+
```

### Outage Policy Invariants
1. **Mandatory Correction 12 (No Silent Fallback)**:
   - When configured in **Advanced Mode** (`SCHEMASENSE_MODE=advanced`), if the distributed message broker (Redis) or worker queue is unreachable, the API gateway **strictly fails closed** with `HTTP 503 Service Unavailable` (`QueueUnavailableError`).
   - It **never** silently downgrades background tasks to synchronous in-process execution. Silent downgrades in production exhaust API event loops and worker thread pools, leading to cascading failures.
2. **Simple Mode Isolation**:
   - In **Simple Mode** (`SCHEMASENSE_MODE=simple`), execution runs synchronously in-process. No Celery, Redis, or PostgreSQL daemons are contacted.

---

## 2. Platform Database Backup & Point-in-Time Recovery

The SchemaSense 2.0 platform state database stores tenant metadata, user accounts, encrypted connection reference pointers, agent run records, and audit events.

### Automated Backup Procedure (PostgreSQL)

To perform a consistent, non-blocking logical backup of the platform database:

```bash
# Set secure environment
export PGPASSWORD="${SCHEMASENSE_DB_PASSWORD}"

# Execute snapshot backup using custom directory format with compression
pg_dump -h "${SCHEMASENSE_DB_HOST}" \
        -U "${SCHEMASENSE_DB_USER}" \
        -d "${SCHEMASENSE_DB_NAME}" \
        -F c \
        -b \
        -v \
        -f "/var/backups/schemasense/schemasense_platform_$(date +%Y%m%d_%H%M%S).dump"
```

### Point-in-Time Recovery (PITR) & Restore Procedure

In the event of database corruption or unintended data loss:

1. **Halt Application Gateway Traffic**:
   Drain incoming traffic by configuring the load balancer or setting the gateway readiness probe to unready.

2. **Restore from Snapshot**:
   ```bash
   # Drop existing active connections
   psql -h "${SCHEMASENSE_DB_HOST}" -U "${SCHEMASENSE_DB_USER}" -d postgres -c \
     "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${SCHEMASENSE_DB_NAME}' AND pid <> pg_backend_pid();"

   # Drop and recreate target database
   dropdb -h "${SCHEMASENSE_DB_HOST}" -U "${SCHEMASENSE_DB_USER}" "${SCHEMASENSE_DB_NAME}"
   createdb -h "${SCHEMASENSE_DB_HOST}" -U "${SCHEMASENSE_DB_USER}" -O "${SCHEMASENSE_DB_USER}" "${SCHEMASENSE_DB_NAME}"

   # Restore schema and data
   pg_restore -h "${SCHEMASENSE_DB_HOST}" \
              -U "${SCHEMASENSE_DB_USER}" \
              -d "${SCHEMASENSE_DB_NAME}" \
              -v \
              "/var/backups/schemasense/schemasense_platform_TARGET_SNAPSHOT.dump"
   ```

3. **Verify Database Integrity**:
   ```bash
   # Check current migration revision against codebase
   python -m schemasense.db.migrate check
   ```

---

## 3. Versioned Database Migration & Rollback Runbook

Alembic controls all platform database schema evolutions. As mandated by **Mandatory Correction 1**, automatic unvetted migrations are strictly forbidden during FastAPI application boot. All migrations must be explicitly verified and executed.

### Pre-Deployment Verification

Before applying any migration to production:
```bash
# 1. Inspect migration status and pending revisions
python -m schemasense.db.migrate check

# 2. Inspect SQL output without applying (dry run)
alembic upgrade head --sql
```

### Applying Migrations
```bash
# Apply forward migration
python -m schemasense.db.migrate upgrade head
```

### Rollback Procedures

If a deployment encounters issues or schema incompatibilities:

#### Rollback Single Revision (N - 1)
```bash
# Downgrade exactly one revision
python -m schemasense.db.migrate downgrade -1

# Verify status returns to expected previous revision
python -m schemasense.db.migrate check
```

#### Rollback to Base (Clean State)
```bash
# Revert all platform tables to base (use during disaster recovery testing only)
python -m schemasense.db.migrate downgrade base
```

---

## 4. Broker / Queue Outage Response Runbook

When Redis is down or network partitions occur:

1. **Symptom**:
   - `POST /api/v1/agent/runs` and `POST /api/v1/agent/profiling` return `HTTP 503 Service Unavailable`.
   - Error detail: `"Distributed task queue outage: Failed to enqueue agent run: ..."`
   - Gateway liveness (`/health/live`) remains HTTP 200, but readiness (`/health/ready`) reports broker degraded.

2. **Triage Steps**:
   ```bash
   # 1. Check Redis process & port
   redis-cli -u "${REDIS_URL}" ping

   # 2. Check Celery worker active status
   celery -A schemasense.tasks.celery_app inspect ping

   # 3. Inspect worker error logs and unacknowledged tasks
   celery -A schemasense.tasks.celery_app inspect active
   ```

3. **Mitigation**:
   - Restart Redis broker service.
   - Celery workers configured with `task_acks_late=True` and `task_reject_on_worker_lost=True` will automatically re-queue and process uncompleted tasks upon reconnecting.
   - Once Redis returns `PONG`, API endpoints automatically resume dispatching without restarting the FastAPI gateway.

---

## 5. Secret & Credential Rotation Protocol

SchemaSense 2.0 strictly enforces zero raw secret leakage (**Mandatory Correction 7**).

### JWT Secret Key Rotation
1. Deploy new application instances configured with the new key in `JWT_SECRET_KEY` and the retired key in `JWT_PREVIOUS_SECRET_KEY` (allowing grace periods for in-flight tokens).
2. Existing issued tokens remain verifiable until expiration (max TTL 3600 seconds).
3. After 1 hour, remove `JWT_PREVIOUS_SECRET_KEY`.

### Target Database Connection Rotation
1. Update database credentials in the secure vault or environment.
2. Invalidate cache in SchemaSense using:
   ```python
   from schemasense.agent.tools import clear_connection_engines
   clear_connection_engines()
   ```
3. Existing connections in the pool terminate cleanly; new requests establish fresh sessions using rotated credentials.

