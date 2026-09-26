"""inspection_sample 单元测试：固定用例 + 小规模独立枚举交叉验证。

暴力参考实现不使用被测模块的子集递推，而是用 itertools 的全部组合逐一
检查预算与每窑覆盖约束后，按「风险分总和最大 → 总耗时最小 →
抽中编号升序列表字典序最小」择优，与位掩码枚举相互独立。
"""

import os
import random
import sys
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.inspection_sample import (  # noqa: E402
    NoFeasibleInspectionSampleError,
    select_inspection_sample,
)


def _brute_select(kilns, risks, minutes, budget):
    """枚举全部非空子集的参考实现；无可行覆盖时返回 None。"""

    ids = sorted({i for kiln in kilns for i in kiln})
    kiln_of = {i: k for k, kiln in enumerate(kilns) for i in kiln}
    best = None  # (风险分, 耗时, 升序编号元组)
    for size in range(1, len(ids) + 1):
        for combo in combinations(ids, size):
            used = sum(minutes[i] for i in combo)
            if used > budget:
                continue
            covered = {kiln_of[i] for i in combo}
            if len(covered) != len(kilns):
                continue
            risk = sum(risks[i] for i in combo)
            members = tuple(sorted(combo))
            if (
                best is None
                or risk > best[0]
                or (risk == best[0] and used < best[1])
                or (risk == best[0] and used == best[1] and members < best[2])
            ):
                best = (risk, used, members)
    return best


def _check_against_brute(kilns, risks, minutes, budget):
    result = select_inspection_sample(kilns, risks, minutes, budget)
    expected = _brute_select(kilns, risks, minutes, budget)
    assert expected is not None, "暴力枚举认为可行，但 select 返回了错误"
    exp_risk, exp_minutes, exp_ids = expected

    assert result.sampled_item_ids == exp_ids
    assert list(result.sampled_item_ids) == sorted(result.sampled_item_ids)
    assert result.total_risk_score == exp_risk
    assert result.total_inspection_minutes == exp_minutes
    assert result.total_inspection_minutes <= budget
    assert result.total_risk_score == sum(risks[i] for i in exp_ids)
    assert result.total_inspection_minutes == sum(minutes[i] for i in exp_ids)

    # 每个窑次至少抽中一件，且各窑明细与全局合计一致
    assert len(result.kiln_coverages) == len(kilns)
    total_risk = total_minutes = total_count = 0
    for idx, coverage in enumerate(result.kiln_coverages, start=1):
        assert coverage.kiln_index == idx
        assert coverage.item_count == len(kilns[idx - 1])
        assert coverage.sampled_count >= 1
        assert coverage.sampled_count == len(coverage.sampled_item_ids)
        assert list(coverage.sampled_item_ids) == sorted(
            coverage.sampled_item_ids
        )
        assert set(coverage.sampled_item_ids) <= set(kilns[idx - 1])
        assert coverage.risk_score == sum(
            risks[i] for i in coverage.sampled_item_ids
        )
        assert coverage.inspection_minutes == sum(
            minutes[i] for i in coverage.sampled_item_ids
        )
        total_risk += coverage.risk_score
        total_minutes += coverage.inspection_minutes
        total_count += coverage.sampled_count
    assert total_risk == result.total_risk_score
    assert total_minutes == result.total_inspection_minutes
    assert total_count == len(result.sampled_item_ids)
    return result


def _expect_error(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    raise AssertionError(f"期望抛出 {exc_type.__name__}，但未抛出")


def test_basic_max_risk_then_min_minutes():
    # 两窑：窑1=[p1,p2]，窑2=[p3,p4]；预算 10
    # 覆盖两窑的组合里 {p1,p2,p3} 风险 11、耗时 8 最高
    # （{p1,p3,p4} 风险 10、耗时 10 次之）
    kilns = [["p1", "p2"], ["p3", "p4"]]
    risks = {"p1": 5, "p2": 5, "p3": 1, "p4": 4}
    minutes = {"p1": 3, "p2": 4, "p3": 1, "p4": 6}
    r = _check_against_brute(kilns, risks, minutes, 10)
    assert r.sampled_item_ids == ("p1", "p2", "p3")
    assert r.total_risk_score == 11
    assert r.total_inspection_minutes == 8
    assert r.kiln_coverages[0].sampled_item_ids == ("p1", "p2")
    assert r.kiln_coverages[1].sampled_item_ids == ("p3",)


def test_tie_on_risk_prefers_less_time():
    # 预算 5 时最多覆盖两窑各一件：{p1,p3} 风险 6 耗时 4；
    # {p2,p3} 风险 6 耗时 5；{p1,p4} 风险 6 耗时 7（超预算）
    kilns = [["p1", "p2"], ["p3", "p4"]]
    risks = {"p1": 3, "p2": 3, "p3": 3, "p4": 3}
    minutes = {"p1": 1, "p2": 2, "p3": 3, "p4": 6}
    r = _check_against_brute(kilns, risks, minutes, 5)
    assert r.sampled_item_ids == ("p1", "p3")
    assert r.total_inspection_minutes == 4
    # 预算放宽后，风险总和最大为 12（全抽，耗时 12）
    r2 = _check_against_brute(kilns, risks, minutes, 12)
    assert r2.sampled_item_ids == ("p1", "p2", "p3", "p4")
    assert r2.total_risk_score == 12
    assert r2.total_inspection_minutes == 12


def test_tie_on_risk_and_time_prefers_lexicographic_ids():
    # {p1,p3} 与 {p1,p4} 风险耗时均相同（4 分、3 分钟），取编号字典序更小
    kilns = [["p1", "p2"], ["p3", "p4"]]
    risks = {"p1": 2, "p2": 2, "p3": 2, "p4": 2}
    minutes = {"p1": 1, "p2": 9, "p3": 2, "p4": 2}
    r = _check_against_brute(kilns, risks, minutes, 3)
    assert r.sampled_item_ids == ("p1", "p3")
    # p1 昂贵被排除后，{p2,p3} 与 {p2,p4} 同为 4 分 3 分钟（预算 3），取 p3
    minutes2 = {"p1": 9, "p2": 1, "p3": 2, "p4": 2}
    r2 = _check_against_brute(kilns, risks, minutes2, 3)
    assert r2.sampled_item_ids == ("p2", "p3")


def test_zero_risk_scores_allowed():
    kilns = [["a"], ["b"]]
    risks = {"a": 0, "b": 0}
    minutes = {"a": 1, "b": 2}
    r = _check_against_brute(kilns, risks, minutes, 3)
    assert r.sampled_item_ids == ("a", "b")
    assert r.total_risk_score == 0


def test_zero_budget_is_infeasible():
    # 检验分钟数恒为正整数，预算 0 时连一件都抽不了 → 无可行覆盖
    _expect_error(
        NoFeasibleInspectionSampleError,
        select_inspection_sample,
        [["a"]],
        {"a": 0},
        {"a": 1},
        0,
    )


def test_infeasible_budget_lists_minimum_minutes():
    # 每窑最省：min(3,5)=3、min(4,8)=4，共 7 分钟；预算 6 不可行
    kilns = [["p1", "p2"], ["p3", "p4"]]
    risks = {"p1": 9, "p2": 9, "p3": 9, "p4": 9}
    minutes = {"p1": 3, "p2": 5, "p3": 4, "p4": 8}
    try:
        select_inspection_sample(kilns, risks, minutes, 6)
    except NoFeasibleInspectionSampleError as exc:
        assert "7" in str(exc)
    else:
        raise AssertionError("期望抛出 NoFeasibleInspectionSampleError")


def test_single_kiln_pure_knapsack():
    # 单窑覆盖约束退化为至少抽一件：预算内风险分总和最大
    kilns = [["a", "b", "c"]]
    risks = {"a": 5, "b": 4, "c": 3}
    minutes = {"a": 4, "b": 3, "c": 3}
    r = _check_against_brute(kilns, risks, minutes, 6)
    # {b,c} 风险 7 耗时 6 最优（{a,b} 耗时 7 超预算）
    assert r.sampled_item_ids == ("b", "c")
    assert r.total_risk_score == 7
    assert r.total_inspection_minutes == 6
    assert r.kiln_coverages[0].sampled_count == 2


def test_invalid_inputs():
    kilns = [["a"], ["b"]]
    risks = {"a": 0, "b": 0}
    minutes = {"a": 1, "b": 1}

    _expect_error(ValueError, select_inspection_sample, [], risks, minutes, 1)
    _expect_error(ValueError, select_inspection_sample, kilns, risks, minutes, -1)
    _expect_error(
        ValueError,
        select_inspection_sample,
        kilns,
        {"a": -1, "b": 0},
        minutes,
        10,
    )
    _expect_error(
        ValueError,
        select_inspection_sample,
        kilns,
        risks,
        {"a": 0, "b": 1},
        10,
    )
    # 编号跨窑重复
    _expect_error(
        ValueError,
        select_inspection_sample,
        [["a", "b"], ["b"]],
        {"a": 0, "b": 0},
        {"a": 1, "b": 1},
        10,
    )
    # 缺少器物的风险分
    _expect_error(
        ValueError,
        select_inspection_sample,
        kilns,
        {"a": 0},
        {"a": 1, "b": 1},
        10,
    )


def test_random_cross_validation():
    rng = random.Random(20260926)
    for trial in range(400):
        n = rng.randint(1, 7)
        ids = [f"i{i:02d}" for i in range(n)]
        # 随机把器物划分为 1～n 个非空窑（窑内编号按升序存）
        shuffled = ids[:]
        rng.shuffle(shuffled)
        k = rng.randint(1, n)
        cuts = sorted(rng.sample(range(1, n), k - 1)) if k > 1 else []
        bounds = [0, *cuts, n]
        kilns = [
            sorted(shuffled[bounds[j]:bounds[j + 1]]) for j in range(k)
        ]
        risks = {i: rng.randint(0, 9) for i in ids}
        minutes = {i: rng.randint(1, 6) for i in ids}
        budget = rng.randint(0, sum(minutes.values()))
        expected = _brute_select(kilns, risks, minutes, budget)
        if expected is None:
            _expect_error(
                NoFeasibleInspectionSampleError,
                select_inspection_sample,
                kilns,
                risks,
                minutes,
                budget,
            )
        else:
            _check_against_brute(kilns, risks, minutes, budget)


def test_performance_n14():
    import time

    kilns = [[f"i{idx:02d}"] for idx in range(14)]
    ids = [kiln[0] for kiln in kilns]
    risks = {i: idx for idx, i in enumerate(ids)}
    minutes = {i: 1 for i in ids}
    t0 = time.time()
    r = select_inspection_sample(kilns, risks, minutes, 14)
    elapsed = time.time() - t0
    assert elapsed < 2.0, f"n=14 耗时 {elapsed:.2f}s"
    assert r.sampled_item_ids == tuple(sorted(ids))
    assert r.total_risk_score == sum(range(14))
    assert r.total_inspection_minutes == 14


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n全部 {len(fns)} 个测试通过")
