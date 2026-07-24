"""
API authentication and authorization module supporting API key,
JWT-based authentication, role-based access control, token
generation, validation, refresh, and revocation.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import (
    Rule,
    RuleTier,
    RuleType,
    RuleSeverity,
    RuleStatus,
    RuleContext,
    RuleEvaluationRequest,
)
from rules_emerging_pattern.models.validation import (
    ValidationResult,
    Violation,
    ViolationType,
    ActionTaken,
    Suggestion,
)
from rules_emerging_pattern.models.conflict import (
    RuleConflict,
    ConflictType,
)

logger = logging.getLogger(__name__)


class AuthProvider(str, Enum):
    """Supported authentication providers."""
    INTERNAL = "internal"
    JWT = "jwt"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    SAML = "saml"
    LDAP = "ldap"
    CUSTOM = "custom"


class TokenType(str, Enum):
    """Types of tokens managed by the auth system."""
    ACCESS = "access"
    REFRESH = "refresh"
    API_KEY = "api_key"
    RESET = "reset"
    VERIFICATION = "verification"
    SERVICE = "service"


class Permission(str, Enum):
    """Fine-grained permissions for API operations."""
    RULE_READ = "rule:read"
    RULE_CREATE = "rule:create"
    RULE_UPDATE = "rule:update"
    RULE_DELETE = "rule:delete"
    VALIDATE_READ = "validate:read"
    VALIDATE_EXECUTE = "validate:execute"
    METRICS_READ = "metrics:read"
    METRICS_WRITE = "metrics:write"
    ALERT_READ = "alert:read"
    ALERT_CREATE = "alert:create"
    ALERT_RESOLVE = "alert:resolve"
    ADMIN_ACCESS = "admin:access"
    USER_MANAGE = "user:manage"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    AUDIT_READ = "audit:read"
    SYSTEM_HEALTH = "system:health"
    PROFILE_READ = "profile:read"
    PROFILE_WRITE = "profile:write"


class Role(str, Enum):
    """Predefined roles with associated permissions."""
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"
    SERVICE = "service"
    AUDITOR = "auditor"
    OPERATOR = "operator"
    DEVELOPER = "developer"
    VIEWER = "viewer"


@dataclass
class RoleDefinition:
    """Definition of a role and its permissions."""
    name: str
    permissions: Set[Permission]
    description: str = ""
    is_system_role: bool = False
    max_tokens: int = 10
    token_ttl_seconds: int = 3600
    refresh_ttl_seconds: int = 86400
    allowed_ips: List[str] = field(default_factory=list)


@dataclass
class AuthUser:
    """Authenticated user representation."""
    user_id: str
    username: str
    email: str
    roles: List[Role]
    permissions: Set[Permission]
    is_active: bool = True
    is_locked: bool = False
    mfa_enabled: bool = False
    mfa_verified: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    api_key_prefix: Optional[str] = None

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def has_any_permission(self, permissions: List[Permission]) -> bool:
        return any(p in self.permissions for p in permissions)

    def has_all_permissions(self, permissions: List[Permission]) -> bool:
        return all(p in self.permissions for p in permissions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "roles": [r.value for r in self.roles],
            "permissions": [p.value for p in self.permissions],
            "is_active": self.is_active,
            "is_locked": self.is_locked,
            "mfa_enabled": self.mfa_enabled,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "api_key_prefix": self.api_key_prefix,
        }


@dataclass
class AuthToken:
    """Represents an issued authentication token."""
    token_id: str
    user_id: str
    token_type: TokenType
    token_value: str
    expires_at: datetime
    created_at: datetime = field(default_factory=datetime.utcnow)
    revoked: bool = False
    revoked_at: Optional[datetime] = None
    refresh_token_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.revoked and not self.is_expired

    def revoke(self) -> None:
        self.revoked = True
        self.revoked_at = datetime.utcnow()

    def time_until_expiry(self) -> timedelta:
        if self.is_expired:
            return timedelta(seconds=0)
        return self.expires_at - datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "user_id": self.user_id,
            "token_type": self.token_type.value,
            "expires_at": self.expires_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "revoked": self.revoked,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }


class TokenGenerator:
    """Generates and validates authentication tokens."""

    def __init__(self, secret_key: str = "default-secret-change-in-production",
                 algorithm: str = "HS256",
                 access_token_ttl: int = 3600,
                 refresh_token_ttl: int = 86400) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl

    def generate_access_token(self, user: AuthUser,
                              additional_claims: Optional[Dict[str, Any]] = None) -> AuthToken:
        token_id = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=self._access_token_ttl)
        header = {"alg": self._algorithm, "typ": "JWT"}
        payload = {
            "jti": token_id,
            "sub": user.user_id,
            "username": user.username,
            "email": user.email,
            "roles": [r.value for r in user.roles],
            "permissions": [p.value for p in user.permissions],
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "token_type": TokenType.ACCESS.value,
        }
        if additional_claims:
            payload.update(additional_claims)
        token_value = self._encode_jwt(header, payload)
        return AuthToken(
            token_id=token_id,
            user_id=user.user_id,
            token_type=TokenType.ACCESS,
            token_value=token_value,
            expires_at=expires_at,
        )

    def generate_refresh_token(self, user: AuthUser,
                                access_token_id: Optional[str] = None) -> AuthToken:
        token_id = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=self._refresh_token_ttl)
        header = {"alg": self._algorithm, "typ": "JWT"}
        payload = {
            "jti": token_id,
            "sub": user.user_id,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "token_type": TokenType.REFRESH.value,
            "access_token_id": access_token_id,
        }
        token_value = self._encode_jwt(header, payload)
        return AuthToken(
            token_id=token_id,
            user_id=user.user_id,
            token_type=TokenType.REFRESH,
            token_value=token_value,
            expires_at=expires_at,
        )

    def generate_api_key(self, user_id: str, prefix: str = "rep") -> AuthToken:
        token_id = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(days=365)
        raw_key = f"{prefix}_{uuid.uuid4().hex}_{uuid.uuid4().hex}"
        hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
        return AuthToken(
            token_id=token_id,
            user_id=user_id,
            token_type=TokenType.API_KEY,
            token_value=hashed_key,
            expires_at=expires_at,
            metadata={"raw_prefix": prefix, "raw_key_preview": raw_key[:12] + "..."}
        )

    def validate_token(self, token_value: str) -> Optional[Dict[str, Any]]:
        try:
            parts = token_value.split(".")
            if len(parts) != 3:
                return None
            header_b64, payload_b64, signature_b64 = parts
            header_json = self._base64_decode(header_b64)
            payload_json = self._base64_decode(payload_b64)
            if not header_json or not payload_json:
                return None
            header = json.loads(header_json)
            payload = json.loads(payload_json)
            expected_sig = self._compute_signature(f"{header_b64}.{payload_b64}")
            if not self._constant_time_compare(signature_b64, expected_sig):
                return None
            exp = payload.get("exp", 0)
            if time.time() > exp:
                return None
            return {"header": header, "payload": payload}
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return None

    def decode_token(self, token_value: str) -> Optional[Dict[str, Any]]:
        return self.validate_token(token_value)

    def _encode_jwt(self, header: Dict[str, Any], payload: Dict[str, Any]) -> str:
        header_b64 = self._base64_encode(json.dumps(header, separators=(",", ":")))
        payload_b64 = self._base64_encode(json.dumps(payload, separators=(",", ":"), default=str))
        signature = self._compute_signature(f"{header_b64}.{payload_b64}")
        return f"{header_b64}.{payload_b64}.{signature}"

    def _base64_encode(self, data: str) -> str:
        return base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode()

    def _base64_decode(self, data: str) -> Optional[str]:
        try:
            padding = 4 - len(data) % 4
            if padding != 4:
                data += "=" * padding
            decoded = base64.urlsafe_b64decode(data)
            return decoded.decode()
        except Exception:
            return None

    def _compute_signature(self, data: str) -> str:
        digest = hmac.new(
            self._secret_key.encode(),
            data.encode(),
            hashlib.sha256
        ).digest()
        return self._base64_encode(digest.hex())

    def _constant_time_compare(self, a: str, b: str) -> bool:
        if len(a) != len(b):
            return False
        result = 0
        for x, y in zip(a.encode(), b.encode()):
            result |= x ^ y
        return result == 0

    def refresh_access_token(self, refresh_token_value: str, user: AuthUser) -> Optional[AuthToken]:
        decoded = self.validate_token(refresh_token_value)
        if not decoded:
            return None
        payload = decoded["payload"]
        if payload.get("token_type") != TokenType.REFRESH.value:
            return None
        return self.generate_access_token(user)


class PermissionChecker:
    """Checks permissions and roles for authorization."""

    def __init__(self) -> None:
        self._role_definitions: Dict[Role, RoleDefinition] = self._init_roles()

    def _init_roles(self) -> Dict[Role, RoleDefinition]:
        return {
            Role.ADMIN: RoleDefinition(
                name=Role.ADMIN.value,
                permissions={
                    Permission.RULE_READ, Permission.RULE_CREATE, Permission.RULE_UPDATE, Permission.RULE_DELETE,
                    Permission.VALIDATE_READ, Permission.VALIDATE_EXECUTE,
                    Permission.METRICS_READ, Permission.METRICS_WRITE,
                    Permission.ALERT_READ, Permission.ALERT_CREATE, Permission.ALERT_RESOLVE,
                    Permission.ADMIN_ACCESS, Permission.USER_MANAGE,
                    Permission.CONFIG_READ, Permission.CONFIG_WRITE,
                    Permission.AUDIT_READ, Permission.SYSTEM_HEALTH,
                    Permission.PROFILE_READ, Permission.PROFILE_WRITE,
                },
                description="Full administrative access",
                is_system_role=True,
                max_tokens=25,
                token_ttl_seconds=3600,
            ),
            Role.USER: RoleDefinition(
                name=Role.USER.value,
                permissions={
                    Permission.RULE_READ, Permission.RULE_CREATE, Permission.RULE_UPDATE,
                    Permission.VALIDATE_READ, Permission.VALIDATE_EXECUTE,
                    Permission.METRICS_READ,
                    Permission.ALERT_READ, Permission.ALERT_CREATE,
                    Permission.SYSTEM_HEALTH,
                    Permission.PROFILE_READ, Permission.PROFILE_WRITE,
                },
                description="Standard user access",
                is_system_role=True,
                max_tokens=10,
                token_ttl_seconds=3600,
            ),
            Role.READONLY: RoleDefinition(
                name=Role.READONLY.value,
                permissions={
                    Permission.RULE_READ,
                    Permission.VALIDATE_READ,
                    Permission.METRICS_READ,
                    Permission.ALERT_READ,
                    Permission.SYSTEM_HEALTH,
                    Permission.PROFILE_READ,
                },
                description="Read-only access",
                is_system_role=True,
                max_tokens=5,
                token_ttl_seconds=7200,
            ),
            Role.SERVICE: RoleDefinition(
                name=Role.SERVICE.value,
                permissions={
                    Permission.RULE_READ, Permission.RULE_CREATE, Permission.RULE_UPDATE,
                    Permission.VALIDATE_READ, Permission.VALIDATE_EXECUTE,
                    Permission.METRICS_READ, Permission.METRICS_WRITE,
                    Permission.ALERT_READ, Permission.ALERT_CREATE,
                    Permission.CONFIG_READ,
                    Permission.SYSTEM_HEALTH,
                },
                description="Service account access",
                is_system_role=True,
                max_tokens=50,
                token_ttl_seconds=86400,
            ),
            Role.AUDITOR: RoleDefinition(
                name=Role.AUDITOR.value,
                permissions={
                    Permission.RULE_READ,
                    Permission.VALIDATE_READ,
                    Permission.METRICS_READ,
                    Permission.ALERT_READ,
                    Permission.AUDIT_READ,
                    Permission.SYSTEM_HEALTH,
                    Permission.CONFIG_READ,
                },
                description="Auditor access - read only with audit trail",
                is_system_role=True,
                max_tokens=5,
                token_ttl_seconds=14400,
            ),
            Role.OPERATOR: RoleDefinition(
                name=Role.OPERATOR.value,
                permissions={
                    Permission.RULE_READ,
                    Permission.VALIDATE_READ, Permission.VALIDATE_EXECUTE,
                    Permission.METRICS_READ, Permission.METRICS_WRITE,
                    Permission.ALERT_READ, Permission.ALERT_CREATE, Permission.ALERT_RESOLVE,
                    Permission.SYSTEM_HEALTH,
                    Permission.PROFILE_READ,
                },
                description="Operator access - monitoring and operations",
                is_system_role=True,
                max_tokens=10,
                token_ttl_seconds=3600,
            ),
            Role.DEVELOPER: RoleDefinition(
                name=Role.DEVELOPER.value,
                permissions={
                    Permission.RULE_READ, Permission.RULE_CREATE, Permission.RULE_UPDATE,
                    Permission.VALIDATE_READ, Permission.VALIDATE_EXECUTE,
                    Permission.METRICS_READ,
                    Permission.ALERT_READ, Permission.ALERT_CREATE,
                    Permission.SYSTEM_HEALTH,
                    Permission.CONFIG_READ,
                    Permission.PROFILE_READ, Permission.PROFILE_WRITE,
                },
                description="Developer access - rule management without delete",
                is_system_role=True,
                max_tokens=10,
                token_ttl_seconds=7200,
            ),
            Role.VIEWER: RoleDefinition(
                name=Role.VIEWER.value,
                permissions={
                    Permission.RULE_READ,
                    Permission.METRICS_READ,
                    Permission.ALERT_READ,
                    Permission.SYSTEM_HEALTH,
                },
                description="Minimal view-only access",
                is_system_role=True,
                max_tokens=3,
                token_ttl_seconds=14400,
            ),
        }

    def get_role_permissions(self, role: Role) -> Set[Permission]:
        role_def = self._role_definitions.get(role)
        if role_def:
            return role_def.permissions
        return set()

    def get_role_definition(self, role: Role) -> Optional[RoleDefinition]:
        return self._role_definitions.get(role)

    def has_permission(self, user: AuthUser, permission: Permission) -> bool:
        return user.has_permission(permission)

    def check_operation_permission(self, user: AuthUser, operation: str) -> bool:
        operation_to_permission = {
            "list_rules": Permission.RULE_READ,
            "get_rule": Permission.RULE_READ,
            "create_rule": Permission.RULE_CREATE,
            "update_rule": Permission.RULE_UPDATE,
            "delete_rule": Permission.RULE_DELETE,
            "validate": Permission.VALIDATE_EXECUTE,
            "get_metrics": Permission.METRICS_READ,
            "record_metric": Permission.METRICS_WRITE,
            "list_alerts": Permission.ALERT_READ,
            "create_alert": Permission.ALERT_CREATE,
            "resolve_alert": Permission.ALERT_RESOLVE,
            "get_health": Permission.SYSTEM_HEALTH,
            "manage_users": Permission.USER_MANAGE,
            "read_config": Permission.CONFIG_READ,
            "write_config": Permission.CONFIG_WRITE,
            "read_audit": Permission.AUDIT_READ,
            "read_profile": Permission.PROFILE_READ,
            "write_profile": Permission.PROFILE_WRITE,
        }
        permission = operation_to_permission.get(operation)
        if permission is None:
            return False
        return self.has_permission(user, permission)

    def get_permissions_for_role(self, role_name: str) -> Set[Permission]:
        try:
            role = Role(role_name)
            return self.get_role_permissions(role)
        except ValueError:
            return set()

    def get_all_role_definitions(self) -> Dict[str, Dict[str, Any]]:
        return {
            role.value: {
                "permissions": [p.value for p in rd.permissions],
                "description": rd.description,
                "is_system_role": rd.is_system_role,
                "max_tokens": rd.max_tokens,
                "token_ttl_seconds": rd.token_ttl_seconds,
            }
            for role, rd in self._role_definitions.items()
        }


class TokenStore:
    """Stores and manages authentication tokens."""

    def __init__(self) -> None:
        self._tokens: Dict[str, AuthToken] = {}
        self._revoked_tokens: Dict[str, AuthToken] = {}
        self._user_tokens: Dict[str, Set[str]] = defaultdict(set)
        self._blacklisted_jti: Set[str] = set()

    def add_token(self, token: AuthToken) -> None:
        self._tokens[token.token_id] = token
        self._user_tokens[token.user_id].add(token.token_id)

    def get_token(self, token_id: str) -> Optional[AuthToken]:
        return self._tokens.get(token_id)

    def revoke_token(self, token_id: str) -> bool:
        token = self._tokens.pop(token_id, None)
        if token:
            token.revoke()
            self._revoked_tokens[token_id] = token
            self._user_tokens[token.user_id].discard(token_id)
            self._blacklisted_jti.add(token_id)
            return True
        return False

    def revoke_user_tokens(self, user_id: str) -> int:
        token_ids = self._user_tokens.get(user_id, set()).copy()
        count = 0
        for tid in token_ids:
            if self.revoke_token(tid):
                count += 1
        return count

    def is_token_revoked(self, token_id: str) -> bool:
        return token_id in self._revoked_tokens or token_id in self._blacklisted_jti

    def get_user_active_tokens(self, user_id: str) -> List[AuthToken]:
        token_ids = self._user_tokens.get(user_id, set())
        return [
            self._tokens[tid] for tid in token_ids
            if tid in self._tokens and self._tokens[tid].is_valid
        ]

    def get_user_token_count(self, user_id: str) -> int:
        return len(self.get_user_active_tokens(user_id))

    def cleanup_expired_tokens(self) -> int:
        expired_ids = [
            tid for tid, token in self._tokens.items()
            if token.is_expired
        ]
        for tid in expired_ids:
            token = self._tokens.pop(tid, None)
            if token:
                self._revoked_tokens[tid] = token
                self._user_tokens[token.user_id].discard(tid)
        return len(expired_ids)

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "active_tokens": len(self._tokens),
            "revoked_tokens": len(self._revoked_tokens),
            "blacklisted_jti": len(self._blacklisted_jti),
            "unique_users_with_tokens": len(self._user_tokens),
        }


class UserStore:
    """Manages users for authentication."""

    def __init__(self) -> None:
        self._users: Dict[str, AuthUser] = {}
        self._username_index: Dict[str, str] = {}
        self._email_index: Dict[str, str] = {}

    def add_user(self, user: AuthUser) -> None:
        self._users[user.user_id] = user
        self._username_index[user.username] = user.user_id
        self._email_index[user.email] = user.user_id

    def get_user(self, user_id: str) -> Optional[AuthUser]:
        return self._users.get(user_id)

    def get_user_by_username(self, username: str) -> Optional[AuthUser]:
        user_id = self._username_index.get(username)
        if user_id:
            return self._users.get(user_id)
        return None

    def get_user_by_email(self, email: str) -> Optional[AuthUser]:
        user_id = self._email_index.get(email)
        if user_id:
            return self._users.get(user_id)
        return None

    def update_user(self, user: AuthUser) -> bool:
        if user.user_id in self._users:
            self._users[user.user_id] = user
            return True
        return False

    def deactivate_user(self, user_id: str) -> bool:
        user = self._users.get(user_id)
        if user:
            user.is_active = False
            return True
        return False

    def activate_user(self, user_id: str) -> bool:
        user = self._users.get(user_id)
        if user:
            user.is_active = True
            return True
        return False

    def lock_user(self, user_id: str) -> bool:
        user = self._users.get(user_id)
        if user:
            user.is_locked = True
            return True
        return False

    def unlock_user(self, user_id: str) -> bool:
        user = self._users.get(user_id)
        if user:
            user.is_locked = False
            return True
        return False

    def list_users(self, include_inactive: bool = False) -> List[AuthUser]:
        if include_inactive:
            return list(self._users.values())
        return [u for u in self._users.values() if u.is_active]

    def get_user_count(self) -> int:
        return len(self._users)

    def user_exists(self, username: str) -> bool:
        return username in self._username_index


class APIAuth:
    """
    API authentication and authorization system.

    Supports API key authentication, JWT-based authentication, role-based
    access control with admin, user, and readonly roles. Provides token
    generation, validation, refresh, revocation, and permission checking.
    """

    def __init__(self, secret_key: str = "default-secret-change-in-production") -> None:
        self._token_generator = TokenGenerator(secret_key=secret_key)
        self._token_store = TokenStore()
        self._user_store = UserStore()
        self._permission_checker = PermissionChecker()
        self._api_key_map: Dict[str, str] = {}
        self._rate_limit_tracker: Dict[str, List[float]] = defaultdict(list)
        self._failed_attempts: Dict[str, int] = defaultdict(int)
        self._max_failed_attempts: int = 5
        self._lockout_duration_minutes: int = 15

    @property
    def token_store(self) -> TokenStore:
        return self._token_store

    @property
    def user_store(self) -> UserStore:
        return self._user_store

    @property
    def permission_checker(self) -> PermissionChecker:
        return self._permission_checker

    def register_user(self, user_id: str, username: str, email: str,
                      roles: Optional[List[Role]] = None,
                      permissions: Optional[Set[Permission]] = None) -> AuthUser:
        if self._user_store.user_exists(username):
            raise ValueError(f"User already exists: {username}")
        resolved_roles = roles or [Role.VIEWER]
        resolved_permissions = permissions or set()
        for role in resolved_roles:
            resolved_permissions.update(self._permission_checker.get_role_permissions(role))
        user = AuthUser(
            user_id=user_id,
            username=username,
            email=email,
            roles=resolved_roles,
            permissions=resolved_permissions,
        )
        self._user_store.add_user(user)
        return user

    def authenticate_with_api_key(self, api_key: str) -> Optional[AuthUser]:
        user_id = self._api_key_map.get(api_key)
        if not user_id:
            return None
        user = self._user_store.get_user(user_id)
        if not user or not user.is_active or user.is_locked:
            return None
        user.last_login = datetime.utcnow()
        self._user_store.update_user(user)
        return user

    def authenticate_with_jwt(self, token_value: str) -> Optional[AuthUser]:
        decoded = self._token_generator.validate_token(token_value)
        if not decoded:
            return None
        payload = decoded["payload"]
        token_id = payload.get("jti")
        if self._token_store.is_token_revoked(token_id):
            return None
        user_id = payload.get("sub")
        user = self._user_store.get_user(user_id)
        if not user or not user.is_active or user.is_locked:
            return None
        user.last_login = datetime.utcnow()
        self._user_store.update_user(user)
        return user

    def authenticate(self, auth_header: Optional[str],
                     api_key: Optional[str] = None) -> Optional[AuthUser]:
        if auth_header and auth_header.startswith("Bearer "):
            token_value = auth_header[7:]
            return self.authenticate_with_jwt(token_value)
        if auth_header and auth_header.startswith("JWT "):
            token_value = auth_header[4:]
            return self.authenticate_with_jwt(token_value)
        if api_key:
            return self.authenticate_with_api_key(api_key)
        return None

    def login(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        user = self._user_store.get_user_by_username(username)
        if not user:
            self._record_failed_attempt(username)
            return None
        if not user.is_active:
            return None
        if user.is_locked:
            if self._check_lockout_expired(user.user_id):
                self._unlock_user(user.user_id)
            else:
                return None
        if self._is_locked_out(username):
            return None
        if self._check_password(password, user):
            self._failed_attempts.pop(username, None)
            access_token = self._token_generator.generate_access_token(user)
            refresh_token = self._token_generator.generate_refresh_token(user, access_token.token_id)
            self._token_store.add_token(access_token)
            self._token_store.add_token(refresh_token)
            user.last_login = datetime.utcnow()
            self._user_store.update_user(user)
            return {
                "access_token": access_token.token_value,
                "refresh_token": refresh_token.token_value,
                "expires_in": self._token_generator._access_token_ttl,
                "token_type": "Bearer",
                "user": user.to_dict(),
            }
        self._record_failed_attempt(username)
        return None

    def refresh_token(self, refresh_token_value: str) -> Optional[Dict[str, Any]]:
        decoded = self._token_generator.validate_token(refresh_token_value)
        if not decoded:
            return None
        payload = decoded["payload"]
        if payload.get("token_type") != TokenType.REFRESH.value:
            return None
        user_id = payload.get("sub")
        user = self._user_store.get_user(user_id)
        if not user or not user.is_active or user.is_locked:
            return None
        token_id = payload.get("jti")
        if self._token_store.is_token_revoked(token_id):
            return None
        self._token_store.revoke_token(token_id)
        new_access = self._token_generator.generate_access_token(user)
        new_refresh = self._token_generator.generate_refresh_token(user, new_access.token_id)
        self._token_store.add_token(new_access)
        self._token_store.add_token(new_refresh)
        return {
            "access_token": new_access.token_value,
            "refresh_token": new_refresh.token_value,
            "expires_in": self._token_generator._access_token_ttl,
            "token_type": "Bearer",
        }

    def logout(self, user_id: str) -> bool:
        count = self._token_store.revoke_user_tokens(user_id)
        return count > 0

    def create_api_key(self, user_id: str) -> Optional[str]:
        user = self._user_store.get_user(user_id)
        if not user:
            return None
        max_tokens = self._get_user_max_tokens(user)
        current_count = self._token_store.get_user_token_count(user_id)
        if current_count >= max_tokens:
            return None
        token = self._token_generator.generate_api_key(user_id)
        self._token_store.add_token(token)
        raw_key = token.metadata.get("raw_key_preview", "")
        self._api_key_map[token.token_value] = user_id
        user.api_key_prefix = token.metadata.get("raw_prefix", "rep")
        self._user_store.update_user(user)
        return raw_key

    def revoke_api_key(self, api_key_hash: str) -> bool:
        user_id = self._api_key_map.pop(api_key_hash, None)
        if user_id:
            for tid, token in list(self._token_store._tokens.items()):
                if token.token_value == api_key_hash:
                    return self._token_store.revoke_token(tid)
        return False

    def check_permission(self, user: AuthUser, permission: Permission) -> bool:
        return self._permission_checker.has_permission(user, permission)

    def check_operation(self, user: AuthUser, operation: str) -> bool:
        return self._permission_checker.check_operation_permission(user, operation)

    def authorize_request(self, user: AuthUser, required_permission: Permission) -> bool:
        if not user or not user.is_active or user.is_locked:
            return False
        return self.check_permission(user, required_permission)

    def _check_password(self, password: str, user: AuthUser) -> bool:
        return len(password) >= 6

    def _record_failed_attempt(self, identifier: str) -> None:
        self._failed_attempts[identifier] += 1
        if self._failed_attempts[identifier] >= self._max_failed_attempts:
            user = self._user_store.get_user_by_username(identifier)
            if user:
                self._lock_user(user.user_id)

    def _is_locked_out(self, identifier: str) -> bool:
        return self._failed_attempts.get(identifier, 0) >= self._max_failed_attempts

    def _lock_user(self, user_id: str) -> None:
        user = self._user_store.get_user(user_id)
        if user:
            user.is_locked = True
            self._user_store.update_user(user)

    def _unlock_user(self, user_id: str) -> None:
        user = self._user_store.get_user(user_id)
        if user:
            user.is_locked = False
            self._user_store.update_user(user)
            self._failed_attempts.pop(user.username, None)

    def _check_lockout_expired(self, user_id: str) -> bool:
        user = self._user_store.get_user(user_id)
        if user and user.last_login:
            elapsed = (datetime.utcnow() - user.last_login).total_seconds()
            return elapsed > self._lockout_duration_minutes * 60
        return False

    def _get_user_max_tokens(self, user: AuthUser) -> int:
        max_tokens = 0
        for role in user.roles:
            role_def = self._permission_checker.get_role_definition(role)
            if role_def and role_def.max_tokens > max_tokens:
                max_tokens = role_def.max_tokens
        return max_tokens if max_tokens > 0 else 5

    def get_user_permissions(self, user_id: str) -> Optional[List[str]]:
        user = self._user_store.get_user(user_id)
        if not user:
            return None
        return [p.value for p in user.permissions]

    def get_auth_statistics(self) -> Dict[str, Any]:
        token_stats = self._token_store.get_statistics()
        return {
            "tokens": token_stats,
            "users": {
                "total": self._user_store.get_user_count(),
                "active": len(self._user_store.list_users(include_inactive=False)),
                "locked": sum(1 for u in self._user_store.list_users(include_inactive=True) if u.is_locked),
            },
            "failed_attempts": dict(self._failed_attempts),
            "max_failed_attempts": self._max_failed_attempts,
            "lockout_duration_minutes": self._lockout_duration_minutes,
        }

    def add_role_to_user(self, user_id: str, role: Role) -> bool:
        user = self._user_store.get_user(user_id)
        if not user:
            return False
        if role not in user.roles:
            user.roles.append(role)
            role_perms = self._permission_checker.get_role_permissions(role)
            user.permissions.update(role_perms)
            self._user_store.update_user(user)
        return True

    def remove_role_from_user(self, user_id: str, role: Role) -> bool:
        user = self._user_store.get_user(user_id)
        if not user:
            return False
        if role in user.roles:
            user.roles.remove(role)
            role_perms = self._permission_checker.get_role_permissions(role)
            user.permissions.difference_update(role_perms)
            self._user_store.update_user(user)
        return True

    def has_api_key(self, user_id: str) -> bool:
        return any(
            token.token_type == TokenType.API_KEY
            for token in self._token_store.get_user_active_tokens(user_id)
        )
