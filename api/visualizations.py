import json
from ast import literal_eval
from langchain_core.prompts import ChatPromptTemplate
from api.LLM import OpenAILLM


class VisualizationDataFormatter:
    def __init__(self):
        self.llm_manager = OpenAILLM()

    def format_data_for_visualization(self, state: dict) -> dict:
        """Format the data for the chosen visualization type."""
        visualization = state["visualization"]
        results = state["results"]
        question = state["question"]
        sql_query = state["sql_query"]

        if visualization == "none":
            return {"formatted_data_for_visualization": None}

        if visualization == "scatter":
            try:
                return self._format_scatter_data(results)
            except Exception as e:
                return self._format_other_visualizations(
                    visualization, question, sql_query, results
                )

        if visualization == "bar" or visualization == "horizontal_bar":
            try:
                return self._format_bar_data(results, question)
            except Exception as e:
                return self._format_other_visualizations(
                    visualization, question, sql_query, results
                )

        if visualization == "line":
            try:
                return self._format_line_data(results, question)
            except Exception as e:
                return self._format_other_visualizations(
                    visualization, question, sql_query, results
                )

        return self._format_other_visualizations(
            visualization, question, sql_query, results
        )

    def _format_line_data(self, results, question):
        if isinstance(results, str):
            results = literal_eval(results)

        if len(results[0]) == 2:

            x_values = [str(row[0]) for row in results]
            y_values = [float(row[1]) for row in results]

            # Use LLM to get a relevant label
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are a data labeling expert. Given a question and some data, provide a concise and relevant label for the data series.",
                    ),
                    (
                        "human",
                        "Question: {question}\n Data (first few rows): {data}\n\nProvide a concise label for this y axis. For example, if the data is the sales figures over time, the label could be 'Sales'. If the data is the population growth, the label could be 'Population'. If the data is the revenue trend, the label could be 'Revenue'.",
                    ),
                ]
            )
            label = self.llm_manager.invoke(
                prompt, question=question, data=str(results[:2])
            )

            formatted_data = {
                "xValues": x_values,
                "yValues": [{"data": y_values, "label": label.strip()}],
            }
        elif len(results[0]) == 3:

            # Group data by label
            data_by_label = {}
            x_values = []

            # Get a list of unique labels
            labels = list(
                set(
                    item2
                    for item1, item2, item3 in results
                    if isinstance(item2, str)
                    and not item2.replace(".", "").isdigit()
                    and "/" not in item2
                )
            )

            # If labels are not in the second position, check the first position
            if not labels:
                labels = list(
                    set(
                        item1
                        for item1, item2, item3 in results
                        if isinstance(item1, str)
                        and not item1.replace(".", "").isdigit()
                        and "/" not in item1
                    )
                )

            for item1, item2, item3 in results:
                # Determine which item is the label (string not convertible to float and not containing "/")
                if (
                    isinstance(item1, str)
                    and not item1.replace(".", "").isdigit()
                    and "/" not in item1
                ):
                    label, x, y = item1, item2, item3
                else:
                    x, label, y = item1, item2, item3

                if str(x) not in x_values:
                    x_values.append(str(x))
                if label not in data_by_label:
                    data_by_label[label] = []
                data_by_label[label].append(float(y))
                print(labels)
                for other_label in labels:
                    if other_label != label:
                        if other_label not in data_by_label:
                            data_by_label[other_label] = []
                        data_by_label[other_label].append(None)

            # Create yValues array
            y_values = [
                {"data": data, "label": label} for label, data in data_by_label.items()
            ]

            formatted_data = {
                "xValues": x_values,
                "yValues": y_values,
                "yAxisLabel": "",
            }

            # Use LLM to get a relevant label for the y-axis
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are a data labeling expert. Given a question and some data, provide a concise and relevant label for the y-axis.",
                    ),
                    (
                        "human",
                        "Question: {question}\n Data (first few rows): {data}\n\nProvide a concise label for the y-axis. For example, if the data represents sales figures over time for different categories, the label could be 'Sales'. If it's about population growth for different groups, it could be 'Population'.",
                    ),
                ]
            )
            y_axis_label = self.llm_manager.invoke(
                prompt, question=question, data=str(results[:2])
            )

            # Add the y-axis label to the formatted data
            formatted_data["yAxisLabel"] = y_axis_label.strip()

        return {"formatted_data_for_visualization": formatted_data}

    def _format_scatter_data(self, results):
        if isinstance(results, str):
            results = literal_eval(results)

        formatted_data = {"series": []}

        if len(results[0]) == 2:
            formatted_data["series"].append(
                {
                    "data": [
                        {"x": float(x), "y": float(y), "id": i + 1}
                        for i, (x, y) in enumerate(results)
                    ],
                    "label": "Data Points",
                }
            )
        elif len(results[0]) == 3:
            entities = {}
            for item1, item2, item3 in results:
                # Determine which item is the label (string not convertible to float and not containing "/")
                if (
                    isinstance(item1, str)
                    and not item1.replace(".", "").isdigit()
                    and "/" not in item1
                ):
                    label, x, y = item1, item2, item3
                else:
                    x, label, y = item1, item2, item3
                if label not in entities:
                    entities[label] = []
                entities[label].append(
                    {"x": float(x), "y": float(y), "id": len(entities[label]) + 1}
                )

            for label, data in entities.items():
                formatted_data["series"].append({"data": data, "label": label})
        else:
            raise ValueError("Unexpected data format in results")

        return {"formatted_data_for_visualization": formatted_data}

    def _format_bar_data(self, results, question):
        if isinstance(results, str):
            results = literal_eval(results)

        if len(results[0]) == 2:
            # Simple bar chart with one series
            labels = [str(row[0]) for row in results]
            data = [float(row[1]) for row in results]

            # Use LLM to get a relevant label
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are a data labeling expert. Given a question and some data, provide a concise and relevant label for the data series.",
                    ),
                    (
                        "human",
                        "Question: {question}\nData (first few rows): {data}\n\nProvide a concise label for this y axis. For example, if the data is the sales figures for products, the label could be 'Sales'. If the data is the population of cities, the label could be 'Population'. If the data is the revenue by region, the label could be 'Revenue'.",
                    ),
                ]
            )
            label = self.llm_manager.invoke(
                prompt, question=question, data=str(results[:2])
            )

            values = [{"data": data, "label": label}]
        elif len(results[0]) == 3:
            # Grouped bar chart with multiple series
            categories = set(row[1] for row in results)
            labels = list(categories)
            entities = set(row[0] for row in results)
            values = []
            for entity in entities:
                entity_data = [float(row[2]) for row in results if row[0] == entity]
                values.append({"data": entity_data, "label": str(entity)})
        else:
            raise ValueError("Unexpected data format in results")

        formatted_data = {"labels": labels, "values": values}

        return {"formatted_data_for_visualization": formatted_data}

    def _format_other_visualizations(self, visualization, question, sql_query, results):
        instructions = graph_instructions[visualization]
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a Data expert who formats data according to the required needs. You are given the question asked by the user, it's sql query, the result of the query and the format you need to format it in.",
                ),
                (
                    "human",
                    "For the given question: {question}\n\nSQL query: {sql_query}\n\nResult: {results}\n\nUse the following example to structure the data: {instructions}. Just give the json string. Do not format it",
                ),
            ]
        )
        response = self.llm_manager.invoke(
            prompt,
            question=question,
            sql_query=sql_query,
            results=results,
            instructions=instructions,
        )

        try:
            formatted_data_for_visualization = json.loads(response)
            return {
                "formatted_data_for_visualization": formatted_data_for_visualization
            }
        except json.JSONDecodeError:
            return {
                "error": "Failed to format data for visualization",
                "raw_response": response,
            }


barGraphIntstruction = """

  Where data is: {
    labels: string[]
    values: {data: number[], label: string}[]
  }

// Examples of usage:
Each label represents a column on the x axis.
Each array in values represents a different entity. 

Here we are looking at average income for each month.
1. data = {
  labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
  values: [{data:[21.5, 25.0, 47.5, 64.8, 105.5, 133.2], label: 'Income'}],
}

Here we are looking at the performance of american and european players for each series. Since there are two entities, we have two arrays in values.
2. data = {
  labels: ['series A', 'series B', 'series C'],
  values: [{data:[10, 15, 20], label: 'American'}, {data:[20, 25, 30], label: 'European'}],
}
"""

horizontalBarGraphIntstruction = """

  Where data is: {
    labels: string[]
    values: {data: number[], label: string}[]
  }

// Examples of usage:
Each label represents a column on the x axis.
Each array in values represents a different entity. 

Here we are looking at average income for each month.
1. data = {
  labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
  values: [{data:[21.5, 25.0, 47.5, 64.8, 105.5, 133.2], label: 'Income'}],
}

Here we are looking at the performance of american and european players for each series. Since there are two entities, we have two arrays in values.
2. data = {
  labels: ['series A', 'series B', 'series C'],
  values: [{data:[10, 15, 20], label: 'American'}, {data:[20, 25, 30], label: 'European'}],
}

"""


lineGraphIntstruction = """

  Where data is: {
  xValues: number[] | string[]
  yValues: { data: number[]; label: string }[]
}

// Examples of usage:

Here we are looking at the momentum of a body as a function of mass.
1. data = {
  xValues: ['2020', '2021', '2022', '2023', '2024'],
  yValues: [
    { data: [2, 5.5, 2, 8.5, 1.5]},
  ],
}

Here we are looking at the performance of american and european players for each year. Since there are two entities, we have two arrays in yValues.
2. data = {
  xValues: ['2020', '2021', '2022', '2023', '2024'],
  yValues: [
    { data: [2, 5.5, 2, 8.5, 1.5], label: 'American' },
    { data: [2, 5.5, 2, 8.5, 1.5], label: 'European' },
  ],
}
"""

pieChartIntstruction = """

  Where data is: {
    labels: string
    values: number
  }[]

// Example usage:
 data = [
        { id: 0, value: 10, label: 'series A' },
        { id: 1, value: 15, label: 'series B' },
        { id: 2, value: 20, label: 'series C' },
      ],
"""

scatterPlotIntstruction = """
Where data is: {
  series: {
    data: { x: number; y: number; id: number }[]
    label: string
  }[]
}

// Examples of usage:
1. Here each data array represents the points for a different entity. 
We are looking for correlation between amount spent and quantity bought for men and women.
data = {
  series: [
    {
      data: [
        { x: 100, y: 200, id: 1 },
        { x: 120, y: 100, id: 2 },
        { x: 170, y: 300, id: 3 },
      ],
      label: 'Men',
    },
    {
      data: [
        { x: 300, y: 300, id: 1 },
        { x: 400, y: 500, id: 2 },
        { x: 200, y: 700, id: 3 },
      ],
      label: 'Women',
    }
  ],
}

2. Here we are looking for correlation between the height and weight of players.
data = {
  series: [
    {
      data: [
        { x: 180, y: 80, id: 1 },
        { x: 170, y: 70, id: 2 },
        { x: 160, y: 60, id: 3 },
      ],
      label: 'Players',
    },
  ],
}

// Note: Each object in the 'data' array represents a point on the scatter plot.
// The 'x' and 'y' values determine the position of the point, and 'id' is a unique identifier.
// Multiple series can be represented, each as an object in the outer array.
"""


graph_instructions = {
    "bar": barGraphIntstruction,
    "horizontal_bar": horizontalBarGraphIntstruction,
    "line": lineGraphIntstruction,
    "pie": pieChartIntstruction,
    "scatter": scatterPlotIntstruction,
}
