"""Autenticação de sessão Streamlit com bcrypt."""

from __future__ import annotations

import os

import bcrypt
import streamlit as st

from app.db import database as db

_SESSION_USER_KEY = "auth_user_id"
_SESSION_EMAIL_KEY = "auth_user_email"
_SESSION_NAME_KEY = "auth_user_name"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def get_current_user_id() -> str | None:
    return st.session_state.get(_SESSION_USER_KEY)


def get_current_user():
    uid = get_current_user_id()
    if not uid:
        return None
    return db.get_user_by_id(uid)


def is_authenticated() -> bool:
    return bool(get_current_user_id())


def login_user(email: str, password: str) -> bool:
    user = db.get_user_by_email(email.strip().lower())
    if not user or not user.is_active:
        return False
    if not verify_password(password, user.password_hash):
        return False
    st.session_state[_SESSION_USER_KEY] = user.id
    st.session_state[_SESSION_EMAIL_KEY] = user.email
    st.session_state[_SESSION_NAME_KEY] = user.name or user.email
    return True


def logout_user() -> None:
    for key in (_SESSION_USER_KEY, _SESSION_EMAIL_KEY, _SESSION_NAME_KEY):
        st.session_state.pop(key, None)


def require_login(*, stop: bool = True) -> str | None:
    """Garante usuário autenticado; exibe formulário de login se necessário."""
    if is_authenticated():
        return get_current_user_id()

    st.markdown("### Entrar")
    st.caption("Faça login para acessar seus contratos.")
    with st.form("login_form"):
        email = st.text_input("E-mail")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
    if submitted:
        if login_user(email, password):
            st.rerun()
        else:
            st.error("E-mail ou senha inválidos.")

    default_email = os.environ.get("BGF_DEFAULT_ADMIN_EMAIL", "admin@bgf.local")
    st.caption(f"Primeiro acesso: use `{default_email}` / senha definida em BGF_DEFAULT_ADMIN_PASSWORD.")

    if stop:
        st.stop()
    return None


def render_logout_button() -> None:
    if is_authenticated():
        name = st.session_state.get(_SESSION_NAME_KEY, "")
        st.caption(f"Conectado: **{name}**")
        if is_admin():
            st.caption("Perfil: **Administrador**")
        if st.button("Sair", key="auth_logout"):
            logout_user()
            st.rerun()


def is_admin() -> bool:
    user = get_current_user()
    return bool(user and user.is_admin)


def require_admin(*, stop: bool = True) -> None:
    """Restringe tela a administradores."""
    require_login()
    if is_admin():
        return
    st.error("Acesso restrito a administradores.")
    if stop:
        st.stop()
