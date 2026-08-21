"""
Database Configuration Management
Handles database connections and credentials for engine_inventory
Uses environment variables directly (no pydantic_settings dependency)

=== DATABASE & TABLE MAP ===
This module provides connection configuration for:

1. threat_engine_inventory (INVENTORY DB) — via get_database_config("inventory") / get_inventory_config()
   Env: INVENTORY_DB_HOST (default: localhost)
        INVENTORY_DB_PORT (default: 5432)
        INVENTORY_DB_NAME (default: threat_engine_inventory)
        INVENTORY_DB_USER (default: inventory_user)
        INVENTORY_DB_PASSWORD (default: inventory_password)
        DB_SSL_MODE / DB_POOL_SIZE / DB_MAX_OVERFLOW / DB_POOL_TIMEOUT / DB_POOL_RECYCLE

2. Neo4j (graph DB) — via get_neo4j_config()
   Env: NEO4J_URI (default: bolt://localhost:7687)
        NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE
        NEO4J_MAX_CONNECTION_LIFETIME / NEO4J_MAX_CONNECTION_POOL_SIZE

Tables READ:  None (configuration only — returns connection objects)
Tables WRITTEN: None
===
"""
import os
from typing import Dict, Optional, Any


class DatabaseConnectionConfig:
    """Database connection configuration"""
    def __init__(self, host: str, port: int, database: str, username: str, password: str,
                 ssl_mode: str = "prefer", pool_size: int = 10, max_overflow: int = 20,
                 pool_timeout: int = 30, pool_recycle: int = 3600):
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.ssl_mode = ssl_mode
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
    
    @property
    def connection_string(self) -> str:
        """Get PostgreSQL connection string"""
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"


class Neo4jConnectionConfig:
    """Neo4j connection configuration"""
    def __init__(self, uri: str, username: str, password: str, database: str = "neo4j",
                 max_connection_lifetime: int = 3600, max_connection_pool_size: int = 50):
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database
        self.max_connection_lifetime = max_connection_lifetime
        self.max_connection_pool_size = max_connection_pool_size
    
    @property
    def connection_string(self) -> str:
        """Get Neo4j connection URI"""
        return self.uri


def get_database_config(engine_name: str = "inventory") -> DatabaseConnectionConfig:
    """
    Get database configuration for inventory engine from environment variables.

    Supports:
      - "inventory" : threat_engine_inventory (INVENTORY_DB_*)
      - "pythonsdk" : threat_engine_pythonsdk (PYTHONSDK_DB_*)
    """
    if engine_name == "inventory":
        return DatabaseConnectionConfig(
            host=os.getenv("INVENTORY_DB_HOST", "localhost"),
            port=int(os.getenv("INVENTORY_DB_PORT", "5432")),
            database=os.getenv("INVENTORY_DB_NAME", "threat_engine_inventory"),
            username=os.getenv("INVENTORY_DB_USER", "inventory_user"),
            password=os.getenv("INVENTORY_DB_PASSWORD", "inventory_password"),
            ssl_mode=os.getenv("DB_SSL_MODE", "prefer"),
            pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
            pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600")),
        )
    elif engine_name == "pythonsdk":
        return DatabaseConnectionConfig(
            host=os.getenv("PYTHONSDK_DB_HOST", os.getenv("DISCOVERIES_DB_HOST", "localhost")),
            port=int(os.getenv("PYTHONSDK_DB_PORT", os.getenv("DISCOVERIES_DB_PORT", "5432"))),
            database=os.getenv("PYTHONSDK_DB_NAME", "threat_engine_pythonsdk"),
            username=os.getenv("PYTHONSDK_DB_USER", os.getenv("DISCOVERIES_DB_USER", "postgres")),
            password=os.getenv("PYTHONSDK_DB_PASSWORD", os.getenv("DISCOVERIES_DB_PASSWORD", "")),
            ssl_mode=os.getenv("DB_SSL_MODE", "prefer"),
        )
    else:
        raise ValueError(f"Inventory engine supports 'inventory' or 'pythonsdk' database, got: {engine_name}")


def get_inventory_config() -> DatabaseConnectionConfig:
    """Get inventory database configuration"""
    return get_database_config("inventory")


def get_neo4j_config() -> Neo4jConnectionConfig:
    """Get Neo4j database configuration"""
    return Neo4jConnectionConfig(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        username=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "neo4j"),
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
        max_connection_lifetime=int(os.getenv("NEO4J_MAX_CONNECTION_LIFETIME", "3600")),
        max_connection_pool_size=int(os.getenv("NEO4J_MAX_CONNECTION_POOL_SIZE", "50")),
    )
