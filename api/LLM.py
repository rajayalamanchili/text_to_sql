from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from typing_extensions import TypedDict


class OpenAILLM:
    """LLM with OpenAI models"""

    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    def invoke(self, prompt: ChatPromptTemplate, **kwargs) -> str:
        """invoke llm"""
        messages = prompt.format_messages(**kwargs)
        response = self.llm.invoke(messages)
        return response.content


class HuggingFaceLLM:
    """LLM with Hugging face models"""

    def __init__(self):
        return


class State(TypedDict):
    """LLM state"""

    question: str
    query: str
    result: str
    answer: str
