"""
DuckDB Connection and Macro Setup
"""
import duckdb

def get_connection(db_path: str = "mortgage_risk.duckdb") -> duckdb.DuckDBPyConnection:
    """
    Initializes a DuckDB connection and registers necessary macros,
    specifically the integer division month_idx macro.
    """
    con = duckdb.connect(db_path)
    
    # Register month_idx macro with integer division //
    con.execute("""
    CREATE OR REPLACE MACRO month_idx(p) AS (p // 100) * 12 + (p % 100);
    """)
    
    # Verify integer division behaviour
    test_val = con.execute("SELECT 7 // 2;").fetchone()[0]
    if test_val != 3:
        raise RuntimeError(f"Expected integer division to yield 3, got {test_val}. Check DuckDB configuration.")
        
    return con
