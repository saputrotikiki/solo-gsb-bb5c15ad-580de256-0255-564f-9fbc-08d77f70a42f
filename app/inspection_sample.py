"""成品质检抽样：预算内每窑至少抽一件，最大化风险分总和。

针对已保存方案的全部器物（按窑次划分），请求为每件器物给出：
  * risk_score_i：非负整数风险分（越大越值得抽检）；
  * inspection_minutes_i：正整数检验分钟数；
并给出总分钟预算 total_minute_budget（非负整数）。

在全部器物子集中选择抽检样本，要求：
  * 总检验分钟数不超过预算；
  * 每个窑次至少抽中一件（覆盖全部窑次）。

择优按以下词典序优先级：
  1. 抽中器物的风险分总和最大；
  2. 风险分总和相同时，总检验分钟数最小；
  3. 仍相同时，抽中编号按标准字符串字典序升序排列后的列表字典序最小。

器物总数 n ≤ 14，直接枚举全部 2^n 个子集：用「去掉最低位 + 一件」递推
每个子集的风险分总和、检验分钟总和与已覆盖窑次位掩码，筛出预算内且覆盖
全部窑次的子集后按上述三级键取最优；一个可行子集都没有时（连每窑仅抽
一件的最省选择都超过预算）抛出 NoFeasibleInspectionSampleError。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class NoFeasibleInspectionSampleError(ValueError):
    """预算内不存在覆盖全部窑次的抽检样本（每窑至少抽一件仍超预算）。"""


@dataclass(frozen=True)
class InspectionKilnCoverage:
    """一个窑次的抽检覆盖明细（抽中编号按升序）。"""

    kiln_index: int
    item_count: int
    sampled_count: int
    sampled_item_ids: tuple[str, ...]
    risk_score: int
    inspection_minutes: int


@dataclass(frozen=True)
class InspectionSample:
    """整份方案的抽检样本：抽中编号（升序）、总风险分与总耗时、各窑明细。"""

    sampled_item_ids: tuple[str, ...]
    total_risk_score: int
    total_inspection_minutes: int
    kiln_coverages: tuple[InspectionKilnCoverage, ...]


def select_inspection_sample(
    kiln_item_ids: Sequence[Sequence[str]],
    risk_scores: Mapping[str, int],
    inspection_minutes: Mapping[str, int],
    total_minute_budget: int,
) -> InspectionSample:
    """在预算内选择覆盖全部窑次的最优抽检样本（只读计算）。

    器物按编号标准字符串字典序升序排列，位 i 对应排序后的第 i 件；
    各窑按传入次序编号（从 1 开始）。

    :param kiln_item_ids: 各窑器物编号（窑次序号即列表位置 + 1），
        须构成全部器物的一个划分：窑非空、编号不跨窑重复
    :param risk_scores: 每件器物的非负整数风险分
    :param inspection_minutes: 每件器物的正整数检验分钟数
    :param total_minute_budget: 总分钟预算（非负整数）
    :raises NoFeasibleInspectionSampleError: 预算内无覆盖全部窑次的样本。
    :raises ValueError: 窑次列表为空 / 含空窑 / 编号跨窑重复 /
        器物缺少风险分或检验分钟 / 分值非法 / 预算为负。
    """

    if not kiln_item_ids:
        raise ValueError("方案至少包含一个窑次")
    if total_minute_budget < 0:
        raise ValueError("总分钟预算必须为非负整数")

    ordered_ids = sorted({item_id for kiln in kiln_item_ids for item_id in kiln})
    if not ordered_ids:
        raise ValueError("方案至少包含一件器物")

    kiln_of: dict[str, int] = {}
    for index, kiln in enumerate(kiln_item_ids, start=1):
        if not kiln:
            raise ValueError(f"窑次 {index} 不能为空")
        for item_id in kiln:
            if item_id in kiln_of:
                raise ValueError(
                    f"器物 {item_id} 同时属于窑次 {kiln_of[item_id]} 与 {index}，"
                    "各窑器物不得重复"
                )
            kiln_of[item_id] = index

    missing_risk = sorted(set(kiln_of) - set(risk_scores))
    if missing_risk:
        raise ValueError("以下器物缺少风险分: " + ", ".join(missing_risk))
    missing_minutes = sorted(set(kiln_of) - set(inspection_minutes))
    if missing_minutes:
        raise ValueError("以下器物缺少检验分钟数: " + ", ".join(missing_minutes))

    risks = [risk_scores[i] for i in ordered_ids]
    minutes = [inspection_minutes[i] for i in ordered_ids]
    for item_id, risk in zip(ordered_ids, risks):
        if not isinstance(risk, int) or isinstance(risk, bool) or risk < 0:
            raise ValueError(f"器物 {item_id} 的风险分必须为非负整数")
    for item_id, minute in zip(ordered_ids, minutes):
        if not isinstance(minute, int) or isinstance(minute, bool) or minute < 1:
            raise ValueError(f"器物 {item_id} 的检验分钟数必须为正整数")

    n = len(ordered_ids)
    m = len(kiln_item_ids)
    kiln_bit = {i: 1 << (kiln_of[i] - 1) for i in ordered_ids}
    full_kiln_mask = (1 << m) - 1

    # 每窑仅抽一件时的最省耗时；超过预算则不存在任何覆盖样本。
    min_cover_minutes = 0
    for index, kiln in enumerate(kiln_item_ids, start=1):
        cheapest = min(inspection_minutes[i] for i in kiln)
        min_cover_minutes += cheapest
    if min_cover_minutes > total_minute_budget:
        raise NoFeasibleInspectionSampleError(
            f"总分钟预算 {total_minute_budget} 内无法覆盖全部 {m} 个窑次: "
            f"每个窑次至少抽中一件的最省耗时为 {min_cover_minutes} 分钟"
        )

    size = 1 << n
    risk_sum = [0] * size
    minute_sum = [0] * size
    kiln_mask = [0] * size
    for mask in range(1, size):
        bit = mask & -mask
        i = bit.bit_length() - 1
        prev = mask ^ bit
        risk_sum[mask] = risk_sum[prev] + risks[i]
        minute_sum[mask] = minute_sum[prev] + minutes[i]
        kiln_mask[mask] = kiln_mask[prev] | kiln_bit[ordered_ids[i]]

    best_mask = 0
    best_risk = -1
    best_minutes = 0
    best_ids: tuple[str, ...] | None = None
    for mask in range(1, size):
        if minute_sum[mask] > total_minute_budget:
            continue
        if kiln_mask[mask] != full_kiln_mask:
            continue
        members = tuple(
            ordered_ids[i] for i in range(n) if (mask >> i) & 1
        )
        risk = risk_sum[mask]
        minutes_used = minute_sum[mask]
        if (
            best_ids is not None
            and (
                risk < best_risk
                or (risk == best_risk and minutes_used > best_minutes)
                or (
                    risk == best_risk
                    and minutes_used == best_minutes
                    and members >= best_ids
                )
            )
        ):
            continue
        best_mask = mask
        best_risk = risk
        best_minutes = minutes_used
        best_ids = members

    # 最省覆盖已在预算内，逐窑各抽一件即为可行子集，枚举必能找到。
    assert best_ids is not None and best_mask != 0

    sampled_set = set(best_ids)
    coverages: list[InspectionKilnCoverage] = []
    for index, kiln in enumerate(kiln_item_ids, start=1):
        sampled = tuple(sorted(sampled_set.intersection(kiln)))
        coverages.append(
            InspectionKilnCoverage(
                kiln_index=index,
                item_count=len(kiln),
                sampled_count=len(sampled),
                sampled_item_ids=sampled,
                risk_score=sum(risk_scores[i] for i in sampled),
                inspection_minutes=sum(inspection_minutes[i] for i in sampled),
            )
        )

    return InspectionSample(
        sampled_item_ids=tuple(sorted(best_ids)),
        total_risk_score=best_risk,
        total_inspection_minutes=best_minutes,
        kiln_coverages=tuple(coverages),
    )
