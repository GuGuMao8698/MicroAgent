from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

ARTIFACT_TYPES = frozenset({"graph_evidence", "psi_tree"})
ARTIFACT_BUILD_STATUSES = frozenset(
    {
        "building",
        "projection_pending",
        "projected",
        "active",
        "failed",
        "repair_pending",
        "repairing",
        "superseded",
        "deleting",
        "deleted",
    }
)
PROJECTION_TARGETS = frozenset({"infinity_graph_candidate", "infinity_psi_node"})
PROJECTION_STATUSES = frozenset(
    {
        "pending",
        "projecting",
        "projected",
        "failed",
        "repair_pending",
        "repairing",
        "deleting",
        "deleted",
    }
)


def connect_artifact_db(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_schema(connection)
    return connection


def initialize_schema(conn: sqlite3.Connection) -> None:
    current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current_version < 0 or current_version > SCHEMA_VERSION:
        msg = (
            f"unsupported artifact schema version: {current_version}; "
            f"expected 0 through {SCHEMA_VERSION}"
        )
        raise ValueError(msg)
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS artifact_documents (
            document_id TEXT PRIMARY KEY,
            filename TEXT,
            file_type TEXT,
            storage_path TEXT,
            parser_signature TEXT,
            chunker_signature TEXT,
            embedding_signature TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        );

        CREATE TABLE IF NOT EXISTS artifact_builds (
            build_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            artifact_scope TEXT NOT NULL DEFAULT 'document',
            builder_version TEXT NOT NULL,
            embedding_signature TEXT NOT NULL,
            status TEXT NOT NULL,
            failure_code TEXT,
            failure_stage TEXT,
            failure_retryable INTEGER,
            error_message TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_attempted_at TEXT,
            created_at TEXT NOT NULL,
            projected_at TEXT,
            activated_at TEXT,
            failed_at TEXT,
            repair_required_at TEXT,
            deleted_at TEXT,
            FOREIGN KEY (document_id) REFERENCES artifact_documents(document_id)
        );

        CREATE TABLE IF NOT EXISTS active_artifacts (
            artifact_type TEXT NOT NULL,
            document_id TEXT NOT NULL,
            active_build_id TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            PRIMARY KEY (artifact_type, document_id),
            FOREIGN KEY (document_id) REFERENCES artifact_documents(document_id),
            FOREIGN KEY (active_build_id) REFERENCES artifact_builds(build_id)
        );

        CREATE TABLE IF NOT EXISTS artifact_projections (
            projection_id TEXT PRIMARY KEY,
            build_id TEXT NOT NULL,
            target TEXT NOT NULL,
            target_table TEXT NOT NULL,
            status TEXT NOT NULL,
            failure_code TEXT,
            failure_stage TEXT,
            failure_retryable INTEGER,
            projected_at TEXT,
            failed_at TEXT,
            repair_required_at TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_attempted_at TEXT,
            deleted_at TEXT,
            error_message TEXT,
            FOREIGN KEY (build_id) REFERENCES artifact_builds(build_id)
        );

        CREATE TABLE IF NOT EXISTS orphan_projection_failures (
            orphan_failure_id TEXT PRIMARY KEY,
            target TEXT NOT NULL,
            target_table TEXT NOT NULL,
            owner_build_id TEXT NOT NULL,
            status TEXT NOT NULL,
            failure_code TEXT NOT NULL,
            failure_stage TEXT NOT NULL,
            detected_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS graph_evidence_batches (
            batch_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            build_id TEXT,
            extractor_version TEXT,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES artifact_documents(document_id),
            FOREIGN KEY (build_id) REFERENCES artifact_builds(build_id)
        );

        CREATE TABLE IF NOT EXISTS graph_entities (
            entity_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            build_id TEXT,
            ordinal INTEGER NOT NULL,
            name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            description TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY (entity_id, document_id, build_id),
            FOREIGN KEY (document_id) REFERENCES artifact_documents(document_id),
            FOREIGN KEY (build_id) REFERENCES artifact_builds(build_id)
        );

        CREATE TABLE IF NOT EXISTS graph_relationships (
            relation_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            build_id TEXT,
            ordinal INTEGER NOT NULL,
            source_entity_id TEXT NOT NULL,
            target_entity_id TEXT NOT NULL,
            source_entity_name TEXT NOT NULL,
            target_entity_name TEXT NOT NULL,
            description TEXT NOT NULL,
            keywords_json TEXT NOT NULL,
            weight REAL NOT NULL,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY (relation_id, document_id, build_id),
            FOREIGN KEY (document_id) REFERENCES artifact_documents(document_id),
            FOREIGN KEY (build_id) REFERENCES artifact_builds(build_id)
        );

        CREATE TABLE IF NOT EXISTS graph_entity_source_chunks (
            entity_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            build_id TEXT,
            chunk_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            PRIMARY KEY (entity_id, document_id, build_id, ordinal)
        );

        CREATE TABLE IF NOT EXISTS graph_relationship_source_chunks (
            relation_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            build_id TEXT,
            chunk_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            PRIMARY KEY (relation_id, document_id, build_id, ordinal)
        );

        CREATE TABLE IF NOT EXISTS psi_trees (
            build_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            max_layer INTEGER NOT NULL,
            highest_queryable_layer INTEGER,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            FOREIGN KEY (build_id) REFERENCES artifact_builds(build_id),
            FOREIGN KEY (document_id) REFERENCES artifact_documents(document_id)
        );

        CREATE TABLE IF NOT EXISTS psi_tree_nodes (
            node_id TEXT PRIMARY KEY,
            build_id TEXT NOT NULL,
            layer INTEGER NOT NULL,
            node_type TEXT NOT NULL,
            abstract_type TEXT,
            text TEXT NOT NULL,
            summary_text TEXT,
            keyword_text TEXT,
            source_document_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            FOREIGN KEY (build_id) REFERENCES artifact_builds(build_id),
            FOREIGN KEY (source_document_id) REFERENCES artifact_documents(document_id)
        );

        CREATE TABLE IF NOT EXISTS psi_tree_edges (
            build_id TEXT NOT NULL,
            parent_node_id TEXT NOT NULL,
            child_node_id TEXT NOT NULL,
            child_rank INTEGER NOT NULL,
            edge_score REAL NOT NULL,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY (build_id, parent_node_id, child_node_id),
            FOREIGN KEY (build_id) REFERENCES artifact_builds(build_id),
            FOREIGN KEY (parent_node_id) REFERENCES psi_tree_nodes(node_id),
            FOREIGN KEY (child_node_id) REFERENCES psi_tree_nodes(node_id)
        );

        CREATE TABLE IF NOT EXISTS psi_node_source_chunks (
            node_id TEXT NOT NULL,
            source_chunk_id TEXT NOT NULL,
            source_rank INTEGER NOT NULL,
            evidence_role TEXT NOT NULL,
            PRIMARY KEY (node_id, source_chunk_id),
            FOREIGN KEY (node_id) REFERENCES psi_tree_nodes(node_id)
        );
        """
    )
    if current_version < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
