import networkx as nx
import tempfile
import os

def build_lineage_graph(nodes, relationships):
    """
    Builds a directed graph using networkx.
    
    Args:
        nodes: List of dictionaries with keys like 'id', 'label', 'color', 'title'
        relationships: List of tuples (src_id, dst_id, relationship_label)
    
    Returns:
        nx.DiGraph
    """
    G = nx.DiGraph()
    
    # Add nodes
    for node in nodes:
        node_id = node.pop('id')
        G.add_node(node_id, **node)
        
    # Add edges
    for src, dst, rel in relationships:
        G.add_edge(src, dst, label=rel, title=rel)
        
    return G

def generate_graph_html(G, output_path=None):
    """
    Renders a networkx graph using PyVis and saves it to an HTML file.
    """
    try:
        from pyvis.network import Network
    except ImportError:
        return "<p>Error: pyvis is not installed. Please install it with 'pip install pyvis'.</p>"

    # Create a pyvis network
    # For Streamlit it's best to use a specific height and width
    net = Network(height="500px", width="100%", directed=True, notebook=False)
    
    # Customize physics for better layout
    net.force_atlas_2based(central_gravity=0.015, spring_length=100, spring_strength=0.08)
    
    # Load networkx graph
    net.from_nx(G)
    
    if output_path is None:
        # Generate temporary file
        fd, output_path = tempfile.mkstemp(suffix='.html')
        os.close(fd)
        
    # Save the graph
    net.save_graph(output_path)
    
    # Return the HTML content to be embedded
    with open(output_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    return html_content
