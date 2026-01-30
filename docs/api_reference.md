# API Reference

## REST API Endpoints

### Health Check
```
GET /health
```
Returns system health status.

### Validate Content
```
POST /api/v1/validate
Content-Type: application/json

{
  "content": "text to validate",
  "tier": "safety",
  "context": {...}
}
```

### List Rules
```
GET /api/v1/rules?tier=safety&active_only=true
```

### Get Metrics
```
GET /api/v1/metrics
```

## Response Format

### ValidationResult
```json
{
  "valid": true,
  "total_score": 1.0,
  "violations": [],
  "processing_time_ms": 50
}
```

## CLI Commands

```bash
# Validate content
rules-cli validate --content "text" --tier safety

# List rules
rules-cli list-rules --tier operational

# Monitor system
rules-cli monitor --interval 60

# Show metrics
rules-cli metrics
```
