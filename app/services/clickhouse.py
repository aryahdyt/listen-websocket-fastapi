"""ClickHouse service for database operations."""

from typing import Any, List, Optional
from clickhouse_driver import Client
from app.core.config import settings


class ClickHouseService:
    """Service for interacting with ClickHouse database."""
    
    def __init__(self):
        """Initialize ClickHouse service."""
        self.host = settings.CLICKHOUSE_HOST
        self.port = settings.CLICKHOUSE_PORT
        self.database = settings.CLICKHOUSE_DATABASE
        self.user = settings.CLICKHOUSE_USER
        self.password = settings.CLICKHOUSE_PASSWORD
        self._client: Optional[Client] = None
    
    def get_client(self) -> Client:
        """Get or create ClickHouse client."""
        if self._client is None:
            self._client = Client(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
        return self._client
    
    def execute_query(self, query: str) -> Optional[List[Any]]:
        """
        Execute a query on ClickHouse.
        
        Args:
            query: SQL query to execute
            
        Returns:
            Query results or None if error occurs
        """
        try:
            client = self.get_client()
            result = client.execute(query)
            return result
        except Exception as e:
            print(f"Error executing ClickHouse query: {e}")
            return None
    
    def test_connection(self) -> bool:
        """
        Test ClickHouse connection.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            client = self.get_client()
            client.execute("SELECT 1")
            return True
        except Exception as e:
            print(f"ClickHouse connection test failed: {e}")
            return False
    
    def close(self):
        """Close ClickHouse connection."""
        if self._client:
            self._client.disconnect()
            self._client = None


# Singleton instance
clickhouse_service = ClickHouseService()
