"""
One relationship per (source, target, edge_type).

An EC2 instance with three ENIs in one security group used to emit that
membership eight times — three from `NetworkInterfaces[].Groups[].GroupId`
(once per ENI), three more from the GroupName variant, and two from the
instance's own `SecurityGroups[]`. The panel drew the group eight times and the
edge count was 14% inflated across the estate.

Agreement between paths is evidence, not noise, so it is counted rather than
discarded.
"""
from providers.aws.validate.live import collapse_duplicates


def edge(src='i-1', tgt='sg-1', kind='protected-by', via='A',
         confidence='medium', resolved=True):
    return {'source_asset_id': src, 'target_asset_id': tgt, 'edge_type': kind,
            'via': via, 'confidence': confidence,
            'resolved': str(resolved).lower()}


def test_the_same_path_resolving_repeatedly_is_one_edge():
    """Three ENIs in one group is one membership, not three."""
    out = collapse_duplicates([edge(via='NetworkInterfaces[].Groups[].GroupId')] * 3)

    assert len(out) == 1
    assert out[0]['corroborations'] == 1


def test_different_paths_finding_the_same_target_are_one_edge():
    out = collapse_duplicates([
        edge(via='SecurityGroups[].GroupId'),
        edge(via='SecurityGroups[].GroupName'),
        edge(via='NetworkInterfaces[].Groups[].GroupId'),
    ])

    assert len(out) == 1
    assert out[0]['corroborations'] == 3
    assert out[0]['via'] == ('NetworkInterfaces[].Groups[].GroupId | '
                             'SecurityGroups[].GroupId | SecurityGroups[].GroupName')


def test_the_strongest_row_survives():
    """A high-confidence c7n path beats a medium-confidence doc one."""
    out = collapse_duplicates([
        edge(via='GroupName', confidence='medium'),
        edge(via='GroupId', confidence='high'),
    ])

    assert out[0]['confidence'] == 'high'


def test_resolved_beats_dangling_at_equal_confidence():
    out = collapse_duplicates([
        edge(via='A', resolved=False),
        edge(via='B', resolved=True),
    ])

    assert out[0]['resolved'] == 'true'


def test_different_edge_types_to_the_same_target_both_survive():
    """
    An instance can be attached-to an ENI and protected-by it in principle;
    collapsing on the pair alone would silently drop one relationship.
    """
    out = collapse_duplicates([
        edge(kind='attached-to'),
        edge(kind='protected-by'),
    ])

    assert {e['edge_type'] for e in out} == {'attached-to', 'protected-by'}


def test_different_targets_are_never_merged():
    out = collapse_duplicates([edge(tgt='sg-1'), edge(tgt='sg-2')])

    assert len(out) == 2


def test_input_order_is_preserved():
    """The edge file stays diffable across runs."""
    out = collapse_duplicates([edge(tgt='sg-2'), edge(tgt='sg-1'), edge(tgt='sg-2')])

    assert [e['target_asset_id'] for e in out] == ['sg-2', 'sg-1']


def test_an_edge_with_no_via_still_survives():
    """Policy-document edges carry their own via; value-matched ones may not."""
    out = collapse_duplicates([{'source_asset_id': 'a', 'target_asset_id': 'b',
                                'edge_type': 'accessible-by'}])

    assert len(out) == 1
    assert out[0]['corroborations'] == 0


def test_a_resource_is_not_related_to_itself():
    """
    Bucket policies emitted the holder's ARN as source and the bucket's bare
    NAME as target — 20 edges saying "accessible by itself", which made every
    S3 bucket in the estate look like it connected to nothing.
    """
    out = collapse_duplicates([
        edge(src='arn:aws:s3:::my-bucket', tgt='my-bucket', kind='accessible-by'),
        edge(src='arn:aws:s3:::my-bucket', tgt='arn:aws:kms:::key/1', kind='encrypted-by'),
    ])

    assert [e['target_asset_id'] for e in out] == ['arn:aws:kms:::key/1']


def test_an_identical_source_and_target_is_dropped():
    out = collapse_duplicates([edge(src='arn:a', tgt='arn:a')])

    assert out == []
