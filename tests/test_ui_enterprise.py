from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

from schemasense.connection import dispose_engine

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


def test_ui_theme_selector():
    """Verifies that the theme selector switches themes cleanly across palettes."""
    at = AppTest.from_file(APP_PATH, default_timeout=20)
    at.run()
    assert not at.exception
    assert at.session_state.app_theme == "Obsidian Dark"

    # Theme selector is in the sidebar
    theme_select = next((s for s in at.sidebar.selectbox if "Theme" in s.label), None)
    assert theme_select is not None
    assert "Clean Light" in theme_select.options
    assert "Steel Gray" in theme_select.options
    assert "Deep Ocean Navy" in theme_select.options

    # Switch to Clean Light
    theme_select.select("Clean Light")
    at.run()
    assert not at.exception
    assert at.session_state.app_theme == "Clean Light"
    # Ensure Light theme CSS contains light background variable
    assert any("--bg-canvas: #F8FAFC" in m.value for m in at.markdown)

    # Re-query widget on new state and switch to Deep Ocean Navy
    theme_select = next((s for s in at.sidebar.selectbox if "Theme" in s.label), None)
    assert theme_select is not None
    theme_select.select("Deep Ocean Navy")
    at.run()
    assert not at.exception
    assert at.session_state.app_theme == "Deep Ocean Navy"
    assert any("--bg-canvas: #0A192F" in m.value for m in at.markdown)


def test_ui_provider_selection_options():
    """Verifies that multi-provider AI options (OpenAI, Anthropic, DeepSeek, Groq, Ollama) are selectable."""
    at = AppTest.from_file(APP_PATH, default_timeout=20)
    at.run()
    assert not at.exception

    provider_select = next(
        (s for s in at.sidebar.selectbox if "Backend Selection" in s.label), None
    )
    assert provider_select is not None
    options = provider_select.options
    assert "Google Gemini (Cloud)" in options
    assert "OpenAI" in options
    assert "Anthropic Claude" in options
    assert "DeepSeek" in options
    assert "Groq (Cloud)" in options
    assert "Ollama (Local Server)" in options
    assert "Custom OpenAI-Compatible Gateway" in options

    # Select OpenAI
    provider_select.select("OpenAI")
    at.run()
    assert not at.exception
    assert at.session_state["backend_mode_select"] == "OpenAI"

    # Re-query and select Anthropic Claude
    provider_select = next(
        (s for s in at.sidebar.selectbox if "Backend Selection" in s.label), None
    )
    assert provider_select is not None
    provider_select.select("Anthropic Claude")
    at.run()
    assert not at.exception
    assert at.session_state["backend_mode_select"] == "Anthropic Claude"


def test_ui_sqlite_connection_and_diff():
    """Verifies connecting to a local SQLite database and capturing a schema snapshot."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        db_path = tmp_db.name

    at = None
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL, created_at TIMESTAMP);"
        )
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL);"
        )
        conn.commit()
        conn.close()

        at = AppTest.from_file(APP_PATH, default_timeout=20)
        at.run()

        # Select SQLite as DB type
        db_type_select = next(
            (s for s in at.sidebar.selectbox if "Database Engine" in s.label), None
        )
        assert db_type_select is not None
        db_type_select.select("SQLite")
        at.run()

        # Enter SQLite DB file path
        path_input = next(
            (t for t in at.sidebar.text_input if "Database File Path" in t.label), None
        )
        assert path_input is not None
        path_input.input(db_path)
        at.run()

        # Click Connect
        connect_btn = next(
            (
                b
                for b in at.sidebar.button
                if "Connect Database" in b.label or "Connect" in b.label
            ),
            None,
        )
        assert connect_btn is not None
        connect_btn.click()
        at.run()

        assert not at.exception
        assert at.session_state.db_engine is not None
        assert at.session_state.db_type == "SQLite"
        assert at.session_state.db_schema is not None
        assert "users" in at.session_state.db_schema.tables
        assert "orders" in at.session_state.db_schema.tables

        # Check Schema Evolution tab: capture snapshot button
        snap_btn = next(
            (b for b in at.button if "Capture Schema Snapshot" in b.label), None
        )
        assert snap_btn is not None
        snap_btn.click()
        at.run()
        assert not at.exception
        assert len(at.session_state.schema_snapshots) >= 1

    finally:
        if (
            at is not None
            and "db_engine" in at.session_state
            and at.session_state["db_engine"] is not None
        ):
            dispose_engine(at.session_state.db_engine)
        Path(db_path).unlink(missing_ok=True)


def test_ui_enterprise_auth_gate_locking_and_unlocking(monkeypatch):
    """Verifies that setting SCHEMASENSE_ACCESS_KEY engages the auth gate until unlocked."""
    monkeypatch.setenv("SCHEMASENSE_ACCESS_KEY", "super-secret-enterprise-token")

    at = AppTest.from_file(APP_PATH, default_timeout=20)
    at.run()
    assert not at.exception

    # In locked mode, the gate card and password input are present
    assert any("Enterprise Security Key" in t.label for t in at.text_input)
    # The normal sidebar database engine selection is NOT rendered
    assert not any("Database Engine" in s.label for s in at.sidebar.selectbox)

    # Attempt wrong password
    auth_input = next(t for t in at.text_input if "Enterprise Security Key" in t.label)
    auth_input.input("wrong-password")
    submit_btn = next(b for b in at.button if "Verify & Enter Console" in b.label)
    submit_btn.click()
    at.run()
    assert any("Access Denied" in e.value for e in at.error)

    # Supply correct token
    auth_input = next(t for t in at.text_input if "Enterprise Security Key" in t.label)
    auth_input.input("super-secret-enterprise-token")
    submit_btn = next(b for b in at.button if "Verify & Enter Console" in b.label)
    submit_btn.click()
    at.run()
    assert not at.exception
    assert at.session_state.authenticated is True
    # Now the console is unlocked and sidebar is available
    assert any("Database Engine" in s.label for s in at.sidebar.selectbox)


def test_ui_production_fail_closed_without_auth(monkeypatch):
    """Verifies that SCHEMASENSE_ENV=production halts with a critical error if no auth is configured."""
    monkeypatch.setenv("SCHEMASENSE_ENV", "production")
    monkeypatch.delenv("SCHEMASENSE_ACCESS_KEY", raising=False)
    monkeypatch.delenv("SCHEMASENSE_AUTH_KEY", raising=False)
    monkeypatch.delenv("SCHEMASENSE_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)

    from unittest.mock import patch

    with patch("schemasense.auth.is_oauth_configured", return_value=False):
        at = AppTest.from_file(APP_PATH, default_timeout=20)
        at.run()

    # In production without auth, an error must be displayed and execution stopped
    assert any("CRITICAL SECURITY CONFIGURATION ERROR" in e.value for e in at.error)


def test_ui_local_operator_evaluation_unlock_and_lock_cycle(monkeypatch):
    """Verifies that in non-production environments, the evaluation unlock button
    allows local testing, sets session identity, and permits re-locking the console."""
    monkeypatch.setenv("SCHEMASENSE_ACCESS_KEY", "prod-token-12345")
    monkeypatch.setenv("SCHEMASENSE_ENV", "development")

    at = AppTest.from_file(APP_PATH, default_timeout=20)
    at.run()
    assert not at.exception
    assert (
        "authenticated" not in at.session_state
        or at.session_state["authenticated"] is False
    )

    # Evaluation button is visible in non-prod
    eval_btn = next(
        (b for b in at.button if "Continue as Local Operator" in b.label), None
    )
    assert eval_btn is not None

    # Click evaluation button to unlock
    eval_btn.click()
    at.run()
    assert not at.exception
    assert at.session_state.authenticated is True
    assert at.session_state.session_locked is False
    assert at.session_state.auth_user == "Local Operator"
    assert at.session_state.auth_method == "Evaluation Mode (Local)"

    # Verify Operator Identity card in sidebar
    sidebar_md_values = [m.value for m in at.sidebar.markdown]
    assert any(
        "Operator Identity" in v and "Local Operator" in v for v in sidebar_md_values
    )
    assert any("Evaluation Mode (Local)" in v for v in sidebar_md_values)

    # Verify Lock Console button is present in sidebar
    assert any("Lock Console / Open Login Gate" in b.label for b in at.sidebar.button)

    # Now verify in production mode the evaluation button is completely hidden
    monkeypatch.setenv("SCHEMASENSE_ENV", "production")
    at_prod = AppTest.from_file(APP_PATH, default_timeout=20)
    at_prod.run()
    assert not any("Continue as Local Operator" in b.label for b in at_prod.button)
