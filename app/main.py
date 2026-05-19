"""Entry point Streamlit — Contract Analyzer."""

import streamlit as st

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

c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button("Novo contrato", type="primary", use_container_width=True):
        st.session_state.active_contract_id = None
        st.switch_page("pages/01_upload.py")
with c2:
    if st.button("Comparar versões", use_container_width=True):
        st.switch_page("pages/02_compare.py")
with c3:
    if st.button("Revisar comentários", use_container_width=True):
        st.switch_page("pages/03_comments.py")
with c4:
    if st.button("Histórico", use_container_width=True):
        st.switch_page("pages/04_history.py")

section_title("Módulos do sistema")
f1, f2, f3, f4 = st.columns(4)
features = [
    (f1, "Checklist", "Verifique cláusulas obrigatórias e requisitos mínimos com IA."),
    (f2, "Comparação", "Análise contratual criteriosa entre versões do mesmo documento."),
    (f3, "Comentários", "Revise comentários da contraparte e gere respostas sugeridas."),
    (f4, "Histórico", "Consulte análises anteriores por cliente e contrato."),
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
