"""Editor compartilhado da matriz de verificação (Upload inicial e Proposta × Contrato)."""

import uuid

import streamlit as st

from app.db import database as db
from app.utils.theme import section_title

DEFAULT_MATRIX_ROWS = [
    {"Categoria": "Escopo / Objeto", "Ação de validação (consultar proposta → validar contrato)": "", "Risco": ""},
    {"Categoria": "Cronograma e Prazos", "Ação de validação (consultar proposta → validar contrato)": "", "Risco": ""},
    {"Categoria": "Entregáveis e Resultados", "Ação de validação (consultar proposta → validar contrato)": "", "Risco": ""},
]

_COL_ACAO = "Ação de validação (consultar proposta → validar contrato)"


def rows_to_matrix_items(rows: list[dict], db_ids: list[str] | None = None) -> list[dict]:
    """Converte linhas do data_editor em itens de matriz com id estável."""
    items: list[dict] = []
    db_ids = db_ids or []
    for i, row in enumerate(rows):
        categoria = (row.get("Categoria") or "").strip()
        parametro = (
            row.get(_COL_ACAO)
            or row.get("Parâmetro de verificação")
            or row.get("parametro_verificacao")
            or ""
        ).strip()
        if not categoria and not parametro:
            continue
        item_id = db_ids[i] if i < len(db_ids) else f"row-{uuid.uuid4().hex[:8]}"
        items.append(
            {
                "id": item_id,
                "categoria": categoria,
                "parametro_verificacao": parametro,
                "risco_padrao": (row.get("Risco") or "").strip(),
            }
        )
    return items


def render_matrix_editor(
    *,
    section_label: str = "Matriz de verificação",
    template_key: str = "matrix_template_choice",
    new_name_key: str = "matrix_new_name",
    new_rows_key: str = "matrix_new_rows",
    new_editor_key: str = "matrix_new_editor",
    save_new_key: str = "matrix_save_new",
) -> list[dict]:
    """Seleção/edição da matriz temática. Retorna itens prontos para análise."""
    section_title(section_label)
    st.caption(
        "Cada linha é um **parâmetro de verificação**: a coluna «Ação de validação» descreve o que a IA "
        "deve fazer (consultar a **proposta** e validar no **contrato**). A coluna «Risco» indica o "
        "impacto se falhar."
    )
    templates = db.get_matrix_templates()
    template_names = [t.name for t in templates] + ["Criar nova"]
    choice = st.selectbox("Modelo da matriz", template_names, key=template_key)

    if choice == "Criar nova":
        new_name = st.text_input("Nome da nova matriz", key=new_name_key)
        if new_rows_key not in st.session_state:
            st.session_state[new_rows_key] = list(DEFAULT_MATRIX_ROWS)
        edited = st.data_editor(
            st.session_state[new_rows_key],
            num_rows="dynamic",
            width="stretch",
            key=new_editor_key,
        )
        if st.button("Salvar matriz", key=save_new_key):
            if new_name:
                tpl = db.create_matrix_template(new_name)
                for i, item in enumerate(rows_to_matrix_items(edited)):
                    db.add_matrix_item(
                        tpl.id,
                        item["categoria"],
                        item["parametro_verificacao"],
                        item["risco_padrao"],
                        i,
                    )
                st.session_state.selected_matrix_template_id = tpl.id
                st.success(f"Matriz '{new_name}' salva.")
                st.rerun()
            else:
                st.warning("Informe o nome da matriz.")
        return rows_to_matrix_items(edited)

    tpl = next(t for t in templates if t.name == choice)
    st.session_state.selected_matrix_template_id = tpl.id
    items_db = db.get_matrix_items(tpl.id)
    rows = [
        {
            "Categoria": it.categoria,
            _COL_ACAO: it.parametro_verificacao,
            "Risco": it.risco_padrao,
        }
        for it in items_db
    ]
    update_key = f"matrix_update_{tpl.id}"
    edited = st.data_editor(
        rows,
        num_rows="dynamic",
        width="stretch",
        key=f"matrix_edit_{tpl.id}",
    )
    if st.button("Salvar alterações na matriz", key=update_key):
        db.delete_matrix_items_for_template(tpl.id)
        for i, item in enumerate(rows_to_matrix_items(edited)):
            db.add_matrix_item(
                tpl.id,
                item["categoria"],
                item["parametro_verificacao"],
                item["risco_padrao"],
                i,
            )
        st.success("Matriz atualizada.")
        st.rerun()
    db_ids = [it.id for it in items_db]
    return rows_to_matrix_items(edited, db_ids)
