# Deferred: connection paths

**Status: not started. Deliberately last.**

Once placement is correct and the identity / encryption / network connections are
verified, the remaining piece is **multi-hop connection paths** — composing single
edges into the routes a request or a permission actually takes.

Examples of what has to come out at the end:

```
tgw → load balancer → ec2 → eni → vpc interface endpoint → s3
ec2 → igw → s3                                   (over the internet)
ec2 → nat gateway → igw → internet               (egress only)
lambda(vpc) → eni → vpc endpoint → dynamodb      (stays private)
```

## Why it is last

A path is only as trustworthy as the edges it composes. Building path traversal
before placement and the identity/encryption/network edges are verified would
produce confident-looking routes assembled from unverified hops — the worst
possible failure mode, because a wrong path reads as authoritative.

The order is therefore:

1. placement architecture correct — regional vs global vs in-VPC     ← in progress
2. IAM, KMS and network connections verified against live data
3. **then** connection paths, so the UI only ever offers routes whose
   every hop is confirmed

## What it will need that does not exist yet

- **Edge attributes.** A hop is conditional. `route_table → nat_gateway` means
  nothing without `Routes[].DestinationCidrBlock` — a route to `0.0.0.0/0` is an
  internet path, a route to `10.0.0.0/8` is not. Same for security-group rules
  (port, protocol, CIDR) and load-balancer listeners. Until edges carry their
  qualifying siblings, no path can be judged reachable.
- **`Routes[].GatewayId`** — the default-route pointer, currently unresolved
  because its docstring is only "The ID of a gateway attached to your VPC".
- **`vpc_endpoint.ServiceName`** (mechanism C, `value-match`) — `com.amazonaws.<region>.s3` naming
  the service the endpoint fronts. Without it the private path to S3 has a hole
  exactly where it matters.
- **A path grammar.** Named, reusable templates (`internet-egress`,
  `private-service-access`) expressed as ordered hop patterns with conditions,
  kept in the catalog like everything else rather than hardcoded.

## The rule to hold to

Only surface a path in the UI when **every hop is a confirmed edge**. A path
containing one `partial` or `absent` hop is a hypothesis, and must be labelled as
one rather than drawn like the rest.
