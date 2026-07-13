"""Gestão de usuários — CRUD (somente administradores)."""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from app.utils.dev_reload import sync_app_modules

sync_app_modules(st.session_state)

from app.utils.auth import require_admin
from app.utils.theme import page_header, render_page_footer, setup_page
from app.utils.users_ui import render_users_admin_panel

setup_page("Usuários")
require_admin()

page_header(
    "Gestão de usuários",
    "Cadastre, edite e desative usuários do sistema. Apenas administradores têm acesso.",
)

render_users_admin_panel()
render_page_footer()
