"""
Reading a rule's field out of an AWS payload.

The rules name fields the way threat-engine's inventory does — `dns_name`,
`block_public_acls`, `public_ip_address`. AWS returns them the way the API does
— `DNSName`, `PublicAccessBlockConfiguration.BlockPublicAcls`,
`PublicIpAddress`. Neither side is wrong and nothing reconciles them, so a
flat key lookup finds about half.

That half matters more than it sounds. On this estate a naive lookup reported
`block_public_acls` as missing across **55 buckets** — which the evaluator would
have recorded as "no rule could run", and a reader would have read as "no public
buckets". The field was there the whole time, one level down.

Two mismatches, both mechanical once seen:

- **Acronyms.** `DNSName` is `dns_name`, not `d_n_s_name`. A naive
  `(?<!^)(?=[A-Z])` split treats every capital as a word boundary and shatters
  every initialism AWS uses — DNS, IP, VPC, ARN, ACL, KMS.
- **Nesting.** `block_public_acls` lives inside
  `PublicAccessBlockConfiguration`. AWS groups related settings into a
  sub-object whenever they came from a separate API call, so the flat name a
  rule uses is a leaf several levels down.

Resolution is therefore a SEARCH, not a lookup — and it stops at the first
match by breadth, so a shallow field always beats a deeply nested one with the
same name.
"""
import re

#: Initialisms AWS uses in payload keys. Longest first, so `IPv6` is matched
#: before `IP` and does not become `i_pv6`.
_ACRONYMS = ("HTTPS", "HTTP", "IPv6", "IPv4", "DNS", "ACL", "ARN", "VPC", "KMS",
             "SSL", "TLS", "URL", "URI", "API", "AZ", "ID", "IP", "SSE", "MFA",
             "CIDR", "EBS", "EC2", "S3", "IAM", "SNS", "SQS", "RDS", "ELB")

_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")

#: How deep to search a payload for a named leaf. Three covers every nesting
#: AWS actually uses for a flag; deeper would start matching coincidences.
MAX_DEPTH = 3


def snake(key: str) -> str:
    """
    An AWS payload key as the rules spell it.

    `DNSName` -> `dns_name`. `PublicIpAddress` -> `public_ip_address`.
    `MapPublicIpOnLaunch` -> `map_public_ip_on_launch`.

    Acronyms are masked before the boundary split and restored after, because
    the split is the thing that breaks them: without masking, every initialism
    in the AWS API becomes one underscore-separated letter per character.
    """
    if not key:
        return ""
    masked = key
    holds = {}
    for i, acro in enumerate(_ACRONYMS):
        if acro in masked:
            token = f"Q{i}z"
            holds[token] = acro.lower()
            masked = masked.replace(acro, token)
    out = _BOUNDARY.sub("_", masked).lower()
    for token, acro in holds.items():
        out = out.replace(token.lower(), acro)
    return re.sub(r"_+", "_", out).strip("_")


def resolve(payload, field, max_depth=MAX_DEPTH):
    """
    The value of `field` in `payload`, wherever it actually lives.

    Breadth-first, so a top-level `status` is never shadowed by a
    `SomeConfig.Status` several levels down. Returns `(found, value)` rather
    than a bare value, because `False`, `0` and `None` are all legitimate
    findings and a rule that cannot tell "absent" from "false" will clear a
    resource it should have flagged.
    """
    if not isinstance(payload, dict) or not field:
        return (False, None)
    wanted = field.lower()
    frontier = [payload]
    depth = 0
    while frontier and depth <= max_depth:
        nxt = []
        for node in frontier:
            if not isinstance(node, dict):
                continue
            for key, value in node.items():
                if snake(key) == wanted or key.lower() == wanted:
                    return (True, value)
            for value in node.values():
                if isinstance(value, dict):
                    nxt.append(value)
                elif isinstance(value, list):
                    nxt.extend(v for v in value if isinstance(v, dict))
        frontier = nxt
        depth += 1
    return (False, None)


def resolvable(payload, fields, max_depth=MAX_DEPTH):
    """Which of `fields` this payload cannot supply. Empty means all of them."""
    return [f for f in fields if not resolve(payload, f, max_depth)[0]]
