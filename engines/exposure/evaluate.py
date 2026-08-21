"""
Deciding whether one resource is reachable from the internet.

The rule this module exists to enforce, and the reason it is written the way it
is rather than the shorter way:

    **A verdict may never be inferred from an absence.**

The first question anyone asks of an exposure report is "what did you not check,
and why". A tool that silently turns "I could not tell" into "not exposed"
cannot answer it — and it fails in the flattering direction, so the estate reads
cleaner than it is and nobody goes looking. Everything below follows from
refusing that.

Hence four verdicts rather than two:

    exposed          a rule ran fully and its conditions held
    not_exposed      a rule ran fully and its conditions did not hold
    undetermined     a rule could not run — a required field was absent
    not_applicable   no rule covers this resource type at all

`undetermined` and `not_applicable` are the two a smaller build leaves out, and
they are the two that make the number defensible. `not_applicable` is not a
failure: the catalog holds 4,647 types and the rule set covers some of them,
which is a fact worth stating rather than hiding in a denominator.

**Optionality is declared, never guessed.** An ENI with no public association
genuinely has no `Association` object, so absence there IS the answer. A missing
`public_ip_address` on an instance means the collector did not tell us, so it
is not. Nothing in the payload distinguishes those two cases — only the rule
author knows — so the rule says which, and a field that says nothing is treated
as required. Guessing wrong in the permissive direction is exactly the failure
this module is built to prevent.
"""
import ipaddress

from .fields import resolve

EXPOSED = "exposed"
NOT_EXPOSED = "not_exposed"
UNDETERMINED = "undetermined"
NOT_APPLICABLE = "not_applicable"

VERDICTS = (EXPOSED, NOT_EXPOSED, UNDETERMINED, NOT_APPLICABLE)

#: What an absent optional field is allowed to mean. A rule may not declare that
#: an absence proves EXPOSURE — that would let a collection gap manufacture a
#: finding, which is the same defect as the permissive case, inverted.
ABSENT_MEANINGS = (NOT_EXPOSED, UNDETERMINED)


class Field:
    """One field a rule needs, and what its absence means."""

    __slots__ = ("name", "optional", "absent_means")

    def __init__(self, name, optional=False, absent_means=UNDETERMINED):
        self.name = name
        self.optional = bool(optional)
        self.absent_means = absent_means

    def __repr__(self):
        return f"<Field {self.name} optional={self.optional}>"


def parse_fields(declared):
    """
    A rule's `required_emitted_fields`, in either spelling.

    The ported catalog writes them as bare strings; ours may write a mapping
    that declares optionality. Both are accepted so a port stays a port — but a
    bare string means REQUIRED, because the safe default is the one that
    refuses to clear a resource it could not check.
    """
    out = []
    for item in declared or []:
        if isinstance(item, str):
            out.append(Field(item))
            continue
        if not isinstance(item, dict) or not item.get("name"):
            raise ValueError(f"unreadable field declaration: {item!r}")
        means = item.get("absent_means", UNDETERMINED)
        if means not in ABSENT_MEANINGS:
            raise ValueError(
                f"{item['name']}: absent_means={means!r} is not one of "
                f"{ABSENT_MEANINGS}. An absence may not prove exposure."
            )
        out.append(Field(item["name"], item.get("optional", False), means))
    return out


# ── operators ─────────────────────────────────────────────────────────

def _contains_cidr_any(value, wanted):
    """
    Whether any rule in an SG permission set opens one of `wanted`.

    Walks the shape AWS actually returns — `IpPermissions[].IpRanges[].CidrIp`
    and its v6 twin — rather than a flattened string, because `"0.0.0.0/0" in
    str(value)` would match a CIDR that merely mentions it in a description.
    """
    targets = set(wanted or [])
    for perm in value if isinstance(value, list) else [value]:
        if not isinstance(perm, dict):
            if str(perm) in targets:
                return True
            continue
        for key in ("IpRanges", "Ipv6Ranges"):
            for entry in perm.get(key) or []:
                cidr = (entry or {}).get("CidrIp") or (entry or {}).get("CidrIpv6")
                if cidr in targets:
                    return True
                # An explicit /0 is the common case, but a rule opening a
                # supernet of it is the same exposure wearing a different mask.
                if cidr:
                    try:
                        net = ipaddress.ip_network(cidr, strict=False)
                        if net.prefixlen == 0:
                            return True
                    except ValueError:
                        pass
    return False


def _contains(value, wanted):
    if isinstance(value, (list, tuple, set)):
        return wanted in value or any(wanted == str(v) for v in value)
    if isinstance(value, dict):
        return wanted in value
    return wanted is not None and str(wanted) in str(value or "")


OPERATORS = {
    "not_null": lambda v, w: v is not None and v != "" and v != [],
    "eq": lambda v, w: v == w,
    "contains": _contains,
    "contains_cidr_any": _contains_cidr_any,
}


class Result:
    """
    One verdict, with everything needed to defend it later.

    `fields_read` is the point. A verdict that says "exposed" and cannot say
    which values made it so is an assertion, not evidence — and the first thing
    anyone disputing a finding asks for is the value we read.
    """

    __slots__ = ("verdict", "rule_id", "reason", "fields_read", "origin_type", "severity")

    def __init__(self, verdict, rule_id=None, reason="", fields_read=None,
                 origin_type=None, severity=None):
        self.verdict = verdict
        self.rule_id = rule_id
        self.reason = reason
        self.fields_read = fields_read or {}
        self.origin_type = origin_type
        self.severity = severity

    def as_dict(self):
        return {"verdict": self.verdict, "rule_id": self.rule_id,
                "reason": self.reason, "fields_read": self.fields_read,
                "origin_type": self.origin_type, "severity": self.severity}

    def __repr__(self):
        return f"<{self.verdict} {self.rule_id or '-'} {self.reason}>"


def evaluate_rule(rule, payload):
    """
    One rule against one resource's payload.

    Tier 1 is structural: the type alone decides, so a payload is not consulted
    and cannot make it undetermined. Tier 2 resolves its fields first and only
    then tests conditions — the order matters, because a condition evaluated
    against a field we never read would silently compare against `None` and
    return a confident `not_exposed`.

    Tier 3 is not evaluated here. It walks the graph, needs edges this function
    is not given, and lives in the traversal evaluator.
    """
    tier = rule.get("tier")
    common = {"rule_id": rule.get("rule_id"),
              "origin_type": rule.get("origin_type"),
              "severity": rule.get("severity")}

    if tier == 1:
        return Result(EXPOSED, reason="public by construction — no condition to test",
                      **common)

    if tier == 3:
        return Result(UNDETERMINED,
                      reason="tier 3 requires graph traversal; not evaluated here",
                      **common)

    fields = parse_fields(rule.get("required_emitted_fields"))
    read = {}
    for field in fields:
        found, value = resolve(payload, field.name)
        if found:
            read[field.name] = value
            continue
        if not field.optional:
            # The whole point. Not cleared, not flagged — not known.
            return Result(UNDETERMINED, reason=f"required field {field.name!r} absent",
                          fields_read=read, **common)
        if field.absent_means == NOT_EXPOSED:
            return Result(NOT_EXPOSED,
                          reason=f"optional field {field.name!r} absent, declared as not exposed",
                          fields_read=read, **common)
        return Result(UNDETERMINED,
                      reason=f"optional field {field.name!r} absent, declared as undetermined",
                      fields_read=read, **common)

    conditions = rule.get("exposure_conditions") or []
    if not conditions:
        return Result(UNDETERMINED,
                      reason="tier 2 rule declares no exposure_conditions",
                      fields_read=read, **common)

    for cond in conditions:
        name = cond.get("field")
        op = OPERATORS.get(cond.get("operator"))
        if op is None:
            # An unknown operator is a catalog error. Treating it as false would
            # clear the resource on the strength of a rule that never ran.
            return Result(UNDETERMINED,
                          reason=f"unknown operator {cond.get('operator')!r}",
                          fields_read=read, **common)
        found, value = resolve(payload, name)
        if not found:
            return Result(UNDETERMINED, reason=f"condition field {name!r} absent",
                          fields_read=read, **common)
        read[name] = value
        if not op(value, cond.get("value")):
            return Result(NOT_EXPOSED,
                          reason=f"{name} did not satisfy {cond.get('operator')}",
                          fields_read=read, **common)

    return Result(EXPOSED,
                  reason="; ".join(f"{c.get('field')} {c.get('operator')}" for c in conditions),
                  fields_read=read, **common)


def evaluate_asset(asset, rules):
    """
    Every applicable rule against one asset, reduced to one verdict.

    Precedence is deliberate and is not "first match wins":

      exposed > undetermined > not_exposed > not_applicable

    `undetermined` outranks `not_exposed` because one rule failing to run is not
    cancelled by another rule succeeding — the resource still has an unchecked
    way in, and collapsing to the cleaner answer is the failure this module is
    built to prevent. `exposed` outranks everything because a proven path is a
    proven path however many rules found nothing.
    """
    kind = asset.get("resource_key") or asset.get("resource_type") or ""
    payload = asset.get("raw") or {}
    applicable = [r for r in rules if r.get("resource_type") == kind and r.get("tier") != 3]
    if not applicable:
        return Result(NOT_APPLICABLE, reason=f"no rule covers {kind or 'this type'}")

    results = [evaluate_rule(r, payload) for r in applicable]
    for verdict in (EXPOSED, UNDETERMINED, NOT_EXPOSED):
        for r in results:
            if r.verdict == verdict:
                return r
    return results[0]


class DuplicateAsset(ValueError):
    """Two resources claiming one identity. A data defect, never a merge."""


def evaluate_all(assets, rules):
    """
    Verdicts for a whole estate, keyed by asset id, in input order.

    **Raises on a duplicate key rather than overwriting.** Keying by id and
    assigning meant two resources sharing an `asset_id` silently became one, and
    the loser vanished from the coverage report — a resource that was never
    evaluated, never counted in any denominator, and left no trace of having
    existed. That is the flattering failure this module exists to prevent,
    arriving through the door rather than the window: the estate looks smaller
    and cleaner, and the total looks authoritative because it is a total.

    A collision is a defect in the inventory, so it surfaces as one. An asset
    with no identity at all is the same problem a step earlier.
    """
    out = {}
    for asset in assets:
        key = asset.get("asset_id") or asset.get("arn") or asset.get("id")
        if not key:
            raise DuplicateAsset(
                f"asset has no asset_id, arn or id: {str(asset)[:120]}"
            )
        if key in out:
            raise DuplicateAsset(
                f"two resources share the identity {key!r}. Verdicts are keyed "
                "by it, so one would be dropped from every denominator without "
                "appearing anywhere as missing."
            )
        out[key] = evaluate_asset(asset, rules)
    return out


def coverage(results):
    """
    The denominators, so a headline number is never reported alone.

    "N exposed" on its own is the same defect as a list that stops at 250 rows
    without saying so. What an enterprise report has to state is N exposed of M
    evaluated, with K unknown and J uncovered, out of T.
    """
    counts = {v: 0 for v in VERDICTS}
    for r in results.values() if isinstance(results, dict) else results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    total = sum(counts.values())
    evaluated = counts[EXPOSED] + counts[NOT_EXPOSED]
    return {
        **counts,
        "total": total,
        "evaluated": evaluated,
        # What fraction of the estate we can actually speak to. The number an
        # auditor asks for, and the one a tool that hides `undetermined` cannot
        # produce at all.
        "coverage_pct": round(100.0 * evaluated / total, 1) if total else 0.0,
    }


def firing_rates(assets, rules):
    """
    How often each rule fires, as a fraction of the type it covers.

    Exists because of a defect that reached the live estate: three ported
    tier-1 rules carried their condition in the TITLE and tested nothing —
    "S3 bucket static website hosting endpoint is publicly accessible" was
    tier 1 on `s3_bucket`, so it fired on all 55 buckets and produced 55 high
    findings, every one of them false.

    A rule at 100% is not necessarily wrong — a genuinely always-public type
    should fire on all of them, which is what tier 1 means. But 100% is where
    "public by construction" and "I forgot to write the condition" look
    identical, so the pair must be told apart deliberately rather than
    discovered by a customer.

    Reported per rule as (fired, population), so the gate can assert on the
    ratio and a human can read the two numbers.
    """
    pop = {}
    fired = {}
    for rule in rules:
        if rule.get("tier") == 3:
            continue
        rid = rule["rule_id"]
        kind = rule.get("resource_type")
        pool = [a for a in assets
                if (a.get("resource_key") or a.get("resource_type")) == kind]
        pop[rid] = len(pool)
        fired[rid] = sum(
            1 for a in pool
            if evaluate_rule(rule, a.get("raw") or {}).verdict == EXPOSED
        )
    return {rid: (fired[rid], pop[rid]) for rid in pop}


def suspicious_rules(assets, rules, floor=3):
    """
    Rules that fire on 100% of a population big enough for that to mean
    something, and are NOT declared tier 1.

    `floor` exists so a type with one instance does not look like a systemic
    false positive. Tier 1 is exempt by definition — it is the declaration that
    a type is always public, and a tier 1 rule at 100% is the rule working.
    """
    by_id = {r["rule_id"]: r for r in rules}
    out = []
    for rid, (fired, pop) in firing_rates(assets, rules).items():
        if pop >= floor and fired == pop and by_id[rid].get("tier") != 1:
            out.append((rid, fired, pop))
    return sorted(out)
