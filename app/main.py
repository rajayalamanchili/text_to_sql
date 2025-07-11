import os
import streamlit as st
import pandas as pd
import openai
from huggingface_hub import whoami
from langchain_community.utilities import SQLDatabase
import requests
from api.SQLAgentGraph import SQLAgentGraph

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

    except Exception:
        return False


def get_agent_response(user_question: str):
    """Get LLM response"""

    response = {"answer": "Not able to connect llm or database"}

    if isvalid_db_uri(DB_URI) and isvalid_openai_key(OPENAI_API_KEY):

        response = SQLAgentGraph(llm_provider="openai").run_sql_agent(question=user_question)

    elif isvalid_db_uri(DB_URI) and isvalid_huggingface_key(HUGGINGFACEHUB_API_TOKEN):

        response = SQLAgentGraph(llm_provider="huggingface").run_sql_agent(question=user_question)


    return response

    # return {
    #     "sql_query": 'SELECT Title, COUNT(*) as employee_count FROM `Employee` WHERE Title IS NOT NULL AND Title != "" AND Title != "N/A" GROUP BY Title',
    #     "answer": "The count of employees by title is as follows:\n\n- General Manager: 1\n- IT Manager: 1\n- IT Staff: 2\n- Sales Manager: 1\n- Sales Support Agent: 3\n\nIn total, there are 8 employees across these titles.",
    #     "visualization": "bar",
    #     "visualization_reason": "A bar graph is suitable for comparing the number of employees across different job titles, as it allows for easy comparison of categorical data.",
    #     "formatted_data_for_visualization": {
    #         "labels": [
    #             "General Manager",
    #             "IT Manager",
    #             "IT Staff",
    #             "Sales Manager",
    #             "Sales Support Agent",
    #         ],
    #         "values": [
    #             {"data": [1.0, 1.0, 2.0, 1.0, 3.0], "label": "Employee Count by Title"}
    #         ],
    #     },
    # }


def display_agent_response(content):
    """display agent reponse"""

    if content["answer"]:
        st.write(content["answer"])
    if ("sql_query" in content) and content["sql_query"]:
        st.write("**SQL Query:**\n\n" + "```" + content["sql_query"] + "```")
    if (
        ("visualization" in content)
        and content["visualization"]
        and content["visualization"] != "none"
        and "values" in content["formatted_data_for_visualization"]
    ):
        st.write("**Visualization:**\n\n")

        match content["visualization"]:
            case "bar":
                st.bar_chart(
                    data=pd.Series(
                        content["formatted_data_for_visualization"]["values"][0][
                            "data"
                        ],
                        index=content["formatted_data_for_visualization"]["labels"],
                    ),
                    x_label=content["formatted_data_for_visualization"]["values"][0][
                        "label"
                    ],
                )
            case _:
                st.write("**Visualization Error\n\n")


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
            OPENAI_API_KEY = ""
            os.environ["OPENAI_API_KEY"] = ""
            st.warning("Please enter valid api key!", icon="⚠️")

    elif model_provider == "Hugging Face":
        HUGGINGFACEHUB_API_TOKEN = st.text_input(
            "Hugging Face API Key", key="HUGGINGFACEHUB_API_TOKEN", type="password"
        )

        if isvalid_huggingface_key(HUGGINGFACEHUB_API_TOKEN):
            os.environ["HUGGINGFACEHUB_API_TOKEN"] = HUGGINGFACEHUB_API_TOKEN
            st.success("Valid API key provided!", icon="✔️")
        else:
            HUGGINGFACEHUB_API_TOKEN = ""
            os.environ["HUGGINGFACEHUB_API_TOKEN"] = ""
            st.warning("Please enter valid api key!", icon="⚠️")

    st.subheader("Database")
    user_db_uri = st.text_input(
        "Provide a database URI", key="DB_URI", type="default", value=DB_URI
    )

    if isvalid_db_uri(user_db_uri):
        os.environ["DB_URI"] = user_db_uri
        st.success("Valid Database URI provided!", icon="✔️")
    else:
        DB_URI = ""
        os.environ["DB_URI"] = ""
        st.warning("Please enter valid Database URI!", icon="⚠️")


st.title("SQL Data assistant")
st.caption("🚀 A Streamlit application")

if "messages" not in st.session_state:

    st.session_state["messages"] = [
        {
            "role": "assistant",
            "content": {
                "answer": "How can I help you?",
                "sql_query": "",
                "visualization": "",
                "formatted_data_for_visualization": {},
            },
        }
    ]

for msg in st.session_state.messages:

    if msg["role"] == "user":
        st.chat_message(msg["role"]).write(msg["content"])

    elif msg["role"] == "assistant":
        with st.chat_message("assistant"):
            display_agent_response(msg["content"])

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

    if st.session_state.messages[-1]["role"] != "assistant":
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                llm_response = get_agent_response(prompt)
                display_agent_response(llm_response)
        message = {"role": "assistant", "content": llm_response}
        st.session_state.messages.append(message)
