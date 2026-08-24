"""Scroll sincronizado (Shift + roda) em painéis lado a lado."""

from __future__ import annotations

import streamlit as st


def sync_group_class(group: str) -> str:
    """Classe CSS estável para agrupar painéis (o Streamlit remove data-*)."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (group or "default"))
    return f"bgf-sg-{safe}"


def sync_scroll_classes(group: str) -> str:
    return f"bgf-sync-scroll {sync_group_class(group)}"


def _current_sync_enabled() -> bool:
    for key, value in st.session_state.items():
        if str(key).endswith("_sync_scroll") and isinstance(value, bool):
            return value
    return True


def ensure_sync_scroll_handler() -> None:
    """Registra Shift+roda no DOM da página (componente Streamlit v2)."""
    from app.utils.page_bridge import mount_page_bridge

    mount_page_bridge(comments=False, sync_enabled=_current_sync_enabled())


def render_sync_scroll_controls(*, key: str = "bgf_sync_scroll") -> bool:
    """Checkbox + dica. Retorna se a rolagem sincronizada está ativa."""
    enabled = st.checkbox(
        "Rolagem sincronizada (Shift + roda do mouse)",
        value=st.session_state.get(key, True),
        key=key,
        help="Com a opção ligada, segure Shift e role a roda do mouse sobre um documento "
        "para descer/subir os dois painéis juntos.",
    )
    if enabled:
        st.caption(
            "Posicione o mouse sobre um dos documentos, segure **Shift** e use a roda "
            "para rolar **os dois** ao mesmo tempo."
        )
    return enabled


def sync_scroll_hint() -> None:
    """Dica curta (sem checkbox — use render_sync_scroll_controls no painel principal)."""
    st.caption(
        "Segure **Shift** e use a roda do mouse para rolar os dois documentos juntos "
        "(com a rolagem sincronizada ligada)."
    )
