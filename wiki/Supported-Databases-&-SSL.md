# Supported Databases & SSL/TLS Configuration

SchemaSense connects to relational and cloud database engines through hardened SQLAlchemy dialeting, bounded connection pooling, and enterprise SSL/TLS encryption.

---

## 1. Supported Relational Engines

| Database Engine | Supported Versions | Driver | Connection Scheme | Cloud Compatibility |
|---|---|---|---|---|
| **PostgreSQL** | 14, 15, 16 | `psycopg2-binary` | `postgresql+psycopg2://` | AWS RDS, Aurora, Azure Database for PostgreSQL, Google Cloud SQL, Supabase, Neon |
| **MySQL** | 8.0, 8.4 LTS | `pymysql` | `mysql+pymysql://` (`utf8mb4`) | AWS RDS MySQL, Azure Database for MySQL, Google Cloud SQL |
| **SQLite** | 3.x | In-process native | `sqlite:///` | Local database files (`.db`, `.sqlite`) and in-memory testing (`:memory:`) |

---

## 2. Cloud Database SSL/TLS Modes

Connecting to managed cloud databases requires transport-layer encryption. SchemaSense exposes 5 distinct SSL modes in the sidebar connection manager:

```
[SSL / TLS Encryption Mode]
  ├── disable     (Plaintext - isolated local docker networks only)
  ├── prefer      (Negotiate TLS if supported by server; fallback to plaintext)
  ├── require     (Enforce TLS; abort connection if server does not support TLS)
  ├── verify-ca   (Enforce TLS and verify server certificate against CA bundle)
  └── verify-full (Enforce TLS, verify CA bundle, and validate server hostname)
```

### PostgreSQL SSL Parameter Mapping
- When connecting with `require`, `verify-ca`, or `verify-full`, `sslmode` is automatically injected into the SQLAlchemy connection URL parameters.
- If a custom Root CA certificate path is provided, it is passed via `sslrootcert=/path/to/ca.pem`.

### MySQL SSL Parameter Mapping
- Uses PyMySQL's `ssl` connection arguments.
- Custom CA certificates are passed via `ssl={"ca": "/path/to/ca.pem"}`.

### Quick Setup for Managed Cloud Providers:
- **Supabase**: Set Host to `db.<project-ref>.supabase.co`, Port `5432` or `6543` (transaction pooler), and SSL Mode to `require`.
- **Neon**: Set Host to `ep-<name>.neon.tech`, Port `5432`, and SSL Mode to `require`.
- **AWS RDS / Aurora**: Set Host to your RDS endpoint URL, Port `5432` (PG) or `3306` (MySQL), and SSL Mode to `require` or `verify-full` using the AWS Global Trust Bundle.

---

## 3. Connection Pooling & Resource Isolation

To avoid exhausting database connection pools and file descriptors, SchemaSense enforces bounded pooling on all engines:

```python
engine = create_engine(
    url,
    poolclass=QueuePool,
    pool_size=5,          # Maximum persistent connections
    max_overflow=2,       # Maximum burst connections
    pool_timeout=10,      # Seconds before connection acquisition times out
    pool_pre_ping=True,   # Tests liveness with 'SELECT 1' before handing connection to query
    pool_recycle=1800,    # Recycle connections after 30 minutes
)
```

### Automatic Engine Cleanup & Garbage Collection
When an operator disconnects or switches databases, the application executes `schemasense.connection.dispose_engine()`, calling `engine.dispose()` to immediately close all active sockets, release backend worker threads, and reset session states.
