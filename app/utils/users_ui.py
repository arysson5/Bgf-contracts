"""CRUD de usuários — painel administrativo."""

from __future__ import annotations

import streamlit as st

from app.db import database as db
from app.utils.auth import get_current_user, hash_password
from app.utils.datetime_br import format_brazil_datetime
from app.utils.theme import section_title


def _user_label(user) -> str:
    admin = " [admin]" if user.is_admin else ""
    active = "" if user.is_active else " [inativo]"
    name = user.name or user.email
    return f"{name} ({user.email}){admin}{active}"


def render_users_admin_panel() -> None:
    """Lista, cria, edita e exclui usuários."""
    current = get_current_user()
    users = db.list_users()

    section_title("Usuários cadastrados")
    if not users:
        st.info("Nenhum usuário cadastrado.")
    else:
        rows = [
            {
                "Nome": u.name or "—",
                "E-mail": u.email,
                "Admin": "Sim" if u.is_admin else "Não",
                "Ativo": "Sim" if u.is_active else "Não",
                "Cadastro": format_brazil_datetime(u.created_at),
                "Contratos": db.count_contracts_for_user(u.id),
            }
            for u in users
        ]
        st.dataframe(rows, width="stretch", hide_index=True)

    st.divider()
    tab_new, tab_edit, tab_pass = st.tabs(["Novo usuário", "Editar", "Alterar senha"])

    with tab_new:
        _render_create_user()

    with tab_edit:
        _render_edit_user(users, current)

    with tab_pass:
        _render_change_password(users)


def _render_create_user() -> None:
    section_title("Cadastrar usuário")
    with st.form("user_create_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Nome completo")
            email = st.text_input("E-mail")
        with c2:
            password = st.text_input("Senha", type="password")
            password2 = st.text_input("Confirmar senha", type="password")
        is_admin = st.checkbox("Administrador")
        is_active = st.checkbox("Ativo", value=True)
        submitted = st.form_submit_button("Criar usuário", type="primary")
    if submitted:
        if not email.strip():
            st.error("Informe o e-mail.")
            return
        if len(password) < 6:
            st.error("A senha deve ter pelo menos 6 caracteres.")
            return
        if password != password2:
            st.error("As senhas não conferem.")
            return
        try:
            db.create_user(
                email,
                hash_password(password),
                name=name,
                is_admin=is_admin,
                is_active=is_active,
            )
            st.success(f"Usuário {email.strip().lower()} criado.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_edit_user(users, current) -> None:
    section_title("Editar usuário")
    if not users:
        st.caption("Cadastre um usuário primeiro.")
        return

    options = {u.id: _user_label(u) for u in users}
    selected_id = st.selectbox(
        "Selecione o usuário",
        options=list(options.keys()),
        format_func=lambda uid: options[uid],
        key="user_edit_select",
    )
    user = db.get_user_by_id(selected_id)
    if not user:
        return

    with st.form("user_edit_form"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Nome", value=user.name)
            email = st.text_input("E-mail", value=user.email)
        with c2:
            is_admin = st.checkbox("Administrador", value=user.is_admin)
            is_active = st.checkbox("Ativo", value=user.is_active)
        save = st.form_submit_button("Salvar alterações", type="primary")
    if save:
        if user.is_admin and not is_admin and db.count_admin_users() <= 1:
            st.error("Não é possível remover o último administrador.")
            return
        try:
            db.update_user(
                user.id,
                email=email,
                name=name,
                is_admin=is_admin,
                is_active=is_active,
            )
            st.success("Usuário atualizado.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    st.divider()
    st.markdown("**Excluir usuário**")
    confirm = st.checkbox("Confirmo a exclusão permanente", key=f"del_confirm_{user.id}")
    if st.button("Excluir usuário", type="secondary", key=f"del_btn_{user.id}"):
        if not confirm:
            st.warning("Marque a confirmação para excluir.")
            return
        try:
            db.delete_user(user.id, current_user_id=current.id if current else None)
            st.success("Usuário excluído.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_change_password(users) -> None:
    section_title("Alterar senha")
    if not users:
        st.caption("Cadastre um usuário primeiro.")
        return

    options = {u.id: _user_label(u) for u in users}
    selected_id = st.selectbox(
        "Usuário",
        options=list(options.keys()),
        format_func=lambda uid: options[uid],
        key="user_pass_select",
    )
    with st.form("user_pass_form"):
        password = st.text_input("Nova senha", type="password")
        password2 = st.text_input("Confirmar nova senha", type="password")
        submitted = st.form_submit_button("Atualizar senha", type="primary")
    if submitted:
        if len(password) < 6:
            st.error("A senha deve ter pelo menos 6 caracteres.")
            return
        if password != password2:
            st.error("As senhas não conferem.")
            return
        if db.update_user_password(selected_id, hash_password(password)):
            st.success("Senha atualizada.")
        else:
            st.error("Usuário não encontrado.")
