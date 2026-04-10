"""Unit tests for _schema.py constants."""

from __future__ import annotations

from theo._schema import (
    CSV_FILES,
    FIELD_MAP,
    NODE_TABLES,
    PK_MAP,
    REL_ENDPOINTS,
    REL_FK_FIELDS,
    REL_TABLES,
)


def test_csv_files_covers_all_tables() -> None:
    """All 7 tables (2 node + 5 rel) have a CSV file defined."""
    all_tables = NODE_TABLES + REL_TABLES
    assert len(CSV_FILES) == 7
    for table in all_tables:
        assert table in CSV_FILES


def test_pk_map_covers_all_node_tables() -> None:
    for table in NODE_TABLES:
        assert table in PK_MAP


def test_rel_endpoints_covers_all_rel_tables() -> None:
    for rel in REL_TABLES:
        assert rel in REL_ENDPOINTS
        from_t, to_t = REL_ENDPOINTS[rel]
        assert from_t in NODE_TABLES
        assert to_t in NODE_TABLES


def test_rel_fk_fields_covers_all_rel_tables() -> None:
    for rel in REL_TABLES:
        assert rel in REL_FK_FIELDS
        from_fk, to_fk = REL_FK_FIELDS[rel]
        assert isinstance(from_fk, str)
        assert isinstance(to_fk, str)


def test_no_duplicate_table_names() -> None:
    all_names = NODE_TABLES + REL_TABLES
    assert len(all_names) == len(set(all_names))


def test_field_map_covers_all_node_tables() -> None:
    for table in NODE_TABLES:
        assert table in FIELD_MAP
        assert PK_MAP[table] in FIELD_MAP[table]


def test_csv_filenames_are_unique() -> None:
    filenames = list(CSV_FILES.values())
    assert len(filenames) == len(set(filenames))
