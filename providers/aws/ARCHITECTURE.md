# `discovery/` — architecture decisions

## 1. Data-driven, not code-driven

Behaviour lives in the catalog, not in Python. Adding a resource type, a
relation, an ARN rule or a layer placement is a **row**, never a patch.

| behaviour | driven by | not by |
|---|---|---|
| which API calls to make, in what order | `catalog/specs/*.discovery.yaml` | hardcoded client calls |
| what relates to what, and via which field | `catalog/relationship_master.csv` | `if resource_type == 'ec2'` |
| how to build/parse an ARN | `catalog/arn_recipes.csv` | per-service branches |
| where a resource states its AZ | `catalog/location_paths.csv` | lookup dicts in code |
| which layer an edge builds | `layer` column of the master sheet | render-time conditionals |
| what confirms a relation | `condition_*` columns | assertions in the validator |

The runtime modules are interpreters over that data. `resolver.py` has one
`resolve_path()` covering all five path shapes rather than five code paths;
`arn.py` reads a recipe rather than knowing about S3; `layers.py` places a node
from its containment edges rather than from a type whitelist.

Test for whether something belongs in code: *would supporting one more AWS
service require editing it?* If yes, it belongs in the catalog.

## 2. Modular — one job per module

```
runtime/arn.py        build + parse ARNs                    (no I/O, no AWS)
runtime/index.py      address nodes by id / arn / name      (no I/O, no AWS)
runtime/resolver.py   walk paths, derive + discover edges   (no I/O, no AWS)
runtime/layers.py     containment tree + cascading filters  (no I/O, no AWS)
runtime/collector.py  execute discovery specs               (the ONLY AWS caller)
```

Everything except `collector.py` is pure: it takes dicts and returns dicts. That
is what lets the whole relation model be tested offline against fixtures, and it
keeps the boundary honest — if a module other than the collector needs
credentials, the layering has gone wrong.

`build/` scripts are offline generators. They run rarely, write to `catalog/`,
and are never imported by the runtime.

## 3. Coexistence with the c7n project — no merge yet

The existing c7n application (`handler.py`, `policies/`, `ui/`, `local-server.py`,
`mock-api.py`) is **untouched and stays that way**. `discovery/` is additive.

- Nothing in `handler.py` imports `discovery/`, and nothing in `discovery/`
  imports `handler.py`.
- The two share no runtime state. The only overlap is at *build* time:
  `extract_c7n_relations.py` and `build_relations.py` at the repo root still use
  the installed `c7n` package to generate catalog rows. That is a generator, not
  a dependency — once `relations.csv` is written, the runtime never needs c7n.
- Both can run against the same account simultaneously; c7n does policy
  evaluation, `discovery/` does inventory and topology.

Merge is a later decision, made once `discovery/` produces graphs worth wiring
into the UI. Candidate integration points when that day comes: a new body-key
branch in `lambda_handler`, a `/inventory` path in `local-server.py`, and a page
in `ui/src/`. None of that is being built now.

## 4. Provenance is carried, never flattened away

Every relation keeps `relation_source` (c7n / cfn / asff / doc / hand),
`confidence`, `corroborated_by` and `evidence`. Downstream code may filter on
confidence, but nothing is allowed to silently promote a guess. The 54
cross-source corroborated relations are trustworthy *because* the disagreement
between sources was preserved rather than resolved at build time.

Dangling edges are kept too. An edge whose target was not found is the signal
that a path is wrong or a type was not collected; discarding it would hide both.
