"""Entry point Streamlit — Contract Analyzer."""

import streamlit as st

from app.utils.dev_reload import sync_app_modules

sync_app_modules(st.session_state)

from app.utils.data_cache import (
    cached_analyses_today_count,
    cached_contracts,
    cached_recent_analyses,
    cached_version_count,
)
from app.utils.theme import (
    activity_feed,
    hero_block,
    section_title,
    setup_page,
    stat_cards,
)

setup_page("Contract Analyzer", page_icon="📄")

contracts = cached_contracts()
total_contracts = len(contracts)
analyses_today = cached_analyses_today_count()
recent = cached_recent_analyses(5)
total_versions = cached_version_count()

hero_block(
    "Contract Analyzer",
    "Plataforma corporativa para análise, comparação e revisão de contratos "
    "em PDF e DOCX com inteligência artificial.",
)

stat_cards([
    ("Contratos", total_contracts),
    ("Análises hoje", analyses_today),
    ("Versões", total_versions),
])

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Nova análise inicial", type="primary", width="stretch"):
        from app.utils.active_contract import apply_active_contract, clear_active_contract_context

        if st.session_state.get("active_contract_id"):
            apply_active_contract(st.session_state.active_contract_id, force=True)
        else:
            clear_active_contract_context()
        st.switch_page("pages/01_upload.py")
with c2:
    if st.button("Comparar / Proposta × Contrato", width="stretch"):
        st.switch_page("pages/02_compare.py")
with c3:
    if st.button("Histórico", width="stretch"):
        st.switch_page("pages/04_history.py")

section_title("Módulos do sistema")
f1, f2, f3 = st.columns(3)
features = [
    (f1, "Análise inicial", "Matriz ou checklist + comentários de revisão no PDF/DOCX."),
    (f2, "Comparação", "Diff entre versões com verificação de comentários atendidos."),
    (f3, "Histórico", "Consulte análises e listas de comentários anteriores."),
]
for col, title, desc in features:
    with col:
        st.markdown(
            f'<div class="ca-feature-card"><h3>{title}</h3><p>{desc}</p></div>',
            unsafe_allow_html=True,
        )

section_title("Últimas atividades")
activity_feed(recent)

st.markdown(
    '<footer class="ca-footer">Contract Analyzer · Análise jurídica assistida por IA</footer>',
    unsafe_allow_html=True,
)
