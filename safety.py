from __future__ import annotations

import re

import sqlparse


DANGEROUS_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "REPLACE",
    "PRAGMA",
    "ATTACH",
    "DETACH",
    "VACUUM",
}


COMMENT_PATTERN = re.compile(r"(--|/\*|\*/)")


def _contains_dangerous_keyword(sql: str) -> str | None:
    normalized = sql.upper()
    for keyword in sorted(DANGEROUS_KEYWORDS):
        if re.search(rf"\b{re.escape(keyword)}\b", normalized):
            return keyword
    return None


def validate_user_question(question: str) -> tuple[bool, str]:
    clean_question = (question or "").strip()
    if not clean_question:
        return False, "Question must not be empty."

    if COMMENT_PATTERN.search(clean_question):
        return False, "SQL comment syntax is not allowed in questions."

    dangerous_keyword = _contains_dangerous_keyword(clean_question)
    if dangerous_keyword:
        return False, f"Dangerous database operation blocked: {dangerous_keyword}."

    return True, "Question is safe."


def validate_sql(sql: str) -> tuple[bool, str]:
    if not sql or not sql.strip():
        return False, "SQL must not be empty."

    stripped_sql = sql.strip()

    if COMMENT_PATTERN.search(stripped_sql):
        return False, "SQL comments are not allowed."

    # Ignore literal values when checking executable SQL tokens.
    parsed_statements = sqlparse.parse(stripped_sql)
    code_tokens = [
        token for statement in parsed_statements for token in statement.flatten()
        if token.ttype not in sqlparse.tokens.Literal.String
    ]
    dangerous_keyword = _contains_dangerous_keyword(" ".join(token.value for token in code_tokens))
    if dangerous_keyword:
        return False, f"Unsafe SQL keyword blocked: {dangerous_keyword}."

    statements = [statement for statement in sqlparse.parse(stripped_sql) if statement.tokens]
    if len(statements) != 1:
        return False, "Only one SQL statement is allowed."

    semicolons = [token for token in code_tokens if token.value == ";"]
    if len(semicolons) > 1 or (semicolons and not stripped_sql.endswith(";")):
        return False, "Multiple SQL statements are not allowed."

    statement = statements[0]
    statement_type = statement.get_type()
    if statement_type != "SELECT":
        return False, "Only read-only SELECT statements are allowed."

    return True, "SQL is safe."
