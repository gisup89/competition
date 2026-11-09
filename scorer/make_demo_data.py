"""데모용 합성 데이터 생성 (실제 데이터가 아닌 난수 기반 예시).

  python -m scorer.make_demo_data --out examples --kind both

생성 결과 (각 폴더): train.csv, test.csv, solution.csv, sample_submission.csv
이후 new_competition 으로 대회를 만들면 됩니다 (README 참고).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def make_house(out: Path, n: int = 4000, seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    gu = rng.choice(["유성구", "서구", "중구", "동구", "대덕구"], size=n, p=[0.3, 0.3, 0.15, 0.13, 0.12])
    gu_effect = {"유성구": 1.25, "서구": 1.15, "중구": 0.95, "동구": 0.85, "대덕구": 0.9}
    area = np.clip(rng.normal(84, 22, n), 35, 200).round(1)
    floor = rng.integers(1, 30, n)
    built = rng.integers(1990, 2024, n)
    subway = np.clip(rng.exponential(700, n), 50, 4000).round(0)
    rooms = np.clip((area / 28).round().astype(int) + rng.integers(-1, 2, n), 1, 6)
    parking = np.clip(rng.normal(1.2, 0.35, n), 0.3, 2.5).round(2)
    brand = rng.choice([0, 1], size=n, p=[0.65, 0.35])

    base = 320 * area ** 0.95
    price = (
        base
        * np.array([gu_effect[g] for g in gu])
        * (1 + 0.004 * (floor - 10))
        * (1 + 0.012 * (built - 2005))
        * np.exp(-subway / 6000)
        * (1 + 0.08 * brand)
        * (1 + 0.05 * (parking - 1.2))
        * np.exp(rng.normal(0, 0.12, n))
    )
    price = (price / 100).round(0) * 100  # 만원 단위

    df = pd.DataFrame(
        {
            "id": np.arange(1, n + 1),
            "gu": gu,
            "area_m2": area,
            "floor": floor,
            "built_year": built,
            "subway_dist_m": subway,
            "rooms": rooms,
            "parking_per_hh": parking,
            "brand": brand,
            "price": price.astype(int),
        }
    )
    _split_and_write(df, out / "demo-house-price", "id", "price", test_ratio=0.3, seed=seed)


def make_churn(out: Path, n: int = 5000, seed: int = 11) -> None:
    rng = np.random.default_rng(seed)
    tenure = rng.integers(1, 72, n)
    monthly = np.clip(rng.normal(65, 25, n), 15, 150).round(2)
    contract = rng.choice(["월단위", "1년", "2년"], size=n, p=[0.55, 0.25, 0.2])
    internet = rng.choice(["광랜", "DSL", "없음"], size=n, p=[0.45, 0.35, 0.2])
    support = rng.integers(0, 6, n)
    autopay = rng.choice([0, 1], size=n, p=[0.4, 0.6])
    age = rng.integers(19, 80, n)

    logit = (
        -1.2
        - 0.035 * tenure
        + 0.012 * monthly
        + np.where(contract == "월단위", 1.1, np.where(contract == "1년", 0.2, -0.6))
        + np.where(internet == "광랜", 0.5, np.where(internet == "DSL", 0.1, -0.4))
        + 0.25 * support
        - 0.5 * autopay
        - 0.004 * (age - 45)
        + rng.normal(0, 0.6, n)
    )
    p = 1 / (1 + np.exp(-logit))
    churn = (rng.random(n) < p).astype(int)

    df = pd.DataFrame(
        {
            "customer_id": [f"C{100000 + i}" for i in range(n)],
            "tenure_months": tenure,
            "monthly_charge": monthly,
            "contract": contract,
            "internet": internet,
            "support_calls": support,
            "autopay": autopay,
            "age": age,
            "churn": churn,
        }
    )
    _split_and_write(df, out / "demo-churn", "customer_id", "churn", test_ratio=0.3, seed=seed, proba_sample=True)


def _split_and_write(df, folder: Path, id_col: str, target: str, test_ratio: float, seed: int, proba_sample=False) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(df))
    n_test = int(len(df) * test_ratio)
    test_idx, train_idx = idx[:n_test], idx[n_test:]
    train = df.iloc[train_idx].sort_values(id_col)
    test = df.iloc[test_idx].sort_values(id_col)
    train.to_csv(folder / "train.csv", index=False)
    test.drop(columns=[target]).to_csv(folder / "test.csv", index=False)
    test[[id_col, target]].to_csv(folder / "solution.csv", index=False)
    sample = test[[id_col]].copy()
    sample[target] = 0.5 if proba_sample else (round(float(train[target].mean()), 2))
    sample.to_csv(folder / "sample_submission.csv", index=False)
    print(f"{folder}: train {len(train)}행, test {len(test)}행")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="examples")
    ap.add_argument("--kind", choices=["regression", "classification", "both"], default="both")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.kind in ("regression", "both"):
        make_house(out)
    if args.kind in ("classification", "both"):
        make_churn(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
