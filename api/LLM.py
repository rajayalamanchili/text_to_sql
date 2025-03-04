from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama



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

class OllamaLLM:
    """LLM with Ollama models"""

    def __init__(self):
        self.llm = ChatOllama(model="gemma2:2b", temperature=0, num_ctx=5000)

    def invoke(self, prompt: ChatPromptTemplate, **kwargs) -> str:
        """invoke llm"""
        messages = prompt.format_messages(**kwargs)
        response = self.llm.invoke(messages)
        return response.content

