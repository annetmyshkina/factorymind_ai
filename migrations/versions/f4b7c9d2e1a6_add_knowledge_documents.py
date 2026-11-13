"""add knowledge documents

Revision ID: f4b7c9d2e1a6
Revises: c8f3a2d1e6b7
Create Date: 2026-11-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "f4b7c9d2e1a6"
down_revision: str | Sequence[str] | None = "c8f3a2d1e6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create document catalogue, immutable versions and applicability."""
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "language",
            sa.String(length=10),
            server_default="ru",
            nullable=False,
        ),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "document_type IN ("
            "'operation_manual', 'maintenance_instruction', "
            "'repair_instruction', 'process_regulation', "
            "'safety_instruction', 'other')",
            name="ck_knowledge_documents_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_documents_created_at",
        "knowledge_documents",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_documents_document_type",
        "knowledge_documents",
        ["document_type"],
        unique=False,
    )

    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="uploaded",
            nullable=False,
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed')",
            name="ck_knowledge_document_versions_status",
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 10485760",
            name="ck_knowledge_document_versions_size",
        ),
        sa.CheckConstraint(
            "length(checksum_sha256) = 64",
            name="ck_knowledge_document_versions_checksum",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "checksum_sha256",
            name="uq_knowledge_document_versions_document_checksum",
        ),
        sa.UniqueConstraint(
            "document_id",
            "version",
            name="uq_knowledge_document_versions_document_version",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_document_versions_document_id"),
        "knowledge_document_versions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_document_versions_created_at",
        "knowledge_document_versions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_document_versions_status",
        "knowledge_document_versions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_knowledge_document_versions_current",
        "knowledge_document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current = 1"),
    )

    op.create_table(
        "knowledge_document_applicability",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.Integer(), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=True),
        sa.Column("equipment_type", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(equipment_id IS NOT NULL AND equipment_type IS NULL) "
            "OR (equipment_id IS NULL AND equipment_type IS NOT NULL)",
            name="ck_knowledge_document_applicability_target",
        ),
        sa.CheckConstraint(
            "equipment_type IS NULL OR length(trim(equipment_type)) > 0",
            name="ck_knowledge_document_applicability_equipment_type",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["knowledge_document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "equipment_id",
            name="uq_knowledge_document_applicability_equipment",
        ),
        sa.UniqueConstraint(
            "document_version_id",
            "equipment_type",
            name="uq_knowledge_document_applicability_type",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_document_applicability_document_version_id"),
        "knowledge_document_applicability",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_document_applicability_equipment_id"),
        "knowledge_document_applicability",
        ["equipment_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_document_applicability_type",
        "knowledge_document_applicability",
        ["equipment_type"],
        unique=False,
    )


def downgrade() -> None:
    """Drop knowledge-base document tables."""
    op.drop_index(
        "ix_knowledge_document_applicability_type",
        table_name="knowledge_document_applicability",
    )
    op.drop_index(
        op.f("ix_knowledge_document_applicability_equipment_id"),
        table_name="knowledge_document_applicability",
    )
    op.drop_index(
        op.f("ix_knowledge_document_applicability_document_version_id"),
        table_name="knowledge_document_applicability",
    )
    op.drop_table("knowledge_document_applicability")
    op.drop_index(
        "uq_knowledge_document_versions_current",
        table_name="knowledge_document_versions",
    )
    op.drop_index(
        "ix_knowledge_document_versions_status",
        table_name="knowledge_document_versions",
    )
    op.drop_index(
        "ix_knowledge_document_versions_created_at",
        table_name="knowledge_document_versions",
    )
    op.drop_index(
        op.f("ix_knowledge_document_versions_document_id"),
        table_name="knowledge_document_versions",
    )
    op.drop_table("knowledge_document_versions")
    op.drop_index(
        "ix_knowledge_documents_document_type",
        table_name="knowledge_documents",
    )
    op.drop_index(
        "ix_knowledge_documents_created_at",
        table_name="knowledge_documents",
    )
    op.drop_table("knowledge_documents")
