import json
# import torch
import pandas as pd

# import apps.eval.reident

# from apps_utils.generate_gpt_codes import generate_prompt
# from apps_utils.test_one_solution import eval_and_save_problems
from datasets import load_dataset, load_metric
from fastcore.script import *
from human_eval.data import write_jsonl, read_problems
from human_eval.evaluation import evaluate_functional_correctness
from pathlib import Path
from tqdm.auto import tqdm
# from metrics.extrinsic_eval import compute_metrics
from subprocess import check_output
from transformers import (
    AutoTokenizer,
    FlaxGPTNeoForCausalLM,
    GPTNeoForCausalLM
)

# bleu = load_metric("sacrebleu")

MAX_TOKS = 1024
MAX_NEW_TOKS = 64


def generate_text_jax(prompt):
    inputs = tokenizer(prompt, return_tensors="jax")
    output_seq = model.generate(
        input_ids=inputs.input_ids, do_sample=True, max_length=MAX_TOKS, temperature=0.8
    )
    output = tokenizer.decode(output_seq["sequences"][0])
    # print(output)
    return output

def generate_text(prompt, n, tokenizer, model):
    inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
    output_seq = model.generate(
        input_ids=inputs.input_ids, max_length=MAX_TOKS,
        max_new_tokens=MAX_NEW_TOKS, 
        do_sample=True, temperature=0.8,
        num_return_sequences=n
    )
    return tokenizer.batch_decode(output_seq, skip_special_tokens=False)

def _eval_concode(path):
    # TODO: format input to model same as App and OpenAI HumanEval datasets are formatted
    data = load_dataset("json", data_files=str(path / "test.json"))["train"]
    predictions = [[]]
    references = []
    for example in data:
        output = generate_text(example["nl"])
        predictions[0].append(output.split(" "))
        references.append(example["code"].split(" "))
    results = compute_metrics(predictions, references)
    print(f"Bleu score for Concode dataset: {results}")


def _eval_apps(path):

    gpt_codes = {}
    apps_ds = load_dataset("../data_processing/apps.py")["test"]
    for idx, example in tqdm(enumerate(apps_ds)):
        answer = generate_text(example["question"])
        gpt_codes[idx] = answer
    with open(path.parent / "all_codes.json", "w") as f:
        json.dump(gpt_codes, f)

    eval_and_save_problems(path, path.parent)


def _eval_human_eval(path, out_path, tokenizer, model):
    problems = read_problems(str(path))
    num_samples_per_task = 10
    samples = []
    for task_id in tqdm(list(problems.keys())):
        for text in generate_text(
                problems[task_id]["prompt"],
                num_samples_per_task,
                tokenizer,
                model
            ):
            samples.append(dict(task_id=task_id, completion=text))
    
    write_jsonl(str(out_path / "human_eval.jsonl"), samples)

    # test out generated functions
    results = evaluate_functional_correctness(str(out_path / "human_eval.jsonl"), [1, 2, 5, 10], 4, 3.0, str(path))
    print(results)


@call_parse
def main(
    model_name_or_path: Param("Name or path of model to evaluate", str),
    concode_path: Param("Path to the concode data in CodeXGLUE", str),
    apps_path: Param("Path to the the App dataset", str),
    human_eval_path: Param("Path to the human eval dataset", str),
    out_path: Param("Path to save results", str),
):
    concode_path = Path(concode_path)
    apps_path = Path(apps_path)
    human_eval_path = Path(human_eval_path)
    out_path = Path(out_path)
    out_path = out_path / model_name_or_path.split("/")[-1]
    out_path.mkdir(exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(
        model_name_or_path, padding_side="left", pad_token="<|endoftext|>"
    )
    model = GPTNeoForCausalLM.from_pretrained(
        model_name_or_path,
        pad_token_id=50256,
        # revision=branch
    ).to("cuda")


    # _eval_concode(concode_path)
    _eval_human_eval(human_eval_path, out_path, tokenizer, model)
    # _eval_apps(apps_path)