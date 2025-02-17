from io import BytesIO
from LLMState import State
from SQLAgent import SQLAgent
from langgraph.graph import StateGraph
from langgraph.graph import END
from dotenv import load_dotenv
from PIL import Image


class SQLAgentGraph:

    def __init__(self):
        self.sql_agent = SQLAgent()

    def create_flow(self) -> StateGraph:
        """Create and configure the flow graph."""
        flow = StateGraph(state_schema=State)

        # Add nodes to the graph
        flow.add_node("parse_question", self.sql_agent.parse_question)
        flow.add_node("generate_sql", self.sql_agent.generate_sql)
        flow.add_node("execute_sql", self.sql_agent.execute_sql)
        flow.add_node("format_results", self.sql_agent.format_results)

        # Define edges
        flow.add_edge("parse_question", "generate_sql")
        flow.add_edge("generate_sql", "execute_sql")
        flow.add_edge("execute_sql", "format_results")
        flow.add_edge("format_results", END)
        flow.set_entry_point("parse_question")

        return flow

    def return_graph(self):
        return self.create_flow().compile()

    def run_sql_agent(self, question: str) -> dict:
        """Run the SQL agent workflow and return the formatted answer and visualization recommendation."""
        app = self.create_flow().compile()
        result = app.invoke({"question": question})
        return {
            "answer": result["answer"],
        }


if __name__ == "__main__":

    load_dotenv(override=True)

    sql_agent_graph = SQLAgentGraph().return_graph()

    img = Image.open(BytesIO(sql_agent_graph.get_graph().draw_mermaid_png()))
    img.save("text_sql_graph.png")

    test_question = "Which country's customers spent the most, list 5 with amount spent?"  # "How many employees are there?"

    for step in sql_agent_graph.stream(
        {"question": test_question}, stream_mode="updates"
    ):
        print(step)
