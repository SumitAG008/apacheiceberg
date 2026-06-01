import streamlit as st
from agent import create_iceberg_agent

st.title("🧊 Apache Iceberg Data Lake Agent")
st.markdown("I can help you create tables, ingest data, and query your Iceberg Data Lake!")

# Initialize the agent in session state
if "agent" not in st.session_state:
    st.session_state.agent = create_iceberg_agent()

# Chat interface
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display past messages
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

user_input = st.chat_input("Ask me to ingest data or query the lake...")

if user_input:
    # Add user message to state
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)
    
    with st.spinner("Thinking..."):
        try:
            response = st.session_state.agent.invoke({"input": user_input})
            bot_response = response['output']
        except Exception as e:
            bot_response = f"Error: {str(e)}"
        
    # Add assistant message to state
    st.session_state.messages.append({"role": "assistant", "content": bot_response})
    st.chat_message("assistant").write(bot_response)
