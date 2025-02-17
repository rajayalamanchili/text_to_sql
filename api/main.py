from SQLAgentGraph import SQLAgentGraph
from dotenv import load_dotenv

load_dotenv(override=True)
graph = SQLAgentGraph().return_graph()


for step in graph.stream(
    {"question": "How many employees are there?"}, stream_mode="updates"
):
    print(step)
