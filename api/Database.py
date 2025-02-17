import os
from typing import List, Any
from langchain_community.utilities import SQLDatabase
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool


class Database:
    def __init__(self):
        self.endpoint_url = os.getenv("DB_URI")
        self.db = SQLDatabase.from_uri(self.endpoint_url)

    def get_schema(self) -> str:
        """Retrieve the database schema."""
        try:
            return self.db.get_table_info_no_throw()
        except Exception as e:
            raise Exception(f"Error fetching schema: {str(e)}")

    def execute_query(self, query: str) -> List[Any]:
        """Execute SQL query on the remote database and return results."""
        try:
            execute_query_tool = QuerySQLDatabaseTool(db=self.db)
            return execute_query_tool.invoke(query)
        except Exception as e:
            raise Exception(f"Error executing query: {str(e)}")
