from typing_extensions import TypedDict, List, Annotated, Dict, Any
import operator


class State(TypedDict):
    """LLM state"""

    question: str
    parsed_question: str
    sql_query: str
    results: str
    answer: str
    unique_nouns: List[str]
    visualization: Annotated[str, operator.add]
    visualization_reason: Annotated[str, operator.add]
    formatted_data_for_visualization: Dict[str, Any]
