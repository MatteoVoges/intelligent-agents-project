"""QLoRA fine-tuning for a persona/style adapter.

Usage (inside WSL2, with the `train` extra):
    uv run --extra train training/train_lora.py --config training/configs/persona_a.yaml

Dataset format (JSONL), one object per line:
    {"messages": [{"role": "system", "content": "..."},
                  {"role": "user", "content": "..."},
                  {"role": "assistant", "content": "..."}]}

Note: adapters are trained on the fp16/NF4 base here, then served on the AWQ base by vLLM.
Validate that they load and change output (PLAN.md Phase 4 gate) before relying on this.
"""

from __future__ import annotations

import argparse

import yaml


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    cfg = load_config(ap.parse_args().config)

    # Heavy imports deferred so the file is importable without the training stack.
    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from peft import get_peft_model
    from peft import prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM
    from transformers import AutoTokenizer
    from transformers import BitsAndBytesConfig
    from trl import SFTConfig
    from trl import SFTTrainer

    base_model = cfg["base_model"]
    tok = AutoTokenizer.from_pretrained(base_model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base_model, quantization_config=bnb, device_map="auto", torch_dtype=torch.bfloat16
    )
    model = prepare_model_for_kbit_training(model)

    lora = cfg.get("lora", {})
    peft_cfg = LoraConfig(
        r=lora.get("r", 16),
        lora_alpha=lora.get("alpha", 32),
        lora_dropout=lora.get("dropout", 0.05),
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=lora.get(
            "target_modules",
            ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        ),
    )
    model = get_peft_model(model, peft_cfg)
    model.print_trainable_parameters()

    ds = load_dataset("json", data_files=cfg["dataset_path"], split="train")

    def format_example(ex: dict) -> dict:
        return {"text": tok.apply_chat_template(ex["messages"], tokenize=False)}

    ds = ds.map(format_example, remove_columns=ds.column_names)

    tr = cfg.get("training", {})
    args = SFTConfig(
        output_dir=cfg["output_dir"],
        num_train_epochs=tr.get("epochs", 3),
        per_device_train_batch_size=tr.get("batch_size", 2),
        gradient_accumulation_steps=tr.get("grad_accum", 4),
        learning_rate=tr.get("lr", 2e-4),
        max_seq_length=tr.get("max_seq_len", 1024),
        logging_steps=10,
        save_strategy="epoch",
        bf16=True,
        dataset_text_field="text",
        report_to=[],
    )
    trainer = SFTTrainer(model=model, args=args, train_dataset=ds)
    trainer.train()

    trainer.model.save_pretrained(cfg["output_dir"])
    tok.save_pretrained(cfg["output_dir"])
    print(f"Saved adapter to {cfg['output_dir']}")


if __name__ == "__main__":
    main()
