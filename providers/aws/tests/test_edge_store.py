"""
The edge row a validator produces vs the row the table accepts.

`out/edges.csv` is CSV, so every value arrives as a string — `resolved` is
`"true"`, `corroborations` is `"4"`. Writing those straight into a BOOLEAN and
an INTEGER column is the kind of thing that works in files mode and fails only
once someone points a real database at it.
"""
from unittest import mock

from store import edges as store_edges


def edge(**over):
    row = {"source_asset_id": "arn:a", "target_asset_id": "arn:b",
           "edge_type": "protected-by", "resolved": "true",
           "corroborations": "4", "via": "SecurityGroups[].GroupId"}
    row.update(over)
    return row


def test_csv_strings_are_coerced_to_column_types():
    row = store_edges._row(edge(), "local", "run-1", "2026-08-15")

    assert row["resolved"] is True
    assert row["corroborations"] == 4


def test_the_string_false_is_false_not_truthy():
    """`bool("false")` is True, which would mark every dangling edge resolved."""
    row = store_edges._row(edge(resolved="false"), "local", "run-1", "2026-08-15")

    assert row["resolved"] is False


def test_a_missing_resolved_defaults_to_true():
    row = store_edges._row(edge(resolved=None), "local", "run-1", "2026-08-15")

    assert row["resolved"] is True


def test_corroborations_defaults_to_one():
    row = store_edges._row(edge(corroborations=""), "local", "run-1", "2026-08-15")

    assert row["corroborations"] == 1


def test_empty_strings_become_null_not_empty_text():
    row = store_edges._row(edge(via="", mechanism=""), "local", "run-1", "2026-08-15")

    assert row["via"] is None
    assert row["mechanism"] is None


def test_a_non_dict_attributes_never_reaches_a_jsonb_column():
    # edges.csv carries attributes as a JSON *string*; unparsed it would be
    # written as text into JSONB and rejected.
    row = store_edges._row(edge(attributes='{"a": 1}'), "local", "run-1", "2026-08-15")

    assert row["attributes"] == {}


def test_only_declared_columns_are_written():
    """
    A validator edge carries verdict fields that belong to the CATALOG. Writing
    them here would duplicate the rule's own record and let the two disagree.
    """
    row = store_edges._row(edge(verdict="confirmed", prefix_ok=True),
                           "local", "run-1", "2026-08-15")

    assert set(row) == set(store_edges._COLUMNS)


class _Backend:
    NAME = "postgres"

    def __init__(self):
        self.written = None

    def upsert(self, table, rows, keys, update_cols):
        self.written = (table, rows, keys, update_cols)
        return len(rows)


def _with_backend(backend):
    return mock.patch.multiple(store_edges,
                               get_backend=lambda: backend,
                               is_postgres=lambda: True)


def test_the_same_edge_twice_is_upserted_once():
    """
    Postgres cannot touch one row twice in a single ON CONFLICT, so a batch
    carrying the same edge from two relation rules would abort the write.
    """
    backend = _Backend()
    with _with_backend(backend):
        written = store_edges.upsert_edges(
            [edge(via="GroupId"), edge(via="GroupName")],
            "run-1", "2026-08-15")

    assert written == 1
    assert len(backend.written[1]) == 1


def test_one_pair_related_two_ways_is_two_edges():
    """Identity is (source, target, TYPE) — collapsing on the pair loses one."""
    backend = _Backend()
    with _with_backend(backend):
        store_edges.upsert_edges(
            [edge(edge_type="attached-to"), edge(edge_type="protected-by")],
            "run-1", "2026-08-15")

    assert len(backend.written[1]) == 2


def test_an_edge_with_a_missing_end_is_dropped():
    backend = _Backend()
    with _with_backend(backend):
        written = store_edges.upsert_edges(
            [edge(target_asset_id=""), edge()], "run-1", "2026-08-15")

    assert written == 1


def test_files_mode_writes_nothing():
    """out/edges.csv already IS the artifact there."""
    with mock.patch.multiple(store_edges, is_postgres=lambda: False):
        assert store_edges.upsert_edges([edge()], "run-1", "2026-08-15") == 0
