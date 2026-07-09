import os
import uuid
import time
import asyncio
import datetime
from typing import Dict, Any
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.callbacks import BaseCallbackHandler
from tools import (
    create_iceberg_table, ingest_csv_to_iceberg, query_iceberg_data,
    run_generic_graph_analysis, sync_iceberg_to_graph_db, query_graph_db_cypher,
    # DQE tools
    distributed_sql_query, distributed_graph_query,
    distributed_python_extract, multi_engine_query,
)
from contextvars import ContextVar
from traffic_bus import traffic_bus, TrafficEvent

# Load environment variables
load_dotenv()

# ContextVar to track the parent request ID for tool logs correlation
current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")

class TrafficCallbackHandler(BaseCallbackHandler):
    def __init__(self):
        super().__init__()
        self.tool_starts = {}

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> None:
        tool_name = serialized.get("name")
        run_id = str(kwargs.get("run_id") or uuid.uuid4())
        self.tool_starts[run_id] = {
            "name": tool_name,
            "args": input_str,
            "start_time": time.time()
        }

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id"))
        start_info = self.tool_starts.pop(run_id, None)
        if start_info:
            latency_ms = (time.time() - start_info["start_time"]) * 1000
            parent_id = current_request_id.get()
            event = TrafficEvent(
                id=str(uuid.uuid4()),
                timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                type="tool_call",
                status="success",
                latency_ms=latency_ms,
                tool_name=start_info["name"],
                tool_args=str(start_info["args"]),
                tool_result=str(output),
                parent_id=parent_id
            )
            # Run async publish inside loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(traffic_bus.publish(event))
                else:
                    loop.run_until_complete(traffic_bus.publish(event))
            except Exception:
                pass

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id"))
        start_info = self.tool_starts.pop(run_id, None)
        if start_info:
            latency_ms = (time.time() - start_info["start_time"]) * 1000
            parent_id = current_request_id.get()
            event = TrafficEvent(
                id=str(uuid.uuid4()),
                timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                type="tool_call",
                status="error",
                latency_ms=latency_ms,
                tool_name=start_info["name"],
                tool_args=str(start_info["args"]),
                tool_result=str(error),
                parent_id=parent_id
            )
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(traffic_bus.publish(event))
                else:
                    loop.run_until_complete(traffic_bus.publish(event))
            except Exception:
                pass

def create_iceberg_agent():
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to Railway environment variables: Settings → Variables → New Variable."
        )
    llm = ChatAnthropic(model="claude-sonnet-4-5", api_key=anthropic_key)
    
    tools = [
        create_iceberg_table,
        ingest_csv_to_iceberg,
        query_iceberg_data,
        run_generic_graph_analysis,
        sync_iceberg_to_graph_db,
        query_graph_db_cypher,
        # DQE tools — use these for advanced queries
        distributed_sql_query,
        distributed_graph_query,
        distributed_python_extract,
        multi_engine_query,
    ]
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an Apache Iceberg Data Lake Assistant.
        You can help users create data lakes, ingest data into them, and query the data.
        
        When a user asks to ingest data:
        1. Find out the CSV file path and schema. If they don't provide a schema, guess one based on common sense or ask them.
        2. Use `create_iceberg_table` to create the table.
        3. Use `ingest_csv_to_iceberg` to insert the data.
        
        When a user asks a question about their data:
        1. Use `query_iceberg_data` to run SQL against the table.
        2. Remember that in `query_iceberg_data`, the table is ALWAYS named 'iceberg_table' in the SQL FROM clause.
        
        Advanced Graph Use Cases (Local/In-Memory):
        Instead of specialized tools, you have a generic `run_generic_graph_analysis` tool for on-the-fly network analysis.
        - To answer a graph-related question using in-memory calculations, identify the source and target columns.
        - Run `run_generic_graph_analysis` with algorithms like 'find_cycles', 'degree_centrality', or 'connected_components'.

        Persistent Enterprise Graph Database (Apache AGE):
        You have direct access to a persistent Apache AGE graph database.
        - To synchronize an Iceberg table into the persistent graph database, use `sync_iceberg_to_graph_db`. You must specify:
          - namespace and table_name
          - source_node_col and target_node_col
          - graph_name (use the table name or namespace as the graph_name)
          - edge_label (a descriptive relationship string, e.g. 'treated_with', 'buys', 'lineage_to')
        - To query the persistent graph database, use `query_graph_db_cypher`. You write Cypher query statements directly against the graph_name.
          - Example Cypher query: MATCH (a:Entity)-[r]->(b:Entity) RETURN a.id, b.id LIMIT 10
          - Always specify which graph_name to query.
          - Make sure Cypher queries specify appropriate RETURN fields (like return properties or node IDs) to yield clean, structured tabular outputs.

        Distributed Query Engine (DQE) — Prefer these for complex or large-scale queries:
        You have access to a production-grade Distributed Query Engine with three modes:

        1. `distributed_sql_query` — Advanced DuckDB SQL with EXPLAIN plans and predicate pushdown.
           Use this instead of `query_iceberg_data` for: aggregations, GROUP BY, ORDER BY, multi-column analytics.
           Always use 'iceberg_table' as the table name in your SQL.

        2. `distributed_graph_query` — Full graph algorithms (pagerank, betweenness_centrality,
           degree_centrality, connected_components, find_cycles, shortest_path, community_detection).
           Use this for: fraud ring detection, vendor collusion analysis, lineage clustering, network influence scoring.
           Provide either a Cypher query string OR an algorithm name.

        3. `distributed_python_extract` — Execute safe Python transformations.
           Use this for: complex pandas operations, multi-step transformations, rolling windows, custom metrics.
           The script must set 'result_df' as a pandas DataFrame.
           Available: df, arrow_table, pd, pa, duckdb, json, datetime, re, math.

        4. `multi_engine_query` — Fan-out queries across multiple engines in one call.
           Use this when the user wants results from both SQL and Graph simultaneously.
           Pass a JSON array of query specs.
        """),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=20,
        max_execution_time=120,
        callbacks=[TrafficCallbackHandler()]
    )
    
    return agent_executor


if __name__ == "__main__":
    from langchain_core.messages import HumanMessage, AIMessage
    
    print("Welcome to LakeMind Iceberg!")
    agent = create_iceberg_agent()
    
    chat_history = []
    
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ['exit', 'quit', 'q']:
                break
                
            response = agent.invoke({
                "input": user_input,
                "chat_history": chat_history
            })
            
            output = response['output']
            print(f"\nAgent: {output}")
            
            # Update chat history
            chat_history.append(HumanMessage(content=user_input))
            chat_history.append(AIMessage(content=output))
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\nError: {e}")
