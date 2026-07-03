import os
import sys
import pandas as pd

# Add the current directory to path so we can import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from graph_db import get_db_connection, create_graph_if_not_exists, sync_dataframe_to_age, execute_cypher_query, get_graph_stats

def run_tests():
    print("🧪 Starting Apache AGE Graph Database Tests...")
    
    # 1. Check database connection
    try:
        conn = get_db_connection()
        print("✅ Database connection established.")
    except Exception as e:
        print(f"❌ Failed database connection: {e}")
        print("Ensure PostgreSQL is running and credentials in environment variables match.")
        return False
        
    # 2. Check graph initialization
    test_graph = "test_verification_graph"
    try:
        create_graph_if_not_exists(conn, test_graph)
        print(f"✅ Graph '{test_graph}' initialized.")
    except Exception as e:
        print(f"❌ Failed to initialize graph '{test_graph}': {e}")
        conn.close()
        return False
    finally:
        conn.close()
        
    # 3. Create mock DataFrame and test sync_dataframe_to_age
    data = {
        "person_a": ["Alice", "Bob", "Charlie", "Alice"],
        "person_b": ["Bob", "Charlie", "David", "David"],
        "rel_type": ["KNOWS", "KNOWS", "KNOWS", "KNOWS"]
    }
    df = pd.DataFrame(data)
    print("\nDataFrame to Sync:")
    print(df)
    
    try:
        sync_result = sync_dataframe_to_age(test_graph, df, "person_a", "person_b", "knows_person")
        print(f"✅ Sync result: {sync_result}")
    except Exception as e:
        print(f"❌ Failed to sync dataframe: {e}")
        return False
        
    # 4. Query graph stats
    try:
        stats = get_graph_stats(test_graph)
        print(f"✅ Graph Stats: {stats}")
        if stats.get("nodes", 0) == 0 or stats.get("edges", 0) == 0:
            print("❌ Graph Stats indicates zero nodes or edges were created.")
            return False
    except Exception as e:
        print(f"❌ Failed to retrieve graph stats: {e}")
        return False
        
    # 5. Execute Cypher Query
    cypher_query = "MATCH (a:Entity)-[r]->(b:Entity) RETURN a.id, b.id LIMIT 5"
    try:
        result_df = execute_cypher_query(test_graph, cypher_query)
        print(f"\n✅ Cypher Query Result for '{cypher_query}':")
        print(result_df)
        if result_df.empty:
            print("❌ Cypher query returned empty results.")
            return False
    except Exception as e:
        print(f"❌ Failed to execute Cypher query: {e}")
        return False
        
    print("\n🎉 All Apache AGE Graph tests passed successfully!")
    return True

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
