#!/usr/bin/env python3
"""Setup script for Rules-Emerging-Pattern."""
import os
import sys
from pathlib import Path

def setup_environment():
    """Set up the development environment."""
    print("Setting up Rules-Emerging-Pattern environment...")
    
    # Create necessary directories
    dirs = [
        "logs",
        "data",
        "cache",
        "config/local"
    ]
    
    for dir_name in dirs:
        Path(dir_name).mkdir(parents=True, exist_ok=True)
        print(f"Created directory: {dir_name}")
    
    # Check Python version
    if sys.version_info < (3, 9):
        print("Error: Python 3.9+ required")
        sys.exit(1)
    
    print("Setup complete!")

if __name__ == "__main__":
    setup_environment()
