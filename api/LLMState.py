from typing_extensions import TypedDict


class State(TypedDict):
    """LLM state"""

    question: str
    parsed_question: str
    sql_query: str
    results: str
    answer: str
