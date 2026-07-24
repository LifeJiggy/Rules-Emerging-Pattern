"""Authentication and authorization middleware for the rules engine."""

import base64
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


class AuthProviderType(Enum):
    TOKEN = "token"
    API_KEY = "api_key"
    SESSION = "session"
    JWT = "jwt"
    OAUTH2 = "oauth2"
    BASIC = "basic"
    BEARER = "bearer"
    CUSTOM = "custom"


class AuthResult(Enum):
    GRANTED = "granted"
    DENIED = "denied"
    EXPIRED = "expired"
    INVALID = "invalid"
    MISSING = "missing"
    REQUIRES_MFA = "requires_mfa"
    RATE_LIMITED = "rate_limited"


class Permission(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"
    EXECUTE = "execute"
    MANAGE = "manage"
    AUDIT = "audit"
    CONFIGURE = "configure"
    EXPORT = "export"
    IMPORT = "import"


@dataclass
class AuthProviderConfig:
    type: AuthProviderType = AuthProviderType.BEARER
    enabled: bool = True
    order: int = 0
    config: Dict[str, Any] = field(default_factory=dict)
    name: str = ""


@dataclass
class TokenConfig:
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expiry: int = 3600
    refresh_token_expiry: int = 86400
    issuer: str = "rules-engine"
    audience: str = "rules-engine-api"
    min_secret_length: int = 32
    token_prefix: str = "Bearer"
    validate_issuer: bool = True
    validate_audience: bool = True
    validate_expiry: bool = True
    clock_skew_seconds: int = 30
    rotate_refresh_tokens: bool = True
    max_refresh_token_uses: int = 10
    store_refresh_tokens: bool = True


@dataclass
class APIKeyConfig:
    header_name: str = "X-API-Key"
    query_param: str = "api_key"
    key_prefix: str = "sk_"
    key_length: int = 32
    hash_keys: bool = True
    hash_algorithm: str = "sha256"
    allow_in_query: bool = False
    allow_in_header: bool = True
    max_keys_per_user: int = 10
    key_expiry_days: Optional[int] = 90
    rate_limit_per_key: int = 1000


@dataclass
class SessionConfig:
    session_header: str = "X-Session-ID"
    session_cookie: str = "session_id"
    session_ttl: int = 1800
    max_sessions_per_user: int = 5
    extend_on_activity: bool = True
    extend_window: int = 300
    validate_ip: bool = True
    validate_user_agent: bool = False
    rotate_session_id: bool = True
    rotation_interval: int = 3600


@dataclass
class RoleConfig:
    roles_field: str = "roles"
    default_role: str = "viewer"
    roles: Dict[str, List[str]] = field(default_factory=lambda: {
        "admin": ["read", "write", "delete", "admin", "manage", "audit", "configure", "export", "import"],
        "editor": ["read", "write", "export", "import"],
        "viewer": ["read", "export"],
        "auditor": ["read", "audit", "export"],
    })
    role_hierarchy: Dict[str, List[str]] = field(default_factory=lambda: {
        "admin": ["editor", "viewer", "auditor"],
        "editor": ["viewer"],
        "auditor": ["viewer"],
    })
    allow_role_inheritance: bool = True


@dataclass
class AuthConfig:
    enabled: bool = True
    default_provider: AuthProviderType = AuthProviderType.BEARER
    providers: List[AuthProviderConfig] = field(default_factory=lambda: [
        AuthProviderConfig(type=AuthProviderType.BEARER, name="bearer"),
        AuthProviderConfig(type=AuthProviderType.API_KEY, name="api_key", order=1),
    ])
    token: TokenConfig = field(default_factory=TokenConfig)
    api_key: APIKeyConfig = field(default_factory=APIKeyConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    roles: RoleConfig = field(default_factory=RoleConfig)
    public_routes: List[str] = field(default_factory=lambda: [
        "/health", "/metrics", "/docs", "/openapi.json",
    ])
    public_path_prefixes: List[str] = field(default_factory=lambda: [
        "/public/", "/static/", "/favicon",
    ])
    auth_header: str = "Authorization"
    challenge_on_missing: bool = True
    challenge_header: str = "WWW-Authenticate"
    challenge_value: str = "Bearer realm=\"rules-engine\""
    cache_auth_results: bool = True
    auth_cache_ttl: int = 60
    max_auth_failures: int = 5
    auth_failure_window: int = 300
    enforce_mfa_for_roles: List[str] = field(default_factory=lambda: [
        "admin",
    ])
    mfa_check_path: str = "/auth/mfa/verify"
    propagate_user_context: bool = True
    user_context_field: str = "_user"


@dataclass
class UserContext:
    user_id: str
    username: str
    roles: List[str]
    permissions: Set[str]
    token: Optional[str] = None
    session_id: Optional[str] = None
    api_key_id: Optional[str] = None
    provider: Optional[str] = None
    authenticated: bool = False
    mfa_verified: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    expires_at: Optional[float] = None
    issued_at: float = field(default_factory=time.time)


@dataclass
class AuthResultData:
    result: AuthResult
    user: Optional[UserContext] = None
    error: Optional[str] = None
    status_code: int = 401
    headers: Dict[str, str] = field(default_factory=dict)
    challenge: Optional[str] = None


class TokenHandler:
    def __init__(self, config: TokenConfig):
        self.config = config

    def generate_token(self, user_id: str, roles: List[str], metadata: Optional[Dict[str, Any]] = None) -> str:
        now = int(time.time())
        payload = {
            "sub": user_id,
            "roles": roles,
            "iat": now,
            "exp": now + self.config.access_token_expiry,
            "jti": str(uuid.uuid4()),
            "iss": self.config.issuer,
            "aud": self.config.audience,
        }
        if metadata:
            payload["metadata"] = metadata
        header = {"alg": self.config.algorithm, "typ": "JWT"}
        segments = [
            self._base64url_encode(json.dumps(header)),
            self._base64url_encode(json.dumps(payload)),
        ]
        signing_input = ".".join(segments)
        signature = self._sign(signing_input)
        segments.append(self._base64url_encode(signature))
        return f"{self.config.token_prefix} {'.'.join(segments)}"

    def generate_refresh_token(self, user_id: str) -> str:
        data = {
            "sub": user_id,
            "type": "refresh",
            "jti": str(uuid.uuid4()),
            "exp": int(time.time()) + self.config.refresh_token_expiry,
        }
        raw = json.dumps(data, separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    def validate_token(self, token: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        if " " in token:
            parts = token.split(" ")
            if len(parts) != 2 or parts[0] != self.config.token_prefix:
                return False, None, "Invalid token format"
            token = parts[1]
        segments = token.split(".")
        if len(segments) != 3:
            return False, None, "Invalid token segments"
        try:
            header_b64 = segments[0]
            payload_b64 = segments[1]
            signature_b64 = segments[2]
            header = json.loads(self._base64url_decode(header_b64))
            payload = json.loads(self._base64url_decode(payload_b64))
            signing_input = f"{header_b64}.{payload_b64}"
            expected_sig = self._sign(signing_input)
            if not hmac.compare_digest(expected_sig, self._base64url_decode(signature_b64)):
                return False, None, "Invalid signature"
            if self.config.validate_expiry:
                now = time.time()
                exp = payload.get("exp", 0)
                if exp + self.config.clock_skew_seconds < now:
                    return False, None, "Token expired"
            if self.config.validate_issuer:
                if payload.get("iss") != self.config.issuer:
                    return False, None, "Invalid issuer"
            if self.config.validate_audience:
                if payload.get("aud") != self.config.audience:
                    return False, None, "Invalid audience"
            return True, payload, None
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            return False, None, f"Token decode failed: {e}"

    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        valid, payload, error = self.validate_token(token)
        return payload if valid else None

    def refresh_access_token(self, refresh_token: str) -> Tuple[Optional[str], Optional[str]]:
        try:
            decoded = base64.urlsafe_b64decode(refresh_token + "==").decode()
            data = json.loads(decoded)
            if data.get("type") != "refresh":
                return None, "Invalid refresh token type"
            if data.get("exp", 0) < time.time():
                return None, "Refresh token expired"
            user_id = data.get("sub", "")
            roles = data.get("roles", ["viewer"])
            new_token = self.generate_token(user_id, roles)
            return new_token, None
        except (json.JSONDecodeError, ValueError, base64.binascii.Error) as e:
            return None, f"Refresh token decode failed: {e}"

    def get_token_expiry(self, token: str) -> Optional[int]:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            payload = json.loads(self._base64url_decode(parts[1]))
            return payload.get("exp")
        except (json.JSONDecodeError, ValueError, IndexError):
            return None

    def revoke_token(self, token: str) -> bool:
        logger.info("Token revocation requested: %s...", token[:20])
        return True

    def _sign(self, data: str) -> bytes:
        if self.config.algorithm == "HS256":
            return hmac.new(
                self.config.secret_key.encode(),
                data.encode(),
                hashlib.sha256,
            ).digest()
        elif self.config.algorithm == "HS384":
            return hmac.new(
                self.config.secret_key.encode(),
                data.encode(),
                hashlib.sha384,
            ).digest()
        elif self.config.algorithm == "HS512":
            return hmac.new(
                self.config.secret_key.encode(),
                data.encode(),
                hashlib.sha512,
            ).digest()
        else:
            raise ValueError(f"Unsupported algorithm: {self.config.algorithm}")

    @staticmethod
    def _base64url_encode(data: Union[str, bytes]) -> str:
        if isinstance(data, str):
            data = data.encode()
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    @staticmethod
    def _base64url_decode(data: str) -> bytes:
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)


class APIKeyHandler:
    def __init__(self, config: APIKeyConfig):
        self.config = config
        self._keys: Dict[str, Dict[str, Any]] = {}

    def generate_key(self, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        key = self.config.key_prefix + uuid.uuid4().hex[: self.config.key_length]
        hashed = self._hash_key(key) if self.config.hash_keys else key
        self._keys[hashed] = {
            "user_id": user_id,
            "created_at": time.time(),
            "last_used": None,
            "usage_count": 0,
            "enabled": True,
            "metadata": metadata or {},
        }
        return key

    def validate_key(self, api_key: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        key_to_check = self._hash_key(api_key) if self.config.hash_keys else api_key
        key_data = self._keys.get(key_to_check)
        if key_data is None:
            return False, None, "Invalid API key"
        if not key_data["enabled"]:
            return False, None, "API key disabled"
        if self.config.key_expiry_days is not None:
            created = key_data["created_at"]
            if time.time() - created > self.config.key_expiry_days * 86400:
                return False, None, "API key expired"
        key_data["last_used"] = time.time()
        key_data["usage_count"] += 1
        return True, key_data, None

    def revoke_key(self, api_key: str) -> bool:
        key_to_check = self._hash_key(api_key) if self.config.hash_keys else api_key
        if key_to_check in self._keys:
            self._keys[key_to_check]["enabled"] = False
            return True
        return False

    def list_keys(self, user_id: str) -> List[Dict[str, Any]]:
        keys = []
        for key_data in self._keys.values():
            if key_data["user_id"] == user_id:
                keys.append(dict(key_data))
        return keys

    def get_key_usage(self, api_key: str) -> Optional[Dict[str, Any]]:
        key_to_check = self._hash_key(api_key) if self.config.hash_keys else api_key
        return self._keys.get(key_to_check)

    def _hash_key(self, key: str) -> str:
        if self.config.hash_algorithm == "sha256":
            return hashlib.sha256(key.encode()).hexdigest()
        elif self.config.hash_algorithm == "sha512":
            return hashlib.sha512(key.encode()).hexdigest()
        return key


class SessionHandler:
    def __init__(self, config: SessionConfig):
        self.config = config
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def create_session(self, user_id: str, ip_address: str, user_agent: Optional[str] = None) -> str:
        session_id = str(uuid.uuid4())
        now = time.time()
        self._sessions[session_id] = {
            "user_id": user_id,
            "created_at": now,
            "last_activity": now,
            "expires_at": now + self.config.session_ttl,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "active": True,
        }
        return session_id

    def validate_session(self, session_id: str, ip_address: str, user_agent: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        session = self._sessions.get(session_id)
        if session is None:
            return False, None, "Session not found"
        if not session["active"]:
            return False, None, "Session inactive"
        if session["expires_at"] < time.time():
            return False, None, "Session expired"
        if self.config.validate_ip and session["ip_address"] != ip_address:
            return False, None, "IP address mismatch"
        if self.config.validate_user_agent and user_agent and session.get("user_agent") != user_agent:
            return False, None, "User Agent mismatch"
        if self.config.extend_on_activity:
            now = time.time()
            if now - session["last_activity"] < self.config.extend_window:
                session["expires_at"] = now + self.config.session_ttl
            session["last_activity"] = now
        if self.config.rotate_session_id:
            now = time.time()
            if now - session["created_at"] > self.config.rotation_interval:
                new_id = str(uuid.uuid4())
                self._sessions[new_id] = session
                del self._sessions[session_id]
                session_id = new_id
        return True, {"session_id": session_id, **session}, None

    def invalidate_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            self._sessions[session_id]["active"] = False
            return True
        return False

    def invalidate_user_sessions(self, user_id: str) -> int:
        count = 0
        for session_id, session in list(self._sessions.items()):
            if session["user_id"] == user_id:
                session["active"] = False
                count += 1
        return count

    def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        sessions = []
        for session in self._sessions.values():
            if session["user_id"] == user_id and session["active"]:
                sessions.append(dict(session))
        return sessions

    def cleanup_expired(self) -> int:
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if s["expires_at"] < now]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)


class RoleManager:
    def __init__(self, config: RoleConfig):
        self.config = config

    def get_permissions_for_role(self, role: str) -> Set[str]:
        permissions = set(self.config.roles.get(role, []))
        if self.config.allow_role_inheritance and role in self.config.role_hierarchy:
            for parent_role in self.config.role_hierarchy[role]:
                permissions.update(self.get_permissions_for_role(parent_role))
        return permissions

    def get_all_permissions(self, roles: List[str]) -> Set[str]:
        permissions: Set[str] = set()
        for role in roles:
            permissions.update(self.get_permissions_for_role(role))
        return permissions

    def has_permission(self, roles: List[str], required_permission: str) -> bool:
        permissions = self.get_all_permissions(roles)
        return required_permission in permissions

    def has_any_permission(self, roles: List[str], required_permissions: List[str]) -> bool:
        permissions = self.get_all_permissions(roles)
        return bool(permissions & set(required_permissions))

    def has_all_permissions(self, roles: List[str], required_permissions: List[str]) -> bool:
        permissions = self.get_all_permissions(roles)
        return set(required_permissions).issubset(permissions)

    def get_role_hierarchy(self, role: str) -> List[str]:
        hierarchy = [role]
        if role in self.config.role_hierarchy:
            for child in self.config.role_hierarchy[role]:
                hierarchy.extend(self.get_role_hierarchy(child))
        return list(dict.fromkeys(hierarchy))

    def add_role(self, role: str, permissions: List[str], inherits: Optional[List[str]] = None) -> None:
        self.config.roles[role] = permissions
        if inherits:
            self.config.role_hierarchy[role] = inherits

    def remove_role(self, role: str) -> bool:
        if role in self.config.roles:
            del self.config.roles[role]
            self.config.role_hierarchy.pop(role, None)
            return True
        return False

    def list_roles(self) -> Dict[str, List[str]]:
        return dict(self.config.roles)

    def validate_role(self, role: str) -> bool:
        return role in self.config.roles


class AuthMiddleware:
    def __init__(self, config: Optional[AuthConfig] = None):
        self.config = config or AuthConfig()
        self.token_handler = TokenHandler(self.config.token) if self.config.token else TokenHandler(TokenConfig())
        self.api_key_handler = APIKeyHandler(self.config.api_key) if self.config.api_key else APIKeyHandler(APIKeyConfig())
        self.session_handler = SessionHandler(self.config.session) if self.config.session else SessionHandler(SessionConfig())
        self.role_manager = RoleManager(self.config.roles) if self.config.roles else RoleManager(RoleConfig())
        self._custom_providers: Dict[str, Callable] = {}
        self._auth_failures: Dict[str, List[float]] = {}
        self._auth_cache: Dict[str, Tuple[AuthResultData, float]] = {}
        logger.info(
            "AuthMiddleware initialized with %d providers",
            len(self.config.providers),
        )

    def authenticate(self, request: Dict[str, Any]) -> AuthResultData:
        if not self.config.enabled:
            return AuthResultData(
                result=AuthResult.GRANTED,
                user=UserContext(
                    user_id="anonymous",
                    username="anonymous",
                    roles=[self.config.roles.default_role],
                    permissions=self.role_manager.get_all_permissions([self.config.roles.default_role]),
                    provider="none",
                ),
            )

        route = request.get("route", "")
        if route in self.config.public_routes:
            return self._public_access()
        for prefix in self.config.public_path_prefixes:
            if route.startswith(prefix):
                return self._public_access()

        method = request.get("method", "GET").upper()
        ip = request.get("headers", {}).get("X-Forwarded-For", request.get("headers", {}).get("X-Real-IP", "unknown"))
        headers = request.get("headers", {})

        if self.config.cache_auth_results:
            cache_key = f"{ip}:{method}:{route}"
            cached = self._auth_cache.get(cache_key)
            if cached and time.time() - cached[1] < self.config.auth_cache_ttl:
                return cached[0]

        if self._is_rate_limited(ip):
            return AuthResultData(
                result=AuthResult.RATE_LIMITED,
                error="Too many authentication failures",
                status_code=429,
            )

        auth_header = headers.get(self.config.auth_header, "")
        for provider in sorted(self.config.providers, key=lambda p: p.order):
            if not provider.enabled:
                continue
            result = self._try_provider(provider, request)
            if result.result in (AuthResult.GRANTED, AuthResult.REQUIRES_MFA):
                if self.config.cache_auth_results:
                    cache_key = f"{ip}:{method}:{route}"
                    self._auth_cache[cache_key] = (result, time.time())
                return result
            if result.result == AuthResult.MISSING:
                continue
            if result.result in (AuthResult.DENIED, AuthResult.EXPIRED, AuthResult.INVALID):
                self._record_failure(ip)
                if result.result == AuthResult.DENIED and result.user:
                    return self._check_mfa_required(result)
                return result

        return self._handle_missing_auth()

    def _try_provider(self, provider: AuthProviderConfig, request: Dict[str, Any]) -> AuthResultData:
        if provider.type == AuthProviderType.BEARER or provider.type == AuthProviderType.TOKEN:
            return self._authenticate_bearer(request)
        elif provider.type == AuthProviderType.API_KEY:
            return self._authenticate_api_key(request)
        elif provider.type == AuthProviderType.SESSION:
            return self._authenticate_session(request)
        elif provider.type == AuthProviderType.BASIC:
            return self._authenticate_basic(request)
        elif provider.type == AuthProviderType.CUSTOM:
            return self._authenticate_custom(provider.name, request)
        return AuthResultData(result=AuthResult.MISSING, error="Unknown provider")

    def _authenticate_bearer(self, request: Dict[str, Any]) -> AuthResultData:
        headers = request.get("headers", {})
        auth_value = headers.get(self.config.auth_header, "")
        if not auth_value:
            return AuthResultData(result=AuthResult.MISSING, error="No authorization header")
        valid, payload, error = self.token_handler.validate_token(auth_value)
        if not valid:
            return AuthResultData(result=AuthResult.INVALID, error=error or "Token validation failed")
        if payload is None:
            return AuthResultData(result=AuthResult.INVALID, error="Empty token payload")
        user_id = payload.get("sub", "")
        roles = payload.get("roles", [self.config.roles.default_role])
        if not roles:
            roles = [self.config.roles.default_role]
        user = UserContext(
            user_id=user_id,
            username=payload.get("username", user_id),
            roles=roles,
            permissions=self.role_manager.get_all_permissions(roles),
            token=auth_value,
            provider="bearer",
            authenticated=True,
            expires_at=payload.get("exp"),
        )
        return AuthResultData(result=AuthResult.GRANTED, user=user)

    def _authenticate_api_key(self, request: Dict[str, Any]) -> AuthResultData:
        api_key = None
        if self.config.api_key.allow_in_header:
            api_key = request.get("headers", {}).get(self.config.api_key.header_name)
        if api_key is None and self.config.api_key.allow_in_query:
            api_key = request.get("query", {}).get(self.config.api_key.query_param)
        if not api_key:
            return AuthResultData(result=AuthResult.MISSING, error="No API key provided")
        valid, key_data, error = self.api_key_handler.validate_key(api_key)
        if not valid:
            return AuthResultData(result=AuthResult.INVALID, error=error or "Invalid API key")
        if key_data is None:
            return AuthResultData(result=AuthResult.INVALID, error="Invalid API key")
        user_id = key_data.get("user_id", "unknown")
        user = UserContext(
            user_id=user_id,
            username=user_id,
            roles=[self.config.roles.default_role],
            permissions=self.role_manager.get_all_permissions([self.config.roles.default_role]),
            api_key_id=api_key[:8] + "...",
            provider="api_key",
            authenticated=True,
        )
        return AuthResultData(result=AuthResult.GRANTED, user=user)

    def _authenticate_session(self, request: Dict[str, Any]) -> AuthResultData:
        headers = request.get("headers", {})
        session_id = headers.get(self.config.session.session_header, headers.get(self.config.session.session_cookie, ""))
        if not session_id:
            return AuthResultData(result=AuthResult.MISSING, error="No session ID")
        ip = headers.get("X-Forwarded-For", headers.get("X-Real-IP", "unknown"))
        ua = headers.get("User-Agent")
        valid, session_data, error = self.session_handler.validate_session(session_id, ip, ua)
        if not valid:
            return AuthResultData(result=AuthResult.INVALID, error=error or "Invalid session")
        if session_data is None:
            return AuthResultData(result=AuthResult.INVALID, error="Invalid session")
        user_id = session_data.get("user_id", "unknown")
        user = UserContext(
            user_id=user_id,
            username=user_id,
            roles=[self.config.roles.default_role],
            permissions=self.role_manager.get_all_permissions([self.config.roles.default_role]),
            session_id=session_id,
            provider="session",
            authenticated=True,
        )
        return AuthResultData(result=AuthResult.GRANTED, user=user)

    def _authenticate_basic(self, request: Dict[str, Any]) -> AuthResultData:
        headers = request.get("headers", {})
        auth_value = headers.get(self.config.auth_header, "")
        if not auth_value or not auth_value.startswith("Basic "):
            return AuthResultData(result=AuthResult.MISSING, error="No Basic auth")
        try:
            decoded = base64.b64decode(auth_value[6:]).decode()
            username, password = decoded.split(":", 1)
            user = UserContext(
                user_id=username,
                username=username,
                roles=[self.config.roles.default_role],
                permissions=self.role_manager.get_all_permissions([self.config.roles.default_role]),
                provider="basic",
                authenticated=True,
            )
            return AuthResultData(result=AuthResult.GRANTED, user=user)
        except (base64.binascii.Error, ValueError) as e:
            return AuthResultData(result=AuthResult.INVALID, error=f"Basic auth decode failed: {e}")

    def _authenticate_custom(self, provider_name: str, request: Dict[str, Any]) -> AuthResultData:
        if provider_name not in self._custom_providers:
            return AuthResultData(result=AuthResult.MISSING, error=f"Custom provider '{provider_name}' not registered")
        try:
            handler = self._custom_providers[provider_name]
            result = handler(request)
            if isinstance(result, AuthResultData):
                return result
            return AuthResultData(result=AuthResult.DENIED, error="Custom provider returned invalid result")
        except Exception as e:
            logger.error("Custom auth provider '%s' failed: %s", provider_name, e)
            return AuthResultData(result=AuthResult.DENIED, error=f"Custom auth error: {e}")

    def _check_mfa_required(self, result: AuthResultData) -> AuthResultData:
        if result.user is None:
            return result
        for role in result.user.roles:
            if role in self.config.enforce_mfa_for_roles:
                return AuthResultData(
                    result=AuthResult.REQUIRES_MFA,
                    user=result.user,
                    error="MFA verification required",
                    status_code=401,
                    headers={"X-MFA-Required": self.config.mfa_check_path},
                )
        return result

    def _public_access(self) -> AuthResultData:
        user = UserContext(
            user_id="public",
            username="public",
            roles=[self.config.roles.default_role],
            permissions=self.role_manager.get_all_permissions([self.config.roles.default_role]),
            provider="public",
            authenticated=False,
        )
        return AuthResultData(result=AuthResult.GRANTED, user=user)

    def _handle_missing_auth(self) -> AuthResultData:
        headers = {}
        if self.config.challenge_on_missing:
            headers[self.config.challenge_header] = self.config.challenge_value
        return AuthResultData(
            result=AuthResult.MISSING,
            error="Authentication required",
            status_code=401,
            headers=headers,
        )

    def _is_rate_limited(self, ip: str) -> bool:
        now = time.time()
        failures = self._auth_failures.get(ip, [])
        failures = [f for f in failures if now - f < self.config.auth_failure_window]
        self._auth_failures[ip] = failures
        return len(failures) >= self.config.max_auth_failures

    def _record_failure(self, ip: str) -> None:
        if ip not in self._auth_failures:
            self._auth_failures[ip] = []
        self._auth_failures[ip].append(time.time())

    def check_permission(self, user: UserContext, required_permission: str) -> bool:
        if "admin" in user.roles:
            return True
        return required_permission in user.permissions

    def check_any_permission(self, user: UserContext, required_permissions: List[str]) -> bool:
        if "admin" in user.roles:
            return True
        return self.role_manager.has_any_permission(user.roles, required_permissions)

    def check_all_permissions(self, user: UserContext, required_permissions: List[str]) -> bool:
        if "admin" in user.roles:
            return True
        return self.role_manager.has_all_permissions(user.roles, required_permissions)

    def register_custom_provider(self, name: str, handler: Callable[[Dict[str, Any]], AuthResultData]) -> None:
        self._custom_providers[name] = handler
        self.config.providers.append(
            AuthProviderConfig(type=AuthProviderType.CUSTOM, name=name, config={"handler": name}),
        )
        logger.info("Registered custom auth provider: %s", name)

    def unregister_custom_provider(self, name: str) -> bool:
        if name in self._custom_providers:
            del self._custom_providers[name]
            self.config.providers = [p for p in self.config.providers if p.name != name]
            return True
        return False

    def generate_token(self, user_id: str, roles: List[str], metadata: Optional[Dict[str, Any]] = None) -> str:
        return self.token_handler.generate_token(user_id, roles, metadata)

    def generate_api_key(self, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        return self.api_key_handler.generate_key(user_id, metadata)

    def create_session(self, user_id: str, ip_address: str, user_agent: Optional[str] = None) -> str:
        return self.session_handler.create_session(user_id, ip_address, user_agent)

    def invalidate_session(self, session_id: str) -> bool:
        return self.session_handler.invalidate_session(session_id)

    def revoke_token(self, token: str) -> bool:
        return self.token_handler.revoke_token(token)

    def revoke_api_key(self, api_key: str) -> bool:
        return self.api_key_handler.revoke_key(api_key)

    def get_user_from_token(self, token: str) -> Optional[UserContext]:
        payload = self.token_handler.decode_token(token)
        if payload is None:
            return None
        roles = payload.get("roles", [self.config.roles.default_role])
        return UserContext(
            user_id=payload.get("sub", ""),
            username=payload.get("username", payload.get("sub", "")),
            roles=roles,
            permissions=self.role_manager.get_all_permissions(roles),
            token=token,
            provider="bearer",
            authenticated=True,
        )

    def get_user_context(self, request: Dict[str, Any]) -> Optional[UserContext]:
        result = self.authenticate(request)
        return result.user if result.result == AuthResult.GRANTED else None

    def add_role(self, role: str, permissions: List[str], inherits: Optional[List[str]] = None) -> None:
        self.role_manager.add_role(role, permissions, inherits)

    def remove_role(self, role: str) -> bool:
        return self.role_manager.remove_role(role)

    def list_roles(self) -> Dict[str, List[str]]:
        return self.role_manager.list_roles()

    def get_user_permissions(self, user: UserContext) -> Set[str]:
        return self.role_manager.get_all_permissions(user.roles)

    def extract_user_context(self, request: Dict[str, Any]) -> Optional[UserContext]:
        result = self.authenticate(request)
        if result.result == AuthResult.GRANTED and result.user:
            if self.config.propagate_user_context:
                request[self.config.user_context_field] = {
                    "user_id": result.user.user_id,
                    "username": result.user.username,
                    "roles": result.user.roles,
                    "permissions": list(result.user.permissions),
                }
            return result.user
        return None

    def is_public_route(self, route: str) -> bool:
        if route in self.config.public_routes:
            return True
        for prefix in self.config.public_path_prefixes:
            if route.startswith(prefix):
                return True
        return False

    def clear_auth_cache(self) -> None:
        self._auth_cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "providers": [p.name for p in self.config.providers if p.enabled],
            "roles": list(self.config.roles.roles.keys()),
            "auth_failures": sum(len(f) for f in self._auth_failures.values()),
            "public_routes": len(self.config.public_routes),
            "public_prefixes": len(self.config.public_path_prefixes),
            "cache_size": len(self._auth_cache),
            "sessions": len(self.session_handler._sessions) if hasattr(self.session_handler, "_sessions") else 0,
            "api_keys": len(self.api_key_handler._keys) if hasattr(self.api_key_handler, "_keys") else 0,
        }

    def update_config(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def reset_config(self) -> None:
        self.config = AuthConfig()
        self.token_handler = TokenHandler(self.config.token)
        self.api_key_handler = APIKeyHandler(self.config.api_key)
        self.session_handler = SessionHandler(self.config.session)
        self.role_manager = RoleManager(self.config.roles)

    def __repr__(self) -> str:
        return f"AuthMiddleware(providers={[p.name for p in self.config.providers]})"
