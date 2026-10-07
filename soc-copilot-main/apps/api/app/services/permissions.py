"""RBAC permission registry + DB-backed overrides.

The registry is the source of truth for *which* permission keys exist and
*what they default to* per role. The `role_permissions` table only stores
deviations from those defaults, so the system is always self-describing —
an admin can wipe the table and end up back at the original policy.

`permissions.manage` is locked: admins always have it, analysts never do.
That lock prevents an admin from accidentally removing their own ability to
recover the policy.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import DbSession
from app.middleware.auth import CurrentUser
from app.models import RolePermission, User, UserRole


@dataclass(frozen=True)
class PermissionDef:
    key: str
    area: str
    action: str
    default_analyst: bool
    default_admin: bool
    locked: bool = False  # If True, defaults can't be overridden in the DB.


# Registry. Keep keys stable — they're stored in role_permissions and audited.
REGISTRY: tuple[PermissionDef, ...] = (
    PermissionDef(
        "users.list", "Usuarios", "Listar usuarios",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "users.create", "Usuarios", "Crear usuario",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "users.delete", "Usuarios", "Eliminar usuario",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "users.update_role", "Usuarios", "Cambiar rol",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "users.update_password", "Usuarios", "Resetear contraseña ajena",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "users.update_level", "Usuarios", "Asignar nivel SOC",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "audit.view", "Auditoría", "Ver registro de auditoría",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "users.reset_llm_quota", "Usuarios", "Resetear cuota diaria de IA",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "users.reset_mfa", "Usuarios", "Resetear MFA (TOTP) de un usuario",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "integrations.manage", "Integraciones", "Ver estado y sincronizar SIEM (Wazuh)",
        default_analyst=False, default_admin=True,
    ),
    PermissionDef(
        "permissions.manage", "Permisos", "Modificar matriz de permisos",
        default_analyst=False, default_admin=True, locked=True,
    ),
)

_BY_KEY = {p.key: p for p in REGISTRY}


def _default_for(role: UserRole, key: str) -> bool:
    p = _BY_KEY[key]
    return p.default_admin if role == UserRole.ADMIN else p.default_analyst


def is_allowed(db: Session, role: UserRole, key: str) -> bool:
    if key not in _BY_KEY:
        return False
    p = _BY_KEY[key]
    if p.locked:
        return _default_for(role, key)
    row = db.scalar(
        select(RolePermission).where(
            RolePermission.role == role,
            RolePermission.permission_key == key,
        )
    )
    return row.allowed if row is not None else _default_for(role, key)


def list_effective(db: Session) -> list[dict]:
    """Return every (role x permission) cell with its current effective value."""
    out = []
    for p in REGISTRY:
        for role in UserRole:
            out.append(
                {
                    "permission_key": p.key,
                    "area": p.area,
                    "action": p.action,
                    "role": role.value,
                    "allowed": is_allowed(db, role, p.key),
                    "locked": p.locked,
                    "default": _default_for(role, p.key),
                }
            )
    return out


def set_permission(
    db: Session, role: UserRole, key: str, allowed: bool
) -> None:
    if key not in _BY_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown permission '{key}'",
        )
    if _BY_KEY[key].locked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"permission '{key}' is locked and cannot be modified",
        )
    row = db.scalar(
        select(RolePermission).where(
            RolePermission.role == role,
            RolePermission.permission_key == key,
        )
    )
    if row is None:
        row = RolePermission(role=role, permission_key=key, allowed=allowed)
        db.add(row)
    else:
        row.allowed = allowed


def require_perm(key: str):
    """FastAPI dependency factory: 403 unless the user's role has `key`."""
    if key not in _BY_KEY:
        raise RuntimeError(f"unknown permission key '{key}'")

    def _dep(user: CurrentUser, db: DbSession) -> User:
        if not is_allowed(db, user.role, key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"permission denied: {key}",
            )
        return user

    return Depends(_dep)
