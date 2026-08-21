# Vendored discovery specs

Copied from `threat-engine/catalog/discovery_generator_data/aws/*/step6_*.discovery.yaml`.

One file per AWS service. Each is an executable discovery plan:

    discovery:
      - discovery_id: aws.<service>.<operation>
        calls:      [{action, save_as, on_error}]
        for_each:   <discovery_id this one depends on>   # multi-hop
        emit:
          items_for: '{{ response.<Container> }}'
          item:      {Field: '{{ item.Field }}', ...}
        resource_type: <type>                            # present on ~3% only

Why vendored rather than re-derived from botocore: these already encode the
multi-hop parameter chains, the alias resolution (`analyzerArn` -> `arn` from
`list_analyzers`), circular-dependency fixes, and the policy-document fetches
(`AssumeRolePolicyDocument`, `get_policy_version`) that mechanism B needs.

Refresh by re-running the copy loop; do not hand-edit.
