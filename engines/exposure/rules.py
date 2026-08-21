"""
Loading the internet-exposure rule catalog, and refusing to load it quietly.

The rules under `rules/aws/` are ported from threat-engine's IEDS catalog and
are **data**, not code — declarative YAML naming a resource type, the fields a
verdict needs, and the conditions that make it true. What lives here is the
part that could not be ported: the reading of them against THIS inventory.

The failure this module exists to prevent is the one that cannot be seen. A rule
whose `resource_type` does not exist in our catalog never matches anything, a
rule whose `check_field` we do not emit never evaluates, and both look exactly
like a clean bill of health. "No internet-exposed resources found" is the most
dangerous sentence this engine can produce, and it is what you get for free by
loading a catalog that does not quite fit and saying nothing.

So every rule is bound at LOAD time — type resolved, fields resolved — and a
rule that cannot bind is an error, not a skip.

Two vocabularies had to be reconciled:

- threat-engine's tiers 1 and 2 name types with an underscore (`ec2_instance`),
  its tier 3 names them with a dot (`ec2.instance`), and ours are dotted
  (`ec2.instance`). The catalog is internally inconsistent, which is worth
  knowing before trusting a straight copy of it.
- Most of the mapping is mechanical — first underscore becomes a dot — and two
  are not: `ec2_address` is `ec2.eip` here and `ec2.securitygroup` is
  `ec2.security_group`. Those two are the whole reason this is a table with an
  explicit exception list rather than a `str.replace`.
"""
import csv
import os

import yaml

RULES_DIR = os.path.join(os.path.dirname(__file__), "rules")
CATALOG = os.path.join(os.path.dirname(__file__), "..", "..",
                       "providers", "aws", "catalog", "resource_catalog.csv")

TIERS = (1, 2, 3)

#: Types whose name does not follow the mechanical rule. Kept short and explicit:
#: every entry is a place where two teams named the same thing differently, and
#: a silent fallback would turn each one into a rule that never fires.
TYPE_ALIASES = {
    "ec2_address": "ec2.eip",
    "ec2.securitygroup": "ec2.security_group",
}


class RuleError(ValueError):
    """A rule that cannot be bound to this inventory. Never a warning."""


def normalise_type(name: str) -> str:
    """
    A rule's resource type in OUR vocabulary.

    `apigateway_rest_api` -> `apigateway.rest_api`: the first underscore
    separates service from resource and the rest belong to the resource's own
    name, which is why this is a single replacement rather than a global one.
    `lambda_function_url_config` becoming `lambda.function.url.config` would
    resolve to nothing at all.
    """
    if not name:
        raise RuleError("a rule has no resource_type")
    if name in TYPE_ALIASES:
        return TYPE_ALIASES[name]
    if "." in name:
        return name
    return name.replace("_", ".", 1)


def catalog_types(path=None):
    """Every resource type this collector knows how to produce."""
    with open(path or CATALOG) as fh:
        return {row["key"] for row in csv.DictReader(fh)}


def load_rules(directory=None, provider="aws"):
    """
    Every rule in the catalog, in a stable order.

    Sorted by rule id, so two runs over the same catalog produce the same list
    and a report can be diffed. Filesystem order is whatever the directory
    happens to hand back, which is not a property anything should depend on.
    """
    root = os.path.join(directory or RULES_DIR, provider)
    if not os.path.isdir(root):
        raise RuleError(f"no rule directory at {root}")
    rules = []
    for name in sorted(os.listdir(root)):
        if not name.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(root, name)
        with open(path) as fh:
            doc = yaml.safe_load(fh) or {}
        for raw in doc.get("rules") or []:
            rules.append(_bind(raw, source=name))
    if not rules:
        raise RuleError(f"{root} contains no rules")
    rules.sort(key=lambda r: r["rule_id"])
    return rules


def _bind(raw, source):
    """One rule, with its type resolved and its shape checked."""
    rule_id = raw.get("rule_id")
    if not rule_id:
        raise RuleError(f"{source}: a rule has no rule_id")
    tier = raw.get("tier")
    if tier not in TIERS:
        raise RuleError(f"{rule_id}: tier {tier!r} is not one of {TIERS}")

    bound = dict(raw)
    bound["source"] = source
    bound["resource_type"] = normalise_type(raw.get("resource_type", ""))
    bound["required_emitted_fields"] = list(raw.get("required_emitted_fields") or [])

    steps = []
    for step in raw.get("traversal_steps") or []:
        step = dict(step)
        for key in ("source_type", "target_type"):
            if step.get(key):
                step[key] = normalise_type(step[key])
        steps.append(step)
    bound["traversal_steps"] = steps

    if tier == 3 and not steps:
        raise RuleError(f"{rule_id}: tier 3 declares no traversal_steps")
    if tier == 2 and not bound["required_emitted_fields"]:
        # A tier 2 rule with no fields is a tier 1 rule wearing the wrong label:
        # it would fire on every resource of its type, unconditionally.
        raise RuleError(
            f"{rule_id}: tier 2 declares no required_emitted_fields, so it "
            "would fire on every resource of its type"
        )
    return bound


def unbound_types(rules, known=None):
    """
    Rules naming a type this collector does not produce.

    The check that matters most, and the one whose absence is invisible: a rule
    for a type we never collect cannot fire, cannot fail, and cannot be
    distinguished from a rule that ran and found nothing.
    """
    known = known if known is not None else catalog_types()
    missing = []
    for rule in rules:
        types = {rule["resource_type"]}
        for step in rule["traversal_steps"]:
            types.update(t for t in (step.get("source_type"), step.get("target_type")) if t)
        for t in sorted(types - known):
            missing.append((rule["rule_id"], t))
    return missing


def validate(rules=None, known=None):
    """
    Bind the whole catalog or refuse it.

    Called from a test and intended to be called from the pipeline before any
    evaluation runs. Raising here costs a failed run; not raising costs a
    report that says an estate is clean because half its rules silently did
    nothing.
    """
    rules = rules if rules is not None else load_rules()
    missing = unbound_types(rules, known)
    if missing:
        detail = ", ".join(f"{rid} -> {t}" for rid, t in missing)
        raise RuleError(
            f"{len(missing)} rule(s) name a resource type this collector does "
            f"not produce: {detail}. A rule that cannot match is not a rule "
            "that found nothing."
        )
    ids = [r["rule_id"] for r in rules]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise RuleError(f"duplicate rule ids: {dupes}")
    return rules
