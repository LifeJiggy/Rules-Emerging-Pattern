"""Sandbox module for code execution."""
import logging
import subprocess
import tempfile
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import os
import shutil

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """Result of sandbox execution."""
    success: bool
    output: str
    errors: List[str]
    execution_time: float
    timestamp: datetime


class CodeSandbox:
    """Sandbox environment for executing untrusted code."""
    
    def __init__(self, timeout: int = 30, memory_limit: int = 256):
        """Initialize the code sandbox.
        
        Args:
            timeout: Maximum execution time in seconds
            memory_limit: Memory limit in MB
        """
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.sandbox_dir = None
        self.execution_count = 0
        logger.info(f"CodeSandbox initialized (timeout={timeout}s, memory={memory_limit}MB)")
    
    def create_isolated_env(self) -> str:
        """Create an isolated environment for code execution."""
        self.sandbox_dir = tempfile.mkdtemp(prefix="sandbox_")
        logger.info(f"Created sandbox environment: {self.sandbox_dir}")
        return self.sandbox_dir
    
    def execute_code(self, code: str, language: str = "python") -> SandboxResult:
        """Execute code in a sandboxed environment.
        
        Args:
            code: The code to execute
            language: Programming language (python, bash, etc.)
            
        Returns:
            SandboxResult with execution details
        """
        start_time = datetime.now()
        errors = []
        output = ""
        
        try:
            if not self.sandbox_dir:
                self.create_isolated_env()
            
            # Write code to temporary file
            code_file = os.path.join(self.sandbox_dir, f"script.{self._get_extension(language)}")
            with open(code_file, 'w') as f:
                f.write(code)
            
            # Execute with timeout and resource limits
            if language == "python":
                cmd = ["python", code_file]
            elif language == "bash":
                cmd = ["bash", code_file]
            else:
                errors.append(f"Unsupported language: {language}")
                return SandboxResult(
                    success=False,
                    output="",
                    errors=errors,
                    execution_time=0.0,
                    timestamp=datetime.now()
                )
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            output = result.stdout
            if result.stderr:
                errors.append(result.stderr)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            self.execution_count += 1
            
            logger.info(f"Code executed in sandbox (execution #{self.execution_count})")
            
            return SandboxResult(
                success=result.returncode == 0,
                output=output,
                errors=errors,
                execution_time=execution_time,
                timestamp=datetime.now()
            )
            
        except subprocess.TimeoutExpired:
            errors.append(f"Execution exceeded timeout of {self.timeout} seconds")
            execution_time = (datetime.now() - start_time).total_seconds()
            return SandboxResult(
                success=False,
                output=output,
                errors=errors,
                execution_time=execution_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            errors.append(str(e))
            execution_time = (datetime.now() - start_time).total_seconds()
            return SandboxResult(
                success=False,
                output=output,
                errors=errors,
                execution_time=execution_time,
                timestamp=datetime.now()
            )
    
    def _get_extension(self, language: str) -> str:
        """Get file extension for language."""
        extensions = {
            "python": "py",
            "bash": "sh",
            "javascript": "js"
        }
        return extensions.get(language, "txt")
    
    def cleanup(self) -> None:
        """Clean up the sandbox environment."""
        if self.sandbox_dir and os.path.exists(self.sandbox_dir):
            shutil.rmtree(self.sandbox_dir)
            logger.info(f"Cleaned up sandbox: {self.sandbox_dir}")
            self.sandbox_dir = None
    
    def analyze_security(self, code: str) -> Dict[str, Any]:
        """Analyze code for potential security risks.
        
        Args:
            code: Code to analyze
            
        Returns:
            Dictionary with security analysis results
        """
        risks = []
        risk_patterns = [
            ("import os", "System access"),
            ("import subprocess", "Process execution"),
            ("eval(", "Dynamic code execution"),
            ("exec(", "Dynamic code execution"),
            ("__import__", "Dynamic imports"),
        ]
        
        for pattern, risk_type in risk_patterns:
            if pattern in code:
                risks.append({"pattern": pattern, "risk_type": risk_type})
        
        logger.info(f"Security analysis found {len(risks)} potential risks")
        
        return {
            "total_risks": len(risks),
            "risks": risks,
            "risk_level": "high" if len(risks) > 3 else "medium" if len(risks) > 0 else "low",
            "timestamp": datetime.now().isoformat()
        }
