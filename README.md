# automation-c7

FinOps & Security as Policy engine for multi-cloud environments.

## Features

- **FinOps policies**: Cost anomaly detection, idle resource identification, rightsizing, tagging compliance
- **Security policies**: Encryption at rest, public access controls, IAM least privilege, network exposure
- **Multi-cloud**: AWS, Azure, GCP support
- **YAML-driven**: Human-readable, git-diffable policy definitions
- **Extensible**: Add custom policies, providers, and reporters

## Quick Start

```bash
pip install -e ".[aws,dev]"

# List available policies
c7 list-policies

# Validate policy YAML
c7 validate

# Scan AWS resources
c7 scan --provider aws --region us-east-1

# Scan with JSON output
c7 scan --provider aws --output json --output-file results.json

# Scan only security policies
c7 scan --provider aws --policy-type security
```

## Policy Structure

Policies are YAML files in `policies/`:

```yaml
name: Encryption at Rest
type: security
provider: aws
resource_type: s3_bucket
description: Ensure S3 buckets are encrypted
rules:
  - id: SEC-ENC-001
    description: S3 bucket encryption not enabled
    severity: high
    conditions:
      - field: encryption_enabled
        operator: eq
        value: false
    remediation: Enable default encryption on the bucket
```

## Supported Operators

`eq`, `ne`, `gt`, `lt`, `gte`, `lte`, `contains`, `not_contains`, `regex`, `in`, `not_in`, `exists`

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
