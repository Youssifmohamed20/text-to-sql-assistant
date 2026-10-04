import json
import sqlite3
import tempfile
import io
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

import sql_engine
import db_setup
from db_setup import execute_sql
from safety import validate_sql
from schema_validator import validate_schema_references


class SQLTests(unittest.TestCase):
    def test_database_download_is_validated_and_atomic(self):
        database_bytes = db_setup.DB_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Chinook.sqlite"
            with patch("db_setup.BASE_DIR", Path(directory)), patch("db_setup.DB_PATH", path), patch("db_setup.urllib.request.urlopen", return_value=io.BytesIO(database_bytes)):
                self.assertEqual(db_setup.download_database_if_missing(), path)
                self.assertEqual(path.read_bytes(), database_bytes)

    def test_invalid_download_does_not_leave_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Chinook.sqlite"
            with patch("db_setup.BASE_DIR", Path(directory)), patch("db_setup.DB_PATH", path), patch("db_setup.urllib.request.urlopen", return_value=io.BytesIO(b"not a database")):
                with self.assertRaises(FileNotFoundError):
                    db_setup.download_database_if_missing()
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_real_database(self):
        result = execute_sql("SELECT COUNT(*) AS count FROM Artist")
        self.assertEqual(result.iloc[0, 0], 275)

    def test_database_enforces_read_only(self):
        from db_setup import get_connection
        conn = get_connection()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE forbidden (id INTEGER)")
        finally:
            conn.close()

    def test_unsafe_sql(self):
        for sql in ["DROP TABLE Artist", "SELECT 1; SELECT 2", "WITH t AS (SELECT 1) DELETE FROM Artist", "SELECT 1 -- comment"]:
            with self.subTest(sql=sql):
                self.assertFalse(validate_sql(sql)[0])

    def test_literal_keywords_and_semicolons(self):
        self.assertTrue(validate_sql("SELECT 'DROP; DELETE' AS value;")[0])

    def test_schema_resolution(self):
        queries = [
            'SELECT "a"."Name" FROM "Artist" AS "a"',
            "WITH totals AS (SELECT ArtistId FROM Artist) SELECT t.ArtistId FROM TOTALS t",
            "SELECT a.Name FROM Artist a WHERE EXISTS (SELECT 1 FROM Album a WHERE a.ArtistId = 1)",
        ]
        for query in queries:
            with self.subTest(query=query):
                self.assertTrue(validate_schema_references(query)[0])

    def test_missing_schema_references(self):
        for query in ["SELECT * FROM MissingTable", "SELECT MissingColumn FROM Artist", "SELECT a.Title FROM Artist a"]:
            with self.subTest(query=query):
                self.assertFalse(validate_schema_references(query)[0])


class BackendTests(unittest.TestCase):
    def test_unavailable_backend(self):
        with patch("sql_engine.Client", side_effect=ConnectionError("connection refused")):
            result = sql_engine.answer_question("How many artists?")
        self.assertIn("Cannot reach Ollama", result[3])
        self.assertTrue(result[2].empty)

    def test_missing_model(self):
        with patch("sql_engine.Client") as client:
            client.return_value.list.return_value = SimpleNamespace(models=[])
            with self.assertRaisesRegex(RuntimeError, "ollama pull"):
                sql_engine.check_backend()

    def test_available_model(self):
        model = SimpleNamespace(model=sql_engine.OLLAMA_MODEL)
        with patch("sql_engine.Client") as client:
            client.return_value.list.return_value = SimpleNamespace(models=[model])
            self.assertIn("Ready", sql_engine.check_backend())

    def test_empty_and_unsafe_questions_skip_model(self):
        with patch("sql_engine.check_backend") as check:
            self.assertIn("Please enter", sql_engine.answer_question("")[3])
            self.assertIn("Blocked", sql_engine.answer_question("DROP TABLE Artist")[3])
            check.assert_not_called()

    def test_generation_and_execution(self):
        output = json.dumps({"sql": "SELECT COUNT(*) AS count FROM Artist", "explanation": "Counts artists."})
        with patch("sql_engine.check_backend"), patch("sql_engine._build_llm", return_value=RunnableLambda(lambda _: output)):
            result = sql_engine.answer_question("How many artists?")
        self.assertEqual(result[2].iloc[0, 0], 275)
        self.assertIn("Success", result[3])

    def test_sql_repair(self):
        responses = iter([
            json.dumps({"sql": "SELECT Missing FROM Artist", "explanation": "Bad column"}),
            json.dumps({"sql": "SELECT COUNT(*) AS count FROM Artist", "explanation": "Counts artists"}),
        ])
        with patch("sql_engine.check_backend"), patch("sql_engine._build_llm", return_value=RunnableLambda(lambda _: next(responses))):
            result = sql_engine.answer_question("How many artists?")
        self.assertEqual(result[2].iloc[0, 0], 275)
        self.assertIn("Repaired", result[3])

    def test_invalid_model_response(self):
        with patch("sql_engine.check_backend"), patch("sql_engine._build_llm", return_value=RunnableLambda(lambda _: "invalid response")):
            result = sql_engine.answer_question("How many artists?")
        self.assertIn("JSON", result[3])


if __name__ == "__main__":
    unittest.main()
