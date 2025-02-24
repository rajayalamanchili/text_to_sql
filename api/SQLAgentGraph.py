from io import BytesIO
from langgraph.graph import StateGraph
from langgraph.graph import END
from dotenv import load_dotenv
from PIL import Image
from api.LLMState import State
from api.SQLAgent import SQLAgent
from api.visualizations import VisualizationDataFormatter


class SQLAgentGraph:

    def __init__(self):
        self.sql_agent = SQLAgent()
        self.visualizationDataFormatter = VisualizationDataFormatter()

    def create_flow(self) -> StateGraph:
        """Create and configure the flow graph."""
        flow = StateGraph(state_schema=State)

        # Add nodes to the graph
        flow.add_node("parse_question", self.sql_agent.parse_question)
        flow.add_node("get_unique_nouns", self.sql_agent.get_unique_nouns)
        flow.add_node("generate_sql", self.sql_agent.generate_sql)
        flow.add_node("validate_and_fix_sql", self.sql_agent.validate_and_fix_sql)
        flow.add_node("execute_sql", self.sql_agent.execute_sql)
        flow.add_node("format_results", self.sql_agent.format_results)
        flow.add_node("choose_visualization", self.sql_agent.choose_visualization)
        flow.add_node(
            "format_data_for_visualization",
            self.visualizationDataFormatter.format_data_for_visualization,
        )

        # Define edges
        flow.add_edge("parse_question", "get_unique_nouns")
        flow.add_edge("get_unique_nouns", "generate_sql")
        flow.add_edge("generate_sql", "validate_and_fix_sql")
        flow.add_edge("validate_and_fix_sql", "execute_sql")
        flow.add_edge("execute_sql", "format_results")
        flow.add_edge("execute_sql", "choose_visualization")
        flow.add_edge("choose_visualization", "format_data_for_visualization")
        flow.add_edge("format_data_for_visualization", END)
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
            "sql_query": result["sql_query"],
            "answer": result["answer"],
            "visualization": result["visualization"],
            "visualization_reason": result["visualization_reason"],
            "formatted_data_for_visualization": result[
                "formatted_data_for_visualization"
            ],
        }


if __name__ == "__main__":

    load_dotenv(override=True)

    sql_agent_graph = SQLAgentGraph().return_graph()

    img = Image.open(BytesIO(sql_agent_graph.get_graph().draw_mermaid_png()))
    img.save("text_sql_graph.png")

    # test_question = "Which country's customers spent the most, list 5 with amount spent?"  # "How many employees are there?"
    # test_question = "how many albums does ac/dc have?"
    # test_question = "how many albums does ac dc have?"
    # test_question = "how many albums does Alice In Chains have?"
    # test_question = "how many albums does Alis In Chain have?"
    # test_question = "count number of employees by title"
    test_question = "how many tracks each artist has ?"

    for step in sql_agent_graph.stream(
        {"question": test_question}, stream_mode="updates"
    ):
        print(step)
