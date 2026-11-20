"""沿线路里程的一维DBSCAN缺陷密度聚类，计入里程误差并区分确认带与待复核点。"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from sklearn.cluster import DBSCAN

MAX_POINT_ERROR_M = 5000.0
MAX_OFFSET_M = 5000.0


def metadata():
    return {
        "name": "轨检缺陷密度追踪", "short": "rail-density",
        "tagline": "沿实际里程识别密集缺陷带，把孤立点与成片问题分开复核。",
        "client": "临江工务段 · 8名线路分析员 · 南环上行120公里巡检区段",
        "workflow": "分析员在里程表上按整公里汇总缺陷，人工拼接跨公里的密集异常。",
        "pains": ["整公里边界切断真实缺陷带", "单个高等级缺陷与密集低等级缺陷混在一起", "密度参数变化没有可重复的结果记录"],
        "upstream": "轨检车轨距与表面缺陷复核记录 south_loop_defects.csv",
        "downstream": "工务复核会确定人工加密检查区段，保留孤立严重缺陷单独复核",
        "entities": ["线路缺陷点", "密度追踪试验", "区段复核简报"],
        "dataset_name": "南环上行线路185个缺陷点",
        "columns": [
            {"key": "defect_id", "label": "缺陷编号", "type": "string"},
            {"key": "mileage_km", "label": "线路里程(km)", "type": "number"},
            {"key": "lateral_mm", "label": "横向偏差(mm)", "type": "number"},
            {"key": "severity", "label": "复核等级(1~5)", "type": "number"},
            {"key": "run_id", "label": "车次(可选)", "type": "string", "required": False},
            {"key": "mileage_error_m", "label": "单点里程误差m(可选)", "type": "number", "required": False},
        ],
        "parameters": [{"key": "eps_m", "label": "邻域沿线半径(m)", "type": "number", "default": 100, "min": 20, "max": 400}, {"key": "min_points", "label": "核心点最少邻居(含自身)", "type": "number", "default": 5, "min": 3, "max": 12}],
        "workbench_title": "沿线缺陷密度追踪", "action_label": "识别密集缺陷带", "unit": "个缺陷点",
        "accent": "oklch(62% 0.14 65)", "style": "survey-archive",
        "seed_story": ["06:50 线路分析员导入 south_loop_defects.csv 的185个缺陷点", "07:00 确认所有里程均为南环上行同一方向", "07:10 创建半径100米、最少5点的密度试验", "07:11 后端将公里转成米计算一维DBSCAN", "07:20 查看缺陷带起止里程、跨度及最高等级", "07:30 将半径收紧到30米观察缺陷带分裂与噪声变化", "07:40 下载复核区段表，并单独核查孤立高等级点", "08:00 组长设置每日08:15内部线路简报"],
        "method": "仅按同一线路方向的校正后里程做一维DBSCAN；eps单位为米，min_samples包含自身。每点登记的里程误差e与车次共同偏移用于校正和桥接判定：两点最坏间距 |Δ|+e_i+e_j 超过eps时连接不可确认，疑似桥接的密集组拆分为独立缺陷带，连接点列为待复核。横向偏差和等级仅用于结果解释。",
        "limitations": ["必须上传同一线路同一方向的数据", "密度带不等同于安全风险等级", "密度可达链可能使整带跨度大于eps，需结合原始点核查", "未登记单点里程误差或车次偏移时按0处理，校准更新会改变待复核点的归属"],
    }


def seed_records():
    rng = np.random.default_rng(1011)
    rows = []
    for center, spread in [(12.4, 0.14), (48.2, 0.20), (93.7, 0.10)]:
        for _ in range(55):
            rows.append({"defect_id": f"NJ-{len(rows)+1:04}", "mileage_km": round(float(rng.normal(center, spread)), 4), "lateral_mm": round(float(rng.normal(2.4, 1.1)), 2), "severity": int(rng.integers(1, 5))})
    for _ in range(20):
        rows.append({"defect_id": f"NJ-{len(rows)+1:04}", "mileage_km": round(float(rng.uniform(1, 119)), 4), "lateral_mm": round(float(rng.normal(2, 1)), 2), "severity": int(rng.integers(1, 6))})
    return sorted(rows, key=lambda row: row["mileage_km"])


def _point_error(row):
    value = row.get("mileage_error_m")
    if value is None or value == "":
        return 0.0
    return float(value)


def _calibration(calibration):
    snapshot = calibration or {}
    try:
        default_offset = float(snapshot.get("default_offset_m", 0.0) or 0.0)
        raw_runs = snapshot.get("run_offsets") or {}
        if not isinstance(raw_runs, dict):
            raise TypeError()
        run_offsets = {str(key): float(value) for key, value in raw_runs.items()}
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("校准偏移必须是有效数值。") from exc
    if not np.isfinite(default_offset) or abs(default_offset) > MAX_OFFSET_M:
        raise ValueError(f"共同偏移须为 ±{MAX_OFFSET_M:g} 米内的有限数值。")
    if any(not np.isfinite(value) or abs(value) > MAX_OFFSET_M for value in run_offsets.values()):
        raise ValueError(f"车次偏移须为 ±{MAX_OFFSET_M:g} 米内的有限数值。")
    try:
        version = int(snapshot.get("version", 0) or 0)
    except (TypeError, ValueError):
        version = 0
    return default_offset, run_offsets, max(version, 0)


def _robust_components(centers, errors, eps):
    """在里程误差下仍能稳定相连的点组；最坏间距 |Δ|+e_i+e_j 不超过eps才算稳定连接。"""
    size = len(centers)
    if size <= 1:
        return np.zeros(size, dtype=int)
    tree = cKDTree(centers.reshape(-1, 1))
    rows, cols = [], []
    for left, right in tree.query_pairs(eps):
        if abs(centers[left] - centers[right]) + errors[left] + errors[right] <= eps + 1e-9:
            rows.append(left); cols.append(right)
    graph = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(size, size))
    _, labels = connected_components(graph, directed=False)
    return labels


def analyze(records, params, calibration=None):
    try:
        eps = float(params.get("eps_m", 100))
        raw_min = float(params.get("min_points", 5))
        minimum = int(raw_min)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("邻域半径与最少点数必须是有效数值。") from exc
    if not 20 <= eps <= 400 or minimum != raw_min or not 3 <= minimum <= 12:
        raise ValueError("半径须20~400米，最少点数须3~12的整数。")
    if len(records) < max(10, minimum):
        raise ValueError("至少需要10个缺陷点，且不少于最少邻居点数。")
    try:
        mileage = np.asarray([float(row["mileage_km"]) for row in records])
        lateral = np.asarray([float(row["lateral_mm"]) for row in records])
        severity = np.asarray([float(row["severity"]) for row in records])
        errors = np.asarray([_point_error(row) for row in records])
        run_ids = [str(row.get("run_id") or "").strip() for row in records]
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        raise ValueError("里程、横向偏差与复核等级必须完整且为数值。") from exc
    if not np.isfinite(np.column_stack([mileage, lateral, severity, errors])).all() or (mileage < 0).any() or not np.isin(severity, [1, 2, 3, 4, 5]).all():
        raise ValueError("里程须非负有限，横向偏差须有限，复核等级须为1~5整数。")
    if (errors < 0).any() or (errors > MAX_POINT_ERROR_M).any():
        raise ValueError(f"单点里程误差须在0~{MAX_POINT_ERROR_M:g}米之间。")

    default_offset, run_offsets, version = _calibration(calibration)
    offsets = np.asarray([default_offset + run_offsets.get(run_id, 0.0) for run_id in run_ids])
    corrected = mileage * 1000 + offsets

    warnings = ["孤立与待复核仅指不满足当前密度与误差条件，不代表无效数据或低风险。"]
    applied = bool(abs(default_offset) > 0 or any(abs(value) > 0 for value in run_offsets.values()))
    if applied:
        warnings.append(f"起止里程已按校准v{version}的共同偏移与车次偏移校正，复核时请与原始里程表对照。")
    known_runs = sorted({run_id for run_id in run_ids if run_id})
    missing_runs = [run_id for run_id in known_runs if run_id not in run_offsets]
    if run_offsets and missing_runs:
        warnings.append(f"车次{'、'.join(missing_runs[:5])}未登记单独偏移，按共同偏移{default_offset:g}米计算。")

    labels = DBSCAN(eps=eps, min_samples=minimum).fit_predict(corrected.reshape(-1, 1))
    nominal = sorted([int(value) for value in np.unique(labels) if value >= 0], key=lambda value: float(np.min(corrected[labels == value])))

    groups = []      # (成员下标, 是否由疑似桥接拆分而来)
    pending = []     # (点下标, 原因代码, 最近确认带的成员下标)
    bridged_groups = 0
    for cluster in nominal:
        members = np.where(labels == cluster)[0]
        components = _robust_components(corrected[members], errors[members], eps)
        parts = [members[components == index] for index in range(int(components.max()) + 1)]
        if len(parts) == 1:
            groups.append((members, False))
            continue
        bridged_groups += 1
        dense = [part for part in parts if len(part) >= minimum]
        sparse = [part for part in parts if len(part) < minimum]
        if dense:
            # 只有真被拆开（至少两个确认部分），否定词才成立
            if len(dense) > 1:
                bridged_groups += 1
            for part in sorted(dense, key=lambda value: float(np.min(corrected[value]))):
                groups.append((part, True))
            for part in sparse:
                pending.extend((int(index), "bridge", None) for index in part)
        else:
            bridged_groups += 1
            for part in parts:
                pending.extend((int(index), "unstable", None) for index in part)

    groups.sort(key=lambda value: float(np.min(corrected[value[0]])))
    confirmed = np.concatenate([part for part, _ in groups]) if groups else np.zeros(0, dtype=int)

    isolated = []
    for index in np.where(labels == -1)[0]:
        if len(confirmed):
            gaps = np.abs(corrected[index] - corrected[confirmed])
            nearest = int(confirmed[int(np.argmin(gaps))])
            if gaps.min() <= eps + errors[index] + errors[nearest]:
                pending.append((int(index), "near", nearest))
                continue
        isolated.append(int(index))

    rows = []
    for display, (part, split) in enumerate(groups, 1):
        start, end = float(corrected[part].min()), float(corrected[part].max())
        rows.append({"band": f"缺陷带{display}", "count": int(len(part)), "from_km": round(start / 1000, 4), "to_km": round(end / 1000, 4), "span_m": round((end - start), 1), "max_severity": int(severity[part].max()), "mean_lateral": round(float(lateral[part].mean()), 2), "review": "人工加密检查（疑似桥接已拆分）" if split else "人工加密检查"})

    band_of = {}
    for (part, _), row in zip(groups, rows):
        for index in part:
            band_of[int(index)] = row["band"]
    pending_rows = []
    for index, reason, nearest in pending:
        band = ""
        gap = None
        if len(confirmed):
            if nearest is None:
                gaps = np.abs(corrected[index] - corrected[confirmed])
                nearest = int(confirmed[int(np.argmin(gaps))])
                gap = float(gaps.min())
            else:
                gap = float(abs(corrected[index] - corrected[nearest]))
            band = band_of.get(nearest, "")
        if reason == "bridge":
            detail = f"疑似桥接：距{band}最近点约{gap:.0f}米，但计入里程误差后连接不可确认，暂不并带。" if band else "疑似桥接：与相邻点无法在里程误差内稳定相连，暂不并带。"
        elif reason == "unstable":
            detail = f"校正后稳定相连的点不足最少点数（{minimum}点），尚未确认为缺陷带。"
        else:
            detail = f"距{band}最近点约{gap:.0f}米，处于里程误差范围，校准或误差更新后归属可能变化。" if band else "与相邻点的距离处于里程误差范围，归属可能变化。"
        pending_rows.append({"defect_id": str(records[index].get("defect_id", "")), "mileage_km": round(float(mileage[index]), 4), "severity": int(severity[index]), "nearest_band": band or "—", "reason": detail})
    pending_rows.sort(key=lambda row: row["mileage_km"])

    isolated_rows = [{"defect_id": str(records[index].get("defect_id", "")), "mileage_km": round(float(mileage[index]), 4), "severity": int(severity[index]), "note": "未发现可在里程误差内稳定相连的相邻点。"} for index in isolated]
    isolated_rows.sort(key=lambda row: row["mileage_km"])

    high_pending = int(sum(1 for row in pending_rows if row["severity"] >= 4))
    high_isolated = int(sum(1 for row in isolated_rows if row["severity"] >= 4))
    findings = []
    if bridged_groups:
        findings.append(f"检测到{bridged_groups}组疑似桥接，已拆分为独立缺陷带；连接点列为待复核，不与相邻带合并。")
    if pending_rows:
        findings.append(f"{len(pending_rows)}个点的归属可能随校准或里程误差更新变化，需人工确认后才可并入缺陷带。")
    findings.append(f"待复核与孤立点中有{high_pending + high_isolated}个等级≥4的缺陷，不能因未并带而忽略。")
    findings.append("收紧邻域半径会使密度带分裂或增加噪声；扩大半径可能把相邻问题连接。")
    findings.append("缺陷带按起始里程排序，标签仅用于定位，不表示处理优先级。")

    return {
        "summary": f"在{len(records)}个缺陷点中确认{len(rows)}条缺陷带，另有{len(pending_rows)}个待复核点、{len(isolated_rows)}个孤立点；邻域半径{eps:g}米，里程校准v{version}。",
        "metrics": [
            {"label": "确认缺陷带", "value": len(rows), "unit": "条"},
            {"label": "确认带内点数", "value": int(len(confirmed))},
            {"label": "待复核点", "value": len(pending_rows), "unit": "个"},
            {"label": "孤立点", "value": len(isolated_rows), "unit": "个"},
            {"label": "高等级待复核/孤立", "value": high_pending + high_isolated, "unit": "个"},
        ],
        "table": {"columns": [{"key": "band", "label": "密度分组"}, {"key": "count", "label": "缺陷点数"}, {"key": "from_km", "label": "起点km"}, {"key": "to_km", "label": "终点km"}, {"key": "span_m", "label": "跨度m"}, {"key": "max_severity", "label": "最高等级"}, {"key": "mean_lateral", "label": "平均横偏mm"}, {"key": "review", "label": "复核动作"}], "rows": rows},
        "pending": {"columns": [{"key": "defect_id", "label": "缺陷编号"}, {"key": "mileage_km", "label": "原始里程km"}, {"key": "severity", "label": "等级"}, {"key": "nearest_band", "label": "最近确认带"}, {"key": "reason", "label": "归属可能变化的缘由"}], "rows": pending_rows},
        "isolated": {"columns": [{"key": "defect_id", "label": "缺陷编号"}, {"key": "mileage_km", "label": "原始里程km"}, {"key": "severity", "label": "等级"}, {"key": "note", "label": "说明"}], "rows": isolated_rows},
        "chart": {"type": "bar", "labels": [row["band"] for row in rows], "series": [{"name": "确认带内点数", "values": [row["count"] for row in rows]}]} if rows else {"type": "bar", "labels": [], "series": []},
        "calibration": {"version": version, "default_offset_m": default_offset, "run_offsets": run_offsets, "applied": applied},
        "findings": findings,
        "method": metadata()["method"], "warnings": warnings + (["当前参数未确认出缺陷带，可核查数据范围或适度增大半径。"] if not rows else []),
    }
