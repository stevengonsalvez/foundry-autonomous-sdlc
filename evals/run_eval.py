"""
Foundry evaluation harness for SDLC agent requirements gate.

Executes local or cloud evaluation against requirement quality datasets,
running both built-in evaluators (TaskAdherenceEvaluator) and custom code
evaluators (ScoreBandEvaluator).

Credentials: uses DefaultAzureCredential (Entra ID service principal or az login).
No secrets or API keys are stored in code or repository files.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from azure.ai.evaluation import TaskAdherenceEvaluator, evaluate
from azure.identity import DefaultAzureCredential, EnvironmentCredential

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.evaluators.score_band import ScoreBandEvaluator

DEFAULT_ENDPOINT = "https://aif-fsdlcd-demo-cnfoi.services.ai.azure.com/api/projects/proj-sdlc"
DEFAULT_DEPLOYMENT = "sdlc-default"
DEFAULT_DATASET = Path(__file__).parent / "datasets" / "req_gate_golden.jsonl"
DEFAULT_OUTPUT = Path(__file__).parent / "results" / "evaluation_results.json"

# GPT-5-mini list pricing (UK South / GlobalStandard): $0.15 / 1M prompt, $0.60 / 1M completion
PRICE_INPUT_1M = 0.15
PRICE_OUTPUT_1M = 0.60


def load_env_file_if_present(env_path: Path | None = None) -> None:
    """Load environment variables from a file if present, without echoing values."""
    candidates = [
        env_path,
        Path.home() / ".secrets" / "azure-sp.env",
    ]
    for p in candidates:
        if p and p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip("\"'"))
            break


def get_credential() -> Any:
    """Obtain Entra ID token credential."""
    if os.environ.get("AZURE_CLIENT_ID") and os.environ.get("AZURE_CLIENT_SECRET"):
        return EnvironmentCredential()
    return DefaultAzureCredential()


def run_evaluation(
    dataset_path: Path,
    *,
    mode: str = "cloud",
    project_endpoint: str = DEFAULT_ENDPOINT,
    deployment_name: str = DEFAULT_DEPLOYMENT,
    output_path: Path = DEFAULT_OUTPUT,
    tolerance: int = 10,
    limit: int | None = None,
) -> dict[str, Any]:
    """Execute evaluation run over the dataset."""
    load_env_file_if_present()
    cred = get_credential()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Slice dataset if limit requested
    run_dataset_path = dataset_path
    if limit is not None:
        sliced_file = output_path.parent / f"sliced_{limit}.jsonl"
        with open(dataset_path, "r", encoding="utf-8") as fin, open(sliced_file, "w", encoding="utf-8") as fout:
            for idx, line in enumerate(fin):
                if idx >= limit:
                    break
                fout.write(line)
        run_dataset_path = sliced_file

    # Count rows
    with open(run_dataset_path, "r", encoding="utf-8") as f:
        row_count = sum(1 for line in f if line.strip())

    print(f"Loaded {row_count} evaluation rows from {run_dataset_path}")

    # Model configuration for TaskAdherenceEvaluator judge
    # Uses the account's OpenAI endpoint derived from the project endpoint or resource name
    account_prefix = project_endpoint.split("://")[1].split(".")[0]
    azure_openai_endpoint = f"https://{account_prefix}.openai.azure.com/"

    model_config = {
        "azure_endpoint": azure_openai_endpoint,
        "azure_deployment": deployment_name,
    }

    # Initialize evaluators
    task_adherence = TaskAdherenceEvaluator(
        model_config=model_config,
        credential=cred,
        is_reasoning_model=True,
    )
    score_band = ScoreBandEvaluator(tolerance=tolerance)

    evaluators = {
        "task_adherence": task_adherence,
        "score_band": score_band,
    }

    evaluator_config = {
        "task_adherence": {
            "column_mapping": {
                "query": "${data.query}",
                "response": "${data.response}",
            }
        },
        "score_band": {
            "column_mapping": {
                "score": "${data.score}",
                "expected_min": "${data.expected_min}",
                "expected_max": "${data.expected_max}",
                "expected_gate": "${data.expected_gate}",
            }
        },
    }

    azure_ai_project = project_endpoint if mode == "cloud" else None
    eval_name = f"req-gate-eval-{int(time.time())}"

    print(f"Starting evaluation (mode={mode}, judge={deployment_name})...")
    start_time = time.time()

    results = evaluate(
        data=str(run_dataset_path),
        evaluators=evaluators,
        evaluator_config=evaluator_config,
        azure_ai_project=azure_ai_project,
        credential=cred,
        output_path=str(output_path),
        evaluation_name=eval_name,
    )

    elapsed_s = time.time() - start_time
    print(f"Evaluation completed in {elapsed_s:.2f}s")

    studio_url = results.get("studio_url")
    metrics = results.get("metrics", {})

    # Extract token metrics if present in rows
    rows_data = results.get("rows", [])
    total_prompt_tokens = 0
    total_completion_tokens = 0
    for r in rows_data:
        props = r.get("outputs.task_adherence.task_adherence_properties", {})
        if isinstance(props, dict):
            total_prompt_tokens += props.get("prompt_tokens", 0)
            total_completion_tokens += props.get("completion_tokens", 0)

    est_cost_usd = (total_prompt_tokens * PRICE_INPUT_1M + total_completion_tokens * PRICE_OUTPUT_1M) / 1_000_000

    summary = {
        "evaluation_name": eval_name,
        "mode": mode,
        "rows": row_count,
        "elapsed_seconds": round(elapsed_s, 2),
        "metrics": metrics,
        "studio_url": studio_url,
        "tokens": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        },
        "estimated_cost_usd": round(est_cost_usd, 6),
    }

    summary_file = output_path.parent / "evaluation_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n=== EVALUATION RUN SUMMARY ===")
    print(f"Rows Evaluated: {row_count}")
    print(f"Execution Time: {elapsed_s:.2f}s")
    print(f"In-Band Pass Rate: {metrics.get('score_band.score_in_band', 'N/A')}")
    print(f"Gate Match Rate:  {metrics.get('score_band.gate_match', 'N/A')}")
    print(f"Task Adherence:   {metrics.get('task_adherence.task_adherence_passed', 'N/A')}")
    print(f"Prompt Tokens:    {total_prompt_tokens}")
    print(f"Comp Tokens:      {total_completion_tokens}")
    print(f"Estimated Cost:   ${est_cost_usd:.5f} USD")
    if studio_url:
        print(f"Foundry Studio URL: {studio_url}")
    print("==============================\n")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SDLC agent requirement evaluation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to JSONL dataset")
    parser.add_argument("--mode", choices=["cloud", "local"], default="cloud", help="Evaluation target mode")
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT, help="Foundry project endpoint")
    parser.add_argument("--deployment", type=str, default=DEFAULT_DEPLOYMENT, help="Judge model deployment")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON path")
    parser.add_argument("--tolerance", type=int, default=10, help="Score band tolerance points")
    parser.add_argument("--limit", type=int, default=None, help="Optional row count limit")

    args = parser.parse_args()
    run_evaluation(
        dataset_path=args.dataset,
        mode=args.mode,
        project_endpoint=args.endpoint,
        deployment_name=args.deployment,
        output_path=args.output,
        tolerance=args.tolerance,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
