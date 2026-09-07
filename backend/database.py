"""Nexus ITSM Database Layer — 100% Native MongoDB.
Eliminates SQLite and PostgreSQL completely. All collections and documents
are stored natively in MongoDB (database: nexus_itsm).
"""
import os
import logging
from sqlalchemy.orm import declarative_base

from backend.mongo_dal import (
    get_db,
    get_mongo_db,
    SessionLocal,
    MongoSession,
    mongo_client,
    mongo_db,
    MONGO_URL,
    MONGO_DATABASE
)

logger = logging.getLogger("backend.database")

Base = declarative_base()
Base.metadata.create_all = lambda *args, **kwargs: None

# Compatibility dummy engine to prevent any SQL or SQLite file instantiation
class DummyConnection:
    def execute(self, *args, **kwargs):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

class DummyEngine:
    def connect(self):
        return DummyConnection()
    def begin(self):
        return DummyConnection()

engine = DummyEngine()

def migrate_legacy_schema():
    """No-op: MongoDB is schemaless and does not require relational SQL migrations."""
    pass

__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "get_db",
    "get_mongo_db",
    "MongoSession",
    "mongo_client",
    "mongo_db",
    "migrate_legacy_schema",
    "MONGO_URL",
    "MONGO_DATABASE"
]
