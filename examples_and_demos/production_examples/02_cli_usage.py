"""Production Example: CLI Usage."""
from rules_emerging_pattern.cli.cli import app

def main():
    print("CLI Commands:")
    print("  rules-cli validate --content 'text' --tier safety")
    print("  rules-cli list-rules --tier operational")
    print("  rules-cli metrics")
    print("  rules-cli monitor --interval 60")

if __name__ == "__main__":
    main()
