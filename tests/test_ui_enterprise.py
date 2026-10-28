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
