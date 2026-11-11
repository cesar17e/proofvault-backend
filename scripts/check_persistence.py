"""Verify ProofVault's database rules using temporary records."""

import argparse
import hashlib
from uuid import UUID, uuid4

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import auth_users
from app.db.session import SessionLocal, engine
from app.models import Course, Entry, EntryEmbedding


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"FAIL: {message}")

    print(f"PASS: {message}")


def expect_rejection(
    session: Session,
    statement,
    *,
    constraint: str,
    message: str,
) -> None:
    try:
        with session.begin_nested():
            session.execute(statement)
            session.flush()

    except IntegrityError as exc:
        actual_constraint = getattr(
            getattr(exc.orig, "diag", None),
            "constraint_name",
            None,
        )

        if actual_constraint != constraint:
            raise RuntimeError(
                f"Unexpected constraint failure: {actual_constraint}"
            ) from None

        print(f"PASS: {message}")

    else:
        raise RuntimeError(f"FAIL: {message}")


def main(user_a: UUID, user_b: UUID) -> None:
    check(user_a != user_b, "Two different user IDs supplied")

    course_id = uuid4()
    entry_id = uuid4()
    loose_entry_id = uuid4()

    statement = "Every convergent sequence of real numbers is bounded."
    content_hash = hashlib.sha256(
        statement.encode("utf-8")
    ).hexdigest()

    # Artificial test vector: no Voyage request is made.
    vector = [1.0] + [0.0] * 1023

    with SessionLocal() as session:
        try:
            existing_users = set(
                session.execute(
                    select(auth_users.c.id).where(
                        auth_users.c.id.in_([user_a, user_b])
                    )
                ).scalars()
            )

            check(
                existing_users == {user_a, user_b},
                "Both development accounts exist",
            )

            course = Course(
                id=course_id,
                owner_id=user_a,
                name="Temporary persistence check",
            )
            session.add(course)
            session.flush()

            entry = Entry(
                id=entry_id,
                owner_id=user_a,
                course_id=course_id,
                title="Convergent sequences are bounded",
                kind="theorem",
                statement=statement,
                proof="Temporary proof text.",
            )

            loose_entry = Entry(
                id=loose_entry_id,
                owner_id=user_a,
                title="Uncategorized problem",
                kind="problem",
                statement="Prove that a Cauchy sequence is bounded.",
            )

            session.add_all([entry, loose_entry])
            session.flush()

            # Force subsequent reads to reload data from PostgreSQL.
            session.expire_all()

            saved_entry = session.get(Entry, entry_id)
            saved_loose_entry = session.get(Entry, loose_entry_id)

            check(
                session.get(Course, course_id).name
                == "Temporary persistence check"
                and saved_entry.statement == statement,
                "Course and entry can be inserted and retrieved",
            )

            check(
                saved_entry.index_status == "pending",
                "New entries default to pending",
            )

            check(
                saved_loose_entry.course_id is None
                and saved_loose_entry.proof is None,
                "Entries can have no course or proof",
            )

            expect_rejection(
                session,
                insert(Entry).values(
                    id=uuid4(),
                    owner_id=user_b,
                    course_id=course_id,
                    title="Wrong owner",
                    kind="problem",
                    statement="This entry references another user's course.",
                ),
                constraint="fk_entries_course_owner",
                message="Cross-owner course assignment is rejected",
            )

            expect_rejection(
                session,
                insert(Entry).values(
                    id=uuid4(),
                    owner_id=user_a,
                    title="Invalid kind",
                    kind="invalid",
                    statement="A nonempty statement.",
                ),
                constraint="ck_entries_kind",
                message="Invalid entry kinds are rejected",
            )

            expect_rejection(
                session,
                insert(Entry).values(
                    id=uuid4(),
                    owner_id=user_a,
                    title="Blank statement",
                    kind="problem",
                    statement="   ",
                ),
                constraint="ck_entries_statement_not_blank",
                message="Blank statements are rejected",
            )

            embedding_values = {
                "entry_id": entry_id,
                "embedding": vector,
                "provider": "synthetic-test",
                "model": "synthetic-1024",
                "content_hash": content_hash,
            }

            session.add(EntryEmbedding(**embedding_values))
            session.flush()

            saved_embedding = session.get(EntryEmbedding, entry_id)
            session.refresh(saved_embedding)

            check(
                len(saved_embedding.embedding) == 1024
                and saved_embedding.content_hash == content_hash,
                "A 1024-dimensional vector can be stored and retrieved",
            )

            # Read the actual primary-key name rather than assuming it.
            embedding_pk = session.execute(
                select(
                    # PostgreSQL's constraint metadata.
                    # The query below uses a bound table-name parameter.
                    # See text() statement further below.
                    EntryEmbedding.entry_id
                ).where(EntryEmbedding.entry_id == entry_id)
            ).scalar_one()

            check(
                embedding_pk == entry_id,
                "Embedding links to the correct entry",
            )

            # A nested transaction lets us continue after the expected error.
            try:
                with session.begin_nested():
                    session.execute(
                        insert(EntryEmbedding).values(**embedding_values)
                    )

            except IntegrityError as exc:
                if getattr(exc.orig, "sqlstate", None) != "23505":
                    raise RuntimeError(
                        "Duplicate embedding failed for an unexpected reason"
                    ) from None

                print("PASS: Duplicate embeddings are rejected")

            else:
                raise RuntimeError(
                    "FAIL: Duplicate embeddings were accepted"
                )

            session.delete(course)
            session.flush()
            session.expire_all()

            preserved_entry = session.get(Entry, entry_id)

            check(
                preserved_entry is not None
                and preserved_entry.course_id is None
                and preserved_entry.owner_id == user_a,
                "Deleting a course preserves its entries and ownership",
            )

            session.delete(preserved_entry)
            session.flush()
            session.expire_all()

            check(
                session.get(Entry, entry_id) is None
                and session.get(EntryEmbedding, entry_id) is None,
                "Deleting an entry also deletes its embedding",
            )

        finally:
            # Deliberately never commit this script's temporary records.
            session.rollback()

    with SessionLocal() as session:
        check(
            session.get(Course, course_id) is None
            and session.get(Entry, entry_id) is None
            and session.get(Entry, loose_entry_id) is None
            and session.get(EntryEmbedding, entry_id) is None,
            "Rollback leaves no temporary records",
        )

    print("\nAll persistence checks passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-a", type=UUID, required=True)
    parser.add_argument("--user-b", type=UUID, required=True)
    args = parser.parse_args()

    try:
        main(args.user_a, args.user_b)
    finally:
        engine.dispose()