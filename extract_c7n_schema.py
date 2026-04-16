#!/usr/bin/env python3
"""
Extract the full Cloud Custodian schema into a CSV database.

Columns:
  provider      - aws
  resource      - ec2, s3, ebs, etc.
  resource_alias- short alias (same as resource usually)
  category      - filter | action | mode
  name          - filter/action name  (e.g. tag-count, stop, notify)
  schema_path   - aws.ec2.filters.tag-count   (dot-notation key)
  doc           - docstring / description (if available)
  params_json   - JSON of the item's jsonschema properties (truncated)

Usage:
  python3 extract_c7n_schema.py > c7n_schema.csv
  python3 extract_c7n_schema.py --output c7n_schema.csv
"""

import importlib
import pkgutil
import json
import csv
import sys
import argparse
import inspect

# ── Load all c7n resource modules ─────────────────────────────────
import c7n.resources
for _, _modname, __ in pkgutil.walk_packages(
    path=c7n.resources.__path__,
    prefix='c7n.resources.',
    onerror=lambda _: None,
):
    try:
        importlib.import_module(_modname)
    except Exception:
        pass

from c7n.provider import clouds  # noqa: E402

PROVIDER = 'aws'


def _clean_doc(cls):
    """Extract first non-empty line of a class docstring."""
    doc = inspect.getdoc(cls) or ''
    lines = [l.strip() for l in doc.splitlines() if l.strip()]
    return lines[0][:200] if lines else ''


def _schema_props(cls):
    """Return compact JSON of the class's jsonschema properties."""
    schema = getattr(cls, 'schema', None)
    if not schema or not isinstance(schema, dict):
        return ''
    # Keep only 'properties' and 'required' to stay compact
    out = {}
    if 'properties' in schema:
        out['properties'] = {
            k: (v.get('type', v.get('enum', v.get('$ref', '?'))) if isinstance(v, dict) else str(v))
            for k, v in schema['properties'].items()
            if k not in ('type',)
        }
    if 'required' in schema:
        out['required'] = schema['required']
    return json.dumps(out, separators=(',', ':')) if out else ''


def _permissions(cls):
    """Return comma-separated IAM permissions if declared."""
    perms = getattr(cls, 'permissions', None)
    if perms and isinstance(perms, (list, tuple)):
        return ','.join(perms)
    return ''


def extract():
    rows = []
    aws = clouds.get(PROVIDER)
    if not aws:
        print("ERROR: aws provider not found", file=sys.stderr)
        sys.exit(1)

    for resource_name in sorted(aws.resources.keys()):
        resource_cls = aws.resources[resource_name]

        # ── Filters ───────────────────────────────────────────────
        filter_registry = getattr(resource_cls, 'filter_registry', None)
        if filter_registry:
            for filter_name in sorted(filter_registry.keys()):
                filter_cls = filter_registry.get(filter_name)
                rows.append({
                    'provider':       PROVIDER,
                    'resource':       resource_name,
                    'category':       'filter',
                    'name':           filter_name,
                    'schema_path':    f'{PROVIDER}.{resource_name}.filters.{filter_name}',
                    'doc':            _clean_doc(filter_cls),
                    'params_json':    _schema_props(filter_cls),
                    'permissions':    _permissions(filter_cls),
                })

        # ── Actions ───────────────────────────────────────────────
        action_registry = getattr(resource_cls, 'action_registry', None)
        if action_registry:
            for action_name in sorted(action_registry.keys()):
                action_cls = action_registry.get(action_name)
                rows.append({
                    'provider':       PROVIDER,
                    'resource':       resource_name,
                    'category':       'action',
                    'name':           action_name,
                    'schema_path':    f'{PROVIDER}.{resource_name}.actions.{action_name}',
                    'doc':            _clean_doc(action_cls),
                    'params_json':    _schema_props(action_cls),
                    'permissions':    _permissions(action_cls),
                })

    return rows


def main():
    parser = argparse.ArgumentParser(description='Extract c7n schema to CSV')
    parser.add_argument('--output', '-o', default='-',
                        help='Output file path (default: stdout)')
    args = parser.parse_args()

    rows = extract()

    fieldnames = ['provider', 'resource', 'category', 'name',
                  'schema_path', 'doc', 'params_json', 'permissions']

    if args.output == '-':
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    else:
        with open(args.output, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Written {len(rows)} rows → {args.output}", file=sys.stderr)

    # Summary to stderr
    resources = len({r['resource'] for r in rows})
    filters   = sum(1 for r in rows if r['category'] == 'filter')
    actions   = sum(1 for r in rows if r['category'] == 'action')
    print(f"\nSummary: {resources} resources · {filters} filters · {actions} actions · {len(rows)} total rows",
          file=sys.stderr)


if __name__ == '__main__':
    main()
