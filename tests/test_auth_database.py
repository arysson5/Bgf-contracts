"""Auth bcrypt e CRUD com isolamento por usuário."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.db import database as db
from app.utils.auth import hash_password, verify_password


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("BGF_DEFAULT_ADMIN_EMAIL", "tester@bgf.local")
    monkeypatch.setenv("BGF_DEFAULT_ADMIN_PASSWORD", "testpass123")
    from app.utils import settings as settings_mod

    settings_mod.reload_settings()
    db._db_ready = False
    db._engine = None
    db.init_db(force=True)
    yield db_path
    db._db_ready = False
    db._engine = None


class TestAuth:
    def test_hash_and_verify_password(self) -> None:
        hashed = hash_password("segredo123")
        assert verify_password("segredo123", hashed)
        assert not verify_password("errado", hashed)

    def test_create_user_and_filter_contracts(self, isolated_db: Path) -> None:
        admin = db.ensure_default_admin_user()
        user = db.create_user(
            f"user_{uuid.uuid4().hex[:6]}@bgf.local",
            hash_password("x"),
            name="Test User",
        )
        c_admin = db.create_contract("Contrato Admin", "Cliente A", owner_user_id=admin.id)
        c_user = db.create_contract("Contrato User", "Cliente B", owner_user_id=user.id)

        admin_contracts = db.get_contracts(owner_user_id=admin.id)
        user_contracts = db.get_contracts(owner_user_id=user.id)
        assert any(c.id == c_admin.id for c in admin_contracts)
        assert any(c.id == c_user.id for c in user_contracts)
        assert not any(c.id == c_user.id for c in admin_contracts)

        foreign = db.get_contract(c_user.id, owner_user_id=admin.id)
        assert foreign is None

    def test_comment_record_persistence(self, isolated_db: Path) -> None:
        admin = db.ensure_default_admin_user()
        contract = db.create_contract("C", "Cliente", owner_user_id=admin.id)
        version = db.add_version(contract.id, "v1", "x.pdf", "pdf", "texto")
        rec = db.save_comment_record(
            version.id,
            "stable-abc123",
            "Incluir multa",
            anchor_text="Cláusula 3",
            source="extracted",
        )
        assert rec.stable_id == "stable-abc123"
        rows = db.get_comment_records(version.id)
        assert len(rows) == 1
        found = db.get_comments_by_stable_ids(["stable-abc123"])
        assert len(found) == 1

    def test_delete_analysis_result(self, isolated_db: Path) -> None:
        from app.models.schemas import TextDiffResult
        from datetime import datetime, timezone

        admin = db.ensure_default_admin_user()
        contract = db.create_contract("C2", "Cliente", owner_user_id=admin.id)
        version = db.add_version(contract.id, "v1", "y.pdf", "pdf", "t")
        payload = TextDiffResult(
            contract_id=contract.id,
            version_a_label="A",
            version_b_label="B",
            analysis_timestamp=datetime.now(timezone.utc),
        )
        saved = db.save_analysis_result(version.id, "text_diff", payload)
        assert db.delete_analysis_result(saved.id)
        assert db.get_analysis_by_id(saved.id) is None


class TestUserCrud:
    def test_list_update_delete_user(self, isolated_db: Path) -> None:
        admin = db.ensure_default_admin_user()
        assert admin.is_admin

        user = db.create_user(
            f"crud_{uuid.uuid4().hex[:6]}@bgf.local",
            hash_password("senha123"),
            name="Operador",
        )
        users = db.list_users()
        assert any(u.id == user.id for u in users)

        updated = db.update_user(user.id, name="Operador BGF", is_active=False)
        assert updated is not None
        assert updated.name == "Operador BGF"
        assert updated.is_active is False

        db.update_user(user.id, is_active=True)
        db.delete_user(user.id, current_user_id=admin.id)
        assert db.get_user_by_id(user.id) is None

    def test_cannot_delete_last_admin(self, isolated_db: Path) -> None:
        admin = db.ensure_default_admin_user()
        with pytest.raises(ValueError, match="último administrador"):
            db.delete_user(admin.id, current_user_id="other-id")

    def test_duplicate_email_raises(self, isolated_db: Path) -> None:
        email = f"dup_{uuid.uuid4().hex[:6]}@bgf.local"
        db.create_user(email, hash_password("a"), name="A")
        with pytest.raises(ValueError, match="já cadastrado"):
            db.create_user(email, hash_password("b"), name="B")

    def test_inactive_flag_persisted(self, isolated_db: Path) -> None:
        email = f"off_{uuid.uuid4().hex[:6]}@bgf.local"
        user = db.create_user(email, hash_password("senha123"), name="Off")
        db.update_user(user.id, is_active=False)
        loaded = db.get_user_by_id(user.id)
        assert loaded is not None
        assert loaded.is_active is False
