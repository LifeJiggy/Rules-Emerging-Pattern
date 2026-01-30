"""Production Example: FastAPI Server Setup."""
from rules_emerging_pattern.main import app
import uvicorn

def main():
    print("Starting FastAPI Server...")
    print("API endpoints:")
    print("  - GET /health")
    print("  - POST /api/v1/validate")
    print("  - GET /api/v1/rules")
    print("  - GET /api/v1/metrics")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
