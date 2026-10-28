"""Database connection lifecycle, least-privilege inspection, and safe URL creation."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

logger = logging.getLogger("schemasense.connection")


class ConnectionConfigError(ValueError):
    """Raised when connection parameters are missing or invalid."""


class DriverMissingError(ImportError):
    """Raised when a required DBAPI driver is not installed."""


class DatabaseConnectionError(RuntimeError):
    """Raised when connection to database server fails."""


class PrivilegedAccountError(PermissionError):
    """Raised when an operation requires a least-privilege account but a privileged account is detected."""


class SSRFProtectionError(ValueError):
    """Raised when a target database host points to prohibited cloud metadata or restricted network ranges."""


class ConcurrencyLimitExceeded(RuntimeError):
    """Raised when active database query concurrency budget is exhausted."""


SUPPORTED_DIALECTS = {
    "PostgreSQL": "postgresql+psycopg2",
    "MySQL": "mysql+pymysql",
    "SQLite": "sqlite",
}

# ─────────────────────────────────────────────────────────────
# RESOURCE BOUNDING: APPLICATION QUERY CONCURRENCY
# ─────────────────────────────────────────────────────────────

MAX_CONCURRENT_QUERIES = 4
QUERY_CONCURRENCY_TIMEOUT_SEC = 5.0
_QUERY_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_QUERIES)


@contextmanager
def acquire_query_budget(timeout_sec: float = QUERY_CONCURRENCY_TIMEOUT_SEC):
    """Context manager enforcing bounded database query concurrency across application threads."""
    acquired = _QUERY_SEMAPHORE.acquire(timeout=timeout_sec)
    if not acquired:
        raise ConcurrencyLimitExceeded(
            f"Query concurrency limit of {MAX_CONCURRENT_QUERIES} active executions reached. "
            "Please wait for in-flight queries to finish."
        )
    try:
        yield
    finally:
        _QUERY_SEMAPHORE.release()


# ─────────────────────────────────────────────────────────────
# LEAST-PRIVILEGE ACCOUNT INSPECTION
# ─────────────────────────────────────────────────────────────


@dataclass
class AccountPrivilegeReport:
    """Report detailing database-level permissions and least-privilege adherence."""

    is_privileged: bool
    reasons: list[str] = field(default_factory=list)
    current_user: str = "unknown"
    db_type: str = ""

    @property
    def summary(self) -> str:
        if not self.is_privileged:
            return (
                f"Verified: Connected with least-privilege role '{self.current_user}'."
            )
        return (
            f"Privileged database account detected for '{self.current_user}': "
            + "; ".join(self.reasons)
            + ". Use a restricted read-only account (e.g. 'schemasense_readonly')."
        )


def inspect_account_privileges(
    engine: Engine, db_type: str = "PostgreSQL"
) -> AccountPrivilegeReport:
    """
    Inspects database engine catalogs and grants to detect superuser or excessive administrative privileges.
    Does NOT rely on username heuristics (e.g., 'admin' or 'root' string matching).
    """
    clean_type = db_type.strip()
    reasons: list[str] = []
    current_user = "unknown"

    with engine.connect() as conn:
        if clean_type.lower() in ("postgresql", "postgres"):
            try:
                current_user = (
                    conn.execute(text("SELECT CURRENT_USER")).scalar() or "unknown"
                )
            except (SQLAlchemyError, DBAPIError):
                pass

            # 1. Check PostgreSQL runtime setting
            try:
                is_super = (
                    conn.execute(
                        text("SELECT current_setting('is_superuser')")
                    ).scalar()
                    == "on"
                )
                if is_super:
                    reasons.append(
                        "PostgreSQL superuser status is active (current_setting('is_superuser') = 'on')"
                    )
            except (SQLAlchemyError, DBAPIError):
                pass

            # 2. Check pg_roles attributes
            try:
                role_row = conn.execute(
                    text(
                        "SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = CURRENT_USER"
                    )
                ).fetchone()
                if role_row:
                    if role_row[0]:
                        reasons.append("Superuser role flag (rolsuper = true)")
                    if role_row[1]:
                        reasons.append(
                            "Role creation permission (rolcreaterole = true)"
                        )
                    if role_row[2]:
                        reasons.append(
                            "Database creation permission (rolcreatedb = true)"
                        )
            except (SQLAlchemyError, DBAPIError):
                pass

            # 3. Check database-level CREATE privilege
            try:
                can_create = conn.execute(
                    text(
                        "SELECT has_database_privilege(CURRENT_USER, current_database(), 'CREATE')"
                    )
                ).scalar()
                if can_create:
                    reasons.append(
                        "Database modification permission (CREATE on current database)"
                    )
            except (SQLAlchemyError, DBAPIError):
                pass

            return AccountPrivilegeReport(
                is_privileged=len(reasons) > 0,
                reasons=list(dict.fromkeys(reasons)),
                current_user=str(current_user),
                db_type="PostgreSQL",
            )

        elif clean_type.lower() == "mysql":
            try:
                current_user = (
                    conn.execute(text("SELECT CURRENT_USER()")).scalar() or "unknown"
                )
            except (SQLAlchemyError, DBAPIError):
                pass

            try:
                grants = [
                    row[0] for row in conn.execute(text("SHOW GRANTS")).fetchall()
                ]
                for grant in grants:
                    g_upper = grant.upper()
                    if (
                        "ALL PRIVILEGES ON *.*" in g_upper
                        or "ALL PRIVILEGES ON `*`.*" in g_upper
                    ):
                        reasons.append(
                            "Global ALL PRIVILEGES on entire MySQL server (*.*)"
                        )
                    elif "ALL PRIVILEGES" in g_upper:
                        reasons.append("Database-wide ALL PRIVILEGES")
                    if "SUPER" in g_upper:
                        reasons.append("SUPER administrative privilege")
                    if "SYSTEM_VARIABLES_ADMIN" in g_upper:
                        reasons.append("SYSTEM_VARIABLES_ADMIN privilege")
                    if "SHUTDOWN" in g_upper:
                        reasons.append("Server SHUTDOWN privilege")
                    if "WITH GRANT OPTION" in g_upper:
                        reasons.append("Privilege delegation (WITH GRANT OPTION)")
                    if (
                        "INSERT" in g_upper
                        or "UPDATE" in g_upper
                        or "DELETE" in g_upper
                        or "DROP" in g_upper
                    ) and "ON *.*" in g_upper:
                        reasons.append("Global write privileges on all databases (*.*)")
            except (SQLAlchemyError, DBAPIError) as e:
                logger.warning(f"Failed to inspect MySQL grants: {e}")

            return AccountPrivilegeReport(
                is_privileged=len(reasons) > 0,
                reasons=list(dict.fromkeys(reasons)),
                current_user=str(current_user),
                db_type="MySQL",
            )

        else:
            # SQLite / embedded
            return AccountPrivilegeReport(
                is_privileged=False,
                reasons=[],
                current_user="local_file",
                db_type="SQLite",
            )


# ─────────────────────────────────────────────────────────────
# SSRF & NETWORK BOUNDARY DEFENSE
# ─────────────────────────────────────────────────────────────

# Unconditionally blocked IP networks across all environments
ALWAYS_BLOCKED_NETWORKS = [
    ipaddress.ip_network("169.254.0.0/16"),  # IPv4 Link-local
    ipaddress.ip_network("fe80::/10"),  # IPv6 Link-local
    ipaddress.ip_network("224.0.0.0/4"),  # IPv4 Multicast
    ipaddress.ip_network("ff00::/8"),  # IPv6 Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
    ipaddress.ip_network("0.0.0.0/8"),  # Unspecified IPv4
    ipaddress.ip_network("::/128"),  # Unspecified IPv6
]

# Explicit Cloud Metadata IP Endpoints
CLOUD_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure IMDSv1/v2
    ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud IMDS
    ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDSv6
}

# Cloud Metadata Hostname substrings
BLOCKED_METADATA_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
    "100.100.100.200",
}

# RFC 1918 / RFC 4193 Private Networks
RFC_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 Unique Local
]

LOOPBACK_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]


def validate_database_host(
    host: str,
    port: int = 0,
    resolve_dns: bool = False,
    allow_private: bool | None = None,
    allow_local: bool | None = None,
    allowed_cidrs: list[str] | None = None,
) -> tuple[str, list[str]]:
    """
    Validates target database host against SSRF, cloud metadata, and prohibited network ranges.
    Deployment-aware: enables legitimate enterprise private network connections while strictly
    blocking cloud metadata endpoints across all environments.

    Returns:
        tuple[str, list[str]]: (normalized_host, list of verified resolved IP strings)
    """
    clean_host = str(host or "").strip().lower()
    if not clean_host:
        raise ConnectionConfigError("Database host cannot be empty.")

    # 1. String-level metadata check
    for blocked in BLOCKED_METADATA_HOSTS:
        if clean_host == blocked or clean_host.endswith(f".{blocked}"):
            raise SSRFProtectionError(
                f"Connection rejected: Host '{clean_host}' is a prohibited cloud metadata endpoint."
            )

    is_prod = (
        os.getenv("SCHEMASENSE_ENV", "").lower() == "production"
        or os.getenv("ENVIRONMENT", "").lower() == "production"
    )

    # 2. Check if clean_host is a direct IP literal
    direct_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    try:
        # Strip IPv6 brackets if present
        ip_str = clean_host.strip("[]")
        direct_ip = ipaddress.ip_address(ip_str)
    except ValueError:
        pass

    verified_ips: list[str] = []

    if direct_ip is not None:
        ips_to_check = [direct_ip]
        verified_ips.append(str(direct_ip))
    elif resolve_dns:
        try:
            addr_info = socket.getaddrinfo(
                clean_host, port or 5432, proto=socket.IPPROTO_TCP
            )
            for res in addr_info:
                sockaddr = res[4]
                ip_cand = sockaddr[0]
                try:
                    ips_to_check_obj = ipaddress.ip_address(ip_cand)
                    if str(ips_to_check_obj) not in verified_ips:
                        verified_ips.append(str(ips_to_check_obj))
                except ValueError:
                    continue
            ips_to_check = [ipaddress.ip_address(ip) for ip in verified_ips]
        except (socket.gaierror, OSError) as err:
            logger.debug(f"DNS pre-resolution failed for host '{clean_host}': {err}")
            ips_to_check = []
    else:
        ips_to_check = []

    # Evaluate each IP against policies
    for ip in ips_to_check:
        # Unconditionally block cloud metadata
        if ip in CLOUD_METADATA_IPS:
            raise SSRFProtectionError(
                f"SSRF Protection: IP address '{ip}' is a prohibited cloud metadata service."
            )

        # Unconditionally block link-local and multicast
        for net in ALWAYS_BLOCKED_NETWORKS:
            if ip in net:
                raise SSRFProtectionError(
                    f"SSRF Protection: IP address '{ip}' belongs to prohibited subnet '{net}'."
                )

        # Loopback policy
        is_loopback = any(ip in net for net in LOOPBACK_NETWORKS)
        if is_loopback:
            local_allowed = allow_local
            if local_allowed is None:
                local_allowed = os.getenv("SCHEMASENSE_ALLOW_LOCAL_DB", "").lower() in (
                    "true",
                    "1",
                    "yes",
                )
            if is_prod and not local_allowed:
                raise SSRFProtectionError(
                    f"SSRF Protection: Loopback connections ('{ip}') are forbidden in production mode. "
                    "Set SCHEMASENSE_ALLOW_LOCAL_DB=true to permit local database connections."
                )

        # Private RFC network policy (Deployment-aware)
        is_private = any(ip in net for net in RFC_PRIVATE_NETWORKS)
        if is_private and is_prod:
            priv_allowed = allow_private
            if priv_allowed is None:
                # Default to true for enterprise internal VPC deployments
                priv_allowed = os.getenv(
                    "SCHEMASENSE_ALLOW_PRIVATE_IPS", "true"
                ).lower() in ("true", "1", "yes")
            if not priv_allowed:
                # Check explicit CIDR allowlist
                configured_cidrs = allowed_cidrs or []
                if not configured_cidrs and (
                    env_cidrs := os.getenv("SCHEMASENSE_ALLOWED_DB_CIDRS")
                ):
                    configured_cidrs = [
                        c.strip() for c in env_cidrs.split(",") if c.strip()
                    ]

                allowed = False
                for c_str in configured_cidrs:
                    try:
                        if ip in ipaddress.ip_network(c_str):
                            allowed = True
                            break
                    except ValueError:
                        continue

                if not allowed:
                    raise SSRFProtectionError(
                        f"SSRF Protection: Connection to private IP '{ip}' is blocked by policy. "
                        "Add CIDR to SCHEMASENSE_ALLOWED_DB_CIDRS or set SCHEMASENSE_ALLOW_PRIVATE_IPS=true."
                    )

    return clean_host, verified_ips


# ─────────────────────────────────────────────────────────────
# SAFE CONNECTION & POOL MANAGEMENT
# ─────────────────────────────────────────────────────────────


def build_safe_url(
    db_type: str,
    host: str = "",
    port: int | str = 0,
    db_name: str = "",
    user: str = "",
    password: str = "",
    ssl_mode: str = "prefer",
) -> URL:
    """Build a safe SQLAlchemy URL object without raw string concatenation."""
    if db_type not in SUPPORTED_DIALECTS:
        raise ConnectionConfigError(
            f"Unsupported database type '{db_type}'. Supported: {', '.join(SUPPORTED_DIALECTS.keys())}"
        )

    if db_type == "SQLite":
        clean_db = str(db_name or "").strip()
        return URL.create(drivername="sqlite", database=clean_db if clean_db else None)

    if not all([host, db_name, user, password]):
        raise ConnectionConfigError(
            "Host, database name, username, and password are all required."
        )

    try:
        clean_port = int(str(port).strip())
        if clean_port <= 0 or clean_port > 65535:
            raise ValueError()
    except (ValueError, TypeError):
        raise ConnectionConfigError(
            f"Port must be an integer between 1 and 65535 (got '{port}')"
        )

    driver = SUPPORTED_DIALECTS[db_type]
    clean_host, _ = validate_database_host(host, port=clean_port, resolve_dns=False)
    clean_db = str(db_name).strip()
    clean_user = str(user).strip()

    query_params = {}
    if db_type == "MySQL":
        query_params["charset"] = "utf8mb4"
    if ssl_mode and ssl_mode.lower() not in ("disable", "none", "off"):
        if db_type == "PostgreSQL":
            query_params["sslmode"] = ssl_mode.lower()

    return URL.create(
        drivername=driver,
        username=clean_user,
        password=str(password),
        host=clean_host,
        port=clean_port,
        database=clean_db,
        query=query_params,
    )


def create_safe_engine(
    db_type: str,
    host: str = "",
    port: int | str = 0,
    db_name: str = "",
    user: str = "",
    password: str = "",
    connect_timeout: int = 10,
    enforce_least_privilege: bool = False,
    ssl_mode: str = "prefer",
) -> Engine:
    """
    Creates a configured SQLAlchemy Engine with bounded connection pool and connection validation.

    Args:
        db_type: Database type ('PostgreSQL', 'MySQL', 'SQLite')
        host: Host IP or hostname
        port: Port number
        db_name: Database name
        user: Username
        password: Password
        connect_timeout: Network connect timeout in seconds
        enforce_least_privilege: If True, rejects privileged accounts with PrivilegedAccountError
        ssl_mode: SSL encryption mode for cloud databases (AWS RDS, Azure, GCP Cloud SQL, Supabase)
    """
    # Validate host destination with DNS resolution check
    verified_ips: list[str] = []
    if db_type in ("PostgreSQL", "MySQL") and host:
        _, verified_ips = validate_database_host(
            host, port=int(port or 0), resolve_dns=True
        )

    url = build_safe_url(
        db_type, host, port, db_name, user, password, ssl_mode=ssl_mode
    )

    connect_args = {}
    if db_type in ("PostgreSQL", "MySQL"):
        connect_args["connect_timeout"] = connect_timeout
    # Pin verified IP address for PostgreSQL to eliminate TOCTOU / DNS rebinding risks
    if db_type == "PostgreSQL" and verified_ips:
        connect_args["hostaddr"] = verified_ips[0]
    if db_type == "MySQL":
        connect_args.update(
            {
                "read_timeout": connect_timeout * 3,
                "write_timeout": connect_timeout * 3,
            }
        )
        if ssl_mode and ssl_mode.lower() not in ("disable", "none", "off"):
            mode_upper = ssl_mode.upper()
            if mode_upper in ("REQUIRE", "REQUIRED"):
                connect_args["ssl"] = {"ssl_mode": "REQUIRED"}
            elif mode_upper in ("VERIFY-CA", "VERIFY_CA"):
                connect_args["ssl"] = {"ssl_mode": "VERIFY_CA"}
            elif mode_upper in ("VERIFY-FULL", "VERIFY_IDENTITY"):
                connect_args["ssl"] = {"ssl_mode": "VERIFY_IDENTITY"}

    # Bounded pool parameters for networked databases
    pool_kwargs = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
    if db_type in ("PostgreSQL", "MySQL"):
        pool_kwargs.update(
            {
                "pool_size": 5,
                "max_overflow": 2,
                "pool_timeout": 10,
            }
        )

    try:
        engine = create_engine(
            url,
            connect_args=connect_args,
            **pool_kwargs,
        )
        # Test connection immediately
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        # Inspect and attach privilege report
        report = inspect_account_privileges(engine, db_type=db_type)
        engine._schemasense_privilege_report = report

        if enforce_least_privilege and report.is_privileged:
            dispose_engine(engine)
            raise PrivilegedAccountError(f"Connection rejected: {report.summary}")

        return engine

    except ImportError as ie:
        err = str(ie).lower()
        if "pymysql" in err:
            raise DriverMissingError(
                "MySQL driver (pymysql) is missing. Install via: pip install pymysql"
            ) from ie
        if "psycopg2" in err:
            raise DriverMissingError(
                "PostgreSQL driver (psycopg2) is missing. Install via: pip install psycopg2-binary"
            ) from ie
        raise
    except PrivilegedAccountError:
        raise
    except SQLAlchemyError as se:
        # Avoid leaking full passwords in error messages
        err_msg = str(se)
        if str(password) in err_msg and password:
            err_msg = err_msg.replace(str(password), "********")
        raise DatabaseConnectionError(f"Database connection failed: {err_msg}") from se


def dispose_engine(engine: Engine | None) -> None:
    """Safely disposes an existing SQLAlchemy engine to close all pool sockets."""
    if engine is not None:
        try:
            engine.dispose()
            logger.info("Successfully disposed database engine connection pool.")
        except (SQLAlchemyError, RuntimeError) as e:
            logger.warning(f"Error disposing database engine: {e}")
