"""Limpeza de resultados de análise no session_state do Streamlit."""

from __future__ import annotations

import streamlit as st

_COMPARE_RESULT_KEYS = (
    "last_diff_result",
    "last_text_diff_result",
    "last_comment_verification",
    "last_compare_mode",
    "last_regression_result",
    "compare_mode_kind",
    "_compare_analysis_token",
)

_MATRIX_INITIAL_KEYS = (
    "last_matrix_initial_result",
    "matrix_analysis_saved",
    "checklist_version_id",
    "_matrix_analysis_token",
)

_OTHER_ANALYSIS_KEYS = (
    "last_checklist_result",
    "last_matrix_result",
    "last_comments_result",
    "annotated_pdf_path",
    "annotated_file_path",
)


def clear_compare_analysis_results() -> None:
    """Remove resultados da comparação de versões (antes de nova análise)."""
    for key in _COMPARE_RESULT_KEYS:
        st.session_state.pop(key, None)
    st.session_state.pop("_bgf_balloon_html_cache", None)


def clear_matrix_initial_analysis_results() -> None:
    """Remove resultado da análise inicial por matriz."""
    for key in _MATRIX_INITIAL_KEYS:
        st.session_state.pop(key, None)


def clear_all_analysis_results() -> None:
    """Limpa todos os resultados em memória (comparação + matriz + legado)."""
    clear_compare_analysis_results()
    clear_matrix_initial_analysis_results()
    for key in _OTHER_ANALYSIS_KEYS:
        st.session_state.pop(key, None)


def set_compare_analysis_token(token: str) -> None:
    st.session_state["_compare_analysis_token"] = token


def get_compare_analysis_token() -> str | None:
    return st.session_state.get("_compare_analysis_token")


def compare_token_matches(token: str | None) -> bool:
    if not token:
        return False
    return st.session_state.get("_compare_analysis_token") == token


def set_matrix_analysis_token(version_id: str | None) -> None:
    st.session_state["_matrix_analysis_token"] = version_id


def matrix_analysis_matches_version(version_id: str | None) -> bool:
    if not version_id:
        return False
    return st.session_state.get("_matrix_analysis_token") == version_id
