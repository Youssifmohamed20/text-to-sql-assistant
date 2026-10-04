"""Verify the configured live Ollama model against the real database."""
from sql_engine import answer_question


if __name__ == "__main__":
    sql, explanation, dataframe, status = answer_question("How many artists are in the database?")
    print(sql)
    print(dataframe)
    print(status)
    assert status.startswith(("Success", "Repaired")), status
    assert dataframe.shape == (1, 1) and dataframe.iloc[0, 0] == 275, dataframe
