"""Exercise actual Gradio HTTP callbacks with deterministic model responses."""
import json
from unittest.mock import patch

from gradio_client import Client
from langchain_core.runnables import RunnableLambda

from app import demo


if __name__ == "__main__":
    output = json.dumps({"sql": "SELECT COUNT(*) AS artist_count FROM Artist", "explanation": "Counts artists."})
    try:
        demo.queue().launch(server_name="127.0.0.1", server_port=7862, prevent_thread_lock=True, quiet=True)
        client = Client("http://127.0.0.1:7862", verbose=False)
        result = client.predict("", api_name="/answer")
        assert result[3] == "Please enter a question.", result
        with patch("sql_engine.check_backend"), patch("sql_engine._build_llm", return_value=RunnableLambda(lambda _: output)):
            result = client.predict("How many artists are in the database?", api_name="/answer")
        assert result[2]["data"] == [[275]], result
        assert "Success" in result[3], result
        with patch("sql_engine.Client", side_effect=ConnectionError("connection refused")):
            result = client.predict("List genres", api_name="/answer")
        assert "Cannot reach Ollama" in result[3], result
        print("Gradio HTTP callbacks passed: empty input, SQL results, backend failure.")
    finally:
        demo.close()
