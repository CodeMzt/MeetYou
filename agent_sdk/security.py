from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any

from Crypto.Cipher import AES


_CREDENTIAL_SECRET_ENV_NAMES = (
    "MEETYOU_CREDENTIAL_SECRET",
    "MEETYOU_GATEWAY_ACCESS_TOKEN",
    "MEETYOU_AGENT_ACCESS_TOKEN",
)
_KDF_SALT = b"MeetYouCredentialTransportV1"
_SENSITIVE_FIELD_NAMES = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "cookie_header",
    "email",
    "password",
    "refresh_token",
    "secret",
    "token",
    "webvpn_cookie",
}
_SENSITIVE_FIELD_SUFFIXES = (
    "_api_key",
    "_cookie",
    "_password",
    "_secret",
    "_token",
)


class CredentialTransportError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProtectedArguments:
    public_arguments: dict[str, Any]
    encrypted_arguments: dict[str, Any] | None
    contains_sensitive_fields: bool


def resolve_credential_secret(explicit_secret: str = "") -> str:
    if str(explicit_secret or "").strip():
        return str(explicit_secret).strip()
    for env_name in _CREDENTIAL_SECRET_ENV_NAMES:
        value = str(os.getenv(env_name, "")).strip()
        if value:
            return value
    raise CredentialTransportError(
        "credential_key_unavailable",
        "缺少凭证加密密钥，请在 .env 中设置 MEETYOU_CREDENTIAL_SECRET。",
    )


def encrypt_json_payload(payload: dict[str, Any], *, purpose: str, explicit_secret: str = "") -> dict[str, Any]:
    try:
        secret = resolve_credential_secret(explicit_secret)
    except CredentialTransportError:
        raise
    except Exception as exc:  # pragma: no cover
        raise CredentialTransportError("credential_key_unavailable", "凭证加密密钥不可用。") from exc

    try:
        plaintext = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        iv = os.urandom(12)
        cipher = AES.new(_derive_key(secret, purpose), AES.MODE_GCM, nonce=iv)
        cipher.update(purpose.encode("utf-8"))
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        return {
            "version": "v1",
            "alg": "aes-256-gcm",
            "purpose": purpose,
            "iv": _b64encode(iv),
            "ciphertext": _b64encode(ciphertext),
            "tag": _b64encode(tag),
        }
    except CredentialTransportError:
        raise
    except Exception as exc:
        raise CredentialTransportError("credential_encrypt_failed", "凭证加密失败，请检查本地安全配置。") from exc


def decrypt_json_payload(envelope: dict[str, Any] | None, *, purpose: str, explicit_secret: str = "") -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise CredentialTransportError("credential_decrypt_failed", "凭证解密失败：缺少有效的加密封装。")

    try:
        secret = resolve_credential_secret(explicit_secret)
        version = str(envelope.get("version") or "")
        algorithm = str(envelope.get("alg") or "").lower()
        envelope_purpose = str(envelope.get("purpose") or "")
        if version != "v1" or algorithm != "aes-256-gcm" or envelope_purpose != purpose:
            raise CredentialTransportError("credential_decrypt_failed", "凭证解密失败：加密封装版本或用途不匹配。")
        iv = _b64decode(str(envelope.get("iv") or ""))
        ciphertext = _b64decode(str(envelope.get("ciphertext") or ""))
        tag = _b64decode(str(envelope.get("tag") or ""))
        cipher = AES.new(_derive_key(secret, purpose), AES.MODE_GCM, nonce=iv)
        cipher.update(purpose.encode("utf-8"))
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        payload = json.loads(plaintext.decode("utf-8"))
        if not isinstance(payload, dict):
            raise CredentialTransportError("credential_decrypt_failed", "凭证解密失败：载荷格式无效。")
        return payload
    except CredentialTransportError:
        raise
    except Exception as exc:
        raise CredentialTransportError("credential_decrypt_failed", "凭证解密失败，请重新提交 Danxi/WebVPN 登录信息。") from exc


def protect_sensitive_arguments(arguments: dict[str, Any] | None, *, purpose: str, explicit_secret: str = "") -> ProtectedArguments:
    normalized = dict(arguments or {})
    if not contains_sensitive_fields(normalized):
        return ProtectedArguments(public_arguments=normalized, encrypted_arguments=None, contains_sensitive_fields=False)
    return ProtectedArguments(
        public_arguments=redact_sensitive_fields(normalized),
        encrypted_arguments=encrypt_json_payload(normalized, purpose=purpose, explicit_secret=explicit_secret),
        contains_sensitive_fields=True,
    )


def contains_sensitive_fields(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = str(key or "").strip().lower()
            if _is_sensitive_field_name(normalized_key):
                return True
            if contains_sensitive_fields(value):
                return True
    elif isinstance(payload, list):
        return any(contains_sensitive_fields(item) for item in payload)
    return False


def redact_sensitive_fields(payload: Any) -> Any:
    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            normalized_key = str(key or "").strip().lower()
            if _is_sensitive_field_name(normalized_key):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = redact_sensitive_fields(value)
        return result
    if isinstance(payload, list):
        return [redact_sensitive_fields(item) for item in payload]
    return payload


def _derive_key(secret: str, purpose: str) -> bytes:
    secret_bytes = str(secret or "").encode("utf-8")
    prk = hmac.new(_KDF_SALT, secret_bytes, hashlib.sha256).digest()
    return hmac.new(prk, purpose.encode("utf-8") + b"\x01", hashlib.sha256).digest()


def _is_sensitive_field_name(normalized_key: str) -> bool:
    if normalized_key in _SENSITIVE_FIELD_NAMES:
        return True
    return any(normalized_key.endswith(suffix) for suffix in _SENSITIVE_FIELD_SUFFIXES)


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(raw: str) -> bytes:
    return base64.b64decode(raw.encode("ascii"))
