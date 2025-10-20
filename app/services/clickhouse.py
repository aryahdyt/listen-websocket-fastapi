"""ClickHouse service for database operations."""

from typing import Any, List, Optional, Dict
import clickhouse_connect
from app.core.config import settings


class ClickHouseService:
    """Service for interacting with ClickHouse database via clickhouse_connect."""
    
    def __init__(self):
        """Initialize ClickHouse service."""
        self.host = settings.CLICKHOUSE_HOST
        self.port = settings.CLICKHOUSE_PORT
        self.database = settings.CLICKHOUSE_DATABASE
        self.user = settings.CLICKHOUSE_USER
        self.password = settings.CLICKHOUSE_PASSWORD
        self._client = None
    
    def get_client(self):
        """Get or create ClickHouse client."""
        if self._client is None:
            try:
                print(f"🔌 Connecting to ClickHouse: {self.host}:{self.port}/{self.database}")
                self._client = clickhouse_connect.get_client(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    username=self.user,
                    password=self.password
                )
                print("✓ ClickHouse connection established")
            except Exception as e:
                print(f"❌ Failed to connect to ClickHouse: {e}")
                self._client = None
        
        return self._client
    
    def execute_query(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a query on ClickHouse.
        
        Args:
            query: SQL query to execute
            
        Returns:
            Query results or None if error occurs
        """
        try:
            client = self.get_client()
            if client is None:
                print("❌ ClickHouse client is not available")
                return None
            
            print(f"⚙️ Executing query: {query[:100]}...")
            
            # Execute query and get results as list of dicts
            result = client.query(query)
            rows = result.result_rows
            columns = result.column_names
            
            # Convert to list of dicts
            results = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                results.append(row_dict)
            
            print(f"✓ Query executed successfully, returned {len(results)} rows")
            return results
            
        except Exception as e:
            print(f"❌ Error executing ClickHouse query: {e}")
            import traceback
            traceback.print_exc()
            # Reset client on error
            self._client = None
            return None
    
    def test_connection(self) -> bool:
        """
        Test ClickHouse connection.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            print(f"🔌 Testing ClickHouse connection: {self.host}:{self.port}/{self.database}")
            
            client = self.get_client()
            if client is None:
                return False
            
            result = client.query("SELECT 1 as test")
            print("✓ ClickHouse connection test passed")
            return True
            
        except Exception as e:
            print(f"❌ ClickHouse connection test failed: {e}")
            self._client = None
            return False
    
    def close(self):
        """Close ClickHouse connection."""
        if self._client:
            try:
                self._client.close()
                print("✓ ClickHouse connection closed")
            except Exception as e:
                print(f"⚠️ Error closing ClickHouse connection: {e}")
            self._client = None


# Singleton instance
clickhouse_service = ClickHouseService()
