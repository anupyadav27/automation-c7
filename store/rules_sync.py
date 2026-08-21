"""
rules-sync — load rule definitions + the authored metadata registry.

    python -m store.rules_sync

Sources (git is the source of truth):
    rules_definitions — posture/catalog/policy_catalog.csv (compliance)
                        + engines/compliance/policies/** (YAML definitions)
                        + engines/cost/rules/** (cost rules)
    rules_metadata    — posture/catalog/policy_metadata.yaml

rule_id convention: compliance = bare c7n name; cost = '<provider>.<name>'.
"""
import csv
import hashlib
import os
import sys

import yaml

from cspm import paths

from . import get_backend, is_postgres

POLICIES_DIR = os.path.join(paths.ROOT, "engines", "compliance", "policies")
COST_RULES_DIR = os.path.join(paths.ROOT, "engines", "cost", "rules")
CATALOG_CSV = os.path.join(paths.ROOT, "posture", "catalog", "policy_catalog.csv")
METADATA_YAML = os.path.join(paths.ROOT, "posture", "catalog", "policy_metadata.yaml")


def _hash(text) -> str:
    return hashlib.sha256(str(text).encode()).hexdigest()


def compliance_rows():
    catalog = {}
    with open(CATALOG_CSV) as fh:
        for row in csv.DictReader(fh):
            catalog[row["policy"]] = row

    definitions = {}
    for base, _dirs, files in os.walk(POLICIES_DIR):
        for fname in sorted(files):
            if not fname.endswith((".yml", ".yaml")):
                continue
            path = os.path.join(base, fname)
            with open(path) as fh:
                doc = yaml.safe_load(fh) or {}
            for pol in doc.get("policies") or []:
                if pol.get("name"):
                    definitions[pol["name"]] = (pol, os.path.relpath(path, paths.ROOT))

    rows = []
    for name, cat in catalog.items():
        pol, source = definitions.get(name, ({}, cat.get("file", "")))
        definition = yaml.safe_dump(pol, sort_keys=False) if pol else None
        rows.append({
            "rule_id": name,
            "rule_kind": "compliance",
            "provider": "aws",
            "resource": cat.get("resource"),
            "domain": cat.get("domain"),
            "severity": cat.get("severity", "medium"),
            "category": None,
            "action_tier": cat.get("action_tier"),
            "automatable": cat.get("automatable") == "yes",
            "graph_check": cat.get("graph_check") or None,
            "parameters": {},
            "savings_model": None,
            "definition": definition,
            "source_file": source,
            "enabled": True,
            "content_hash": _hash(definition or name),
        })
    return rows


def cost_rows():
    rows = []
    for base, _dirs, files in os.walk(COST_RULES_DIR):
        for fname in sorted(files):
            if not fname.endswith(".yaml"):
                continue
            path = os.path.join(base, fname)
            with open(path) as fh:
                doc = yaml.safe_load(fh) or {}
            for wrapper in doc.get("rules") or []:
                rule = wrapper.get("rule") or {}
                name = rule.get("name")
                if not name:
                    continue
                provider = rule.get("provider") or rule.get("cloud") or "aws"
                action = rule.get("action") or {}
                condition = rule.get("condition") or {}
                definition = yaml.safe_dump(rule, sort_keys=False)
                rows.append({
                    "rule_id": f"{provider}.{name}",
                    "rule_kind": "cost",
                    "provider": provider,
                    "resource": rule.get("resource"),
                    "domain": "cost",
                    "severity": action.get("severity", "medium"),
                    "category": rule.get("finops_category"),
                    "action_tier": action.get("type", "notify"),
                    "automatable": False,
                    "graph_check": None,
                    "parameters": condition.get("parameters") or {},
                    "savings_model": action.get("savings_model"),
                    "definition": definition,
                    "source_file": os.path.relpath(path, paths.ROOT),
                    "enabled": True,
                    "content_hash": _hash(definition),
                })
    return rows


def metadata_rows(valid_ids):
    if not os.path.exists(METADATA_YAML):
        return []
    with open(METADATA_YAML) as fh:
        registry = yaml.safe_load(fh) or {}
    rows = []
    for rule_id, entry in registry.items():
        if rule_id not in valid_ids:
            print(f"  ! registry entry with no definition: {rule_id}", file=sys.stderr)
            continue
        rows.append({
            "rule_id": rule_id,
            "title": entry.get("title") or rule_id,
            "description": entry.get("description"),
            "rationale": entry.get("rationale"),
            "recommendation": entry.get("recommendation"),
            "ai_fix_prompt": entry.get("ai_fix_prompt"),
            "references": entry.get("references") or [],
            "frameworks": entry.get("frameworks") or [],
        })
    return rows


def main(argv=None):
    if not is_postgres():
        print("rules-sync: postgres backend unavailable — files mode reads "
              "out/registry.json directly, nothing to sync", file=sys.stderr)
        return 0
    backend = get_backend()

    definitions = compliance_rows() + cost_rows()
    backend.upsert("rules_definitions", definitions, ["rule_id"])
    metadata = metadata_rows({d["rule_id"] for d in definitions})
    if metadata:
        backend.upsert("rules_metadata", metadata, ["rule_id"])

    kinds = {}
    for d in definitions:
        kinds[d["rule_kind"]] = kinds.get(d["rule_kind"], 0) + 1
    print(f"rules-sync: {len(definitions)} definitions {kinds}, "
          f"{len(metadata)} metadata entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
