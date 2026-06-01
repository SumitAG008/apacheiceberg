import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tools import (
    create_iceberg_table, ingest_csv_to_iceberg, query_iceberg_data,
    run_generic_graph_analysis
)

# Load environment variables
load_dotenv()

def create_iceberg_agent():
    # Verify API key is available
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Warning: ANTHROPIC_API_KEY environment variable not found. The agent will not run without it.")
        print("You can create a .env file with ANTHROPIC_API_KEY=your_key")
        
    llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)
    
    tools = [
        create_iceberg_table,
        ingest_csv_to_iceberg,
        query_iceberg_data,
        run_generic_graph_analysis
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
        
        Advanced Graph Use Cases:
        Instead of specialized tools, you now have a generic `run_generic_graph_analysis` tool.
        - To answer a graph-related question, first determine the schema of the table.
        - Identify the source and target node columns to form relationships (edges).
        - Pass these columns to `run_generic_graph_analysis` along with the appropriate algorithm ('find_cycles' for fraud/layering, 'degree_centrality' for isolation/attrition, 'connected_components' for lineage).
        - You can optionally pass a pandas query string (like "amount > 9000") to filter the graph.
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
        max_execution_time=120
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
