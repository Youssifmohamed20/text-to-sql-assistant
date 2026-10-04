from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_ollama import ChatOllama
from ollama import Client

from db_setup import build_schema_context, execute_sql
from prompt_templates import create_prompt_template
from safety import validate_sql, validate_user_question
from schema_validator import validate_schema_references


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LOG_FILE = BASE_DIR / "query_log.txt"


def check_backend() -> str:
    """Check the actual model dependency before attempting generation."""
    try:
        models = Client(host=OLLAMA_BASE_URL, timeout=5).list().models
    except Exception as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {OLLAMA_BASE_URL}. Install Ollama from "
            "https://ollama.com/download/windows, start it (ollama serve), "
            f"then run: ollama pull {OLLAMA_MODEL}. Details: {exc}"
        ) from exc
    model_name = OLLAMA_MODEL if ":" in OLLAMA_MODEL else f"{OLLAMA_MODEL}:latest"
    available = [model.model for model in models]
    if model_name not in available:
        raise RuntimeError(
            f"Ollama is running, but model '{OLLAMA_MODEL}' is missing. "
            f"Run: ollama pull {OLLAMA_MODEL}. Available models: "
            + (", ".join(available) or "none")
        )
    return f"Ready: Ollama model {OLLAMA_MODEL} is available."


def get_backend_status() -> str:
    try:
        build_schema_context()
        return check_backend()
    except Exception as exc:
        return str(exc)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def _empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame()


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("The model did not return a JSON object.")

    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("The model JSON output was not an object.")
    return parsed


def _log_question(question: str, sql: str, status: str) -> None:
    logging.info("question=%r | sql=%r | status=%s", question, sql, status)


def _build_llm() -> ChatOllama:
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
        format="json",
        num_ctx=8192,
        num_predict=2048,
        client_kwargs={"timeout": 180},
    )


def build_chain():
    schema_context = build_schema_context()
    prompt = create_prompt_template()
    llm = _build_llm()
    return prompt | llm | StrOutputParser(), schema_context


def _validate_and_execute(sql: str) -> pd.DataFrame:
    is_safe, safety_message = validate_sql(sql)
    if not is_safe:
        raise ValueError(f"SQL safety validation failed: {safety_message}")

    schema_is_valid, schema_message = validate_schema_references(sql)
    if not schema_is_valid:
        raise ValueError(f"SQL schema validation failed: {schema_message}")

    return execute_sql(sql)


def _repair_sql(
    question: str,
    schema_context: str,
    bad_sql: str,
    error_message: str,
) -> tuple[str, str]:
    repair_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You repair failed SQLite SELECT queries for the Chinook Music Store database.

Schema context:
{schema}

Rules:
- Return JSON only.
- SELECT only.
- SQLite only.
- Use only schema tables/columns.
- Every referenced table/alias must be in FROM/JOIN.
- Do not reference columns that do not exist.
- Use explicit JOIN conditions.
- Use CTEs for aggregate comparisons.
- Identify the correct result grain before writing SQL.
- Aggregate detail rows to the requested entity/group grain before comparing totals, averages, minimums, maximums, or ranks.
- Return every metric requested by the question explicitly.
- For top item per group, compute the metric in a CTE and use ROW_NUMBER() OVER (PARTITION BY group ORDER BY metric DESC/ASC), then filter to row number 1.
- Do not reference SELECT aliases from the same SELECT level's WHERE clause or from sibling subqueries.
- Use LEFT JOIN and COALESCE for optional related information when appropriate.
- Do not include comments, markdown fences, or multiple SQL statements.

Return only valid JSON in this exact shape:
{{"sql": "SELECT ...", "explanation": "Short explanation ..."}}""",
            ),
            (
                "human",
                """Original question:
{question}

Failed SQL:
{bad_sql}

Validation/execution error:
{error_message}

Repair the SQL generally using the schema. Return only the JSON object.""",
            ),
        ]
    )
    chain = repair_prompt | _build_llm() | StrOutputParser()
    raw_output = chain.invoke(
        {
            "schema": schema_context,
            "question": question,
            "bad_sql": bad_sql,
            "error_message": error_message,
        }
    )
    parsed = _extract_json_object(raw_output)
    return (
        str(parsed.get("sql", "") or "").strip(),
        str(parsed.get("explanation", "") or "").strip(),
    )


def answer_question(question: str) -> tuple[str, str, pd.DataFrame, str]:
    clean_question = (question or "").strip()
    if not clean_question:
        status = "Please enter a question."
        _log_question("", "", status)
        return "", "No question was provided.", _empty_dataframe(), status

    question_is_safe, question_safety_message = validate_user_question(clean_question)
    if not question_is_safe:
        status = f"Blocked unsafe question: {question_safety_message}"
        _log_question(clean_question, "", status)
        return "", question_safety_message, _empty_dataframe(), status

    try:
        check_backend()
        chain, schema_context = build_chain()
        raw_output = chain.invoke({"schema": schema_context, "question": clean_question})
        parsed = _extract_json_object(raw_output)

        generated_sql = str(parsed.get("sql", "") or "").strip()
        explanation = str(parsed.get("explanation", "") or "").strip()

        if not generated_sql:
            status = "No SQL was generated because the question cannot be answered from this schema."
            _log_question(clean_question, generated_sql, status)
            return generated_sql, explanation, _empty_dataframe(), status

        try:
            dataframe = _validate_and_execute(generated_sql)
        except Exception as first_error:
            first_error_message = str(first_error)
            _log_question(
                clean_question,
                generated_sql,
                f"Initial SQL failed. Error: {first_error_message}",
            )

            try:
                repaired_sql, repaired_explanation = _repair_sql(
                    clean_question,
                    schema_context,
                    generated_sql,
                    first_error_message,
                )
                if not repaired_sql:
                    raise ValueError("Repair did not return SQL.")

                repaired_dataframe = _validate_and_execute(repaired_sql)
                status = (
                    "Repaired after initial failure. "
                    f"Initial error: {first_error_message} "
                    f"Returned {len(repaired_dataframe)} row(s)."
                )
                _log_question(clean_question, repaired_sql, status)
                return repaired_sql, repaired_explanation, repaired_dataframe, status
            except Exception as repair_error:
                status = (
                    "Initial SQL failed and repair was unsuccessful. "
                    f"Initial error: {first_error_message} "
                    f"Repair error: {repair_error}"
                )
                _log_question(clean_question, generated_sql, status)
                return generated_sql, explanation or first_error_message, _empty_dataframe(), status

        status = f"Success. Returned {len(dataframe)} row(s)."
        _log_question(clean_question, generated_sql, status)
        return generated_sql, explanation, dataframe, status

    except Exception as exc:
        status = f"Could not process this question: {exc}"
        _log_question(clean_question, "", f"{status} Error: {exc}")
        return "", str(exc), _empty_dataframe(), status


def get_model_settings() -> dict[str, str]:
    return {
        "OLLAMA_MODEL": OLLAMA_MODEL,
        "OLLAMA_BASE_URL": OLLAMA_BASE_URL,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
