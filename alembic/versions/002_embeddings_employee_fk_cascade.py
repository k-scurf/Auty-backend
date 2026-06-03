"""embeddings_employee_fk_cascade

Ensure embeddings.employee_id FK has ON DELETE CASCADE so that deleting an
employee removes their embeddings at the database level.  Without this,
SQLAlchemy's db.delete(employee) raises NotNullViolation because the ORM tries
to NULL out employee_id on related rows before deleting the parent.

Revision ID: 002_embeddings_employee_fk_cascade
Revises: 001_initial
Create Date: 2026-06-02

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_embeddings_employee_fk_cascade"
down_revision: Union[str, Sequence[str], None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the existing FK (Postgres auto-name from the initial migration).
    # If the constraint was already created with CASCADE this is still safe —
    # drop + recreate is idempotent with respect to data.
    op.drop_constraint(
        "embeddings_employee_id_fkey",
        "embeddings",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "embeddings_employee_id_fkey",
        "embeddings",        # source table
        "employees",         # referent table
        ["employee_id"],     # local cols
        ["id"],              # remote cols
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Revert to a plain FK without CASCADE.
    op.drop_constraint(
        "embeddings_employee_id_fkey",
        "embeddings",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "embeddings_employee_id_fkey",
        "embeddings",
        "employees",
        ["employee_id"],
        ["id"],
    )
