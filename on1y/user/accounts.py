"""User account CRUD backed by SQLite."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from on1y.auth.passwords import hash_password, verify_password
from on1y.config import Settings, get_settings
from on1y.user.migrate import migrate_legacy_files_to_user
from on1y.user.profile import _default_payload, _normalize_profile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserRow:
    id: int
    username: str
    email: str | None
    display_name: str
    is_active: bool
    created_at: str | None


def _row_to_user(row: Any) -> UserRow:
    return UserRow(
        id=int(row["id"]),
        username=str(row["username"]),
        email=str(row["email"]) if row["email"] else None,
        display_name=str(row["display_name"] or ""),
        is_active=bool(row["is_active"]),
        created_at=str(row["created_at"]) if row["created_at"] else None,
    )


def user_public_dict(user: UserRow) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at,
    }


class UserStore:
    def __init__(self, storage: Any) -> None:
        self._storage = storage

    def _conn(self) -> Any:
        return self._storage._connect()

    def _schema_has_users(self) -> bool:
        return self._storage._current_schema_version(self._conn()) >= 9

    def count_users(self) -> int:
        if not self._schema_has_users():
            return 0
        row = self._conn().execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"]) if row else 0

    def list_active_user_ids(self) -> list[int]:
        if not self._schema_has_users():
            return [1]
        rows = self._conn().execute(
            "SELECT id FROM users WHERE is_active = 1 ORDER BY id ASC"
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def get_user_by_id(self, user_id: int) -> UserRow | None:
        if not self._schema_has_users():
            return None
        row = self._conn().execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1",
            (user_id,),
        ).fetchone()
        return _row_to_user(row) if row else None

    def get_user_by_username(self, username: str) -> UserRow | None:
        if not self._schema_has_users():
            return None
        row = self._conn().execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
        return _row_to_user(row) if row else None

    def create_user(
        self,
        *,
        username: str,
        password: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> UserRow:
        if not self._schema_has_users():
            raise RuntimeError("users table not available (schema < 9)")
        name = username.strip()
        if not name:
            raise ValueError("username is required")
        pwd_hash = hash_password(password)
        disp = (display_name or name).strip()
        mail = (email or "").strip() or None
        with self._storage.transaction() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO users (username, email, password_hash, display_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (name, mail, pwd_hash, disp),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise ValueError("username or email already exists") from exc
                raise
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if row is None:
                raise RuntimeError("failed to create user")
            user = _row_to_user(row)
            profile = _default_payload()
            profile["owner"] = name
            conn.execute(
                """
                INSERT INTO user_profiles (user_id, profile_json, updated_at)
                VALUES (?, ?, datetime('now'))
                """,
                (user.id, json.dumps(_normalize_profile(profile), ensure_ascii=False)),
            )
            from on1y.subscriptions.settings import _empty_payload

            conn.execute(
                """
                INSERT INTO user_subscription_settings (user_id, settings_json, updated_at)
                VALUES (?, ?, datetime('now'))
                """,
                (user.id, json.dumps(_empty_payload(), ensure_ascii=False)),
            )
        return user

    def update_profile_fields(
        self,
        user_id: int,
        *,
        display_name: str | None = None,
        email: str | None = None,
    ) -> UserRow:
        if not self._schema_has_users():
            raise RuntimeError("users table not available (schema < 9)")
        sets: list[str] = []
        params: list[Any] = []
        if display_name is not None:
            sets.append("display_name = ?")
            params.append(display_name.strip())
        if email is not None:
            sets.append("email = ?")
            params.append(email.strip() or None)
        if not sets:
            user = self.get_user_by_id(user_id)
            if user is None:
                raise ValueError("user not found")
            return user
        params.append(user_id)
        with self._storage.transaction() as conn:
            try:
                conn.execute(
                    f"UPDATE users SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise ValueError("email already in use") from exc
                raise
        user = self.get_user_by_id(user_id)
        if user is None:
            raise ValueError("user not found")
        return user

    def verify_user_password(self, user_id: int, password: str) -> bool:
        row = self._conn().execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return False
        return verify_password(password, str(row["password_hash"]))

    def set_password_by_id(self, user_id: int, password: str) -> None:
        if not self._schema_has_users():
            raise RuntimeError("users table not available (schema < 9)")
        pwd_hash = hash_password(password)
        with self._storage.transaction() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (pwd_hash, user_id),
            )

    def set_password(self, username: str, password: str) -> UserRow:
        if not self._schema_has_users():
            raise RuntimeError("users table not available (schema < 9)")
        pwd_hash = hash_password(password)
        with self._storage.transaction() as conn:
            cur = conn.execute(
                """
                UPDATE users SET password_hash = ?
                WHERE username = ? COLLATE NOCASE AND is_active = 1
                """,
                (pwd_hash, username.strip()),
            )
            if cur.rowcount == 0:
                raise ValueError(f"user not found: {username}")
        user = self.get_user_by_username(username)
        if user is None:
            raise ValueError(f"user not found: {username}")
        return user

    def authenticate(self, username: str, password: str) -> UserRow | None:
        if not self._schema_has_users():
            return None
        row = self._conn().execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND is_active = 1",
            (username.strip(),),
        ).fetchone()
        if row is None:
            return None
        if not verify_password(password, str(row["password_hash"])):
            return None
        return _row_to_user(row)

    def get_profile_json(self, user_id: int) -> dict[str, Any] | None:
        if not self._schema_has_users():
            return None
        row = self._conn().execute(
            "SELECT profile_json FROM user_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(str(row["profile_json"]))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    def save_profile_json(self, user_id: int, profile: dict[str, Any]) -> None:
        if not self._schema_has_users():
            return
        payload = json.dumps(profile, ensure_ascii=False)
        with self._storage.transaction() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles (user_id, profile_json, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = datetime('now')
                """,
                (user_id, payload),
            )

    def get_subscription_json(self, user_id: int) -> dict[str, Any] | None:
        if not self._schema_has_users():
            return None
        row = self._conn().execute(
            "SELECT settings_json FROM user_subscription_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(str(row["settings_json"]))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    def save_subscription_json(self, user_id: int, settings: dict[str, Any]) -> None:
        if not self._schema_has_users():
            return
        payload = json.dumps(settings, ensure_ascii=False)
        with self._storage.transaction() as conn:
            conn.execute(
                """
                INSERT INTO user_subscription_settings (user_id, settings_json, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    settings_json = excluded.settings_json,
                    updated_at = datetime('now')
                """,
                (user_id, payload),
            )


def bootstrap_default_user(storage: Any, *, settings: Settings | None = None) -> UserRow | None:
    """Create the first user from env and import legacy data/user_profile.json."""
    settings = settings or get_settings()
    store = UserStore(storage)
    if store.count_users() > 0:
        ids = store.list_active_user_ids()
        user = store.get_user_by_id(ids[0]) if ids else None
        if user is not None:
            assign_orphan_raw_items_to_user(user.id, storage)
        return user

    legacy = migrate_legacy_files_to_user(1, settings=settings)
    username = (settings.bootstrap_username or "admin").strip()
    password = (settings.bootstrap_password or "").strip()
    if not password:
        import secrets

        password = secrets.token_urlsafe(12)
        logger.warning(
            "Created bootstrap user %r with generated password (save it now): %s",
            username,
            password,
        )
    email = (settings.bootstrap_email or "").strip() or None

    with storage.transaction() as conn:
        conn.execute(
            """
            INSERT INTO users (id, username, email, password_hash, display_name)
            VALUES (1, ?, ?, ?, ?)
            """,
            (username, email, hash_password(password), username),
        )
        profile = _default_payload(settings)
        if legacy.get("profile") and isinstance(legacy.get("profile_payload"), dict):
            profile = _normalize_profile({**profile, **legacy["profile_payload"]})
        profile["owner"] = username
        from on1y.user.paths import COOKIE_PLATFORMS, user_cookie_path

        cookies_map = profile.setdefault("integrations", {}).setdefault("cookies", {})
        if not isinstance(cookies_map, dict):
            cookies_map = {}
            profile["integrations"]["cookies"] = cookies_map
        for platform in COOKIE_PLATFORMS:
            cookies_map[platform] = str(user_cookie_path(1, platform))

        conn.execute(
            """
            INSERT INTO user_profiles (user_id, profile_json, updated_at)
            VALUES (1, ?, datetime('now'))
            """,
            (json.dumps(profile, ensure_ascii=False),),
        )
        from on1y.subscriptions.settings import _empty_payload

        sub = _empty_payload()
        if legacy.get("subscription") and isinstance(legacy.get("subscription_payload"), dict):
            sub.update(legacy["subscription_payload"])
        conn.execute(
            """
            INSERT INTO user_subscription_settings (user_id, settings_json, updated_at)
            VALUES (1, ?, datetime('now'))
            """,
            (json.dumps(sub, ensure_ascii=False),),
        )

    with storage.transaction() as conn:
        conn.execute("UPDATE raw_items SET user_id = 1 WHERE user_id IS NULL")
    user = store.get_user_by_id(1)
    logger.info("Bootstrapped default user id=1 username=%s", username)
    return user


def assign_orphan_raw_items_to_user(user_id: int, storage: Any) -> int:
    with storage.transaction() as conn:
        cur = conn.execute(
            "UPDATE raw_items SET user_id = ? WHERE user_id IS NULL",
            (user_id,),
        )
        return int(cur.rowcount)
