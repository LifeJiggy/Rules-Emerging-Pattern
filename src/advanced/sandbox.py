"""Sandbox module for code execution."""
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """Result of sandbox execution."""
    success: bool
    output: str
    errors: List[str]
    execution_time: float
    timestamp: datetime
    exit_code: int = 0
    resource_usage: Dict[str, float] = field(default_factory=dict)
    execution_id: str = ""
    language: str = "unknown"
    risk_level: str = "unknown"
    risks_found: int = 0


@dataclass
class ExecutionRecord:
    """Record of a sandbox execution for audit."""
    execution_id: str
    language: str
    code_hash: str
    success: bool
    execution_time: float
    timestamp: datetime
    risk_level: str
    risks_found: int
    sandbox_id: str


@dataclass
class ResourceLimits:
    """Resource limits for sandbox execution."""
    cpu_timeout: int = 30
    memory_mb: int = 256
    disk_mb: int = 100
    network_enabled: bool = False
    max_processes: int = 10
    max_file_size_mb: int = 5
    max_output_size_kb: int = 1024


@dataclass
class SandboxPoolEntry:
    """A sandbox in the pool."""
    sandbox_id: str
    sandbox_dir: str
    created_at: datetime
    in_use: bool = False
    last_used: Optional[datetime] = None
    use_count: int = 0


@dataclass
class SandboxConfig:
    """Configuration for the sandbox system."""
    default_timeout: int = 30
    default_memory_mb: int = 256
    enable_pooling: bool = True
    pool_size: int = 5
    pool_idle_timeout_minutes: int = 30
    enable_audit_trail: bool = True
    enable_resource_limits: bool = True
    enable_cleanup_guarantee: bool = True
    max_execution_history: int = 1000
    allowed_languages: List[str] = field(default_factory=lambda: ["python", "bash", "js", "ruby", "go"])
    blocked_modules: List[str] = field(default_factory=lambda: [
        "ctypes", "socket", "os.system", "subprocess", "shutil.rmtree",
        "shutil.disk_usage", "pdb", "trace", "sys.stdin",
    ])
    restricted_paths: List[str] = field(default_factory=lambda: [
        "/etc", "/var", "/root", "/home", "/proc", "/sys",
    ])
    temp_dir: Optional[str] = None
    log_all_executions: bool = False


class CodeSandbox:
    """Sandbox environment for executing untrusted code."""

    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()
        self.sandbox_dir: Optional[str] = None
        self.sandbox_id: str = uuid.uuid4().hex[:12]
        self.execution_count: int = 0
        self.execution_history: List[ExecutionRecord] = []
        self.pool: Dict[str, SandboxPoolEntry] = {}
        self.risk_patterns = self._build_risk_patterns()
        self._lock = threading.Lock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._pool_cleanup_running: bool = False
        self._start_pool_cleanup()
        logger.info(f"CodeSandbox {self.sandbox_id} initialized "
                    f"(timeout={config.default_timeout if config else 30}s, "
                    f"memory={config.default_memory_mb if config else 256}MB)")

    def _build_risk_patterns(self) -> Dict[str, List[Tuple[str, str, int]]]:
        return {
            "python": [
                (r"import\s+os", "System access", 7),
                (r"import\s+subprocess", "Process execution", 9),
                (r"import\s+socket", "Network access", 8),
                (r"import\s+ctypes", "Low-level system access", 9),
                (r"import\s+shutil", "File system operations", 5),
                (r"import\s+sys", "System introspection", 3),
                (r"eval\s*\(|exec\s*\(", "Dynamic code execution", 10),
                (r"__import__\s*\(", "Dynamic imports", 7),
                (r"open\s*\(.*[,\)]", "File I/O", 4),
                (r"os\.system\s*\(", "Shell command execution", 10),
                (r"os\.popen\s*\(", "Shell command execution", 10),
                (r"subprocess\.[a-z]+\s*\(", "Subprocess execution", 9),
                (r"shutil\.rmtree\s*\(", "Destructive file operation", 8),
                (r"os\.remove\s*\(|os\.unlink\s*\(", "File deletion", 7),
                (r"os\.chmod\s*\(|os\.chown\s*\(", "Permission change", 6),
                (r"tempfile\.", "Temporary file usage", 2),
                (r"pickle\.loads?|pickle\.dumps?", "Deserialization risk", 7),
                (r"marshal\.", "Unsafe deserialization", 8),
                (r"shelve\.", "Persistent storage", 3),
                (r"sqlite3\.", "Database access", 4),
                (r"requests\.", "HTTP requests", 6),
                (r"urllib\.", "URL access", 6),
                (r"http\.client|http\.server", "HTTP operations", 6),
                (r"ftplib\.", "FTP access", 7),
                (r"telnetlib\.", "Telnet access", 7),
                (r"paramiko\.", "SSH access", 8),
                (r"redis\.", "Redis access", 5),
                (r"pymongo\.", "MongoDB access", 5),
                (r"psycopg2\.", "PostgreSQL access", 5),
                (r"multiprocessing\.", "Process spawning", 8),
                (r"threading\.", "Threading", 5),
                (r"signal\.", "Signal handling", 6),
                (r"fcntl\.", "File control", 6),
                (r"mmap\.", "Memory mapping", 7),
                (r"struct\.", "Binary data manipulation", 3),
                (r"platform\.", "System information", 2),
                (r"getpass\.", "Password input", 3),
                (r"crypt\.", "Cryptography", 3),
                (r"hashlib\.", "Hashing", 1),
                (r"base64\.", "Encoding", 1),
                (r"glob\.", "File pattern matching", 2),
                (r"fnmatch\.", "File pattern matching", 2),
                (r"pathlib\.", "Path operations", 2),
                (r"configparser\.", "Config file reading", 2),
                (r"json\.", "JSON operations", 1),
                (r"csv\.", "CSV operations", 1),
                (r"xml\.", "XML parsing", 3),
                (r"yaml\.", "YAML parsing", 3),
                (r"typing\.", "Type hints", 0),
                (r"dataclasses\.", "Data classes", 0),
                (r"enum\.", "Enumerations", 0),
                (r"collections\.", "Collections", 0),
                (r"functools\.", "Function tools", 0),
                (r"itertools\.", "Iteration tools", 0),
            ],
            "bash": [
                (r"rm\s+-rf|rmdir\s+", "Destructive file removal", 9),
                (r"wget\s+|curl\s+", "Network download", 7),
                (r"nc\s+|netcat\s+", "Network connection", 9),
                (r"mkfs|dd\s+|fdisk", "Disk operations", 10),
                (r"chmod|chown", "Permission changes", 6),
                (r":\(\)\s*\{", "Fork bomb", 10),
                (r"exec\s+", "Process replacement", 7),
                (r"eval\s+", "Dynamic evaluation", 8),
                (r"kill\s+|pkill\s+", "Process termination", 6),
                (r"iptables|ufw", "Firewall changes", 9),
                (r"passwd|useradd|userdel", "User management", 9),
                (r"mount|umount", "Mount operations", 9),
                (r">\s*/dev/", "Device access", 8),
                (r"ssh\s+|scp\s+|sftp\s+", "SSH operations", 8),
                (r"telnet\s+", "Telnet connection", 7),
                (r"nmap\s+|nikto\s+", "Network scanning", 8),
                (r"gcc|g\+\+|make", "Compilation", 4),
                (r"pip\s+install", "Package installation", 5),
                (r"apt-get|yum|dnf|pacman", "Package manager", 6),
                (r"/etc/", "System config access", 7),
                (r"/var/log", "Log file access", 3),
                (r"/proc/", "Process information", 4),
                (r"/sys/", "Kernel interface", 8),
                (r"dd\s+", "Disk duplicator", 10),
                (r"reboot|shutdown|halt", "System shutdown", 10),
                (r"crontab", "Scheduled tasks", 7),
                (r"systemctl|service", "Service management", 7),
            ],
            "js": [
                (r"eval\s*\(", "Dynamic code execution", 10),
                (r"Function\s*\(", "Dynamic function creation", 8),
                (r"require\s*\(\s*['\"]child_process['\"]\s*\)", "Child process", 9),
                (r"require\s*\(\s*['\"]fs['\"]\s*\)", "File system access", 7),
                (r"require\s*\(\s*['\"]net['\"]\s*\)", "Network access", 8),
                (r"require\s*\(\s*['\"]http['\"]\s*\)", "HTTP access", 6),
                (r"require\s*\(\s*['\"]https['\"]\s*\)", "HTTPS access", 6),
                (r"require\s*\(\s*['\"]dns['\"]\s*\)", "DNS access", 5),
                (r"require\s*\(\s*['\"]cluster['\"]\s*\)", "Cluster operations", 6),
                (r"process\.env", "Environment access", 4),
                (r"process\.exit", "Process termination", 5),
                (r"process\.kill", "Signal sending", 6),
                (r"global\.", "Global object access", 3),
                (r"__proto__", "Prototype pollution", 8),
                (r"constructor\.", "Constructor access", 5),
                (r"Reflect\.", "Reflection API", 5),
                (r"Proxy\.", "Proxy object", 3),
                (r"new\s+Function", "Dynamic function", 8),
                (r"setTimeout|setInterval", "Timer operations", 2),
                (r"Worker\s*\(", "Web worker", 4),
                (r"SharedArrayBuffer", "Shared memory", 6),
                (r"Atomics\.", "Atomic operations", 5),
                (r"WebAssembly\.", "WebAssembly", 4),
                (r"fetch\s*\(", "Network request", 6),
                (r"XMLHttpRequest", "Network request", 6),
                (r"WebSocket\s*\(", "WebSocket connection", 7),
            ],
            "ruby": [
                (r"eval\s+", "Dynamic code execution", 10),
                (r"exec\s+", "Process execution", 9),
                (r"system\s+", "System command", 9),
                (r"`[^`]+`", "Shell command", 9),
                (r"IO\.popen|Open3\.", "Process execution", 8),
                (r"require\s+['\"]socket['\"]", "Network access", 8),
                (r"require\s+['\"]net/", "Network access", 8),
                (r"require\s+['\"]open-uri['\"]", "URL access", 6),
                (r"require\s+['\"]fileutils['\"]", "File operations", 5),
                (r"require\s+['\"]tempfile['\"]", "Temp file", 2),
                (r"File\.(open|read|write|delete|rename)", "File operations", 5),
                (r"Dir\.(mkdir|rmdir|delete|entries)", "Directory operations", 5),
                (r"Process\.(fork|spawn|kill|exit)", "Process control", 8),
                (r"Thread\.(new|start|kill)", "Threading", 5),
                (r"Marshal\.(load|dump)", "Deserialization", 7),
                (r"YAML\.(load|load_file)", "YAML deserialization", 6),
                (r"ERB\.new", "Template evaluation", 5),
                (r"Binding\.", "Binding access", 6),
                (r"send\s*\(?\s*:[\"\']", "Dynamic method call", 5),
                (r"define_method|define_singleton_method", "Method definition", 4),
                (r"class_eval|instance_eval|module_eval", "Dynamic evaluation", 8),
                (r"const_set|const_get|remove_const", "Constant manipulation", 5),
                (r"remove_method|undef_method", "Method removal", 4),
            ],
            "go": [
                (r"os\.Exec|os\.StartProcess", "Process execution", 9),
                (r"os\.Remove(All)?", "File deletion", 7),
                (r"os\.Chmod|os\.Chown", "Permission change", 6),
                (r"os\.(Create|Open|Write)", "File operations", 5),
                (r"net\.Dial|net\.Listen", "Network operations", 8),
                (r"net/http\.(Get|Post|Do)", "HTTP request", 6),
                (r"syscall\.", "System call", 10),
                (r"unsafe\.", "Unsafe operations", 9),
                (r"reflect\.", "Reflection", 4),
                (r"exec\.Command|exec\.CommandContext", "Command execution", 9),
                (r"os/exec\.", "Command execution", 9),
                (r"plugin\.Open", "Plugin loading", 7),
                (r"cgo\s+", "C interop", 8),
                (r"debug/gosym\.", "Symbol debugging", 5),
                (r"runtime\.(GC|Goexit|GoroutineProfile)", "Runtime control", 5),
                (r"os\.Signal|os\.Notify", "Signal handling", 5),
                (r"database/sql\.", "Database access", 5),
                (r"io/ioutil\.", "File I/O", 4),
                (r"os\.(Rename|Mkdir|MkdirAll)", "File system changes", 4),
                (r"context\.WithCancel|context\.WithTimeout", "Context control", 2),
            ],
        }

    def _start_pool_cleanup(self) -> None:
        if self.config.enable_pooling and not self._pool_cleanup_running:
            self._pool_cleanup_running = True
            self._cleanup_thread = threading.Thread(target=self._pool_cleanup_loop, daemon=True)
            self._cleanup_thread.start()

    def _pool_cleanup_loop(self) -> None:
        while self._pool_cleanup_running:
            try:
                self._cleanup_idle_pool_entries()
            except Exception as e:
                logger.error(f"Pool cleanup error: {e}")
            time.sleep(60)

    def _cleanup_idle_pool_entries(self) -> None:
        now = datetime.now()
        timeout = timedelta(minutes=self.config.pool_idle_timeout_minutes)
        to_remove = []
        with self._lock:
            for sid, entry in self.pool.items():
                if not entry.in_use and entry.last_used and (now - entry.last_used) > timeout:
                    try:
                        if os.path.exists(entry.sandbox_dir):
                            shutil.rmtree(entry.sandbox_dir, ignore_errors=True)
                    except Exception as e:
                        logger.error(f"Failed to cleanup pool entry {sid}: {e}")
                    to_remove.append(sid)
            for sid in to_remove:
                del self.pool[sid]
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} idle pool entries")

    def create_isolated_env(self) -> str:
        base_dir = self.config.temp_dir
        self.sandbox_dir = tempfile.mkdtemp(prefix=f"sandbox_{self.sandbox_id}_", dir=base_dir)
        logger.info(f"Created sandbox environment: {self.sandbox_dir}")
        os.makedirs(os.path.join(self.sandbox_dir, "tmp"), exist_ok=True)
        os.makedirs(os.path.join(self.sandbox_dir, "data"), exist_ok=True)
        return self.sandbox_dir

    def _acquire_from_pool(self) -> Optional[SandboxPoolEntry]:
        if not self.config.enable_pooling:
            return None
        with self._lock:
            for entry in self.pool.values():
                if not entry.in_use:
                    entry.in_use = True
                    entry.last_used = datetime.now()
                    entry.use_count += 1
                    self.sandbox_dir = entry.sandbox_dir
                    return entry
            if len(self.pool) < self.config.pool_size:
                sandbox_dir = tempfile.mkdtemp(prefix="sandbox_pool_", dir=self.config.temp_dir)
                entry = SandboxPoolEntry(
                    sandbox_id=uuid.uuid4().hex[:12],
                    sandbox_dir=sandbox_dir,
                    created_at=datetime.now(),
                    in_use=True,
                    last_used=datetime.now(),
                    use_count=1,
                )
                self.pool[entry.sandbox_id] = entry
                self.sandbox_dir = sandbox_dir
                return entry
        return None

    def _release_to_pool(self) -> None:
        if not self.config.enable_pooling:
            return
        with self._lock:
            for entry in self.pool.values():
                if entry.sandbox_dir == self.sandbox_dir:
                    entry.in_use = False
                    entry.last_used = datetime.now()
                    return

    def _get_extension(self, language: str) -> str:
        extensions = {
            "python": "py", "bash": "sh", "js": "js",
            "ruby": "rb", "go": "go",
        }
        return extensions.get(language, "txt")

    def execute_code(self, code: str, language: str = "python") -> SandboxResult:
        start_time = time.time()
        errors: List[str] = []
        output = ""
        exit_code = 0
        execution_id = uuid.uuid4().hex[:12]

        if language not in self.config.allowed_languages:
            errors.append(f"Unsupported language: {language}")
            return SandboxResult(
                success=False, output="", errors=errors,
                execution_time=0.0, timestamp=datetime.now(),
                execution_id=execution_id, language=language,
                risk_level="unknown", risks_found=0,
            )

        try:
            pool_entry = self._acquire_from_pool()
            if not self.sandbox_dir:
                self.create_isolated_env()

            code_file = os.path.join(self.sandbox_dir, f"script.{self._get_extension(language)}")
            with open(code_file, 'w', encoding='utf-8') as f:
                f.write(code)

            interpreters = {
                "python": sys.executable,
                "bash": "bash" if platform.system() != "Windows" else "C:\\Windows\\System32\\bash.exe",
                "js": "node",
                "ruby": "ruby",
                "go": "go",
            }

            interpreter = interpreters.get(language)
            if not interpreter:
                errors.append(f"No interpreter configured for {language}")
                return SandboxResult(
                    success=False, output="", errors=errors,
                    execution_time=0.0, timestamp=datetime.now(),
                    execution_id=execution_id, language=language,
                )

            timeout = self.config.default_timeout
            result = subprocess.run(
                [interpreter, code_file],
                capture_output=True, text=True,
                timeout=timeout,
                cwd=self.sandbox_dir,
            )

            output = result.stdout
            if result.stderr:
                errors.append(result.stderr)
            exit_code = result.returncode

            if self.config.enable_resource_limits and len(output) > self.config.default_memory_mb * 1024:
                errors.append("Output exceeded size limit")

            execution_time = time.time() - start_time
            self.execution_count += 1

            security_analysis = self.analyze_security(code)
            risk_level = security_analysis.get("risk_level", "low")
            risks_found = security_analysis.get("total_risks", 0)

            logger.info(f"Code executed in sandbox (execution #{self.execution_count}, "
                        f"language={language}, time={execution_time:.2f}s)")

            sandbox_result = SandboxResult(
                success=exit_code == 0,
                output=output,
                errors=errors,
                execution_time=execution_time,
                timestamp=datetime.now(),
                exit_code=exit_code,
                execution_id=execution_id,
                language=language,
                risk_level=risk_level,
                risks_found=risks_found,
            )

            if self.config.enable_audit_trail:
                self._add_execution_record(sandbox_result, code)

            self._release_to_pool()
            return sandbox_result

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            errors.append(f"Execution exceeded timeout of {self.config.default_timeout} seconds")
            self._release_to_pool()
            return SandboxResult(
                success=False, output=output, errors=errors,
                execution_time=execution_time, timestamp=datetime.now(),
                exit_code=-1, execution_id=execution_id, language=language,
            )
        except FileNotFoundError as e:
            execution_time = time.time() - start_time
            errors.append(f"Interpreter not found: {e}")
            self._release_to_pool()
            return SandboxResult(
                success=False, output="", errors=errors,
                execution_time=execution_time, timestamp=datetime.now(),
                exit_code=-1, execution_id=execution_id, language=language,
            )
        except Exception as e:
            execution_time = time.time() - start_time
            errors.append(str(e))
            self._release_to_pool()
            return SandboxResult(
                success=False, output=output, errors=errors,
                execution_time=execution_time, timestamp=datetime.now(),
                exit_code=-1, execution_id=execution_id, language=language,
            )

    def _add_execution_record(self, result: SandboxResult, code: str) -> None:
        record = ExecutionRecord(
            execution_id=result.execution_id,
            language=result.language,
            code_hash=hashlib.sha256(code.encode()).hexdigest()[:16],
            success=result.success,
            execution_time=result.execution_time,
            timestamp=result.timestamp,
            risk_level=result.risk_level,
            risks_found=result.risks_found,
            sandbox_id=self.sandbox_id,
        )
        self.execution_history.append(record)
        if len(self.execution_history) > self.config.max_execution_history:
            self.execution_history = self.execution_history[-self.config.max_execution_history:]

    def analyze_security(self, code: str, language: str = "python") -> Dict[str, Any]:
        risks = []
        total_risk_score = 0

        language_patterns = self.risk_patterns.get(language, self.risk_patterns.get("python", []))

        for pattern, risk_type, severity in language_patterns:
            if re.search(pattern, code):
                risks.append({
                    "pattern": pattern,
                    "risk_type": risk_type,
                    "severity": severity,
                })
                total_risk_score += severity

        for blocked in self.config.blocked_modules:
            if blocked in code:
                risks.append({
                    "pattern": blocked,
                    "risk_type": "Blocked module reference",
                    "severity": 10,
                })
                total_risk_score += 10

        for restricted_path in self.config.restricted_paths:
            if restricted_path in code:
                risks.append({
                    "pattern": restricted_path,
                    "risk_type": "Restricted path reference",
                    "severity": 8,
                })
                total_risk_score += 8

        if total_risk_score == 0:
            risk_level = "low"
        elif total_risk_score <= 20:
            risk_level = "low"
        elif total_risk_score <= 50:
            risk_level = "medium"
        elif total_risk_score <= 100:
            risk_level = "high"
        else:
            risk_level = "critical"

        unique_risk_types = list(set(r["risk_type"] for r in risks))

        logger.info(f"Security analysis found {len(risks)} potential risks "
                    f"(level={risk_level}, score={total_risk_score})")

        return {
            "total_risks": len(risks),
            "risks": risks,
            "risk_level": risk_level,
            "risk_score": total_risk_score,
            "unique_risk_types": unique_risk_types,
            "timestamp": datetime.now().isoformat(),
            "language": language,
        }

    def cleanup(self) -> None:
        if self.sandbox_dir and os.path.exists(self.sandbox_dir):
            try:
                shutil.rmtree(self.sandbox_dir, ignore_errors=True)
                logger.info(f"Cleaned up sandbox: {self.sandbox_dir}")
                self.sandbox_dir = None
            except Exception as e:
                logger.error(f"Failed to cleanup sandbox: {e}")

    def cleanup_all_pool_entries(self) -> int:
        count = 0
        with self._lock:
            for sid, entry in list(self.pool.items()):
                try:
                    if os.path.exists(entry.sandbox_dir):
                        shutil.rmtree(entry.sandbox_dir, ignore_errors=True)
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to cleanup pool entry {sid}: {e}")
                del self.pool[sid]
        logger.info(f"Cleaned up {count} pool entries")
        return count

    def get_execution_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        recent = self.execution_history[-limit:] if self.execution_history else []
        return [
            {
                "execution_id": e.execution_id,
                "language": e.language,
                "code_hash": e.code_hash,
                "success": e.success,
                "execution_time": e.execution_time,
                "timestamp": e.timestamp.isoformat(),
                "risk_level": e.risk_level,
                "risks_found": e.risks_found,
            }
            for e in reversed(recent)
        ]

    def get_execution_statistics(self) -> Dict[str, Any]:
        if not self.execution_history:
            return {
                "total_executions": self.execution_count,
                "history_size": 0,
            }
        total = len(self.execution_history)
        successful = sum(1 for e in self.execution_history if e.success)
        failed = total - successful
        avg_time = sum(e.execution_time for e in self.execution_history) / total if total > 0 else 0
        risk_distribution: Dict[str, int] = defaultdict(int)
        language_distribution: Dict[str, int] = defaultdict(int)
        for e in self.execution_history:
            risk_distribution[e.risk_level] += 1
            language_distribution[e.language] += 1
        return {
            "total_executions": self.execution_count,
            "history_size": total,
            "successful": successful,
            "failed": failed,
            "success_rate": round(successful / total * 100, 1) if total > 0 else 0,
            "average_execution_time": round(avg_time, 3),
            "risk_distribution": dict(risk_distribution),
            "language_distribution": dict(language_distribution),
            "pool_size": len(self.pool),
        }

    def set_resource_limits(self, timeout: Optional[int] = None,
                             memory_mb: Optional[int] = None) -> None:
        if timeout is not None:
            self.config.default_timeout = timeout
        if memory_mb is not None:
            self.config.default_memory_mb = memory_mb
        logger.info(f"Resource limits updated: timeout={self.config.default_timeout}s, "
                    f"memory={self.config.default_memory_mb}MB")

    def add_risk_pattern(self, language: str, pattern: str,
                          risk_type: str, severity: int) -> None:
        if language not in self.risk_patterns:
            self.risk_patterns[language] = []
        self.risk_patterns[language].append((pattern, risk_type, severity))
        logger.info(f"Added risk pattern for {language}: {risk_type} (severity={severity})")

    def execute_code_safe(self, code: str, language: str = "python") -> SandboxResult:
        security = self.analyze_security(code, language)
        if security["risk_level"] in ("high", "critical"):
            logger.warning(f"Code blocked: risk level {security['risk_level']}")
            return SandboxResult(
                success=False, output="", errors=[f"Code blocked: {security['risk_level']} risk"],
                execution_time=0.0, timestamp=datetime.now(),
                execution_id=uuid.uuid4().hex[:12], language=language,
                risk_level=security["risk_level"],
                risks_found=security["total_risks"],
            )
        return self.execute_code(code, language)

    def get_pool_status(self) -> Dict[str, Any]:
        total = len(self.pool)
        in_use = sum(1 for e in self.pool.values() if e.in_use)
        available = total - in_use
        return {
            "total": total,
            "in_use": in_use,
            "available": available,
            "max_pool_size": self.config.pool_size,
            "entries": [
                {
                    "id": e.sandbox_id,
                    "created": e.created_at.isoformat(),
                    "in_use": e.in_use,
                    "use_count": e.use_count,
                    "last_used": e.last_used.isoformat() if e.last_used else None,
                }
                for e in self.pool.values()
            ],
        }

    def get_supported_languages(self) -> List[str]:
        return list(self.config.allowed_languages)

    def add_supported_language(self, language: str, interpreter: str,
                                extension: str) -> None:
        if language not in self.config.allowed_languages:
            self.config.allowed_languages.append(language)
            self.risk_patterns[language] = []
            logger.info(f"Added supported language: {language}")

    def is_sandbox_active(self) -> bool:
        return self.sandbox_dir is not None and os.path.exists(self.sandbox_dir)

    def get_sandbox_info(self) -> Dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "active": self.is_sandbox_active(),
            "directory": self.sandbox_dir,
            "execution_count": self.execution_count,
            "history_size": len(self.execution_history),
            "pool_size": len(self.pool),
            "config": {
                "timeout": self.config.default_timeout,
                "memory_mb": self.config.default_memory_mb,
                "pooling": self.config.enable_pooling,
                "pool_size": self.config.pool_size,
                "audit_trail": self.config.enable_audit_trail,
                "cleanup_guarantee": self.config.enable_cleanup_guarantee,
                "allowed_languages": self.config.allowed_languages,
            },
            "risk_pattern_count": sum(len(v) for v in self.risk_patterns.values()),
        }

    def shutdown(self) -> None:
        self._pool_cleanup_running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
        self.cleanup()
        self.cleanup_all_pool_entries()
        logger.info(f"CodeSandbox {self.sandbox_id} shut down")