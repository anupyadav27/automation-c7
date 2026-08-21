# Relationship mechanisms

Three ways a relationship between two AWS resources can be discovered. They are
genuinely different — different data, different resolver code, different failure
modes — so each has its own catalog and its own name. The `A/B/C` prefixes are
kept only for ordering and cross-reference.

| id | name | the target is found as | catalog |
|----|------|------------------------|---------|
| **A** | `field-pointer` | an id or ARN sitting in a response field | `relations_full.csv` |
| **B** | `policy-document` | an ARN inside an embedded JSON policy | `policy_sources.csv` |
| **C** | `value-match` | no id anywhere — equal or derived values | `value_joins.csv` |

---

## A · field-pointer

The target's identifier is a value in the source's response.

```
ec2.instance   NetworkInterfaces[].Groups[].GroupId  →  ec2.security_group
rds.db_instance  DBSubnetGroup.VpcId                 →  ec2.vpc
```

**Resolver:** walk the path (`resolver.resolve_path`), look the value up in the
triple index by id, ARN or name.

**Fails when** the field exists but the miner could not tell what it points at.
`Routes[].GatewayId` is documented only as "The ID of a gateway attached to your
VPC", which names no resource type — so it needs a hand rule. A hand rule is
still mechanism A: the value *is* an ordinary id, only the mining failed.

**Status:** 2,774 relations, 1,658 high confidence.

---

## B · policy-document

The target is an ARN inside a JSON document stored in a field. Field-pointer
mining is structurally blind to these, because the ARN is a substring of a
serialised policy rather than a member of any shape.

```
iam.role  AssumeRolePolicyDocument  →  Statement[].Principal   →  who may assume
iam.role  PolicyDocument            →  Statement[].Resource    →  what it reaches
s3.bucket Policy                    →  Statement[].Principal   →  who may read
```

**Resolver:** URL-decode where required, parse, walk `Statement[]`, extract ARNs
from `Resource`, `Principal` and `Condition`, then type each via `arn.parse`.

**Distinct hazards:** documents are URL-encoded by IAM only; `Statement` may be a
bare dict or a list; `Principal` has four different shapes; wildcard ARNs name a
*set*, not a resource, and must be kept and flagged rather than resolved or
dropped.

**Status:** 73 sources across 42 services; parser built and tested.

---

## C · value-match

Neither end carries the other's identifier. The join is on a value that happens
to be equal, or that must be parsed before it matches.

```
ec2.vpc_endpoint  ServiceName  = "com.amazonaws.ap-southeast-1.s3"  →  the S3 service
route53 record    AliasTarget.DNSName  ==  elbv2.load_balancer.DNSName
cloudfront        Origins[].DomainName  ⊃  s3.bucket.Name
ec2.security_group  IpRanges[].CidrIp   ⊇  ec2.subnet.CidrBlock
```

**Resolver:** per-rule, because the match differs — string equality, substring
extraction, CIDR containment, or a structured-name parse.

**Why it cannot be folded into A:** `com.amazonaws.ap-southeast-1.s3` is not the
identifier of any resource. No amount of better documentation would make a
field-pointer resolver find it; the value has to be interpreted first.

**Status:** 11 rules defined, resolver not built.

---

## Choosing between them

Ask what the value *is*:

- an id or ARN of the target → **A**
- an ARN inside a JSON document → **B**
- anything else that identifies the target indirectly → **C**

The three are complementary, not ranked. A estate's structure comes from A, its
permissions from B, and its traffic paths from C — and the connection scenarios
in `topology_scenarios.yaml` need all three at once.
