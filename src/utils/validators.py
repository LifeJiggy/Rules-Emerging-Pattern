"""Production-grade validation utilities with regex, heuristic, batch, and custom validators."""

import re
import socket
import struct
import ipaddress
import logging
import datetime
import threading
from typing import Any, Callable, Optional, Union, Pattern, List, Dict, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import defaultdict
from functools import wraps

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    ERROR = auto()
    WARNING = auto()
    INFO = auto()


class ValidationErrorType(Enum):
    INVALID_FORMAT = auto()
    OUT_OF_RANGE = auto()
    LENGTH_VIOLATION = auto()
    PATTERN_MISMATCH = auto()
    EMPTY_VALUE = auto()
    TYPE_MISMATCH = auto()
    CUSTOM_FAILURE = auto()


@dataclass
class ValidationResult:
    is_valid: bool
    value: Any = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, error_type: ValidationErrorType, message: str, field: Optional[str] = None):
        self.is_valid = False
        self.errors.append({
            "type": error_type,
            "message": message,
            "field": field,
            "timestamp": datetime.datetime.utcnow().isoformat()
        })

    def add_warning(self, message: str):
        self.warnings.append(message)

    def merge(self, other: "ValidationResult"):
        if not other.is_valid:
            self.is_valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def first_error(self) -> Optional[str]:
        return self.errors[0]["message"] if self.errors else None

    def summary(self) -> str:
        parts = []
        if self.is_valid:
            parts.append("VALID")
        else:
            parts.append(f"INVALID ({len(self.errors)} error(s))")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        return " | ".join(parts)

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings
        }


@dataclass
class ValidatorConfig:
    email_allow_display_name: bool = False
    email_check_mx: bool = False
    email_mx_timeout: float = 3.0
    phone_default_region: str = "US"
    url_check_reachability: bool = False
    url_timeout: float = 5.0
    ip_allow_private: bool = True
    ip_allow_reserved: bool = False
    date_strict_parsing: bool = True
    range_inclusive: bool = True
    string_strip_before_length: bool = True
    max_batch_size: int = 1000
    strict_mode: bool = False
    custom_rule_prefix: str = "custom_"


EMAIL_REGEX = re.compile(
    r"^(?P<local>[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+)"
    r"@"
    r"(?P<domain>[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
    r"\.[a-zA-Z]{2,})$"
)

PHONE_REGEX = re.compile(
    r"^\+?[1-9]\d{1,14}$"
)

URL_REGEX = re.compile(
    r"^(?P<scheme>[a-z][a-z0-9+\-.]*)://"
    r"(?P<netloc>[^/\s:?#]+)"
    r"(?::(?P<port>\d+))?"
    r"(?P<path>/[^\s?#]*)?"
    r"(?:\?(?P<query>[^\s#]*))?"
    r"(?:#(?P<fragment>[^\s]*))?$",
    re.IGNORECASE
)

IPV4_REGEX = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d{1,2})\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d{1,2})$"
)

DATE_FORMAT_REGEXES = {
    "%Y-%m-%d": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "%Y/%m/%d": re.compile(r"^\d{4}/\d{2}/\d{2}$"),
    "%d-%m-%Y": re.compile(r"^\d{2}-\d{2}-\d{4}$"),
    "%d/%m/%Y": re.compile(r"^\d{2}/\d{2}/\d{4}$"),
    "%m-%d-%Y": re.compile(r"^\d{2}-\d{2}-\d{4}$"),
    "%m/%d/%Y": re.compile(r"^\d{2}/\d{2}/\d{4}$"),
    "%Y-%m-%dT%H:%M:%S": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$"),
    "%Y-%m-%dT%H:%M:%SZ": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    "%Y-%m-%d %H:%M:%S": re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"),
    "%d-%b-%Y": re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$"),
    "%d %B %Y": re.compile(r"^\d{1,2} [A-Za-z]{3,9} \d{4}$"),
}

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}


class UtilityValidators:
    """Comprehensive validation toolbox with regex, heuristic, batch, and custom validators."""

    def __init__(self, config: Optional[ValidatorConfig] = None):
        self.config = config or ValidatorConfig()
        self._custom_validators: Dict[str, Callable] = {}
        self._validator_lock = threading.RLock()
        self._mx_cache: Dict[str, Tuple[bool, float]] = {}
        self._mx_cache_ttl: float = 3600.0
        self._validation_history: List[Dict[str, Any]] = []
        self._history_max: int = 10000

    def _record_validation(self, method: str, result: ValidationResult, **kwargs):
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "method": method,
            "result": result.is_valid,
            "error_count": len(result.errors),
            "params": {k: v for k, v in kwargs.items() if not callable(v)}
        }
        with self._validator_lock:
            self._validation_history.append(entry)
            if len(self._validation_history) > self._history_max:
                self._validation_history = self._validation_history[-self._history_max:]

    def validate_email(self, email: Any) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=email)
        if not isinstance(email, str) or not email.strip():
            result.add_error(ValidationErrorType.EMPTY_VALUE, "Email must be a non-empty string")
            self._record_validation("validate_email", result, email=email)
            return result
        email = email.strip()
        match = EMAIL_REGEX.match(email)
        if not match:
            result.add_error(ValidationErrorType.INVALID_FORMAT, f"Email '{email}' does not match standard format")
            self._record_validation("validate_email", result, email=email)
            return result
        local = match.group("local")
        domain = match.group("domain")
        if len(local) > 64:
            result.add_error(ValidationErrorType.LENGTH_VIOLATION, f"Local part exceeds 64 characters ({len(local)})")
        if len(domain) > 255:
            result.add_error(ValidationErrorType.LENGTH_VIOLATION, f"Domain part exceeds 255 characters ({len(domain)})")
        if ".." in domain:
            result.add_error(ValidationErrorType.INVALID_FORMAT, f"Domain contains consecutive dots")
        if domain.startswith("-") or domain.endswith("-"):
            result.add_error(ValidationErrorType.INVALID_FORMAT, f"Domain segment starts or ends with hyphen")
        for part in domain.split("."):
            if len(part) > 63:
                result.add_error(ValidationErrorType.LENGTH_VIOLATION, f"Domain segment exceeds 63 characters")
                break
        if self.config.email_check_mx and result.is_valid:
            has_mx = self._check_mx(domain)
            if not has_mx:
                result.add_warning(f"No MX record found for domain '{domain}'")
        if self.config.email_allow_display_name:
            if "<" in email and ">" in email:
                result.add_warning("Email contains display name wrapper")
        self._record_validation("validate_email", result, email=email)
        return result

    def _check_mx(self, domain: str) -> bool:
        now = datetime.datetime.utcnow().timestamp()
        if domain in self._mx_cache:
            cached, ts = self._mx_cache[domain]
            if now - ts < self._mx_cache_ttl:
                return cached
        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "MX", lifetime=self.config.email_mx_timeout)
            has_mx = len(answers) > 0
        except ImportError:
            logger.warning("dnspython not installed, MX check skipped for %s", domain)
            has_mx = True
        except Exception:
            has_mx = False
        self._mx_cache[domain] = (has_mx, now)
        return has_mx

    def validate_phone(self, phone: Any, region: Optional[str] = None) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=phone)
        if not isinstance(phone, str) or not phone.strip():
            result.add_error(ValidationErrorType.EMPTY_VALUE, "Phone must be a non-empty string")
            self._record_validation("validate_phone", result, phone=phone, region=region)
            return result
        phone = phone.strip()
        cleaned = re.sub(r"[\s\-\(\)\.]+", "", phone)
        if cleaned.startswith("+"):
            e164 = cleaned
        elif cleaned.startswith("00"):
            e164 = "+" + cleaned[2:]
        elif region or self.config.phone_default_region:
            r = region or self.config.phone_default_region
            country_codes = {"US": "1", "GB": "44", "DE": "49", "FR": "33",
                             "JP": "81", "CN": "86", "IN": "91", "BR": "55",
                             "AU": "61", "CA": "1", "RU": "7", "KR": "82",
                             "SG": "65", "HK": "852", "NL": "31", "IT": "39",
                             "ES": "34", "MX": "52", "ID": "62", "TR": "90",
                             "SA": "966", "AE": "971", "CH": "41", "SE": "46",
                             "NO": "47", "DK": "45", "FI": "358", "PL": "48",
                             "BE": "32", "AT": "43", "IE": "353", "NZ": "64",
                             "IL": "972", "ZA": "27", "AR": "54", "CO": "57",
                             "CL": "56", "PE": "51", "MY": "60", "PH": "63",
                             "TH": "66", "VN": "84", "EG": "20", "NG": "234",
                             "KE": "254", "PK": "92", "BD": "880"}
            cc = country_codes.get(r.upper(), "1")
            if cleaned.startswith(cc):
                e164 = "+" + cleaned
            else:
                e164 = "+" + cc + cleaned
        else:
            e164 = "+" + cleaned
        if not PHONE_REGEX.match(e164):
            result.add_error(ValidationErrorType.INVALID_FORMAT, f"Phone '{phone}' does not match E.164 format")
        if len(e164) < 8 or len(e164) > 16:
            result.add_error(ValidationErrorType.LENGTH_VIOLATION, f"Phone number length {len(e164)} out of E.164 range (8-16)")
        self._record_validation("validate_phone", result, phone=phone, region=region)
        result.value = e164
        return result

    def validate_url(self, url: Any) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=url)
        if not isinstance(url, str) or not url.strip():
            result.add_error(ValidationErrorType.EMPTY_VALUE, "URL must be a non-empty string")
            self._record_validation("validate_url", result, url=url)
            return result
        url = url.strip()
        if len(url) > 8192:
            result.add_error(ValidationErrorType.LENGTH_VIOLATION, f"URL exceeds 8192 characters ({len(url)})")
            self._record_validation("validate_url", result, url=url)
            return result
        match = URL_REGEX.match(url)
        if not match:
            result.add_error(ValidationErrorType.INVALID_FORMAT, f"URL '{url}' does not match URI syntax")
            self._record_validation("validate_url", result, url=url)
            return result
        scheme = match.group("scheme").lower()
        netloc = match.group("netloc")
        if scheme not in ("http", "https", "ftp", "ftps", "sftp", "ws", "wss",
                          "git", "ssh", "telnet", "ldap", "ldaps", "s3", "gcs",
                          "file", "data", "mailto", "tel", "fax", "sms"):
            result.add_warning(f"Uncommon URL scheme '{scheme}'")
        port_str = match.group("port")
        if port_str:
            port = int(port_str)
            if port < 1 or port > 65535:
                result.add_error(ValidationErrorType.OUT_OF_RANGE, f"Port {port} out of valid range (1-65535)")
        if " " in netloc:
            result.add_error(ValidationErrorType.INVALID_FORMAT, "Netloc contains spaces")
        if not self.config.ip_allow_private:
            try:
                ipaddress.ip_address(netloc)
                result.add_warning("URL uses raw IP address")
            except ValueError:
                pass
        if self.config.url_check_reachability:
            reachable = self._check_url_reachability(url)
            if not reachable:
                result.add_warning(f"URL '{url}' is not reachable")
        self._record_validation("validate_url", result, url=url)
        return result

    def _check_url_reachability(self, url: str) -> bool:
        try:
            import urllib.request
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=self.config.url_timeout) as resp:
                return 200 <= resp.status < 400
        except Exception:
            return False

    def validate_ip(self, ip: Any) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=ip)
        if not isinstance(ip, str) or not ip.strip():
            result.add_error(ValidationErrorType.EMPTY_VALUE, "IP must be a non-empty string")
            self._record_validation("validate_ip", result, ip=ip)
            return result
        ip = ip.strip()
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            result.add_error(ValidationErrorType.INVALID_FORMAT, f"'{ip}' is not a valid IP address")
            self._record_validation("validate_ip", result, ip=ip)
            return result
        is_ipv4 = isinstance(addr, ipaddress.IPv4Address)
        is_ipv6 = isinstance(addr, ipaddress.IPv6Address)
        if not self.config.ip_allow_private:
            if addr.is_private:
                result.add_error(ValidationErrorType.CUSTOM_FAILURE, f"Private IP '{ip}' not allowed")
        if not self.config.ip_allow_reserved:
            if addr.is_reserved:
                result.add_warning(f"Reserved IP address '{ip}'")
            if addr.is_loopback:
                result.add_warning(f"Loopback IP address '{ip}'")
            if addr.is_multicast:
                result.add_warning(f"Multicast IP address '{ip}'")
            if addr.is_link_local:
                result.add_warning(f"Link-local IP address '{ip}'")
        if is_ipv6 and addr.ipv4_mapped:
            result.add_info = f"IPv4-mapped IPv6 address (::ffff:{addr.ipv4_mapped})"
        if is_ipv4:
            octets = ip.split(".")
            if any(o != "0" and o.startswith("0") for o in octets):
                result.add_warning(f"IPv4 address has leading zeros: '{ip}'")
        self._record_validation("validate_ip", result, ip=ip)
        result.value = str(addr)
        return result

    def validate_date(self, date_str: Any, formats: Optional[List[str]] = None) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=date_str)
        if not isinstance(date_str, str) or not date_str.strip():
            result.add_error(ValidationErrorType.EMPTY_VALUE, "Date must be a non-empty string")
            self._record_validation("validate_date", result, date_str=date_str, formats=formats)
            return result
        date_str = date_str.strip()
        if formats is None:
            formats = list(DATE_FORMAT_REGEXES.keys())
        parsed = None
        used_format = None
        for fmt in formats:
            try:
                parsed = datetime.datetime.strptime(date_str, fmt)
                used_format = fmt
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                parsed = self._parse_fuzzy_date(date_str)
                used_format = "fuzzy"
            except Exception:
                result.add_error(ValidationErrorType.INVALID_FORMAT, f"Date '{date_str}' does not match any format")
                self._record_validation("validate_date", result, date_str=date_str, formats=formats)
                return result
        if self.config.date_strict_parsing:
            try:
                year = parsed.year
                month = parsed.month
                day = parsed.day
                if year < 1900 or year > 2200:
                    result.add_warning(f"Year {year} outside common range (1900-2200)")
                if month < 1 or month > 12:
                    result.add_error(ValidationErrorType.OUT_OF_RANGE, f"Month {month} invalid")
                if day < 1 or day > 31:
                    result.add_error(ValidationErrorType.OUT_OF_RANGE, f"Day {day} invalid")
            except Exception:
                pass
        self._record_validation("validate_date", result, date_str=date_str, formats=formats)
        result.value = parsed.isoformat() if parsed else date_str
        return result

    def _parse_fuzzy_date(self, text: str) -> datetime.datetime:
        text = text.strip()
        parts = text.split()
        if len(parts) == 3:
            a, b, c = parts
            year = None
            month = None
            day = None
            for val in (a, b, c):
                if val.isdigit() and len(val) == 4:
                    year = int(val)
                elif val.isdigit():
                    if day is None:
                        day = int(val)
                    else:
                        if month is None:
                            month = int(val)
                        else:
                            day = int(val)
                elif val.lower() in MONTH_NAMES:
                    month = MONTH_NAMES[val.lower()]
            if year and month and day:
                return datetime.datetime(year, month, day)
        if "," in text:
            text = text.replace(",", "")
            parts = text.split()
            if len(parts) == 3:
                return self._parse_fuzzy_date(" ".join(parts))
        raise ValueError(f"Cannot parse date: {text}")

    def validate_range(self, value: Any, min_val: Optional[Union[int, float]] = None,
                       max_val: Optional[Union[int, float]] = None) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if not isinstance(value, (int, float)):
            result.add_error(ValidationErrorType.TYPE_MISMATCH, f"Expected numeric type, got {type(value).__name__}")
            self._record_validation("validate_range", result, value=value, min=min_val, max=max_val)
            return result
        if self.config.range_inclusive:
            if min_val is not None and value < min_val:
                result.add_error(ValidationErrorType.OUT_OF_RANGE, f"Value {value} < minimum {min_val}")
            if max_val is not None and value > max_val:
                result.add_error(ValidationErrorType.OUT_OF_RANGE, f"Value {value} > maximum {max_val}")
        else:
            if min_val is not None and value <= min_val:
                result.add_error(ValidationErrorType.OUT_OF_RANGE, f"Value {value} <= minimum {min_val} (exclusive)")
            if max_val is not None and value >= max_val:
                result.add_error(ValidationErrorType.OUT_OF_RANGE, f"Value {value} >= maximum {max_val} (exclusive)")
        self._record_validation("validate_range", result, value=value, min=min_val, max=max_val)
        return result

    def validate_length(self, value: Any, min_len: Optional[int] = None,
                        max_len: Optional[int] = None) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if not hasattr(value, "__len__"):
            result.add_error(ValidationErrorType.TYPE_MISMATCH, f"Object of type {type(value).__name__} has no len()")
            self._record_validation("validate_length", result, value=value, min=min_len, max=max_len)
            return result
        if isinstance(value, str) and self.config.string_strip_before_length:
            length = len(value.strip())
        else:
            length = len(value)
        if min_len is not None and length < min_len:
            result.add_error(ValidationErrorType.LENGTH_VIOLATION, f"Length {length} < minimum {min_len}")
        if max_len is not None and length > max_len:
            result.add_error(ValidationErrorType.LENGTH_VIOLATION, f"Length {length} > maximum {max_len}")
        self._record_validation("validate_length", result, value=value, min=min_len, max=max_len)
        return result

    def validate_pattern(self, value: Any, pattern: Union[str, Pattern]) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if not isinstance(value, str):
            result.add_error(ValidationErrorType.TYPE_MISMATCH, f"Expected string, got {type(value).__name__}")
            self._record_validation("validate_pattern", result, value=value, pattern=str(pattern))
            return result
        if isinstance(pattern, str):
            try:
                compiled = re.compile(pattern)
            except re.error as e:
                result.add_error(ValidationErrorType.CUSTOM_FAILURE, f"Invalid regex pattern: {e}")
                self._record_validation("validate_pattern", result, value=value, pattern=pattern)
                return result
        else:
            compiled = pattern
        if not compiled.search(value):
            result.add_error(ValidationErrorType.PATTERN_MISMATCH, f"Value does not match pattern '{compiled.pattern}'")
        self._record_validation("validate_pattern", result, value=value, pattern=compiled.pattern)
        return result

    def validate_not_empty(self, value: Any) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if value is None:
            result.add_error(ValidationErrorType.EMPTY_VALUE, "Value is None")
            return result
        if isinstance(value, str) and not value.strip():
            result.add_error(ValidationErrorType.EMPTY_VALUE, "String is empty or whitespace-only")
            return result
        if hasattr(value, "__len__") and len(value) == 0:
            result.add_error(ValidationErrorType.EMPTY_VALUE, f"{type(value).__name__} is empty")
            return result
        return result

    def validate_type(self, value: Any, expected_type: Union[type, Tuple[type, ...]]) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if not isinstance(value, expected_type):
            type_names = ", ".join(t.__name__ for t in (expected_type if isinstance(expected_type, tuple) else (expected_type,)))
            result.add_error(ValidationErrorType.TYPE_MISMATCH, f"Expected {type_names}, got {type(value).__name__}")
        return result

    def validate_choice(self, value: Any, choices: Union[List, Set, Tuple]) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if value not in choices:
            result.add_error(ValidationErrorType.CUSTOM_FAILURE, f"Value '{value}' not in allowed choices {choices}")
        return result

    def validate_uuid(self, value: Any, version: Optional[int] = None) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if not isinstance(value, str) or not value.strip():
            result.add_error(ValidationErrorType.EMPTY_VALUE, "UUID must be a non-empty string")
            return result
        import uuid
        try:
            u = uuid.UUID(value.strip())
            if version is not None and u.version != version:
                result.add_error(ValidationErrorType.CUSTOM_FAILURE,
                                 f"UUID version {u.version} != expected version {version}")
        except (ValueError, AttributeError):
            result.add_error(ValidationErrorType.INVALID_FORMAT, f"'{value}' is not a valid UUID")
        return result

    def validate_credit_card(self, value: Any) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if not isinstance(value, str):
            result.add_error(ValidationErrorType.TYPE_MISMATCH, "Credit card must be a string")
            return result
        cleaned = re.sub(r"[\s\-]", "", value)
        if not cleaned.isdigit():
            result.add_error(ValidationErrorType.INVALID_FORMAT, "Credit card must contain only digits, spaces, or hyphens")
            return result
        if len(cleaned) < 13 or len(cleaned) > 19:
            result.add_error(ValidationErrorType.LENGTH_VIOLATION, f"Card number length {len(cleaned)} out of range (13-19)")
            return result
        total = 0
        reverse_digits = cleaned[::-1]
        for i, ch in enumerate(reverse_digits):
            n = int(ch)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        if total % 10 != 0:
            result.add_error(ValidationErrorType.CUSTOM_FAILURE, "Luhn check failed")
        prefix = cleaned[0]
        if prefix == "4":
            result.value = "Visa"
        elif prefix == "5":
            result.value = "MasterCard"
        elif prefix == "3":
            result.value = "American Express" if cleaned[1] in ("4", "7") else "Diners Club"
        elif prefix == "6":
            result.value = "Discover"
        return result

    def validate_json(self, value: Any) -> ValidationResult:
        import json
        result = ValidationResult(is_valid=True, value=value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                result.value = parsed
            except json.JSONDecodeError as e:
                result.add_error(ValidationErrorType.INVALID_FORMAT, f"Invalid JSON: {e}")
        elif isinstance(value, (dict, list)):
            result.value = value
        else:
            result.add_error(ValidationErrorType.TYPE_MISMATCH, "Expected string, dict, or list for JSON validation")
        return result

    def validate_bool(self, value: Any, strict: bool = False) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if strict:
            if not isinstance(value, bool):
                result.add_error(ValidationErrorType.TYPE_MISMATCH, f"Expected bool, got {type(value).__name__}")
        else:
            if isinstance(value, str):
                if value.lower() in ("true", "1", "yes", "on"):
                    result.value = True
                elif value.lower() in ("false", "0", "no", "off"):
                    result.value = False
                else:
                    result.add_error(ValidationErrorType.CUSTOM_FAILURE, f"Cannot interpret '{value}' as boolean")
            elif isinstance(value, (int, float)):
                if value in (0, 1):
                    result.value = bool(value)
                else:
                    result.add_error(ValidationErrorType.CUSTOM_FAILURE, f"Numeric value {value} not 0 or 1")
            elif not isinstance(value, bool):
                result.add_error(ValidationErrorType.TYPE_MISMATCH, f"Cannot coerce {type(value).__name__} to bool")
        return result

    def validate_color_hex(self, value: Any) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if not isinstance(value, str):
            result.add_error(ValidationErrorType.TYPE_MISMATCH, "Color must be a string")
            return result
        if not re.match(r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$", value.strip()):
            result.add_error(ValidationErrorType.INVALID_FORMAT, f"'{value}' is not a valid hex color")
        return result

    def validate_password_strength(self, value: Any, min_length: int = 8,
                                   require_upper: bool = True, require_lower: bool = True,
                                   require_digit: bool = True, require_special: bool = True) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        if not isinstance(value, str):
            result.add_error(ValidationErrorType.TYPE_MISMATCH, "Password must be a string")
            return result
        if len(value) < min_length:
            result.add_error(ValidationErrorType.LENGTH_VIOLATION, f"Password length {len(value)} < minimum {min_length}")
        if require_upper and not re.search(r"[A-Z]", value):
            result.add_error(ValidationErrorType.PATTERN_MISMATCH, "Password must contain uppercase letter")
        if require_lower and not re.search(r"[a-z]", value):
            result.add_error(ValidationErrorType.PATTERN_MISMATCH, "Password must contain lowercase letter")
        if require_digit and not re.search(r"\d", value):
            result.add_error(ValidationErrorType.PATTERN_MISMATCH, "Password must contain digit")
        if require_special and not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", value):
            result.add_error(ValidationErrorType.PATTERN_MISMATCH, "Password must contain special character")
        common_patterns = ["123456", "password", "qwerty", "abc123", "letmein", "admin", "welcome"]
        for pat in common_patterns:
            if pat in value.lower():
                result.add_warning(f"Password contains common pattern '{pat}'")
                break
        return result

    def validate(self, value: Any, rules: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=value)
        for rule, params in rules.items():
            if rule == "email":
                result.merge(self.validate_email(value))
            elif rule == "phone":
                result.merge(self.validate_phone(value, **params if isinstance(params, dict) else {}))
            elif rule == "url":
                result.merge(self.validate_url(value))
            elif rule == "ip":
                result.merge(self.validate_ip(value))
            elif rule == "date":
                fmts = params if isinstance(params, list) else params.get("formats") if isinstance(params, dict) else None
                result.merge(self.validate_date(value, fmts))
            elif rule == "range":
                result.merge(self.validate_range(value, params.get("min"), params.get("max")))
            elif rule == "length":
                result.merge(self.validate_length(value, params.get("min"), params.get("max")))
            elif rule == "pattern":
                result.merge(self.validate_pattern(value, params))
            elif rule == "not_empty":
                result.merge(self.validate_not_empty(value))
            elif rule == "type":
                result.merge(self.validate_type(value, params if isinstance(params, type) else type(params)))
            elif rule == "choice":
                result.merge(self.validate_choice(value, params))
            elif rule == "uuid":
                result.merge(self.validate_uuid(value, params if isinstance(params, int) else None))
            elif rule == "password":
                result.merge(self.validate_password_strength(value, **params if isinstance(params, dict) else {}))
            elif rule == "json":
                result.merge(self.validate_json(value))
            elif rule.startswith(self.config.custom_rule_prefix):
                name = rule[len(self.config.custom_rule_prefix):]
                result.merge(self.run_custom(name, value, params))
            else:
                result.add_warning(f"Unknown validation rule: {rule}")
        return result

    def validate_batch(self, items: List[Tuple[str, Any, Optional[Dict]]]) -> Dict[str, ValidationResult]:
        results = {}
        if len(items) > self.config.max_batch_size:
            items = items[:self.config.max_batch_size]
        for item in items:
            if len(item) == 3:
                key, value, rules = item
            else:
                key, value = item
                rules = None
            if rules:
                results[key] = self.validate(value, rules)
            else:
                results[key] = self.validate_not_empty(value)
        return results

    def validate_dict(self, data: Dict[str, Any], schema: Dict[str, Dict[str, Any]],
                      allow_extra: bool = True) -> Dict[str, ValidationResult]:
        results = {}
        for field, rules in schema.items():
            value = data.get(field)
            if value is None and rules.get("required", False):
                res = ValidationResult(is_valid=False)
                res.add_error(ValidationErrorType.EMPTY_VALUE, f"Required field '{field}' is missing")
                results[field] = res
            elif value is not None:
                results[field] = self.validate(value, rules.get("rules", {}))
            else:
                res = ValidationResult(is_valid=True, value=None)
                results[field] = res
        if not allow_extra:
            for field in data:
                if field not in schema:
                    res = ValidationResult(is_valid=False)
                    res.add_error(ValidationErrorType.CUSTOM_FAILURE, f"Unexpected field '{field}'")
                    results[field] = res
        return results

    def register_custom(self, name: str, validator_fn: Callable[[Any, Any], ValidationResult]):
        if not callable(validator_fn):
            raise TypeError("validator_fn must be callable")
        if not name.isidentifier():
            raise ValueError(f"Custom validator name '{name}' must be a valid identifier")
        with self._validator_lock:
            self._custom_validators[name] = validator_fn
            logger.info("Registered custom validator '%s'", name)

    def unregister_custom(self, name: str):
        with self._validator_lock:
            if name in self._custom_validators:
                del self._custom_validators[name]
                logger.info("Unregistered custom validator '%s'", name)
            else:
                logger.warning("Custom validator '%s' not found", name)

    def run_custom(self, name: str, value: Any, params: Any = None) -> ValidationResult:
        with self._validator_lock:
            fn = self._custom_validators.get(name)
        if fn is None:
            result = ValidationResult(is_valid=False)
            result.add_error(ValidationErrorType.CUSTOM_FAILURE, f"Custom validator '{name}' not registered")
            return result
        try:
            return fn(value, params)
        except Exception as e:
            result = ValidationResult(is_valid=False)
            result.add_error(ValidationErrorType.CUSTOM_FAILURE, f"Custom validator '{name}' raised: {e}")
            return result

    def list_custom_validators(self) -> List[str]:
        with self._validator_lock:
            return list(self._custom_validators.keys())

    def get_statistics(self) -> Dict[str, Any]:
        with self._validator_lock:
            total = len(self._validation_history)
            valid_count = sum(1 for e in self._validation_history if e["result"])
            invalid_count = total - valid_count
            method_counts = defaultdict(int)
            for e in self._validation_history:
                method_counts[e["method"]] += 1
        return {
            "total_validations": total,
            "valid": valid_count,
            "invalid": invalid_count,
            "methods": dict(method_counts),
            "mx_cache_size": len(self._mx_cache),
            "custom_validators": len(self._custom_validators)
        }

    def clear_history(self):
        with self._validator_lock:
            self._validation_history.clear()

    def clear_mx_cache(self):
        with self._validator_lock:
            self._mx_cache.clear()

    def set_config(self, config: ValidatorConfig):
        self.config = config

    def update_config(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                logger.warning("Unknown config key: %s", key)

    def sanitize_html(self, value: str, allowed_tags: Optional[Set[str]] = None) -> str:
        if allowed_tags is None:
            allowed_tags = {"b", "i", "em", "strong", "a", "br", "p", "ul", "ol", "li", "code", "pre"}
        import html
        escaped = html.escape(value)
        for tag in allowed_tags:
            escaped = re.sub(
                rf"&lt;{tag}([^&]*)&gt;(.*?)&lt;/{tag}&gt;",
                rf"<{tag}\1>\2</{tag}>",
                escaped,
                flags=re.IGNORECASE | re.DOTALL
            )
        escaped = re.sub(
            r"&lt;(/?)(" + "|".join(re.escape(t) for t in allowed_tags) + r")([^&]*)&gt;",
            r"<\1\2\3>",
            escaped,
            flags=re.IGNORECASE
        )
        return escaped

    def extract_emails(self, text: str) -> List[str]:
        pattern = re.compile(r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}")
        return list(set(pattern.findall(text)))

    def extract_urls(self, text: str) -> List[str]:
        pattern = re.compile(r"https?://[^\s<>\"']+|ftp://[^\s<>\"']+")
        return list(set(pattern.findall(text)))

    def normalize_phone(self, phone: str, region: Optional[str] = None) -> Optional[str]:
        result = self.validate_phone(phone, region)
        return result.value if result.is_valid else None

    def is_valid_email(self, email: Any) -> bool:
        return self.validate_email(email).is_valid

    def is_valid_phone(self, phone: Any) -> bool:
        return self.validate_phone(phone).is_valid

    def is_valid_url(self, url: Any) -> bool:
        return self.validate_url(url).is_valid

    def is_valid_ip(self, ip: Any) -> bool:
        return self.validate_ip(ip).is_valid

    def is_valid_date(self, date_str: Any) -> bool:
        return self.validate_date(date_str).is_valid

    def chain(self, *validators_fn) -> Callable:
        def chain_validator(value: Any) -> ValidationResult:
            result = ValidationResult(is_valid=True, value=value)
            for fn in validators_fn:
                r = fn(value)
                result.merge(r)
                if not r.is_valid and self.config.strict_mode:
                    break
            return result
        return chain_validator

    def validator_for(self, rule_type: str) -> Optional[Callable]:
        registry = {
            "email": self.validate_email,
            "phone": self.validate_phone,
            "url": self.validate_url,
            "ip": self.validate_ip,
            "date": self.validate_date,
            "range": self.validate_range,
            "length": self.validate_length,
            "pattern": self.validate_pattern,
            "not_empty": self.validate_not_empty,
            "type": self.validate_type,
            "choice": self.validate_choice,
            "uuid": self.validate_uuid,
            "password": self.validate_password_strength,
            "json": self.validate_json,
            "bool": self.validate_bool,
            "color_hex": self.validate_color_hex,
            "credit_card": self.validate_credit_card,
        }
        return registry.get(rule_type)

    def validate_optional(self, value: Any, validator_fn: Callable, default: Any = None) -> ValidationResult:
        if value is None:
            result = ValidationResult(is_valid=True, value=default)
            return result
        return validator_fn(value)

    def validate_all_or_nothing(self, values: Dict[str, Any], validator_map: Dict[str, Callable]) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=values)
        all_none = all(v is None for v in values.values())
        all_present = all(v is not None for v in values.values())
        if not all_none and not all_present:
            missing = [k for k, v in values.items() if v is None]
            result.add_error(ValidationErrorType.CUSTOM_FAILURE, f"Must provide all or none of: {', '.join(missing)}")
            return result
        if all_present:
            for key, validator_fn in validator_map.items():
                val = values.get(key)
                if val is not None:
                    result.merge(validator_fn(val))
        return result

    def validate_at_least_one(self, values: Dict[str, Any], validator_map: Dict[str, Callable]) -> ValidationResult:
        result = ValidationResult(is_valid=True, value=values)
        present = {k: v for k, v in values.items() if v is not None}
        if not present:
            result.add_error(ValidationErrorType.CUSTOM_FAILURE, "At least one field must be provided")
            return result
        for key, validator_fn in validator_map.items():
            val = values.get(key)
            if val is not None:
                result.merge(validator_fn(val))
        return result
