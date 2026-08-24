"""Tema corporativo — paleta azul, amarelo e branco."""

from __future__ import annotations

from pathlib import Path

import streamlit as st


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_APP_ICON_ICO = _PROJECT_ROOT / "aplicativo.ico"
_APP_FAVICON_PNG = _PROJECT_ROOT / ".streamlit" / "favicon.png"


def get_app_icon() -> str:
    """Caminho do ícone do app (favicon e sidebar). Gera PNG a partir do .ico se necessário."""
    if _APP_ICON_ICO.is_file():
        try:
            if (
                not _APP_FAVICON_PNG.is_file()
                or _APP_FAVICON_PNG.stat().st_mtime < _APP_ICON_ICO.stat().st_mtime
            ):
                from PIL import Image

                _APP_FAVICON_PNG.parent.mkdir(parents=True, exist_ok=True)
                Image.open(_APP_ICON_ICO).save(_APP_FAVICON_PNG)
        except Exception:
            return str(_APP_ICON_ICO)
        return str(_APP_FAVICON_PNG)
    if _APP_FAVICON_PNG.is_file():
        return str(_APP_FAVICON_PNG)
    return "📄"
from app.db import database as db
from app.utils.datetime_br import format_brazil_datetime
from app.utils.active_contract import ensure_active_contract_applied, render_sidebar_contract_controls
from app.utils.auth import is_admin, render_logout_button, require_login
from app.utils.ui import init_session_state

# Paleta corporativa
COLORS = {
    "navy": "#0A3D7A",
    "blue": "#1565C0",
    "blue_light": "#E8F1FB",
    "gold": "#F5B800",
    "gold_dark": "#D4A017",
    "gold_light": "#FFF9E6",
    "white": "#FFFFFF",
    "bg": "#F4F7FB",
    "text": "#0D2137",
    "text_muted": "#5A6B7D",
    "border": "#D6E2F0",
}

ANALYSIS_LABELS = {
    "checklist": "Checklist (requisitos)",
    "matrix_initial": "Análise inicial (parâmetros)",
    "diff": "Análise contratual",
    "text_diff": "Comparar textos",
    "comments": "Revisão de comentários (legado)",
    "document_comments": "Comentários no documento",
    "matrix": "Proposta × Contrato",
}

CORPORATE_CSS = f"""
<style>
html, body, [class*="css"] {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
}}

/* Fundo geral */
[data-testid="stAppViewContainer"] > .main {{
    background: linear-gradient(180deg, {COLORS["bg"]} 0%, {COLORS["white"]} 120px);
}}

.block-container {{
    padding-top: 1.5rem;
    max-width: 1200px;
}}

/* Sidebar */
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {COLORS["navy"]} 0%, #0D2F5C 100%);
    border-right: 3px solid {COLORS["gold"]};
}}
section[data-testid="stSidebar"] * {{
    color: #E8EEF5 !important;
}}
section[data-testid="stSidebar"] .stMarkdown h1 {{
    color: {COLORS["white"]} !important;
    font-weight: 700;
    font-size: 1.25rem !important;
}}
section[data-testid="stSidebar"] .stCaption {{
    color: #B8C9DC !important;
}}
section[data-testid="stSidebar"] hr {{
    border-color: rgba(255,255,255,0.15);
}}
section[data-testid="stSidebar"] a {{
    color: #E8EEF5 !important;
    text-decoration: none;
    border-radius: 8px;
    padding: 0.35rem 0.5rem;
    display: block;
}}
section[data-testid="stSidebar"] a:hover {{
    background: rgba(245, 184, 0, 0.15);
    color: {COLORS["gold"]} !important;
}}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] label {{
    color: #B8C9DC !important;
}}
section[data-testid="stSidebar"] .stButton > button {{
    background: {COLORS["gold"]} !important;
    color: {COLORS["navy"]} !important;
    border: none !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
    background: #FFD54F !important;
    box-shadow: 0 4px 12px rgba(245, 184, 0, 0.35);
}}

/* Botões principais */
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {{
    background: linear-gradient(135deg, {COLORS["navy"]} 0%, {COLORS["blue"]} 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 0.5rem 1.25rem !important;
    box-shadow: 0 2px 8px rgba(10, 61, 122, 0.25);
}}
.stButton > button[kind="primary"]:hover {{
    box-shadow: 0 4px 14px rgba(10, 61, 122, 0.35);
    transform: translateY(-1px);
}}

/* Métricas nativas */
[data-testid="stMetric"] {{
    background: {COLORS["white"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
    padding: 1rem 1.25rem;
    border-left: 4px solid {COLORS["gold"]};
    box-shadow: 0 1px 3px rgba(10, 61, 122, 0.06);
}}
[data-testid="stMetricLabel"] {{
    color: {COLORS["text_muted"]} !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
[data-testid="stMetricValue"] {{
    color: {COLORS["navy"]} !important;
    font-weight: 700 !important;
}}

/* Alertas */
[data-testid="stAlert"] {{
    border-radius: 10px;
    border-left-width: 4px;
}}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background: {COLORS["blue_light"]};
    border-radius: 10px;
    padding: 4px;
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 8px;
    font-weight: 500;
    color: {COLORS["text_muted"]};
}}
.stTabs [aria-selected="true"] {{
    background: {COLORS["white"]} !important;
    color: {COLORS["navy"]} !important;
    box-shadow: 0 1px 4px rgba(10,61,122,0.1);
}}

/* Expanders */
details {{
    border: 1px solid {COLORS["border"]} !important;
    border-radius: 10px !important;
    background: {COLORS["white"]};
    margin-bottom: 0.5rem;
}}
details summary {{
    font-weight: 600;
    color: {COLORS["navy"]};
}}

/* Radio horizontal */
[data-testid="stRadio"] > div {{
    background: {COLORS["white"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 10px;
    padding: 0.5rem 1rem;
}}

/* File uploader */
[data-testid="stFileUploader"] {{
    border: 2px dashed {COLORS["border"]};
    border-radius: 12px;
    padding: 0.5rem;
    background: {COLORS["white"]};
}}
[data-testid="stFileUploader"]:hover {{
    border-color: {COLORS["gold"]};
    background: {COLORS["gold_light"]};
}}

/* --- Componentes custom --- */
.ca-hero {{
    background: linear-gradient(135deg, {COLORS["navy"]} 0%, {COLORS["blue"]} 55%, #1a5fad 100%);
    border-radius: 16px;
    padding: 2rem 2.5rem;
    margin-bottom: 1.75rem;
    color: white;
    position: relative;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(10, 61, 122, 0.2);
}}
.ca-hero::after {{
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 4px;
    background: linear-gradient(90deg, {COLORS["gold"]}, #FFD54F, {COLORS["gold"]});
}}
.ca-hero h1 {{
    margin: 0 0 0.5rem 0;
    font-size: 1.85rem;
    font-weight: 700;
    color: white !important;
}}
.ca-hero p {{
    margin: 0;
    opacity: 0.92;
    font-size: 1.05rem;
    max-width: 640px;
    line-height: 1.5;
}}
.ca-badge {{
    display: inline-block;
    background: {COLORS["gold"]};
    color: {COLORS["navy"]};
    font-size: 0.7rem;
    font-weight: 700;
    padding: 0.2rem 0.65rem;
    border-radius: 999px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.75rem;
}}

.ca-stat-card {{
    background: {COLORS["white"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 14px;
    padding: 1.35rem 1.5rem;
    text-align: center;
    box-shadow: 0 2px 8px rgba(10, 61, 122, 0.06);
    border-top: 3px solid {COLORS["gold"]};
    height: 100%;
}}
.ca-stat-card .value {{
    font-size: 2.25rem;
    font-weight: 700;
    color: {COLORS["navy"]};
    line-height: 1.1;
}}
.ca-stat-card .label {{
    font-size: 0.8rem;
    color: {COLORS["text_muted"]};
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.35rem;
    font-weight: 500;
}}

.ca-section-title {{
    font-size: 1.15rem;
    font-weight: 700;
    color: {COLORS["navy"]};
    margin: 1.5rem 0 1rem 0;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid {COLORS["gold"]};
    display: inline-block;
}}

.ca-page-header {{
    margin-bottom: 1.5rem;
}}
.ca-page-header h1 {{
    color: {COLORS["navy"]} !important;
    font-size: 1.65rem !important;
    font-weight: 700 !important;
    margin-bottom: 0.25rem !important;
}}
.ca-page-header .subtitle {{
    color: {COLORS["text_muted"]};
    font-size: 1rem;
    margin: 0;
}}

.ca-activity-item {{
    background: {COLORS["white"]};
    border: 1px solid {COLORS["border"]};
    border-left: 4px solid {COLORS["blue"]};
    border-radius: 10px;
    padding: 0.85rem 1.1rem;
    margin-bottom: 0.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}}
.ca-activity-item .type {{
    font-weight: 600;
    color: {COLORS["navy"]};
    font-size: 0.9rem;
}}
.ca-activity-item .time {{
    color: {COLORS["text_muted"]};
    font-size: 0.8rem;
}}

.ca-feature-card {{
    background: {COLORS["white"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
    padding: 1.25rem;
    height: 100%;
    transition: box-shadow 0.2s, border-color 0.2s;
}}
.ca-feature-card:hover {{
    border-color: {COLORS["gold"]};
    box-shadow: 0 4px 16px rgba(10, 61, 122, 0.1);
}}
.ca-feature-card h3 {{
    color: {COLORS["navy"]};
    font-size: 1rem;
    margin: 0 0 0.5rem 0;
}}
.ca-feature-card p {{
    color: {COLORS["text_muted"]};
    font-size: 0.875rem;
    margin: 0;
    line-height: 1.45;
}}

.ca-risk-high {{ color: #C62828; font-weight: 600; }}
.ca-risk-med {{ color: #E65100; font-weight: 600; }}
.ca-risk-low {{ color: #2E7D32; font-weight: 600; }}

footer.ca-footer {{
    text-align: center;
    color: {COLORS["text_muted"]};
    font-size: 0.75rem;
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid {COLORS["border"]};
}}

.ca-sidebar-context {{
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(245, 184, 0, 0.45);
    border-left: 4px solid {COLORS["gold"]};
    border-radius: 10px;
    padding: 0.75rem 0.85rem;
    margin: 0.65rem 0 0.85rem 0;
}}
.ca-sidebar-context .kicker {{
    font-size: 0.65rem !important;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: {COLORS["gold"]} !important;
    margin-bottom: 0.35rem;
}}
.ca-sidebar-context .title {{
    font-size: 0.95rem !important;
    font-weight: 700;
    color: {COLORS["white"]} !important;
    line-height: 1.3;
}}
.ca-sidebar-context .meta {{
    font-size: 0.8rem !important;
    color: #B8C9DC !important;
    margin-bottom: 0.55rem;
}}
.ca-sidebar-context .row {{
    font-size: 0.78rem !important;
    color: #E8EEF5 !important;
    margin-top: 0.2rem;
    line-height: 1.35;
}}
.ca-sidebar-context .row span {{
    display: inline-block;
    min-width: 4.4rem;
    color: {COLORS["gold"]} !important;
    font-weight: 600;
}}

.ca-source-card {{
    background: {COLORS["white"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
    padding: 1rem 1.2rem;
    margin-bottom: 1.1rem;
    box-shadow: 0 1px 4px rgba(10, 61, 122, 0.06);
}}
.ca-source-card.is-saved,
.ca-source-card.is-salva {{
    border-left: 4px solid {COLORS["gold"]};
}}
.ca-source-card.is-new,
.ca-source-card.is-novo {{
    border-left: 4px solid {COLORS["blue"]};
}}
.ca-source-head {{
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.45rem 0.7rem;
    margin-bottom: 0.75rem;
}}
.ca-source-head strong {{
    color: {COLORS["navy"]};
    font-size: 1.05rem;
}}
.ca-source-client {{
    color: {COLORS["text_muted"]};
    font-size: 0.9rem;
}}
.ca-source-card p {{
    margin: 0.35rem 0 0 0;
    color: {COLORS["text_muted"]};
    font-size: 0.9rem;
    line-height: 1.45;
}}
.ca-source-row {{
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    padding: 0.45rem 0;
    border-top: 1px solid {COLORS["border"]};
}}
.ca-source-row strong {{
    color: {COLORS["text"]};
    display: block;
}}
.ca-source-file {{
    display: block;
    color: {COLORS["text_muted"]};
    font-size: 0.8rem;
    margin-top: 0.1rem;
}}
.ca-pill {{
    display: inline-block;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    border-radius: 999px;
    padding: 0.18rem 0.55rem;
    white-space: nowrap;
    flex-shrink: 0;
    margin-top: 0.15rem;
}}
.ca-pill-saved, .ca-pill-salvo, .ca-pill-salva {{
    background: {COLORS["gold_light"]};
    color: {COLORS["navy"]};
}}
.ca-pill-new, .ca-pill-novo, .ca-pill-nova {{
    background: {COLORS["blue_light"]};
    color: {COLORS["blue"]};
}}
.ca-pill-none, .ca-pill-nenhuma, .ca-pill-pendente {{
    background: #EEF2F6;
    color: {COLORS["text_muted"]};
}}

/* Subtítulos nativos Streamlit */
[data-testid="stSubheader"] {{
    color: {COLORS["navy"]} !important;
    font-weight: 700 !important;
    padding-bottom: 0.35rem;
    border-bottom: 2px solid {COLORS["gold"]};
    display: inline-block;
    margin-bottom: 0.75rem !important;
}}

/* Barra superior do Streamlit — sem linha amarela global */
[data-testid="stHeader"],
[data-testid="stDecoration"] {{
    border-bottom: none !important;
    background: transparent !important;
}}

/* Selectbox, inputs e dataframes */
[data-testid="stSelectbox"] > div,
[data-testid="stTextInput"] > div,
[data-testid="stTextArea"] > div {{
    border-radius: 8px;
}}
[data-testid="stDataFrame"] {{
    border: 1px solid {COLORS["border"]};
    border-radius: 10px;
    overflow: hidden;
}}

/* Info / success / warning alinhados à paleta */
[data-testid="stAlert"][data-baseweb="notification"] {{
    border-radius: 10px;
}}
div[data-testid="stAlert"]:has(svg[data-testid="stIcon"]) {{
    background: {COLORS["blue_light"]};
    border-left: 4px solid {COLORS["blue"]};
}}
</style>
"""


_THEME_INJECTED_KEY = "_corp_theme_css_injected"


def inject_corporate_theme() -> None:
    """Injeta CSS corporativo uma vez por sessão (evita erro removeChild no React)."""
    if st.session_state.get(_THEME_INJECTED_KEY):
        return
    st.markdown(CORPORATE_CSS, unsafe_allow_html=True)
    st.session_state[_THEME_INJECTED_KEY] = True


def setup_page(
    title: str,
    *,
    page_icon: str | None = None,
    layout: str = "wide",
    with_sidebar: bool = True,
    require_auth: bool = True,
) -> None:
    """Configura página Streamlit com tema e sidebar padronizados."""
    st.set_page_config(
        page_title=title,
        page_icon=page_icon if page_icon is not None else get_app_icon(),
        layout=layout,
    )
    init_session_state()
    db.init_db()
    inject_corporate_theme()
    if require_auth:
        require_login()
    if with_sidebar:
        render_app_sidebar()
        ensure_active_contract_applied()


def page_header(title: str, subtitle: str = "", badge: str = "Contract Analyzer") -> None:
    """Cabeçalho de página com o mesmo hero azul/amarelo da página inicial."""
    hero_block(title, subtitle, badge=badge)


def render_page_footer() -> None:
    st.markdown(
        '<footer class="ca-footer">Contract Analyzer · Análise jurídica assistida por IA</footer>',
        unsafe_allow_html=True,
    )


def hero_block(title: str, subtitle: str, badge: str = "Contract Analyzer") -> None:
    st.markdown(
        f"""
        <div class="ca-hero">
            <span class="ca-badge">{badge}</span>
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def stat_cards(values: list[tuple[str, str | int]]) -> None:
    cols = st.columns(len(values))
    for col, (label, value) in zip(cols, values):
        with col:
            st.markdown(
                f"""
                <div class="ca-stat-card">
                    <div class="value">{value}</div>
                    <div class="label">{label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def section_title(text: str) -> None:
    """Título de seção — componente nativo (estável no DOM do Streamlit)."""
    st.subheader(text)


def activity_feed(records: list) -> None:
    if not records:
        st.info("Nenhuma análise registrada ainda. Comece pelo upload de um contrato.")
        return
    for rec in records:
        label = ANALYSIS_LABELS.get(rec.analysis_type, rec.analysis_type)
        when = format_brazil_datetime(rec.created_at)
        st.markdown(
            f"""
            <div class="ca-activity-item">
                <span class="type">{label}</span>
                <span class="time">{when}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_app_sidebar() -> None:
    """Sidebar corporativa compartilhada."""
    with st.sidebar:
        icon = get_app_icon()
        if icon != "📄":
            st.image(icon, width=64)
        st.markdown("### Contract Analyzer")
        st.caption("Análise inteligente de contratos")

        render_sidebar_contract_controls()

        if st.button("Novo contrato", width="stretch", type="primary"):
            from app.utils.active_contract import clear_active_contract_context

            clear_active_contract_context()
            st.switch_page("pages/01_upload.py")

        st.divider()
        st.page_link("main.py", label="Início")
        st.page_link("pages/01_upload.py", label="Upload & Análise inicial")
        st.page_link("pages/02_compare.py", label="Comparar versões")
        st.page_link("pages/04_history.py", label="Histórico")
        if is_admin():
            st.page_link("pages/05_users.py", label="Usuários")
        st.divider()
        render_logout_button()
        st.divider()
        st.caption("Powered by OpenAI")
