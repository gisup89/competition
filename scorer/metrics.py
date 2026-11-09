"""평가지표 정의, 제출 파일 검증, Public/Private 채점."""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .common import SubmissionError


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    higher_is_better: bool
    kind: str  # regression | label | proba
    description: str


METRICS: dict[str, Metric] = {
    "rmse": Metric("rmse", "RMSE", False, "regression", "Root Mean Squared Error"),
    "mae": Metric("mae", "MAE", False, "regression", "Mean Absolute Error"),
    "rmsle": Metric("rmsle", "RMSLE", False, "regression", "Root Mean Squared Logarithmic Error"),
    "mape": Metric("mape", "MAPE (%)", False, "regression", "Mean Absolute Percentage Error"),
    "r2": Metric("r2", "R²", True, "regression", "Coefficient of determination"),
    "accuracy": Metric("accuracy", "Accuracy", True, "label", "정확도"),
    "f1": Metric("f1", "F1 (binary)", True, "label", "양성 클래스 F1 점수"),
    "f1_macro": Metric("f1_macro", "F1 (macro)", True, "label", "클래스별 F1 의 단순 평균"),
    "auc": Metric("auc", "ROC AUC", True, "proba", "이진 분류 ROC 곡선 아래 면적"),
    "logloss": Metric("logloss", "Log Loss", False, "proba", "이진 분류 로그 손실"),
}


def get_metric(key: str) -> Metric:
    key = str(key).lower().strip()
    if key not in METRICS:
        raise RuntimeError(f"지원하지 않는 평가지표입니다: {key}. 사용 가능: {', '.join(METRICS)}")
    return METRICS[key]


# ---------------------------------------------------------------------------
# 지표 계산 (numpy 만 사용)
# ---------------------------------------------------------------------------
def _rmse(y, p):
    return float(np.sqrt(np.mean((y - p) ** 2)))


def _mae(y, p):
    return float(np.mean(np.abs(y - p)))


def _rmsle(y, p):
    if np.any(p < 0):
        raise SubmissionError("RMSLE 지표에서는 음수 예측값을 사용할 수 없습니다.")
    return float(np.sqrt(np.mean((np.log1p(y) - np.log1p(p)) ** 2)))


def _mape(y, p):
    mask = y != 0
    if not mask.any():
        raise SubmissionError("MAPE 를 계산할 수 없습니다 (실제값이 모두 0).")
    return float(np.mean(np.abs((y[mask] - p[mask]) / y[mask])) * 100.0)


def _r2(y, p):
    ss_res = np.sum((y - p) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    if ss_tot == 0:
        return 0.0
    return float(1.0 - ss_res / ss_tot)


def _accuracy(y, p):
    return float(np.mean(y == p))


def _f1_for(y, p, label) -> float:
    tp = np.sum((y == label) & (p == label))
    fp = np.sum((y != label) & (p == label))
    fn = np.sum((y == label) & (p != label))
    denom = 2 * tp + fp + fn
    return float(2 * tp / denom) if denom > 0 else 0.0


def _f1_binary(y, p, pos_label):
    return _f1_for(y, p, pos_label)


def _f1_macro(y, p):
    labels = np.unique(y)
    return float(np.mean([_f1_for(y, p, lab) for lab in labels]))


def _auc(y, s):
    """Mann-Whitney 통계량 기반 AUC (동점은 평균 순위)."""
    y = y.astype(int)
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    if n_pos == 0 or n_neg == 0:
        raise SubmissionError("AUC 를 계산할 수 없습니다 (한 클래스만 존재).")
    order = np.argsort(s, kind="mergesort")
    sorted_s = s[order]
    ranks = np.empty(len(s), dtype=float)
    i = 0
    n = len(s)
    while i < n:
        j = i
        while j + 1 < n and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    sum_pos = ranks[y == 1].sum()
    return float((sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def _logloss(y, p):
    eps = 1e-15
    p = np.clip(p, eps, 1 - eps)
    y = y.astype(float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# ---------------------------------------------------------------------------
# 값 정규화
# ---------------------------------------------------------------------------
def _norm_label(v) -> str:
    s = str(v).strip()
    try:
        f = float(s)
        if np.isfinite(f) and f.is_integer():
            return str(int(f))
        return repr(f)
    except ValueError:
        return s


def _to_numeric(series: pd.Series, what: str) -> np.ndarray:
    num = pd.to_numeric(series, errors="coerce")
    bad = num.isna() & series.notna()
    if bad.any():
        examples = series[bad].astype(str).head(3).tolist()
        raise SubmissionError(f"{what} 열에 숫자가 아닌 값이 {int(bad.sum())}개 있습니다. 예: {examples}")
    if num.isna().any():
        raise SubmissionError(f"{what} 열에 빈 값(NaN)이 {int(num.isna().sum())}개 있습니다.")
    arr = num.to_numpy(dtype=float)
    if not np.all(np.isfinite(arr)):
        raise SubmissionError(f"{what} 열에 무한대(inf) 값이 있습니다.")
    return arr


# ---------------------------------------------------------------------------
# 제출 파일 파싱 / 검증
# ---------------------------------------------------------------------------
def read_submission_csv(data: bytes) -> pd.DataFrame:
    if not data or not data.strip():
        raise SubmissionError("제출 파일이 비어 있습니다.")
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SubmissionError("CSV 파일 인코딩을 읽을 수 없습니다 (UTF-8 로 저장해 주세요).")
    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as exc:  # noqa: BLE001
        raise SubmissionError(f"CSV 파일을 읽는 중 오류가 발생했습니다: {exc}") from exc
    if df.empty:
        raise SubmissionError("제출 파일에 데이터 행이 없습니다.")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _match_column(df: pd.DataFrame, wanted: str) -> str:
    if wanted in df.columns:
        return wanted
    lower = {c.lower(): c for c in df.columns}
    if wanted.lower() in lower:
        return lower[wanted.lower()]
    raise SubmissionError(
        f"제출 파일에 `{wanted}` 열이 없습니다. 현재 열: {list(df.columns)[:10]}. "
        "sample_submission.csv 형식을 확인해 주세요."
    )


def score_submission(solution: pd.DataFrame, submission: pd.DataFrame, cfg: dict) -> dict:
    """검증 후 Public/Private 점수를 계산해 dict 로 반환."""
    metric = get_metric(cfg["metric"])
    id_col = cfg["id_column"]
    target_col = cfg["target_column"]

    # 정답 파일 열 확인
    if id_col not in solution.columns or target_col not in solution.columns:
        raise RuntimeError(
            f"정답 파일에 `{id_col}` 또는 `{target_col}` 열이 없습니다. config.yml 을 확인하세요."
        )
    sub_id = _match_column(submission, id_col)
    sub_target = _match_column(submission, target_col)

    sol = solution[[id_col, target_col] + (["Usage"] if "Usage" in solution.columns else [])].copy()
    sub = submission[[sub_id, sub_target]].copy()
    sub.columns = [id_col, target_col]

    sol[id_col] = sol[id_col].astype(str).str.strip()
    sub[id_col] = sub[id_col].astype(str).str.strip()

    dup = sub[id_col].duplicated()
    if dup.any():
        raise SubmissionError(
            f"`{id_col}` 값이 중복된 행이 {int(dup.sum())}개 있습니다. 예: {sub.loc[dup, id_col].head(3).tolist()}"
        )
    sol_ids = set(sol[id_col])
    sub_ids = set(sub[id_col])
    missing = sol_ids - sub_ids
    extra = sub_ids - sol_ids
    if missing:
        raise SubmissionError(
            f"테스트 데이터의 `{id_col}` 가운데 {len(missing)}개가 제출 파일에 없습니다. "
            f"예: {sorted(missing)[:3]} (필요한 행 수: {len(sol_ids)}, 제출된 행 수: {len(sub_ids)})"
        )
    if extra:
        raise SubmissionError(
            f"테스트 데이터에 없는 `{id_col}` 가 {len(extra)}개 있습니다. 예: {sorted(extra)[:3]}"
        )

    merged = sol.merge(sub, on=id_col, how="left", suffixes=("_true", "_pred"))
    y_raw = merged[f"{target_col}_true"]
    p_raw = merged[f"{target_col}_pred"]
    if p_raw.isna().any():
        raise SubmissionError(f"`{target_col}` 열에 빈 값이 {int(p_raw.isna().sum())}개 있습니다.")

    if metric.kind == "regression":
        y = _to_numeric(y_raw, "정답")
        p = _to_numeric(p_raw, f"`{target_col}`")
    elif metric.kind == "proba":
        y = _to_numeric(y_raw, "정답")
        if not set(np.unique(y)).issubset({0.0, 1.0}):
            raise RuntimeError("AUC/LogLoss 지표의 정답은 0/1 이어야 합니다.")
        p = _to_numeric(p_raw, f"`{target_col}`")
        if metric.key == "logloss" and (np.any(p < 0) or np.any(p > 1)):
            raise SubmissionError("Log Loss 지표에서는 예측값이 0~1 사이의 확률이어야 합니다.")
    else:  # label
        y = y_raw.map(_norm_label).to_numpy()
        p = p_raw.map(_norm_label).to_numpy()
        unknown = set(np.unique(p)) - set(np.unique(y))
        if unknown and len(unknown) > 0:
            # 정답에 없는 클래스 라벨은 경고 수준으로만 처리 (오타 가능성 안내)
            pass

    if "Usage" in merged.columns:
        usage = merged["Usage"].astype(str).str.strip().str.lower()
        pub_mask = (usage == "public").to_numpy()
        prv_mask = (usage == "private").to_numpy()
        if not pub_mask.any():
            pub_mask = ~(usage == "ignored").to_numpy()
        if not prv_mask.any():
            prv_mask = ~(usage == "ignored").to_numpy()
    else:
        pub_mask = np.ones(len(merged), dtype=bool)
        prv_mask = pub_mask

    def compute(mask):
        yy, pp = y[mask], p[mask]
        if metric.key == "rmse":
            return _rmse(yy, pp)
        if metric.key == "mae":
            return _mae(yy, pp)
        if metric.key == "rmsle":
            return _rmsle(yy, pp)
        if metric.key == "mape":
            return _mape(yy, pp)
        if metric.key == "r2":
            return _r2(yy, pp)
        if metric.key == "accuracy":
            return _accuracy(yy, pp)
        if metric.key == "f1":
            return _f1_binary(yy, pp, _norm_label(cfg.get("pos_label", 1)))
        if metric.key == "f1_macro":
            return _f1_macro(yy, pp)
        if metric.key == "auc":
            return _auc(yy, pp)
        if metric.key == "logloss":
            return _logloss(yy, pp)
        raise RuntimeError(metric.key)

    public_score = compute(pub_mask)
    private_score = compute(prv_mask)
    return {
        "public": public_score,
        "private": private_score,
        "n_public": int(pub_mask.sum()),
        "n_private": int(prv_mask.sum()),
        "n_rows": int(len(merged)),
    }
