# Contributing to Rules-Emerging-Pattern

We welcome contributions to the Rules-Emerging-Pattern project!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/your-username/rules-emerging-pattern.git`
3. Create a virtual environment: `python -m venv venv`
4. Activate it: `source venv/bin/activate` (Linux/Mac) or `venv\Scripts\activate` (Windows)
5. Install dependencies: `pip install -r requirements.txt`
6. Install dev dependencies: `pip install -e ".[dev]"`

## Development Workflow

1. Create a feature branch: `git checkout -b feature/your-feature-name`
2. Make your changes
3. Run tests: `pytest`
4. Run linting: `black . && isort . && flake8`
5. Commit your changes: `git commit -m "Add your feature"`
6. Push to your fork: `git push origin feature/your-feature-name`
7. Create a Pull Request

## Code Standards

- Follow PEP 8 style guide
- Use type hints for all functions
- Write docstrings for all public functions
- Maintain test coverage above 85%
- Add tests for new features

## Reporting Issues

Please use GitHub Issues to report bugs or request features.

## Code of Conduct

Be respectful and constructive in all interactions.
