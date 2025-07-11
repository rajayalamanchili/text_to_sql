FROM python:3.10-slim

# Set working directory
WORKDIR /usr/src/sql_assistant

# Copy requirements and folders
COPY requirements.txt .
COPY api ./api
COPY app ./app
COPY Chinook.db .

# Install dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Add sql_assistant to PYTHONPATH
ENV PYTHONPATH="${PYTHONPATH}:/sql_assistant"


# Expose Streamlit default port
EXPOSE 8501

# Run Streamlit app (assuming main file is app/main.py)
CMD ["streamlit", "run", "app/main.py"]