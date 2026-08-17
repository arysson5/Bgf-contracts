"""Scroll sincronizado (Shift + roda) em painéis lado a lado."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

# No Windows, Shift+roda costuma virar deltaX (scroll horizontal).
_SYNC_SCROLL_JS = """
<script>
(function () {
  const doc = window.parent.document;
  if (doc.__bgfSyncScrollHandler) {
    try {
      doc.removeEventListener("wheel", doc.__bgfSyncScrollHandler, true);
    } catch (err) {}
  }
  if (typeof doc.__bgfSyncScrollEnabled === "undefined") {
    doc.__bgfSyncScrollEnabled = true;
  }

  function handler(e) {
    if (!doc.__bgfSyncScrollEnabled) return;
    if (!e.shiftKey) return;
    const el = e.target && e.target.closest
      ? e.target.closest(".bgf-sync-scroll")
      : null;
    if (!el) return;
    const group = el.getAttribute("data-sync-group");
    if (!group) return;
    const peers = doc.querySelectorAll(
      '.bgf-sync-scroll[data-sync-group="' + group + '"]'
    );
    if (peers.length < 2) return;

    const delta = e.deltaY !== 0 ? e.deltaY : e.deltaX;
    if (!delta) return;

    e.preventDefault();
    e.stopPropagation();
    peers.forEach(function (p) {
      p.scrollTop += delta;
    });
  }

  doc.__bgfSyncScrollHandler = handler;
  doc.addEventListener("wheel", handler, { passive: false, capture: true });
})();
</script>
"""

_ENABLE_JS = """
<script>
(function () {
  window.parent.document.__bgfSyncScrollEnabled = %s;
})();
</script>
"""


_SYNC_SCROLL_INJECTED_KEY = "_bgf_sync_scroll_handler_injected"


def ensure_sync_scroll_handler() -> None:
    """Registra listener de Shift+roda uma vez por sessão (evita removeChild no React)."""
    if st.session_state.get(_SYNC_SCROLL_INJECTED_KEY):
        return
    components.html(_SYNC_SCROLL_JS, height=0, scrolling=False)
    st.session_state[_SYNC_SCROLL_INJECTED_KEY] = True


def render_sync_scroll_controls(*, key: str = "bgf_sync_scroll") -> bool:
    """Checkbox + dica. Retorna se a rolagem sincronizada está ativa."""
    enabled = st.checkbox(
        "Rolagem sincronizada (Shift + roda do mouse)",
        value=st.session_state.get(key, True),
        key=key,
        help="Com a opção ligada, segure Shift e role a roda do mouse sobre um documento "
        "para descer/subir os dois painéis juntos.",
    )
    components.html(
        _ENABLE_JS % ("true" if enabled else "false"),
        height=0,
        scrolling=False,
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
