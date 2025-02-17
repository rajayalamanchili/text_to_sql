from langgraph.graph import StateGraph
from LLM import State
from SQLAgent import SQLAgent
from langgraph.graph import END


class SQLAgentGraph:

    def __init__(self):
        self.sql_agent = SQLAgent()

    def create_flow(self) -> StateGraph:
        """Create and configure the flow graph."""
        flow = StateGraph(input=State, output=State)

        # Add nodes to the graph
        flow.add_node("parse_question", self.sql_agent.parse_question)
        flow.add_node("generate_sql", self.sql_agent.generate_sql)
        flow.add_node("execute_sql", self.sql_agent.execute_sql)
        flow.add_node("format_results", self.sql_agent.format_results)

        # Define edges
        flow.add_edge("parse_question", "generate_sql")
        flow.add_edge("validate_and_fix_sql", "execute_sql")
        flow.add_edge("generate_sql", "format_results")
        flow.add_edge("format_results", END)
        flow.set_entry_point("parse_question")

        return flow

    def returnGraph(self):
        return self.create_flow().compile()

    def run_sql_agent(self, question: str, uuid: str) -> dict:
        """Run the SQL agent workflow and return the formatted answer and visualization recommendation."""
        app = self.create_flow().compile()
        result = app.invoke({"question": question, "uuid": uuid})
        return {
            "answer": result["answer"],
        }
