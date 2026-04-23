"""Add project graph rag tables

Revision ID: 9b3f4d2c1a6e
Revises: b7f3d9a12e44
Create Date: 2026-04-23 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b3f4d2c1a6e"
down_revision: Union[str, Sequence[str], None] = "b7f3d9a12e44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("docs_index_status", sa.String(), nullable=False, server_default="not_indexed"))
        batch_op.add_column(sa.Column("docs_index_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("docs_indexed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("docs_nodes_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("docs_relations_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("docs_communities_count", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "project_doc_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("node_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_doc_nodes_id"), "project_doc_nodes", ["id"], unique=False)
    op.create_index(op.f("ix_project_doc_nodes_project_id"), "project_doc_nodes", ["project_id"], unique=False)
    op.create_index(op.f("ix_project_doc_nodes_node_key"), "project_doc_nodes", ["node_key"], unique=False)

    op.create_table(
        "project_doc_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_node_key", sa.String(), nullable=False),
        sa.Column("target_node_key", sa.String(), nullable=False),
        sa.Column("relation", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_doc_relations_id"), "project_doc_relations", ["id"], unique=False)
    op.create_index(op.f("ix_project_doc_relations_project_id"), "project_doc_relations", ["project_id"], unique=False)
    op.create_index(op.f("ix_project_doc_relations_source_node_key"), "project_doc_relations", ["source_node_key"], unique=False)
    op.create_index(op.f("ix_project_doc_relations_target_node_key"), "project_doc_relations", ["target_node_key"], unique=False)

    op.create_table(
        "project_doc_communities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("community_key", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_doc_communities_id"), "project_doc_communities", ["id"], unique=False)
    op.create_index(op.f("ix_project_doc_communities_project_id"), "project_doc_communities", ["project_id"], unique=False)
    op.create_index(op.f("ix_project_doc_communities_community_key"), "project_doc_communities", ["community_key"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_project_doc_communities_community_key"), table_name="project_doc_communities")
    op.drop_index(op.f("ix_project_doc_communities_project_id"), table_name="project_doc_communities")
    op.drop_index(op.f("ix_project_doc_communities_id"), table_name="project_doc_communities")
    op.drop_table("project_doc_communities")

    op.drop_index(op.f("ix_project_doc_relations_target_node_key"), table_name="project_doc_relations")
    op.drop_index(op.f("ix_project_doc_relations_source_node_key"), table_name="project_doc_relations")
    op.drop_index(op.f("ix_project_doc_relations_project_id"), table_name="project_doc_relations")
    op.drop_index(op.f("ix_project_doc_relations_id"), table_name="project_doc_relations")
    op.drop_table("project_doc_relations")

    op.drop_index(op.f("ix_project_doc_nodes_node_key"), table_name="project_doc_nodes")
    op.drop_index(op.f("ix_project_doc_nodes_project_id"), table_name="project_doc_nodes")
    op.drop_index(op.f("ix_project_doc_nodes_id"), table_name="project_doc_nodes")
    op.drop_table("project_doc_nodes")

    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("docs_communities_count")
        batch_op.drop_column("docs_relations_count")
        batch_op.drop_column("docs_nodes_count")
        batch_op.drop_column("docs_indexed_at")
        batch_op.drop_column("docs_index_error")
        batch_op.drop_column("docs_index_status")
