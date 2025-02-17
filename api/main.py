from SQLAgentGraph import SQLAgentGraph

graph = SQLAgentGraph().returnGraph()


for step in graph.stream(
    {"question": "How many employees are there?"}, stream_mode="updates"
):
    print(step)
