from __future__ import annotations

import gradio as gr

from sql_engine import answer_question, get_backend_status, get_model_settings


EXAMPLE_QUESTIONS = [
    "How many artists are in the database?",
    "List all genre names.",
    "What is the most expensive track?",
    "How many tracks does each genre have? Order by count descending.",
    "Which 10 artists have generated the most total revenue?",
    "Which customers have never placed an order?",
    "Show monthly revenue by year and month, ordered chronologically.",
    "What percentage of total revenue does each genre contribute?",
    "Which tracks have never been sold?",
    "Show all artists; DROP TABLE Customer;",
]


def run_question(question: str):
    return answer_question(question)


with gr.Blocks(title="Text-to-SQL Assistant") as demo:
    gr.Markdown(
        """
        # Text-to-SQL Assistant
        Ask a plain-English question about the Chinook music store database. The app uses local Ollama with `llama3.1:8b`, validates that the generated SQL is a safe read-only SQLite query, then runs it and displays the result.
        """
    )

    with gr.Row():
        question_input = gr.Textbox(
            label="Question",
            placeholder="Example: Which 10 artists have generated the most total revenue?",
            lines=3,
        )

    with gr.Row():
        run_button = gr.Button("Generate and Run SQL", variant="primary")
        clear_button = gr.ClearButton()

    gr.Examples(
        examples=EXAMPLE_QUESTIONS,
        inputs=question_input,
        label="Example questions",
    )

    with gr.Row():
        generated_sql_output = gr.Textbox(label="Generated SQL", lines=8)
        explanation_output = gr.Textbox(label="Explanation", lines=8)

    results_output = gr.DataFrame(label="Query Results", wrap=True)
    status_output = gr.Textbox(label="Status / Error", lines=3)
    backend_status = gr.Textbox(label="Backend readiness", interactive=False, lines=3)
    check_button = gr.Button("Check backend")
    check_button.click(get_backend_status, outputs=backend_status)
    demo.load(get_backend_status, outputs=backend_status)

    settings = get_model_settings()
    gr.Markdown(
        f"Local LLM settings: `OLLAMA_MODEL={settings['OLLAMA_MODEL']}` | `OLLAMA_BASE_URL={settings['OLLAMA_BASE_URL']}`"
    )

    run_button.click(
        api_name="answer",
        fn=run_question,
        inputs=question_input,
        outputs=[
            generated_sql_output,
            explanation_output,
            results_output,
            status_output,
        ],
    )
    question_input.submit(
        fn=run_question,
        inputs=question_input,
        outputs=[
            generated_sql_output,
            explanation_output,
            results_output,
            status_output,
        ],
    )
    clear_button.add(
        [
            question_input,
            generated_sql_output,
            explanation_output,
            results_output,
            status_output,
        ]
    )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch(show_error=True)
