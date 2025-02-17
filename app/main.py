import streamlit as st
import openai
from huggingface_hub import whoami
from langchain_community.utilities import SQLDatabase
import requests
import os

OPENAI_API_KEY = ""
HUGGINGFACEHUB_API_TOKEN = ""
DB_URI = "sqlite:///Chinook.db"


def isvalid_openai_key(api_key):
    """validate if OpenAI api key is valid"""

    if not api_key:
        return False

    client = openai.OpenAI(api_key=api_key)
    try:
        client.models.list()
    except openai.AuthenticationError:
        return False

    return True


def isvalid_huggingface_key(api_key):
    """validate if Hugging face api key is valid"""

    if not api_key:
        return False

    try:
        user = whoami(token=api_key)
        return True

    except requests.exceptions.RequestException:
        return False


def isvalid_db_uri(db_uri):
    """validate if Database URI is valid"""

    if not db_uri:
        return False

    try:
        db = SQLDatabase.from_uri(db_uri)
        return True

    except:
        return False


with st.sidebar:

    st.subheader("Model Provider")
    model_provider = st.sidebar.selectbox(
        "Choose a LLM model provider", ["OpenAI", "Hugging Face"], key="model_provider"
    )

    if model_provider == "OpenAI":
        OPENAI_API_KEY = st.text_input(
            "OpenAI API Key", key="OPENAI_API_KEY", type="password"
        )

        if isvalid_openai_key(OPENAI_API_KEY):
            os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

            st.success("Valid API key provided!", icon="✔️")
        else:
            st.warning("Please enter valid api key!", icon="⚠️")

    elif model_provider == "Hugging Face":
        HUGGINGFACEHUB_API_TOKEN = st.text_input(
            "Hugging Face API Key", key="HUGGINGFACEHUB_API_TOKEN", type="password"
        )

        if isvalid_huggingface_key(HUGGINGFACEHUB_API_TOKEN):
            os.environ["HUGGINGFACEHUB_API_TOKEN"] = HUGGINGFACEHUB_API_TOKEN

            st.success("Valid API key provided!", icon="✔️")
        else:
            st.warning("Please enter valid api key!", icon="⚠️")

    st.subheader("Database")
    DB_URI = st.text_input(
        "Provide a database URI", key="DB_URI", type="default", value=DB_URI
    )

    if isvalid_db_uri(DB_URI):
        st.success("Valid Database URI provided!", icon="✔️")
    else:
        st.warning("Please enter valid Database URI!", icon="⚠️")


st.title("SQL Data assistant")
st.caption("🚀 A Streamlit application")

if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "assistant", "content": "How can I help you?"}
    ]

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if prompt := st.chat_input():
    if model_provider == "OpenAI" and not isvalid_openai_key(OPENAI_API_KEY):
        st.info("Please enter valid OpenAI API key to continue.")
        st.stop()

    elif model_provider == "Hugging Face" and not isvalid_huggingface_key(
        HUGGINGFACEHUB_API_TOKEN
    ):
        st.info("Please enter valid Hugging face API key to continue.")
        st.stop()

    elif not DB_URI:
        st.info("Please add your Database URI to continue.")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    msg = "llm response"

    st.session_state.messages.append({"role": "assistant", "content": msg})
    st.chat_message("assistant").write(msg)
