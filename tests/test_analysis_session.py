"""Testes de limpeza de sessão de análise."""

from app.utils import analysis_session


def test_compare_token_roundtrip():
  class FakeState(dict):
    def get(self, key, default=None):
      return super().get(key, default)

    def pop(self, key, default=None):
      return super().pop(key, default)

  state = FakeState()
  import streamlit as st

  original = st.session_state
  try:
    st.session_state = state  # type: ignore[misc]
    analysis_session.set_compare_analysis_token("saved:a:b:text_diff")
    assert analysis_session.compare_token_matches("saved:a:b:text_diff")
    assert not analysis_session.compare_token_matches("saved:a:b:other")
    analysis_session.clear_compare_analysis_results()
    assert state.get("_compare_analysis_token") is None
  finally:
    st.session_state = original


def test_matrix_version_token():
  class FakeState(dict):
    def get(self, key, default=None):
      return super().get(key, default)

    def pop(self, key, default=None):
      return super().pop(key, default)

  state = FakeState()
  import streamlit as st

  original = st.session_state
  try:
    st.session_state = state  # type: ignore[misc]
    analysis_session.set_matrix_analysis_token("ver-1")
    assert analysis_session.matrix_analysis_matches_version("ver-1")
    assert not analysis_session.matrix_analysis_matches_version("ver-2")
    analysis_session.clear_matrix_initial_analysis_results()
    assert state.get("_matrix_analysis_token") is None
  finally:
    st.session_state = original
