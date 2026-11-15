import re

from app.models.entry import Entry
from app.models.entry_embedding import EntryEmbedding
from app.schemas.entry import EntryKind


def test_entry_kind_constraint_matches_public_entry_kind_enum() -> None:
    constraint = next(
        constraint
        for constraint in Entry.__table__.constraints
        if constraint.name == "ck_entries_kind"
    )
    database_kinds = set(re.findall(r"'([^']+)'", str(constraint.sqltext)))

    assert database_kinds == {kind.value for kind in EntryKind}


def test_deleting_course_unassigns_entry_without_changing_owner() -> None:
    constraint = next(
        constraint
        for constraint in Entry.__table__.foreign_key_constraints
        if constraint.name == "fk_entries_course_owner"
    )

    assert constraint.column_keys == ["course_id", "owner_id"]
    assert [element.target_fullname for element in constraint.elements] == [
        "proofvault.courses.id",
        "proofvault.courses.owner_id",
    ]
    assert constraint.ondelete == "SET NULL (course_id)"


def test_deleting_entry_cascades_to_its_embedding() -> None:
    foreign_key = next(iter(EntryEmbedding.__table__.c.entry_id.foreign_keys))

    assert foreign_key.target_fullname == "proofvault.entries.id"
    assert foreign_key.ondelete == "CASCADE"
