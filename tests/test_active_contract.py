"""Testes do contexto de contrato/proposta da análise inicial."""

from types import SimpleNamespace
from unittest.mock import patch

from app.utils import active_contract as ac


class FakeState(dict):
    """Imita o session_state do Streamlit (item e atributo)."""

    def get(self, key, default=None):
        return super().get(key, default)

    def pop(self, key, default=None):
        return super().pop(key, default)

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


def _with_state(fn):
    import streamlit as st

    state = FakeState()
    original = st.session_state
    try:
        st.session_state = state  # type: ignore[misc]
        fn(state)
    finally:
        st.session_state = original


def test_proposal_mode_none_ignores_saved_text():
    def run(state):
        state["analysis_proposal_mode"] = ac.PROPOSAL_MODE_NONE
        contract = SimpleNamespace(
            proposal_extracted_text="proposta antiga",
            proposal_label="Proposta A",
            proposal_file_path="/tmp/a.pdf",
        )
        with patch.object(ac.db, "contract_has_proposal", return_value=True):
            text, _label, used = ac.get_proposal_for_analysis(contract)
        assert used is False
        assert text == ""

    _with_state(run)


def test_proposal_mode_new_does_not_use_saved_file():
    def run(state):
        state["analysis_proposal_mode"] = ac.PROPOSAL_MODE_NEW
        contract = SimpleNamespace(
            proposal_extracted_text="proposta antiga",
            proposal_label="Proposta A",
            proposal_file_path="/tmp/a.pdf",
        )
        with patch.object(ac.db, "contract_has_proposal", return_value=True):
            text, _label, used = ac.get_proposal_for_analysis(contract)
        assert used is False
        assert text == ""
        assert ac.proposal_requires_save() is True

    _with_state(run)


def test_proposal_mode_saved_uses_contract_proposal():
    def run(state):
        state["analysis_proposal_mode"] = ac.PROPOSAL_MODE_SAVED
        contract = SimpleNamespace(
            proposal_extracted_text="texto da proposta nova",
            proposal_label="Proposta B",
            proposal_file_path="/tmp/b.pdf",
        )
        with patch.object(ac.db, "contract_has_proposal", return_value=True):
            text, label, used = ac.get_proposal_for_analysis(contract)
        assert used is True
        assert text == "texto da proposta nova"
        assert label == "Proposta B"
        assert ac.proposal_requires_save() is False

    _with_state(run)


def test_clear_context_does_not_keep_first_contract():
    def run(state):
        state["active_contract_id"] = "contract-1"
        state["_applied_contract_id"] = "contract-1"
        state["upload_version_id"] = "ver-1"
        state["analysis_proposal_mode"] = ac.PROPOSAL_MODE_SAVED
        ac.clear_active_contract_context()
        assert state.get("active_contract_id") is None
        assert state.get("upload_version_id") is None
        assert state.get("analysis_contract_mode") == "new"
        assert state.get("analysis_proposal_mode") == ac.PROPOSAL_MODE_NONE
        assert state.get("upload_contract_source") == ac.CONTRACT_SOURCE_NEW
        assert state.get(ac.PENDING_SIDEBAR_CONTRACT_KEY) is None

    _with_state(run)


def test_set_active_version_updates_analysis_keys():
    def run(state):
        version = SimpleNamespace(id="ver-9", contract_id="c1")
        with patch.object(ac.db, "get_version", return_value=version):
            ac.set_active_version("ver-9")
        assert state["upload_version_id"] == "ver-9"
        assert state["active_version_id"] == "ver-9"
        assert state["checklist_version_id"] == "ver-9"

    _with_state(run)
