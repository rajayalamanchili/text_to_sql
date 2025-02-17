from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from Database import Database
from LLM import OpenAILLM


class SQLAgent:

    def __init__(self):
        self.db = Database()
        self.llm = OpenAILLM()

    def parse_question(self, state: dict) -> dict:
        """Parse user question and identify relevant tables and columns."""
        question = state["question"]
        schema = self.db.get_schema()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a data analyst that can help summarize SQL tables and parse user questions about a database. 
Given the question and database schema, identify the relevant tables and columns. 
If the question is not relevant to the database or if there is not enough information to answer the question, set is_relevant to false.

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database. if question is related to DML statement, set is_dml to true.

Schema of the database with sample rows and column descriptions:
#
CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

Your response should be in the following JSON format:
{{
    "is_relevant": boolean,
    "is_dml": boolean,
    "relevant_tables": [
        {{
            "table_name": string,
            "columns": [string],
            "noun_columns": [string]
        }}
    ]
}}

The "noun_columns" field should contain only the columns that are relevant to the question and contain nouns or names, for example, the column "Artist name" contains nouns relevant to the question "What are the top selling artists?", but the column "Artist ID" is not relevant because it does not contain a noun. Do not include columns that contain numbers.
""",
                ),
                (
                    "human",
                    "===Database schema:\n{schema}\n\n===User question:\n{question}\n\nIdentify relevant tables and columns:",
                ),
            ]
        )

        output_parser = JsonOutputParser()

        response = self.llm.invoke(prompt, schema=schema, question=question)
        parsed_response = output_parser.parse(response)
        return {"parsed_question": parsed_response}

    def generate_sql(self, state: dict) -> dict:
        """Generate SQL query based on parsed question and unique nouns."""
        question = state["question"]
        parsed_question = state["parsed_question"]
        # unique_nouns = state["unique_nouns"]

        if parsed_question["is_dml"]:
            return {"sql_query": "NOT_ALLOWED", "is_dml": True}

        if not parsed_question["is_relevant"]:
            return {"sql_query": "NOT_RELEVANT", "is_relevant": False}

        schema = self.db.get_schema()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
You are an AI assistant that generates SQL queries based on user questions, database schema, and unique nouns found in the relevant tables. Generate a valid SQL query to answer the user's question.

If there is not enough information to write a SQL query, respond with "NOT_ENOUGH_INFO".

Here are some examples:

1. What is the top selling product?
Answer: SELECT product_name, SUM(quantity) as total_quantity FROM sales WHERE product_name IS NOT NULL AND quantity IS NOT NULL AND product_name != "" AND quantity != "" AND product_name != "N/A" AND quantity != "N/A" GROUP BY product_name ORDER BY total_quantity DESC LIMIT 1

2. What is the total revenue for each product?
Answer: SELECT \`product name\`, SUM(quantity * price) as total_revenue FROM sales WHERE \`product name\` IS NOT NULL AND quantity IS NOT NULL AND price IS NOT NULL AND \`product name\` != "" AND quantity != "" AND price != "" AND \`product name\` != "N/A" AND quantity != "N/A" AND price != "N/A" GROUP BY \`product name\`  ORDER BY total_revenue DESC

3. What is the market share of each product?
Answer: SELECT \`product name\`, SUM(quantity) * 100.0 / (SELECT SUM(quantity) FROM sa  les) as market_share FROM sales WHERE \`product name\` IS NOT NULL AND quantity IS NOT NULL AND \`product name\` != "" AND quantity != "" AND \`product name\` != "N/A" AND quantity != "N/A" GROUP BY \`product name\`  ORDER BY market_share DESC

4. Plot the distribution of income over time
Answer: SELECT income, COUNT(*) as count FROM users WHERE income IS NOT NULL AND income != "" AND income != "N/A" GROUP BY income

5. Describe movies table
Answer: PRAGMA table_info(movies)

THE RESULTS SHOULD ONLY BE IN THE FOLLOWING FORMAT, SO MAKE SURE TO ONLY GIVE TWO OR THREE COLUMNS:
[[x, y]]
or 
[[label, x, y]]
             
For questions like "plot a distribution of the fares for men and women", count the frequency of each fare and plot it. The x axis should be the fare and the y axis should be the count of people who paid that fare.
SKIP ALL ROWS WHERE ANY COLUMN IS NULL or "N/A" or "".
Just give the query string. Do not format it. Make sure to use the correct spellings of nouns as provided in the unique nouns list. All the table and column names should be enclosed in backticks.
""",
                ),
                (
                    "human",
                    """===Database schema:
{schema}

===User question:
{question}

===Relevant tables and columns:
{parsed_question}

===Unique nouns in relevant tables:


Generate SQL query string""",
                ),
            ]
        )

        response = self.llm.invoke(
            prompt,
            schema=schema,
            question=question,
            parsed_question=parsed_question,
            # unique_nouns=unique_nouns,
        )

        if response.strip() == "NOT_ENOUGH_INFO":
            return {"sql_query": "NOT_RELEVANT"}
        else:
            return {"sql_query": response}

    def execute_sql(self, state: dict) -> dict:
        """Execute SQL query and return results."""
        query = state["sql_query"]

        if query == "NOT_ALLOWED":
            return {"results": "NOT_ALLOWED"}

        if query == "NOT_RELEVANT":
            return {"results": "NOT_RELEVANT"}

        try:
            results = self.db.execute_query(query)
            return {"results": results}
        except Exception as e:
            return {"error": str(e)}

    def format_results(self, state: dict) -> dict:
        """Format query results into a human-readable response."""
        question = state["question"]
        results = state["results"]

        if results == "NOT_RELEVANT":
            return {
                "answer": "Sorry, I can only give answers relevant to the database."
            }
        if results == "NOT_ALLOWED":
            return {
                "answer": "Sorry, DML statements (INSERT, UPDATE, DELETE, DROP etc.) are not allowed."
            }

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an AI assistant that formats database query results into a human-readable response. Give a conclusion to the user's question based on the query results.",
                ),
                (
                    "human",
                    "User question: {question}\n\nQuery results: {results}\n\nFormatted response:",
                ),
            ]
        )

        response = self.llm.invoke(prompt, question=question, results=results)
        return {"answer": response}
