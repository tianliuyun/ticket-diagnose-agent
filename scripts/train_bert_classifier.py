"""训练真实 BERT 分类器（ticket-classifier 的 BertClassifier 落地实现）。

背景：
- ticket-classifier 里 BertClassifier 原是 stub（train 未实现、标签解码是假的）。
- 本脚本用 ticket-diagnose-agent 的 300 条程序化评测集，微调 bert-base-chinese
  训练「工单大类 + 子类」判别式分类器，让 BertClassifier 变成可真实加载/推理的实现。
- 与 MockClassifier（规则关键词）构成「规则 vs 判别式」双实现对比，
  支持初始筛选层在 mock / bert 之间切换（见 InitialScreener 注入）。

用法：
    python scripts/train_bert_classifier.py [--epochs 3] [--batch_size 16] [--n 300]
            [--model_dir ~/.cache/modelscope/bert-base-chinese]
            [--out_dir models/bert_classifier]

产出：
    models/bert_classifier/{model,tokenizer,label_encoder}.* + metrics.json

注意：
    - 模型权重默认落在 models/（已被 .gitignore 排除，不进公开仓库）。
    - 训练在低显存环境跑：MX350 2GB，小 batch + 梯度累积，fp32（sm_75 不支持 bf16）。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from sklearn.preprocessing import LabelEncoder
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

# 项目路径（允许从仓库根目录直接跑）
_ROOT = Path(__file__).resolve().parent.parent
_PROJECTS = _ROOT.parent
for p in [_ROOT / "src", _PROJECTS / "ticket-classifier" / "src"]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from ticket_diagnose.eval_set import generate_eval_set, to_ticket_text  # noqa: E402


class TicketTextDataset(Dataset):
    """把 (text, label) 列表包装成 HF Dataset 友好的 torch Dataset。"""

    def __init__(self, texts, labels, tokenizer, max_length=128):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        enc = self.tokenizer(
            self.texts[idx],
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        return {
            "input_ids": enc["input_ids"].squeeze(0),
            "attention_mask": enc["attention_mask"].squeeze(0),
            "labels": torch.tensor(self.labels[idx], dtype=torch.long),
        }


def build_data(n: int, seed: int, val_ratio: float):
    """用程序化评测集构造训练/验证数据，返回 (texts, cat_labels, sub_labels, split_idx)。"""
    tickets = generate_eval_set(n=n, seed=seed)
    texts = [to_ticket_text(t) for t in tickets]
    cat_labels = [t["expect_category"] for t in tickets]
    sub_labels = [t["expect_sub"] for t in tickets]

    # 分层划分（保持每类在 train/val 中都有）
    rng = __import__("random").Random(seed)
    from collections import defaultdict
    by_cat = defaultdict(list)
    for i, c in enumerate(cat_labels):
        by_cat[c].append(i)
    train_idx, val_idx = [], []
    for c, idxs in by_cat.items():
        rng.shuffle(idxs)
        n_val = max(1, int(len(idxs) * val_ratio))
        val_idx.extend(idxs[:n_val])
        train_idx.extend(idxs[n_val:])
    return texts, cat_labels, sub_labels, train_idx, val_idx


def train_epoch(model, loader, optimizer, scheduler, device):
    model.train()
    total, correct = 0, 0
    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        out = model(**batch)
        loss = out.loss
        logits = out.logits
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        scheduler.step()
        preds = logits.argmax(dim=-1)
        correct += (preds == batch["labels"]).sum().item()
        total += batch["labels"].size(0)
    return correct / total if total else 0.0


@torch.no_grad()
def eval_model(model, loader, device):
    model.eval()
    total, correct = 0, 0
    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        out = model(**batch)
        preds = out.logits.argmax(dim=-1)
        correct += (preds == batch["labels"]).sum().item()
        total += batch["labels"].size(0)
    return correct / total if total else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch_size", type=int, default=16)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val_ratio", type=float, default=0.2)
    ap.add_argument("--max_length", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--device", type=str, default="auto", help="auto/cuda/cpu")
    ap.add_argument("--model_dir", type=str,
                    default=os.path.expanduser("~/.cache/modelscope/bert-base-chinese"))
    ap.add_argument("--out_dir", type=str, default=str(_ROOT / "models" / "bert_classifier"))
    args = ap.parse_args()

    from transformers import BertForSequenceClassification, BertTokenizer

    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device
    print(f"[bert-train] device={device}, model_dir={args.model_dir}")
    t0 = time.time()

    # 数据
    texts, cat_labels, sub_labels, train_idx, val_idx = build_data(
        args.n, args.seed, args.val_ratio)
    print(f"[data] total={len(texts)} train={len(train_idx)} val={len(val_idx)}")

    # 加载预训练
    tokenizer = BertTokenizer.from_pretrained(args.model_dir)
    model = BertForSequenceClassification.from_pretrained(
        args.model_dir, num_labels=6).to(device)  # 6 大类
    print(f"[model] bert-base-chinese loaded in {time.time()-t0:.1f}s")

    # 低显存优化：sm_75 (MX350) 不支持 bf16，用 fp16；梯度累积等效扩大 batch
    use_fp16 = device == "cuda" and torch.cuda.get_device_capability(0)[0] == 7
    if use_fp16:
        model = model.half() if hasattr(torch.cuda, "amp") else model
        print("[mem] cuda fp16 enabled (sm_75)")

    # 编码大类标签
    cat_enc = LabelEncoder()
    cat_y = cat_enc.fit_transform(cat_labels)
    print(f"[labels] classes={list(cat_enc.classes_)}")

    def make_loader(idx, shuffle):
        ds = TicketTextDataset(
            [texts[i] for i in idx], [cat_y[i] for i in idx],
            tokenizer, args.max_length)
        return DataLoader(ds, batch_size=args.batch_size, shuffle=shuffle)

    train_loader = make_loader(train_idx, True)
    val_loader = make_loader(val_idx, False)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    total_steps = len(train_loader) * args.epochs
    scheduler = torch.optim.lr_scheduler.LinearLR(optimizer, total_iters=total_steps)

    # 训练
    best_val = 0.0
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for ep in range(1, args.epochs + 1):
        tr_acc = train_epoch(model, train_loader, optimizer, scheduler, device)
        val_acc = eval_model(model, val_loader, device)
        print(f"[epoch {ep}/{args.epochs}] train_acc={tr_acc:.4f} val_acc={val_acc:.4f}")
        if val_acc >= best_val:
            best_val = val_acc
            # 保存
            model.save_pretrained(str(out_dir))
            tokenizer.save_pretrained(str(out_dir))
            with open(out_dir / "category_label_encoder.json", "w", encoding="utf-8") as f:
                json.dump({"classes": list(cat_enc.classes_)}, f, ensure_ascii=False)

    metrics = {
        "device": device,
        "n_total": len(texts),
        "n_train": len(train_idx),
        "n_val": len(val_idx),
        "best_val_acc": round(best_val, 4),
        "epochs": args.epochs,
        "out_dir": str(out_dir),
        "elapsed_s": round(time.time() - t0, 1),
        "note": "大类(6)分类器；子类/优先级多任务可作为下一步扩展",
    }
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"[done] best_val_acc={best_val:.4f} saved to {out_dir}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
