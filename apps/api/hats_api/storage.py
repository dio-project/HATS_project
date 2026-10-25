"""Transactional persistence for HATS configuration, drafts, history, and audit events."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Iterator

from sqlalchemy import ForeignKey, Integer, String, Text, create_engine, delete, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from hats_api.config import SystemConfig


def utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


class StoreError(Exception):
    """Base class for expected persistence-layer errors."""


class VersionConflict(StoreError):
    def __init__(self, active_version: int):
        self.active_version = active_version
        super().__init__(f"Active configuration is version {active_version}")


class DraftNotFound(StoreError):
    pass


class InvalidConfirmation(StoreError):
    pass


class Base(DeclarativeBase):
    pass


class ConfigurationSnapshot(Base):
    __tablename__ = "configuration_snapshots"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)


class AppState(Base):
    __tablename__ = "app_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active_version: Mapped[int] = mapped_column(
        ForeignKey("configuration_snapshots.version"), nullable=False
    )


class ConfigurationDraft(Base):
    __tablename__ = "configuration_drafts"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[str] = mapped_column(String(64), nullable=False)
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class ConfigStore:
    """SQLAlchemy-backed store; SQLite is suitable for development, PostgreSQL for deployment."""

    def __init__(self, database_url: str | None = None):
        raw_url = database_url or os.getenv("HATS_DATABASE_URL") or os.getenv(
            "DATABASE_URL", "sqlite:///./.hats/hats.db"
        )
        if raw_url.startswith("postgresql://"):
            raw_url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
        url = make_url(raw_url)
        connect_args: dict = {}
        engine_options: dict = {"pool_pre_ping": True}
        if url.get_backend_name() == "sqlite":
            connect_args["check_same_thread"] = False
            if url.database and url.database not in {":memory:"}:
                Path(url.database).expanduser().resolve().parent.mkdir(
                    parents=True, exist_ok=True
                )
            else:
                engine_options["poolclass"] = StaticPool
        self.engine: Engine = create_engine(
            url, connect_args=connect_args, **engine_options
        )
        self._sessions = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=Session
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._sessions.begin() as session:
            yield session

    def initialize(self) -> None:
        """Bootstrap missing tables and seed the first configuration once."""
        Base.metadata.create_all(self.engine)
        with self.session() as session:
            state = session.get(AppState, 1)
            if state is None:
                initial = SystemConfig()
                session.add(
                    ConfigurationSnapshot(
                        version=initial.version,
                        updated_at=initial.updated_at.isoformat(),
                        config_json=initial.model_dump_json(),
                        label="Initial defaults",
                    )
                )
                session.flush()
                session.add(AppState(id=1, active_version=initial.version))

    def reset_for_tests(self) -> None:
        """Reset the store. Intended only for isolated automated tests."""
        Base.metadata.drop_all(self.engine)
        self.initialize()

    def get_active(self) -> SystemConfig:
        with self.session() as session:
            state = session.get(AppState, 1)
            if state is None:
                raise RuntimeError("Configuration store has not been initialized")
            snapshot = session.get(ConfigurationSnapshot, state.active_version)
            if snapshot is None:
                raise RuntimeError("Active configuration snapshot is missing")
            return SystemConfig.model_validate_json(snapshot.config_json)

    def get_history(self) -> dict:
        with self.session() as session:
            state = session.get(AppState, 1)
            rows = session.scalars(
                select(ConfigurationSnapshot).order_by(
                    ConfigurationSnapshot.version.desc()
                )
            ).all()
            return {
                "configurations": [
                    {
                        "version": row.version,
                        "updated_at": row.updated_at,
                        "label": row.label,
                    }
                    for row in rows
                ],
                "active_version": state.active_version if state else None,
            }

    def get_version(self, version: int) -> dict | None:
        with self.session() as session:
            row = session.get(ConfigurationSnapshot, version)
            if row is None:
                return None
            return {
                "configuration": json.loads(row.config_json),
                "label": row.label,
            }

    def get_audit(self, limit: int = 100) -> list[dict]:
        with self.session() as session:
            rows = session.scalars(
                select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
            ).all()
            return [
                {"at": row.at, "event": row.event, **json.loads(row.payload_json)}
                for row in reversed(rows)
            ]

    def _audit(self, session: Session, event: str, payload: dict) -> None:
        session.add(
            AuditEvent(
                at=_utc_iso(),
                event=event,
                payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            )
        )

    def create_draft(
        self, expected_version: int, candidate: SystemConfig, draft_id: str
    ) -> dict:
        with self.session() as session:
            state = session.scalar(
                select(AppState).where(AppState.id == 1).with_for_update()
            )
            if state is None:
                raise RuntimeError("Configuration store has not been initialized")
            if state.active_version != expected_version:
                raise VersionConflict(state.active_version)
            candidate = candidate.model_copy(deep=True)
            candidate.version = state.active_version + 1
            candidate.updated_at = utc_now()
            snapshot = candidate.model_dump(mode="json")
            digest = __import__("hashlib").sha256(
                json.dumps(snapshot, sort_keys=True).encode()
            ).hexdigest()
            session.add(
                ConfigurationDraft(
                    id=draft_id,
                    config_json=json.dumps(snapshot, sort_keys=True),
                    digest=digest,
                    base_version=state.active_version,
                    created_at=_utc_iso(),
                )
            )
            self._audit(
                session,
                "config_draft_created",
                {
                    "draft_id": draft_id,
                    "base_version": state.active_version,
                    "digest": digest,
                },
            )
            return {
                "draft_id": draft_id,
                "digest": digest,
                "requires_confirmation_phrase": "APPLY CONFIG",
                "proposed_config": snapshot,
            }

    def confirm_draft(self, draft_id: str, confirmation_phrase: str) -> dict:
        if confirmation_phrase != "APPLY CONFIG":
            raise InvalidConfirmation("Confirmation phrase does not match")
        with self.session() as session:
            draft = session.get(ConfigurationDraft, draft_id)
            if draft is None:
                raise DraftNotFound("Draft not found or already consumed")
            state = session.scalar(
                select(AppState).where(AppState.id == 1).with_for_update()
            )
            if state is None:
                raise RuntimeError("Configuration store has not been initialized")
            if draft.base_version != state.active_version:
                raise VersionConflict(state.active_version)
            candidate = SystemConfig.model_validate_json(draft.config_json)
            previous_version = state.active_version
            session.add(
                ConfigurationSnapshot(
                    version=candidate.version,
                    updated_at=candidate.updated_at.isoformat(),
                    config_json=candidate.model_dump_json(),
                    label=f"Configuration v{candidate.version}",
                )
            )
            session.flush()
            state.active_version = candidate.version
            session.delete(draft)
            self._audit(
                session,
                "config_activated",
                {
                    "previous_version": previous_version,
                    "active_version": candidate.version,
                    "digest": draft.digest,
                },
            )
            return {
                "status": "activated",
                "active": candidate.model_dump(mode="json"),
                "audit_event_recorded": True,
            }

    def clear_history(self) -> int:
        with self.session() as session:
            state = session.scalar(
                select(AppState).where(AppState.id == 1).with_for_update()
            )
            if state is None:
                raise RuntimeError("Configuration store has not been initialized")
            active = session.get(ConfigurationSnapshot, state.active_version)
            if active is None:
                raise RuntimeError("Active configuration snapshot is missing")
            session.execute(
                delete(ConfigurationSnapshot).where(
                    ConfigurationSnapshot.version != state.active_version
                )
            )
            active.label = "Active configuration (retained)"
            self._audit(
                session,
                "config_history_cleared",
                {"active_version_retained": state.active_version},
            )
            return state.active_version
