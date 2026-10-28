from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import streamlit as st

from schemasense.ai_agent import (
    AIAgentError,
    AIProviderError,
    AIQuotaExceededError,
    AITimeoutError,
    SchemaSenseAIAgent,
    extract_sql_from_text,
    get_session_agent,
    load_api_keys,
    verify_schema_fidelity,
)
from schemasense.connection import (
    AccountPrivilegeReport,
    ConnectionConfigError,
    DatabaseConnectionError,
    DriverMissingError,
    PrivilegedAccountError,
    create_safe_engine,
    dispose_engine,
    inspect_account_privileges,
)
from schemasense.profiler import (
    build_safe_profiling_query,
    profile_dataframe,
)
from schemasense.rules_engine import (
    PDFIngestionError,
    extract_rules_from_pdf,
    format_rules_for_prompt,
)
from schemasense.schema_inspector import (
    diff_database_schemas,
    inspect_database_schema,
)
from schemasense.sql_guard import (
    QueryExecutionError,
    QueryTimeoutError,
    SQLGuard,
    SQLSecurityViolation,
    execute_safe_query,
)

# ──────────────────────────────────────────────
# CORE CONFIGURATION & PAGE METADATA
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="SchemaSense — Enterprise Database Intelligence & Security Console",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# ENTERPRISE THEMES PALETTES
# ──────────────────────────────────────────────
THEMES = {
    "Obsidian Dark": {
        "name": "Obsidian Dark",
        "bg_canvas": "#080B12",
        "bg_surface": "#0E1424",
        "bg_panel": "#11192C",
        "border_subtle": "rgba(148, 163, 184, 0.14)",
        "border_active": "rgba(56, 189, 248, 0.3)",
        "accent_cyan": "#38BDF8",
        "accent_cyan_hover": "#0EA5E9",
        "accent_violet": "#8B5CF6",
        "accent_emerald": "#10B981",
        "accent_amber": "#F59E0B",
        "accent_rose": "#F43F5E",
        "text_primary": "#F8FAFC",
        "text_secondary": "#94A3B8",
        "text_muted": "#64748B",
        "header_bg": "linear-gradient(180deg, #10182D 0%, #0C1220 100%)",
        "sidebar_bg": "#0A0F1B",
        "card_bg": "#0D1527",
        "chip_bg": "rgba(17, 25, 44, 0.85)",
    },
    "Clean Light": {
        "name": "Clean Light",
        "bg_canvas": "#F8FAFC",
        "bg_surface": "#FFFFFF",
        "bg_panel": "#F1F5F9",
        "border_subtle": "rgba(148, 163, 184, 0.28)",
        "border_active": "rgba(2, 132, 199, 0.4)",
        "accent_cyan": "#0284C7",
        "accent_cyan_hover": "#0369A1",
        "accent_violet": "#7C3AED",
        "accent_emerald": "#059669",
        "accent_amber": "#D97706",
        "accent_rose": "#E11D48",
        "text_primary": "#0F172A",
        "text_secondary": "#334155",
        "text_muted": "#64748B",
        "header_bg": "linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%)",
        "sidebar_bg": "#FFFFFF",
        "card_bg": "#FFFFFF",
        "chip_bg": "#F1F5F9",
    },
    "Steel Gray": {
        "name": "Steel Gray",
        "bg_canvas": "#1E293B",
        "bg_surface": "#334155",
        "bg_panel": "#475569",
        "border_subtle": "rgba(255, 255, 255, 0.14)",
        "border_active": "rgba(56, 189, 248, 0.4)",
        "accent_cyan": "#38BDF8",
        "accent_cyan_hover": "#0EA5E9",
        "accent_violet": "#A78BFA",
        "accent_emerald": "#34D399",
        "accent_amber": "#FBBF24",
        "accent_rose": "#FB7185",
        "text_primary": "#F8FAFC",
        "text_secondary": "#CBD5E1",
        "text_muted": "#94A3B8",
        "header_bg": "linear-gradient(180deg, #334155 0%, #1E293B 100%)",
        "sidebar_bg": "#182234",
        "card_bg": "#273549",
        "chip_bg": "rgba(51, 65, 85, 0.85)",
    },
    "Deep Ocean Navy": {
        "name": "Deep Ocean Navy",
        "bg_canvas": "#0A192F",
        "bg_surface": "#112240",
        "bg_panel": "#1E3A5F",
        "border_subtle": "rgba(100, 255, 218, 0.2)",
        "border_active": "rgba(100, 255, 218, 0.5)",
        "accent_cyan": "#64FFDA",
        "accent_cyan_hover": "#4CD6B3",
        "accent_violet": "#9D4EDD",
        "accent_emerald": "#2EC4B6",
        "accent_amber": "#FF9F1C",
        "accent_rose": "#E71D36",
        "text_primary": "#E6F1FF",
        "text_secondary": "#8892B0",
        "text_muted": "#64748B",
        "header_bg": "linear-gradient(180deg, #112240 0%, #0A192F 100%)",
        "sidebar_bg": "#071324",
        "card_bg": "#0F2644",
        "chip_bg": "rgba(17, 34, 64, 0.85)",
    },
}

if "app_theme" not in st.session_state:
    st.session_state.app_theme = "Obsidian Dark"

curr_theme = THEMES.get(st.session_state.app_theme, THEMES["Obsidian Dark"])

# ──────────────────────────────────────────────
# DYNAMIC THEMED STYLING INJECTION
# ──────────────────────────────────────────────
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {{
    --bg-canvas: {curr_theme["bg_canvas"]};
    --bg-surface: {curr_theme["bg_surface"]};
    --bg-panel: {curr_theme["bg_panel"]};
    --border-subtle: {curr_theme["border_subtle"]};
    --border-active: {curr_theme["border_active"]};
    --accent-cyan: {curr_theme["accent_cyan"]};
    --accent-cyan-hover: {curr_theme["accent_cyan_hover"]};
    --accent-violet: {curr_theme["accent_violet"]};
    --accent-emerald: {curr_theme["accent_emerald"]};
    --accent-amber: {curr_theme["accent_amber"]};
    --accent-rose: {curr_theme["accent_rose"]};
    --text-primary: {curr_theme["text_primary"]};
    --text-secondary: {curr_theme["text_secondary"]};
    --text-muted: {curr_theme["text_muted"]};
}}

html, body, [class*="css"] {{
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    letter-spacing: -0.01em;
}}

code, kbd, samp, pre, .stCodeBlock, [data-testid="stCode"] {{
    font-family: 'JetBrains Mono', monospace !important;
}}

[data-testid="stAppViewContainer"] {{
    background-color: var(--bg-canvas) !important;
    color: var(--text-primary) !important;
}}

[data-testid="stSidebar"] {{
    background-color: {curr_theme["sidebar_bg"]} !important;
    border-right: 1px solid var(--border-subtle) !important;
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
    gap: 0.75rem;
}}

[data-testid="stHeader"] {{
    background: transparent !important;
}}

.block-container {{
    padding-top: 1.25rem !important;
    padding-bottom: 2.5rem !important;
    max-width: 1440px !important;
}}

/* Form inputs & text fields adapt cleanly across light/dark */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, [data-testid="stSelectbox"] div[data-baseweb="select"] {{
    color: var(--text-primary) !important;
    background-color: var(--bg-surface) !important;
    border-color: var(--border-subtle) !important;
}}

/* SECURITY CONSOLE HEADER */
.console-header {{
    background: {curr_theme["header_bg"]};
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
    padding: 1rem 1.4rem;
    margin-bottom: 1.25rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.75rem;
    box-shadow: 0 4px 16px -4px rgba(0, 0, 0, 0.15);
}}

.console-brand-group {{
    display: flex;
    align-items: baseline;
    gap: 12px;
}}

.console-brand-title {{
    font-size: 1.35rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: var(--text-primary);
    margin: 0;
    line-height: 1;
}}

.console-brand-subtitle {{
    font-size: 0.78rem;
    color: var(--text-muted);
    font-weight: 500;
}}

.console-badges {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}}

.console-badge {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 4px;
    background: {curr_theme["chip_bg"]};
    border: 1px solid var(--border-subtle);
    color: var(--text-secondary);
    display: inline-flex;
    align-items: center;
    gap: 6px;
}}

.status-dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    display: inline-block;
}}

.dot-green {{
    background-color: var(--accent-emerald);
    box-shadow: 0 0 6px var(--accent-emerald);
}}

.dot-gray {{
    background-color: var(--text-muted);
}}

.badge-connected {{
    background: rgba(16, 185, 129, 0.12) !important;
    color: var(--accent-emerald) !important;
    border: 1px solid rgba(16, 185, 129, 0.3) !important;
}}

.badge-disconnected {{
    background: rgba(148, 163, 184, 0.08) !important;
    color: var(--text-muted) !important;
    border: 1px solid var(--border-subtle) !important;
}}

.badge-cyan {{
    background: rgba(56, 189, 248, 0.1) !important;
    color: var(--accent-cyan) !important;
    border: 1px solid var(--accent-cyan) !important;
}}

.badge-violet {{
    background: rgba(139, 92, 246, 0.1) !important;
    color: var(--accent-violet) !important;
    border: 1px solid var(--accent-violet) !important;
}}

.badge-warning {{
    background: rgba(245, 158, 11, 0.1) !important;
    color: var(--accent-amber) !important;
    border: 1px solid rgba(245, 158, 11, 0.3) !important;
}}

.console-badge.active {{
    border-color: var(--accent-emerald);
    color: var(--accent-emerald);
}}

.console-badge.cloud {{
    border-color: var(--accent-cyan);
    color: var(--accent-cyan);
}}

/* DYNAMIC GATEWAY LIVE BADGE BAR */
.gateway-live-bar {{
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
    align-items: center;
    background: {curr_theme["card_bg"]};
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 0.65rem 0.95rem;
    margin-bottom: 0.85rem;
}}

.gateway-chip {{
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    font-size: 0.78rem;
    color: var(--text-secondary);
    background: {curr_theme["chip_bg"]};
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 0.3rem 0.65rem;
}}

.gateway-chip strong {{
    color: var(--text-primary);
}}

.chip-badge {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    color: var(--accent-cyan);
    background: rgba(56, 189, 248, 0.12);
    padding: 1px 5px;
    border-radius: 4px;
}}

.live-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
    box-shadow: 0 0 6px currentColor;
}}

/* LEGACY TELEMETRY STRIP COMPATIBILITY */
.telemetry-strip {{
    display: flex;
    gap: 1.5rem;
    align-items: center;
    font-size: 0.8rem;
    color: var(--text-secondary);
    background: {curr_theme["card_bg"]};
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 0.55rem 0.95rem;
    margin-bottom: 0.85rem;
    flex-wrap: wrap;
}}

.telemetry-strip span strong {{
    color: var(--text-primary);
}}

/* METRIC CARDS */
.stat-card {{
    background: {curr_theme["card_bg"]};
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 0.85rem 1.1rem;
}}

.stat-label {{
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.2rem;
}}

.stat-value {{
    font-size: 1.45rem;
    font-weight: 800;
    color: var(--text-primary);
    line-height: 1.1;
}}

.stat-sub {{
    font-size: 0.72rem;
    color: var(--text-muted);
    margin-top: 0.25rem;
}}

/* TAB NAVIGATION */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
    gap: 0.4rem;
    background: transparent;
    border-bottom: 1px solid var(--border-subtle);
    padding-bottom: 2px;
}}

[data-testid="stTabs"] [data-baseweb="tab"] {{
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    color: var(--text-muted) !important;
    border-radius: 6px 6px 0 0 !important;
    padding: 0.45rem 0.95rem !important;
    border: 1px solid transparent !important;
    background: transparent !important;
}}

[data-testid="stTabs"] [aria-selected="true"] {{
    color: var(--accent-cyan) !important;
    border-bottom: 2px solid var(--accent-cyan) !important;
}}

/* CHAT MESSAGES */
[data-testid="stChatMessage"] {{
    background: {curr_theme["card_bg"]} !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px !important;
    padding: 0.85rem 1.1rem !important;
    margin-bottom: 0.65rem !important;
}}

/* DATAFRAMES */
[data-testid="stDataFrame"] {{
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}}
</style>
""",
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# MODEL CLIENT & SECURE CREDENTIALS
# ──────────────────────────────────────────────
DEFAULT_API_KEYS = load_api_keys()
if "active_key_index" not in st.session_state:
    st.session_state.active_key_index = 0


def _get_agent(
    model_name: str,
    backend_type: str | None = None,
    model_path: str | Path | None = None,
    custom_api_key: str | None = None,
    base_url: str | None = None,
) -> SchemaSenseAIAgent:
    """Retrieve or instantiate a SchemaSenseAIAgent for the active backend."""
    key_to_use = custom_api_key or st.session_state.get("custom_api_key")
    base_to_use = base_url or st.session_state.get("custom_base_url")
    return get_session_agent(
        model_name=model_name,
        backend_type=backend_type,
        model_path=model_path,
        custom_api_key=key_to_use,
        default_api_keys=DEFAULT_API_KEYS,
        cache_store=st.session_state,
        timeout_seconds=20.0,
        base_url=base_to_use,
    )


# Backward compatibility aliases
extract_sql_from_response = extract_sql_from_text


def generate_with_fallback(
    model_name: str, system_prompt: str, messages_or_prompt, stream: bool = False
):
    """Compatibility bridge routing legacy callers to the modernized agent."""
    agent = _get_agent(model_name)
    if isinstance(messages_or_prompt, str):
        prompt = messages_or_prompt
        history = None
    else:
        history, prompt = messages_or_prompt
    if stream:
        return agent.generate_stream(
            prompt=prompt, history=history
        ), agent.active_key_index
    resp = agent.generate_structured(prompt=prompt)
    return resp, agent.active_key_index


# ──────────────────────────────────────────────
# APPLICATION STATE INITIALIZATION
# ──────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Welcome! Connect a PostgreSQL, MySQL, or SQLite database in the sidebar to inspect live schemas, or ask any SQL and database architecture questions.",
        }
    ]
if "db_engine" not in st.session_state:
    st.session_state.db_engine = None
if "db_schema" not in st.session_state:
    st.session_state.db_schema = None
if "db_type" not in st.session_state:
    st.session_state.db_type = ""
if "last_sql" not in st.session_state:
    st.session_state.last_sql = None
if "business_rules" not in st.session_state:
    st.session_state.business_rules = []
if "privilege_report" not in st.session_state:
    st.session_state.privilege_report = None
if "selected_tables" not in st.session_state:
    st.session_state.selected_tables = []
if "schema_snapshots" not in st.session_state:
    st.session_state.schema_snapshots = {}

# ──────────────────────────────────────────────
# SIDEBAR: CONNECTION GATEWAY & SETTINGS
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        """
        <div style="padding: 0.2rem 0 0.7rem 0; border-bottom: 1px solid rgba(148, 163, 184, 0.12); margin-bottom: 0.8rem;">
            <div style="font-size:1.2rem; font-weight:800; letter-spacing:-0.02em; color:var(--text-primary);">
                SchemaSense
            </div>
            <div style="font-size:0.75rem; color:var(--text-muted);">
                Universal Database Intelligence & Security Console
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # UI Theme Palette Switcher
    st.markdown(
        "<div style=\"font-family:'JetBrains Mono',monospace; font-size:0.68rem; font-weight:700; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.06em; margin-bottom:0.1rem;\">Appearance & Theme</div>",
        unsafe_allow_html=True,
    )
    theme_choice = st.selectbox(
        "UI Theme",
        options=list(THEMES.keys()),
        index=list(THEMES.keys()).index(st.session_state.app_theme)
        if st.session_state.app_theme in THEMES
        else 0,
        key="app_theme_select",
        label_visibility="collapsed",
    )
    if theme_choice != st.session_state.app_theme:
        st.session_state.app_theme = theme_choice
        st.rerun()

    st.divider()

    # Universal AI Inference Backend
    st.markdown(
        "<div style=\"font-family:'JetBrains Mono',monospace; font-size:0.68rem; font-weight:700; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.06em; margin-bottom:0.1rem;\">Inference Backend</div>",
        unsafe_allow_html=True,
    )
    backend_mode_choice = st.selectbox(
        "Backend Selection",
        [
            "Google Gemini (Cloud)",
            "OpenAI",
            "Anthropic Claude",
            "DeepSeek",
            "Groq (Cloud)",
            "Ollama (Local Server)",
            "Custom OpenAI-Compatible Gateway",
            "llama.cpp (Local GGUF)",
        ],
        key="backend_mode_select",
        label_visibility="collapsed",
    )

    is_local_backend = (
        "Local" in backend_mode_choice or "llama.cpp" in backend_mode_choice
    )
    selected_model = "gemini-2.5-flash"
    active_backend_key = "gemini"

    if backend_mode_choice == "Google Gemini (Cloud)":
        active_backend_key = "gemini"
        st.markdown(
            '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem;">'
            "Provider: <strong style='color:var(--accent-cyan);'>Google Gemini API</strong> (Cloud inference)"
            "</div>",
            unsafe_allow_html=True,
        )
        selected_model = st.selectbox(
            "Model Selection",
            [
                "gemini-2.5-flash",
                "gemini-2.5-pro",
                "gemini-2.0-flash",
                "gemini-3-flash-preview",
            ],
            key="gemini_model_select",
            label_visibility="collapsed",
        )
        custom_key = st.text_input(
            "Gemini API Key (Optional)",
            type="password",
            placeholder="Custom API Key (or use environment)",
            help="Optional API key override. Credentials are kept in memory and never logged.",
            key="gemini_custom_key_input",
        )
        if custom_key.strip():
            st.session_state.custom_api_key = custom_key.strip()
        else:
            st.session_state.custom_api_key = ""

    elif backend_mode_choice == "OpenAI":
        active_backend_key = "openai"
        st.markdown(
            '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem;">'
            "Provider: <strong style='color:var(--accent-cyan);'>OpenAI Official API</strong>"
            "</div>",
            unsafe_allow_html=True,
        )
        selected_model = st.selectbox(
            "OpenAI Model",
            ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini", "gpt-4-turbo"],
            key="openai_model_select",
            label_visibility="collapsed",
        )
        custom_key = st.text_input(
            "OpenAI API Key",
            type="password",
            placeholder="sk-proj-...",
            key="openai_key_input",
        )
        if custom_key.strip():
            st.session_state.custom_api_key = custom_key.strip()

    elif backend_mode_choice == "Anthropic Claude":
        active_backend_key = "anthropic"
        st.markdown(
            '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem;">'
            "Provider: <strong style='color:var(--accent-violet);'>Anthropic Claude API</strong>"
            "</div>",
            unsafe_allow_html=True,
        )
        selected_model = st.selectbox(
            "Claude Model",
            [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ],
            key="claude_model_select",
            label_visibility="collapsed",
        )
        custom_key = st.text_input(
            "Anthropic API Key",
            type="password",
            placeholder="sk-ant-...",
            key="anthropic_key_input",
        )
        if custom_key.strip():
            st.session_state.custom_api_key = custom_key.strip()

    elif backend_mode_choice == "DeepSeek":
        active_backend_key = "deepseek"
        st.markdown(
            '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem;">'
            "Provider: <strong style='color:var(--accent-cyan);'>DeepSeek AI Platform</strong>"
            "</div>",
            unsafe_allow_html=True,
        )
        selected_model = st.selectbox(
            "DeepSeek Model",
            ["deepseek-chat", "deepseek-reasoner"],
            key="deepseek_model_select",
            label_visibility="collapsed",
        )
        custom_key = st.text_input(
            "DeepSeek API Key",
            type="password",
            placeholder="sk-...",
            key="deepseek_key_input",
        )
        if custom_key.strip():
            st.session_state.custom_api_key = custom_key.strip()

    elif backend_mode_choice == "Groq (Cloud)":
        active_backend_key = "groq"
        st.markdown(
            '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem;">'
            "Provider: <strong style='color:var(--accent-amber);'>Groq LPU Engine</strong> (Ultra-fast)"
            "</div>",
            unsafe_allow_html=True,
        )
        selected_model = st.selectbox(
            "Groq Model",
            [
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
                "deepseek-r1-distill-llama-70b",
                "mixtral-8x7b-32768",
            ],
            key="groq_model_select",
            label_visibility="collapsed",
        )
        custom_key = st.text_input(
            "Groq API Key",
            type="password",
            placeholder="gsk_...",
            key="groq_key_input",
        )
        if custom_key.strip():
            st.session_state.custom_api_key = custom_key.strip()

    elif backend_mode_choice == "Ollama (Local Server)":
        active_backend_key = "ollama"
        st.markdown(
            '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem;">'
            "Provider: <strong style='color:var(--accent-emerald);'>Ollama</strong> (Local server, zero egress)"
            "</div>",
            unsafe_allow_html=True,
        )
        selected_model = st.text_input(
            "Ollama Model Name",
            value="llama3.2",
            placeholder="e.g. qwen2.5-coder, llama3.2, mistral",
            key="ollama_model_input",
        )
        ollama_url = st.text_input(
            "Ollama Base URL",
            value="http://localhost:11434/v1",
            key="ollama_url_input",
        )
        st.session_state.custom_base_url = ollama_url.strip()

    elif backend_mode_choice == "Custom OpenAI-Compatible Gateway":
        active_backend_key = "custom"
        st.markdown(
            '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem;">'
            "Provider: <strong style='color:var(--accent-cyan);'>Custom API Gateway</strong> (vLLM / OpenRouter / Azure)"
            "</div>",
            unsafe_allow_html=True,
        )
        custom_base = st.text_input(
            "Gateway Base URL",
            placeholder="https://api.gateway.com/v1",
            key="custom_gateway_url_input",
        )
        selected_model = st.text_input(
            "Model Name / Identifier",
            value="custom-model",
            key="custom_gateway_model_input",
        )
        custom_key = st.text_input(
            "Gateway API Key",
            type="password",
            placeholder="Bearer token or API key",
            key="custom_gateway_key_input",
        )
        if custom_base.strip():
            st.session_state.custom_base_url = custom_base.strip()
        if custom_key.strip():
            st.session_state.custom_api_key = custom_key.strip()

    else:
        # llama.cpp (Local GGUF)
        active_backend_key = "llama_cpp"
        st.markdown(
            '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem;">'
            "Provider: <strong style='color:var(--accent-emerald);'>llama.cpp</strong> (In-process offline inference)"
            "</div>",
            unsafe_allow_html=True,
        )
        local_path_val = st.text_input(
            "Local GGUF Model Path",
            value=st.session_state.get("local_model_path", ""),
            placeholder="e.g. C:/models/model.gguf or /models/model.gguf",
            help="Local filesystem path to a compatible .gguf model file. No automatic downloads or directory scans.",
            key="local_model_path_input",
        )
        if local_path_val.strip():
            st.session_state.local_model_path = local_path_val.strip()
        else:
            st.session_state.local_model_path = ""

        selected_model = (
            Path(local_path_val.strip()).name
            if local_path_val.strip()
            else "local-gguf"
        )

        from schemasense.runtime.backends.llama_cpp import (
            LLAMA_CPP_AVAILABLE,
            LlamaCppBackend,
        )

        if not LLAMA_CPP_AVAILABLE:
            st.caption(
                "Engine: `llama-cpp-python` not installed. Install via: `pip install -r requirements-local.txt`"
            )
        elif not local_path_val.strip():
            st.caption("Engine: Please specify a local `.gguf` file path above.")
        else:
            check_backend = LlamaCppBackend(model_path=local_path_val.strip())
            if not check_backend.is_available():
                st.caption("Status: File not found or not a valid `.gguf` model file.")
            else:
                cached_agent = st.session_state.get("_active_agent")
                if (
                    cached_agent is not None
                    and hasattr(cached_agent.backend, "_llm")
                    and cached_agent.backend._llm is not None
                    and getattr(cached_agent, "model_path", None)
                    == Path(local_path_val.strip())
                ):
                    st.caption("Status: Model loaded in memory (ready for queries).")
                else:
                    st.caption(
                        "Status: Model verified on disk (weights load on first query)."
                    )

    # Provider connection verification test button
    if active_backend_key != "llama_cpp":
        if st.button(
            "⚡ Test Provider Ping", use_container_width=True, key="ping_provider_btn"
        ):
            with st.spinner("Testing provider connectivity..."):
                t_start = time.monotonic()
                try:
                    test_agent = _get_agent(
                        model_name=selected_model,
                        backend_type=active_backend_key,
                        custom_api_key=st.session_state.get("custom_api_key"),
                        base_url=st.session_state.get("custom_base_url"),
                    )
                    if test_agent.backend.is_available():
                        ping_ms = round((time.monotonic() - t_start) * 1000)
                        st.success(
                            f"Verified: {test_agent.backend_info.display_name} ready ({ping_ms}ms)"
                        )
                    else:
                        st.error(
                            "Verification failed: Check API key or URL configuration."
                        )
                except Exception as p_err:  # noqa: BLE001
                    st.error(f"Ping failed: {p_err}")

    st.divider()

    # Database Connection Form
    st.markdown(
        "<div style=\"font-family:'JetBrains Mono',monospace; font-size:0.68rem; font-weight:700; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.06em; margin-bottom:0.1rem;\">Database Connection</div>",
        unsafe_allow_html=True,
    )
    db_engine_choice = st.selectbox(
        "Database Engine",
        ["PostgreSQL", "MySQL", "SQLite"],
        label_visibility="collapsed",
    )

    with st.form("db_connect_form"):
        if db_engine_choice == "SQLite":
            db_sqlite_file = st.text_input(
                "SQLite Database File Path",
                value="schemasense_sample.db",
                help="Path to local .db or .sqlite file, or leave blank/:memory: for in-memory.",
            )
            # Retain dummy values for variable binding
            db_host, db_port, db_name, db_user, db_pass = "", "", db_sqlite_file, "", ""
            enforce_least_priv = False
        else:
            db_host = st.text_input("Host URL / IP", placeholder="e.g. 127.0.0.1")
            db_port = st.text_input(
                "Port", value="5432" if db_engine_choice == "PostgreSQL" else "3306"
            )
            db_name = st.text_input("Database Name", placeholder="database_name")
            db_user = st.text_input("Username", placeholder="username")
            db_pass = st.text_input("Password", type="password")
            enforce_least_priv = st.checkbox(
                "Enforce Least-Privilege Role",
                value=False,
                help="Enforces that connecting credentials belong to a read-only role. Rejects superusers or administrative accounts.",
            )

        connect_btn = st.form_submit_button("Secure Connect", use_container_width=True)

    if connect_btn:
        if db_engine_choice != "SQLite" and not all(
            [db_host, db_port, db_name, db_user, db_pass]
        ):
            st.error("All connection parameters are mandatory.")
        else:
            with st.spinner("Connecting to database and inspecting schema..."):
                try:
                    if st.session_state.db_engine is not None:
                        dispose_engine(st.session_state.db_engine)
                        st.session_state.db_engine = None

                    if db_engine_choice == "SQLite":
                        engine = create_safe_engine(
                            db_type="SQLite",
                            db_name=db_name or ":memory:",
                            enforce_least_privilege=False,
                        )
                    else:
                        engine = create_safe_engine(
                            db_type=db_engine_choice,
                            host=db_host,
                            port=db_port,
                            db_name=db_name,
                            user=db_user,
                            password=db_pass,
                            enforce_least_privilege=enforce_least_priv,
                        )

                    schema_obj = inspect_database_schema(engine)
                    report = getattr(
                        engine, "_schemasense_privilege_report", None
                    ) or inspect_account_privileges(engine, db_type=db_engine_choice)

                    st.session_state.db_engine = engine
                    st.session_state.db_schema = schema_obj
                    st.session_state.db_type = db_engine_choice
                    st.session_state.privilege_report = report

                    table_count = len(schema_obj.tables)
                    if report.is_privileged:
                        st.warning(f"Security Advisory: {report.summary}")
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": (
                                    f"Security Advisory: Connected to **{db_name}** with a privileged account "
                                    f"(`{report.current_user}`). {report.summary}. For production deployment, provision a restricted read-only account."
                                ),
                            }
                        )
                    else:
                        st.success(
                            f"Connected: Discovered {table_count} tables with least-privilege role (`{report.current_user}`)."
                        )
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": (
                                    f"Connected to **{db_name}** ({db_engine_choice}) with verified least-privilege account "
                                    f"(`{report.current_user}`). Discovered {table_count} tables. AST Guard active for all queries."
                                ),
                            }
                        )

                except PrivilegedAccountError as pae:
                    st.error(f"Security Policy Violation: {pae}")
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": (
                                f"Connection Blocked: Administrative or superuser accounts are prohibited when least-privilege "
                                f"enforcement is active. {pae}. Please configure and use a read-only service account."
                            ),
                        }
                    )
                except (ConnectionConfigError, DriverMissingError) as ce:
                    st.error(f"Configuration / Driver Error: {ce}")
                except DatabaseConnectionError as dce:
                    st.error(f"Connection Failed: {dce}")
                except Exception as e:  # noqa: BLE001
                    st.error(f"Unexpected Connection Fault: {e}")

    if st.session_state.get("db_engine") is not None and st.button(
        "Disconnect Database", use_container_width=True
    ):
        dispose_engine(st.session_state.db_engine)
        st.session_state.db_engine = None
        st.session_state.db_schema = None
        st.session_state.db_type = ""
        st.session_state.privilege_report = None
        st.session_state.selected_tables = []
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "Database disconnected. Connection pool disposed cleanly. Operating in offline SQL guidance mode.",
            }
        )
        st.rerun()

    # Active schema summary & PDF rules ingestion
    if st.session_state.get("db_schema") is not None:
        schema = st.session_state.db_schema
        st.divider()
        st.markdown(
            f"<div style=\"font-family:'JetBrains Mono',monospace; font-size:0.68rem; font-weight:700; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.06em; margin-bottom:0.1rem;\">Active Schema: {schema.database_name}</div>",
            unsafe_allow_html=True,
        )

        all_table_names = list(schema.tables.keys())
        selected = st.multiselect(
            "Active Tables Filter",
            options=all_table_names,
            default=st.session_state.selected_tables or all_table_names,
            help="Limit AI prompt context and SQL Guard validation to specific tables.",
            label_visibility="collapsed",
        )
        st.session_state.selected_tables = selected

        st.divider()
        st.markdown(
            "<div style=\"font-family:'JetBrains Mono',monospace; font-size:0.68rem; font-weight:700; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.06em; margin-bottom:0.1rem;\">Business Rules (PDF Ingestion)</div>",
            unsafe_allow_html=True,
        )
        pdf_file = st.file_uploader(
            "Upload Business Rules Document",
            type=["pdf"],
            help="Ingest enterprise policies and domain definitions to ground SQL generation.",
            label_visibility="collapsed",
        )
        if pdf_file is not None:
            try:
                extracted_rules = extract_rules_from_pdf(pdf_file)
                st.session_state.business_rules = extracted_rules
                st.success(f"Ingested {len(extracted_rules)} business rules.")
            except PDFIngestionError as pie:
                st.error(f"Rule Ingestion Error: {pie}")

        if st.session_state.business_rules:
            with st.expander(f"Active Rules ({len(st.session_state.business_rules)})"):
                for i, rule in enumerate(st.session_state.business_rules, 1):
                    st.markdown(
                        f"<div style='font-size:0.75rem; color:var(--text-secondary); margin-bottom:4px;'><strong>Rule {i}:</strong> {rule[:140]}...</div>",
                        unsafe_allow_html=True,
                    )
                if st.button("Clear Rules", use_container_width=True):
                    st.session_state.business_rules = []
                    st.rerun()

# ──────────────────────────────────────────────
# MAIN NAVIGATION TABS
# ──────────────────────────────────────────────
is_connected = st.session_state.get("db_engine") is not None
priv_report: AccountPrivilegeReport | None = st.session_state.get("privilege_report")
active_mode_select = st.session_state.get(
    "backend_mode_select", "Google Gemini (Cloud)"
)
is_local_active = "Local" in active_mode_select or "llama.cpp" in active_mode_select

# Construct human-readable badge string
if is_local_active:
    engine_badge = f"Local (llama.cpp - {selected_model})"
elif "Gemini" in active_mode_select:
    engine_badge = f"Cloud (Gemini - {selected_model})"
else:
    engine_badge = f"Cloud ({active_backend_key.title()} - {selected_model})"

if is_connected:
    db_name_val = (
        st.session_state.db_schema.database_name
        if st.session_state.db_schema
        else "Connected"
    )
    conn_badge_html = f'<div class="console-badge badge-connected"><span class="status-dot dot-green"></span><span>Connected: {db_name_val} ({st.session_state.db_type})</span></div>'
    if priv_report and priv_report.is_privileged:
        role_badge_html = f'<div class="console-badge badge-warning"><span>Role: Privileged ({priv_report.current_user})</span></div>'
    elif priv_report:
        role_badge_html = f'<div class="console-badge badge-connected"><span>Role: Least-Privilege ({priv_report.current_user})</span></div>'
    else:
        role_badge_html = '<div class="console-badge badge-disconnected"><span>Role: Unknown</span></div>'
else:
    conn_badge_html = '<div class="console-badge badge-disconnected"><span class="status-dot dot-gray"></span><span>Disconnected</span></div>'
    role_badge_html = '<div class="console-badge badge-disconnected"><span>Role: Not checked</span></div>'

ast_badge_html = '<div class="console-badge badge-cyan"><span>AST Guard: Active (sqlglot)</span></div>'
pool_badge_html = '<div class="console-badge badge-violet"><span>Pool Limit: 4 Concurrent</span></div>'
provider_badge_html = f'<div class="console-badge badge-cyan"><span>{active_backend_key.title()} ({selected_model})</span></div>'
theme_badge_html = (
    f'<div class="console-badge"><span>Theme: {st.session_state.app_theme}</span></div>'
)

# CONSOLE HEADER
st.markdown(
    f"""
    <div class="console-header">
        <div class="console-brand-group">
            <h1 class="console-brand-title">SchemaSense</h1>
            <span class="console-brand-subtitle">Enterprise Database Intelligence & Security Console</span>
        </div>
        <div class="console-badges">
            {conn_badge_html}
            {role_badge_html}
            {ast_badge_html}
            {pool_badge_html}
            {provider_badge_html}
            {theme_badge_html}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_chat, tab_schema, tab_profiler, tab_sql, tab_diff = st.tabs(
    [
        "AI Agent Studio",
        "Schema Architecture",
        "Column Profiler & Health",
        "SQL Guard Sandbox",
        "Schema Evolution & Diff",
    ]
)

# ═══════════════════════════════════════════════
# TAB 1: AI AGENT STUDIO
# ═══════════════════════════════════════════════
with tab_chat:
    active_tables_count = len(
        st.session_state.get("selected_tables")
        or (st.session_state.db_schema.tables if st.session_state.db_schema else [])
    )
    active_rules_count = len(st.session_state.business_rules)
    db_name_display = (
        st.session_state.db_schema.database_name
        if is_connected and st.session_state.db_schema
        else "Disconnected"
    )

    if is_connected and st.session_state.db_schema:
        st.markdown(
            f"""
            <div class="telemetry-strip">
                <span>Database: <strong>{st.session_state.db_schema.database_name}</strong> ({st.session_state.db_type})</span>
                <span>Active Schema Context: <strong>{active_tables_count} tables</strong></span>
                <span>Business Constraints: <strong>{active_rules_count} rules active</strong></span>
                <span>Inference: <strong>{engine_badge}</strong></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="telemetry-strip">
                <span>Status: <strong>Database disconnected</strong></span>
                <span>Operating Mode: <strong>General SQL guidance</strong></span>
                <span>Inference: <strong>{engine_badge}</strong></span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    col_mode, col_clear = st.columns([3, 1])
    with col_mode:
        ai_mode = st.radio(
            "Response Mode",
            ["Streaming Dialogue", "Structured Schema Reasoning (Pydantic)"],
            horizontal=True,
            label_visibility="collapsed",
        )
    with col_clear:
        if st.button("Clear Chat", use_container_width=True):
            st.session_state.messages = [
                {
                    "role": "assistant",
                    "content": "Welcome! Connect a PostgreSQL, MySQL, or SQLite database in the sidebar to inspect live schemas, or ask any SQL and database architecture questions.",
                }
            ]
            st.session_state.last_sql = None
            st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input(
        "Ask a question about database schema, query construction, or business rules..."
    ):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        schema_prompt_section = ""
        allowed_tables = set()
        if is_connected and st.session_state.db_schema:
            allowed_tables = set(
                st.session_state.get("selected_tables")
                or st.session_state.db_schema.tables.keys()
            )
            filtered_schema = st.session_state.db_schema.filter_tables(
                list(allowed_tables)
            )
            schema_prompt_section = filtered_schema.to_markdown()

        rules_prompt_section = format_rules_for_prompt(st.session_state.business_rules)

        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            full_response = ""

            try:
                agent = _get_agent(
                    model_name=selected_model,
                    backend_type=active_backend_key,
                    model_path=st.session_state.get("local_model_path")
                    if is_local_backend
                    else None,
                    custom_api_key=st.session_state.get("custom_api_key"),
                    base_url=st.session_state.get("custom_base_url"),
                )

                if "Structured" in ai_mode:
                    with st.spinner("Generating structured schema reasoning..."):
                        structured_resp = agent.generate_structured(
                            prompt=prompt,
                            schema_context=schema_prompt_section,
                            business_rules_context=rules_prompt_section,
                            dialect=st.session_state.db_type or "postgres",
                            allowed_tables=allowed_tables,
                        )

                        full_response = structured_resp.explanation
                        if structured_resp.sql_query:
                            full_response += (
                                f"\n\n```sql\n{structured_resp.sql_query}\n```"
                            )
                        if structured_resp.safety_notes:
                            full_response += f"\n\n> **Safety Notes**: {structured_resp.safety_notes}"
                        response_placeholder.markdown(full_response)
                        st.session_state.messages.append(
                            {"role": "assistant", "content": full_response}
                        )

                        if structured_resp.sql_query:
                            st.session_state.last_sql = structured_resp.sql_query
                            if structured_resp.is_executable:
                                st.info(
                                    "Structured SQL query verified against schema and loaded into SQL Guard Sandbox."
                                )
                            else:
                                st.warning(
                                    "Query generated with safety restrictions or hallucination warning. Inspect in SQL Guard Sandbox."
                                )
                else:
                    for chunk in agent.generate_stream(
                        prompt=prompt,
                        schema_context=schema_prompt_section,
                        business_rules_context=rules_prompt_section,
                        dialect=st.session_state.db_type or "postgres",
                        history=st.session_state.messages[:-1],
                    ):
                        full_response += chunk
                        response_placeholder.markdown(full_response + "...")

                    response_placeholder.markdown(full_response)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": full_response}
                    )

                    sql = extract_sql_from_text(full_response)
                    if sql:
                        st.session_state.last_sql = sql
                        if allowed_tables:
                            from schemasense.sql_guard import SQLGuard

                            try:
                                ast_tables = SQLGuard(
                                    allowed_tables=allowed_tables
                                )._extract_all_table_references(sql)
                                hallucinations = verify_schema_fidelity(
                                    list(ast_tables), allowed_tables
                                )
                                if hallucinations:
                                    st.warning(
                                        f"Schema Grounding Alert: Query references tables not present in active schema: {', '.join(hallucinations)}."
                                    )
                                else:
                                    st.info(
                                        "SQL query verified against active schema and loaded into the SQL Guard Sandbox."
                                    )
                            except Exception:  # noqa: BLE001
                                st.info(
                                    "SQL query detected and loaded into the SQL Guard Sandbox for inspection and execution."
                                )
                        else:
                            st.info(
                                "SQL query detected and loaded into the SQL Guard Sandbox for inspection and execution."
                            )

            except (
                AIQuotaExceededError,
                AITimeoutError,
                AIProviderError,
                AIAgentError,
            ) as err:
                response_placeholder.error(f"Inference Fault: {err}")
            except Exception as e:  # noqa: BLE001
                response_placeholder.error(f"Execution Error: {e}")

# ═══════════════════════════════════════════════
# TAB 2: SCHEMA ARCHITECTURE
# ═══════════════════════════════════════════════
with tab_schema:
    if not is_connected or not st.session_state.db_schema:
        st.markdown(
            """
            <div class="telemetry-strip">
                <span>Status: <strong>No database connected</strong></span>
                <span>Connect via sidebar to inspect live relational schemas</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        schema = st.session_state.db_schema
        total_cols = sum(len(t.columns) for t in schema.tables.values())
        total_fks = sum(len(t.foreign_keys) for t in schema.tables.values())
        total_indexes = sum(len(t.indexes) for t in schema.tables.values())

        st.markdown(
            f"""
            <div class="telemetry-strip">
                <span>Dialect: <strong>{schema.dialect}</strong></span>
                <span>Database: <strong>{schema.database_name}</strong></span>
                <span>Tables: <strong>{len(schema.tables)}</strong></span>
                <span>Columns: <strong>{total_cols}</strong></span>
                <span>Foreign Keys: <strong>{total_fks}</strong></span>
                <span>Indexes: <strong>{total_indexes}</strong></span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            st.download_button(
                label="Download Data Dictionary (JSON)",
                data=schema.to_json(),
                file_name=f"{schema.database_name}_data_dictionary.json",
                mime="application/json",
                use_container_width=True,
            )
        with col_exp2:
            st.download_button(
                label="Download Data Dictionary (Markdown)",
                data=schema.to_markdown(),
                file_name=f"{schema.database_name}_data_dictionary.md",
                mime="text/markdown",
                use_container_width=True,
            )

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

        for table_name, table_info in schema.tables.items():
            pk_list = (
                ", ".join(table_info.primary_key) if table_info.primary_key else "None"
            )
            with st.expander(
                f"{table_name}  [{len(table_info.columns)} columns | PK: {pk_list}]"
            ):
                col_c1, col_c2 = st.columns([1, 1])
                with col_c1:
                    st.markdown(
                        "<div style='font-family:\"JetBrains Mono\",monospace; font-size:0.75rem; font-weight:700; color:var(--accent-cyan); text-transform:uppercase;'>Column Definitions</div>",
                        unsafe_allow_html=True,
                    )
                    col_records = []
                    for c in table_info.columns:
                        col_records.append(
                            {
                                "Column": c.name,
                                "Type": c.data_type,
                                "Primary Key": "True" if c.is_primary_key else "False",
                                "Nullable": "True" if c.nullable else "False",
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(col_records),
                        use_container_width=True,
                        hide_index=True,
                    )

                with col_c2:
                    st.markdown(
                        "<div style='font-family:\"JetBrains Mono\",monospace; font-size:0.75rem; font-weight:700; color:var(--accent-violet); text-transform:uppercase;'>Foreign Keys & Indexes</div>",
                        unsafe_allow_html=True,
                    )
                    if table_info.foreign_keys:
                        fk_records = [
                            {
                                "Column": fk["constrained_columns"][0]
                                if fk["constrained_columns"]
                                else "N/A",
                                "References": f"{fk['referred_table']}.{fk['referred_columns'][0] if fk['referred_columns'] else 'N/A'}",
                            }
                            for fk in table_info.foreign_keys
                        ]
                        st.dataframe(
                            pd.DataFrame(fk_records),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.caption("No foreign key constraints defined.")

# ═══════════════════════════════════════════════
# TAB 3: COLUMN PROFILER & HEALTH
# ═══════════════════════════════════════════════
with tab_profiler:
    if not is_connected or not st.session_state.db_schema:
        st.markdown(
            """
            <div class="telemetry-strip">
                <span>Status: <strong>No database connected</strong></span>
                <span>Connect via sidebar to perform analytical column profiling</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        schema = st.session_state.db_schema
        selected_prof_table = st.selectbox(
            "Select Table to Profile",
            options=list(schema.tables.keys()),
            key="profiler_table_select",
        )

        sample_size = st.slider(
            "Sample Row Limit", min_value=500, max_value=5000, value=1000, step=500
        )

        if st.button(
            "Run Column Health Audit", type="primary", use_container_width=True
        ):
            with st.spinner(
                f"Profiling {selected_prof_table} (sampling up to {sample_size:,} rows)..."
            ):
                try:
                    prof_sql = build_safe_profiling_query(
                        selected_prof_table, limit=sample_size
                    )
                    sample_df, _ = execute_safe_query(
                        engine=st.session_state.db_engine,
                        query=prof_sql,
                        allowed_tables={selected_prof_table},
                        dialect=st.session_state.db_type,
                        timeout_ms=10000,
                        max_rows=sample_size,
                    )

                    if sample_df.empty:
                        st.warning(f"Table '{selected_prof_table}' contains no rows.")
                    else:
                        profile_res = profile_dataframe(sample_df)
                        dq_score = profile_res["data_quality_score"]

                        c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            st.markdown(
                                f'<div class="stat-card"><div class="stat-label">Data Quality Score</div><div class="stat-value">{dq_score:.1f}%</div><div class="stat-sub">Composite health metric</div></div>',
                                unsafe_allow_html=True,
                            )
                        with c2:
                            st.markdown(
                                f'<div class="stat-card"><div class="stat-label">Sampled Rows</div><div class="stat-value">{len(sample_df):,}</div><div class="stat-sub">From {selected_prof_table}</div></div>',
                                unsafe_allow_html=True,
                            )
                        with c3:
                            st.markdown(
                                f'<div class="stat-card"><div class="stat-label">Duplicate Rows</div><div class="stat-value">{profile_res["duplicate_rows"]}</div><div class="stat-sub">Duplicate rate: {profile_res["duplicate_rate"]:.2%}</div></div>',
                                unsafe_allow_html=True,
                            )
                        with c4:
                            st.markdown(
                                f'<div class="stat-card"><div class="stat-label">Candidate Keys</div><div class="stat-value">{len(profile_res["candidate_keys"])}</div><div class="stat-sub">{", ".join(profile_res["candidate_keys"]) or "None"}</div></div>',
                                unsafe_allow_html=True,
                            )

                        st.markdown(
                            "<div style='height: 12px;'></div>", unsafe_allow_html=True
                        )
                        st.dataframe(
                            pd.DataFrame(profile_res["columns"]),
                            use_container_width=True,
                            hide_index=True,
                        )

                except Exception as pe:  # noqa: BLE001
                    st.error(f"Profiling Failure: {pe}")

# ═══════════════════════════════════════════════
# TAB 4: SQL GUARD SANDBOX
# ═══════════════════════════════════════════════
with tab_sql:
    if is_connected and st.session_state.db_schema:
        st.markdown(
            f"""
            <div class="telemetry-strip">
                <span>Database: <strong>{st.session_state.db_schema.database_name}</strong> ({st.session_state.db_type})</span>
                <span>Active Table Restrictions: <strong>{len(st.session_state.get("selected_tables") or st.session_state.db_schema.tables)} allowed</strong></span>
                <span>Security Engine: <strong>AST SQLGuard Active</strong></span>
                <span>Timeout: <strong>5,000 ms</strong></span>
                <span>Row Limit: <strong>1,000 rows</strong></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="telemetry-strip">
                <span>Mode: <strong>Offline Sandbox</strong></span>
                <span>Validation Rule: <strong>Read-Only Enforced</strong></span>
                <span>Connect via sidebar to execute against live data</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    default_sql = st.session_state.last_sql or ""
    sql_input = st.text_area(
        "SQL Query Buffer",
        value=default_sql,
        height=140,
        placeholder="SELECT * FROM table_name LIMIT 50;",
    )

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        run_btn = st.button(
            "Execute Guarded Query", type="primary", use_container_width=True
        )
    with col_btn2:
        if st.button("Clear Buffer", use_container_width=True):
            st.session_state.last_sql = None
            st.rerun()

    if run_btn and sql_input.strip():
        if not is_connected:
            try:
                validation = SQLGuard.validate(
                    query=sql_input.strip(),
                    dialect=st.session_state.db_type or "postgres",
                )
                if validation.is_valid:
                    st.success(
                        "AST Validation Passed: Statement classified as strictly read-only. "
                        "Connect a live database in the sidebar to execute against real tables."
                    )
                else:
                    st.error(f"Security Block (SQLGuard): {validation.error_message}")
            except Exception as e:  # noqa: BLE001
                st.error(f"AST Validation Error: {e}")
        else:
            allowed_tables = set(
                st.session_state.get("selected_tables")
                or st.session_state.db_schema.tables.keys()
            )
            try:
                with st.spinner("Validating AST and executing query..."):
                    result_df, is_truncated = execute_safe_query(
                        engine=st.session_state.db_engine,
                        query=sql_input.strip(),
                        allowed_tables=allowed_tables,
                        dialect=st.session_state.db_type,
                        timeout_ms=5000,
                        max_rows=1000,
                    )

                if is_truncated:
                    st.warning(
                        "Result exceeded memory limit (1,000 rows) and was truncated."
                    )

                st.success(f"Query executed: {len(result_df):,} rows retrieved.")
                st.dataframe(result_df, use_container_width=True)

            except QueryTimeoutError as qte:
                st.error(f"Query Execution Timeout: {qte}")
            except SQLSecurityViolation as ssv:
                st.error(f"Security Block (SQLGuard): {ssv}")
            except QueryExecutionError as qee:
                st.error(f"Database Query Error: {qee}")
            except Exception as e:  # noqa: BLE001
                st.error(f"Unexpected Execution Error: {e}")

# ═══════════════════════════════════════════════
# TAB 5: SCHEMA EVOLUTION & DIFFING
# ═══════════════════════════════════════════════
with tab_diff:
    st.markdown(
        """
        <div style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:1rem;">
            Track and compare schema changes over time. Capture snapshots of your live database and detect added tables, dropped columns, or altered data types.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not is_connected or not st.session_state.db_schema:
        st.markdown(
            """
            <div class="telemetry-strip">
                <span>Status: <strong>No database connected</strong></span>
                <span>Connect via sidebar to capture and diff live schema snapshots</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        schema = st.session_state.db_schema
        col_snap1, col_snap2 = st.columns([1, 1])

        with col_snap1:
            snapshot_label = st.text_input(
                "Snapshot Name", value=f"v_{time.strftime('%Y%m%d_%H%M%S')}"
            )
            if st.button("📸 Capture Schema Snapshot", use_container_width=True):
                st.session_state.schema_snapshots[snapshot_label] = schema
                st.success(
                    f"Snapshot '{snapshot_label}' captured with {len(schema.tables)} tables."
                )

        with col_snap2:
            snapshots = list(st.session_state.schema_snapshots.keys())
            if not snapshots:
                st.info(
                    "No saved snapshots yet. Capture a snapshot on the left to begin diffing."
                )
            else:
                baseline_name = st.selectbox(
                    "Compare Current Schema Against:", options=snapshots
                )
                if st.button(
                    "🔍 Generate Schema Diff", type="primary", use_container_width=True
                ):
                    baseline_schema = st.session_state.schema_snapshots[baseline_name]
                    diff_res = diff_database_schemas(baseline_schema, schema)

                    d1, d2, d3 = st.columns(3)
                    with d1:
                        st.markdown(
                            f'<div class="stat-card"><div class="stat-label">Added Tables</div><div class="stat-value">{len(diff_res["added_tables"])}</div><div class="stat-sub">{", ".join(diff_res["added_tables"]) or "None"}</div></div>',
                            unsafe_allow_html=True,
                        )
                    with d2:
                        st.markdown(
                            f'<div class="stat-card"><div class="stat-label">Removed Tables</div><div class="stat-value">{len(diff_res["removed_tables"])}</div><div class="stat-sub">{", ".join(diff_res["removed_tables"]) or "None"}</div></div>',
                            unsafe_allow_html=True,
                        )
                    with d3:
                        st.markdown(
                            f'<div class="stat-card"><div class="stat-label">Modified Tables</div><div class="stat-value">{len(diff_res["modified_tables"])}</div><div class="stat-sub">Column or type shifts</div></div>',
                            unsafe_allow_html=True,
                        )

                    if diff_res["modified_tables"]:
                        st.markdown("### Table Modifications")
                        for t_name, mod in diff_res["modified_tables"].items():
                            with st.expander(f"Table: {t_name}"):
                                if mod["added_columns"]:
                                    st.markdown(
                                        f"**Added Columns**: `{', '.join(mod['added_columns'])}`"
                                    )
                                if mod["removed_columns"]:
                                    st.markdown(
                                        f"**Removed Columns**: `{', '.join(mod['removed_columns'])}`"
                                    )
                                if mod["type_changes"]:
                                    st.markdown(
                                        f"**Type Changes**: `{', '.join(mod['type_changes'])}`"
                                    )
                    elif (
                        not diff_res["added_tables"] and not diff_res["removed_tables"]
                    ):
                        st.success("Schemas are identical. Zero drift detected.")
