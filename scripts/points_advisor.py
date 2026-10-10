#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
points_advisor.py — 麦麦积分价值顾问（麦麦省钱助手）

解决的问题
----------
"我有 N 积分，怎么花最划算？" 这个问题难在**积分没有统一标价**：
同一个积分，可以换餐券、换实物、换会员卡、还能抽奖。抽奖是概率收益，
和确定性兑换根本不在一个维度上，用户只能凭感觉。

本脚本引入一把统一的尺子：**每积分价值（元/分）**。

  · 确定性兑换：值 = 商品现金价值 ÷ 所需积分
  · 抽奖：值 = 期望奖品价值 ÷ 消耗积分
  · 判断抽奖值不值 → 算出"盈亏平衡奖品价值"（break-even），
    即"期望奖品至少要值多少钱，抽奖才跑赢最优兑换"

这样两类选择就被换算到了同一维度。再叠加**过期紧急度**：
快过期的积分，即使单位价值略低也应优先花掉——归零的价值是 0。

用法
----
    python points_advisor.py --input points.json --out points_result.json
    python points_advisor.py --input points.json --pretty
    python points_advisor.py --self-test

输入 JSON
---------
{
  "account": { ...query-my-account 的 data... },
  "products": [ ...mall-points-products 的 data... ],
  "productDetails": { "1830": { ...mall-product-detail 的 data... } },   // 可选
  "lottery": { ...query-lottery-info 的 data... },                       // 可选
  "valueHints": { "优惠券": 8, "实物商品": 15 },                          // 可选：按类目给现金估值(元)
  "options": { "maxItems": 20 }
}
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# 类目默认现金估值（元）——当接口未给出可用现金价时兜底。
# 这是**保守的启发式**，会被显式 price 字段或 valueHints 覆盖，并在输出中标注置信度。
CATEGORY_FALLBACK_YUAN = {
    "优惠券": 10.0,
    "餐品券": 12.0,
    "实物商品": 20.0,
    "周边产品": 20.0,
    "会员卡": 15.0,
    "权益卡": 15.0,
    "读书会": 45.0,
    "品鉴会": 50.0,
}


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def yuan(fen: int | float | None) -> str:
    if fen is None:
        return "-"
    return f"{fen / 100:.2f}"


def _to_fen(value: Any, unit: str | None = None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            f = float(s)
        except ValueError:
            return None
        if unit == "fen":
            return round(f)
        if unit == "yuan":
            return round(f * 100)
        return round(f * 100) if ("." in s or abs(f) < 1000) else round(f)
    if isinstance(value, (int, float)):
        f = float(value)
        if unit == "fen":
            return round(f)
        if unit == "yuan":
            return round(f * 100)
        return round(f)
    return None


def _int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return 0


def _pick(d: dict, *keys, default=None):
    if not isinstance(d, dict):
        return default
    lm = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = lm.get(k.lower())
        if v is not None:
            return v
    return default


# --------------------------------------------------------------------------- #
# 主逻辑
# --------------------------------------------------------------------------- #
def advise(payload: dict) -> dict:
    account = payload.get("account") or {}
    products = payload.get("products") or []
    details = payload.get("productDetails") or {}
    lottery = payload.get("lottery") or {}
    hints = payload.get("valueHints") or {}
    options = payload.get("options") or {}
    max_items = int(options.get("maxItems", 20))

    available = _int(_pick(account, "availablePoint", "availablePoints"))
    expire_now = _int(_pick(account, "currentMouthExpirePoint", "currentMonthExpirePoint"))
    expire_next = _int(_pick(account, "nextMouthExpirePoint", "nextMonthExpirePoint"))

    # ---------- 1) 兑换项估价 ----------
    items = []
    for p in products:
        spu_id = str(_pick(p, "spuId", "spuID", "id") or "")
        name = _pick(p, "spuName", "name", "title") or ""
        cat = _pick(p, "catName", "categoryName", "cat") or ""
        points = _int(_pick(p, "point", "points", "needPoint", "exchangePoint"))
        cash_fen = _to_fen(_pick(p, "price", "cashPrice", "salePrice"))
        shop_id = _pick(p, "shopId")
        img = _pick(p, "spuImage", "image")

        # 详情里的 SKU 可能给出更准的积分/价格
        if spu_id and spu_id in details:
            det = details[spu_id]
            skus = _pick(det, "skuList", "skus", "skuInfos") or []
            if isinstance(skus, list) and skus:
                best = None
                for s in skus:
                    spts = _int(_pick(s, "point", "points", "needPoint"))
                    if spts and (best is None or spts < best):
                        best = spts
                if best and not points:
                    points = best

        if not points:
            continue

        # 现金价值：优先接口价，其次类目兜底
        confidence = "high"
        value_fen = cash_fen if (cash_fen and cash_fen > 0) else None
        if value_fen is None:
            fallback_yuan = hints.get(cat)
            if fallback_yuan is None:
                for key, val in CATEGORY_FALLBACK_YUAN.items():
                    if cat and (key in cat or cat in key):
                        fallback_yuan = val
                        break
            if fallback_yuan is not None:
                value_fen = round(float(fallback_yuan) * 100)
                confidence = "low"
            else:
                confidence = "unknown"

        # 单位价值（元/积分）= 现金价值(分) ÷ 100 ÷ 所需积分
        vpp = (value_fen / 100 / points) if (value_fen and points) else None
        items.append({
            "spuId": spu_id,
            "shopId": shop_id,
            "name": name,
            "category": cat,
            "points": points,
            "cashValueFen": value_fen,
            "cashValueYuan": yuan(value_fen),
            "valuePerPointYuan": round(vpp, 6) if vpp else None,
            "affordable": points <= available,
            "confidence": confidence,
            "image": img,
        })

    # 只看有估值的，按每积分价值降序
    ranked = sorted([i for i in items if i["valuePerPointYuan"]],
                    key=lambda x: x["valuePerPointYuan"], reverse=True)[:max_items]

    benchmark_vpp = ranked[0]["valuePerPointYuan"] if ranked else None

    # ---------- 2) 抽奖机会成本 ----------
    lottery_out = None
    if lottery:
        draw_point = _int(_pick(lottery, "drawPoint", "consumePoint", "costPoint"))
        prizes = _pick(lottery, "prizes", "prizeList") or []
        status_text = _pick(lottery, "activityStatusText", "statusText") or ""
        activity_name = _pick(lottery, "activityName", "name") or ""
        draw_decision = _pick(lottery, "drawDecision") or {}

        if draw_point > 0 and benchmark_vpp:
            # 机会成本：这些积分拿去做最优确定性兑换能值多少
            # benchmark_vpp 单位是 元/积分，× 积分 = 元，再 ×100 转为分
            opportunity_fen = round(draw_point * benchmark_vpp * 100)
            lottery_out = {
                "activityName": activity_name,
                "statusText": status_text,
                "drawCostPoints": draw_point,
                "prizeCount": len(prizes) if isinstance(prizes, list) else 0,
                "prizeNames": [(_pick(p, "name") or "") for p in prizes] if isinstance(prizes, list) else [],
                "opportunityCostFen": opportunity_fen,
                "opportunityCostYuan": yuan(opportunity_fen),
                "breakEvenPrizeValueFen": opportunity_fen,
                "breakEvenPrizeValueYuan": yuan(opportunity_fen),
                "eligible": bool(draw_decision.get("resourceEligible")) if isinstance(draw_decision, dict) else None,
                "ineligibleReason": (_pick(draw_decision, "reason") if isinstance(draw_decision, dict) else None),
                "canAfford": draw_point <= available,
                "verdict": (
                    f"单次抽奖耗 {draw_point} 积分，这些积分若用于最优兑换约值 "
                    f"{yuan(opportunity_fen)} 元。因此只有当「期望奖品价值 ≥ {yuan(opportunity_fen)} 元」时，"
                    f"抽奖才跑赢直接兑换——低于这条线就是亏的。"
                ),
                "note": "官方未公开各奖品中奖概率，期望值需由中奖概率推算；此处给出的是盈亏平衡线（break-even）。",
            }

    # ---------- 3) 过期紧急度 ----------
    urgency = []
    if expire_now > 0:
        urgency.append({
            "level": "urgent",
            "points": expire_now,
            "message": f"本月有 {expire_now} 积分即将过期，务必优先用掉（归零价值为 0，即使单位价值低也要花）",
        })
    if expire_next > 0:
        urgency.append({
            "level": "soon",
            "points": expire_next,
            "message": f"下月还有 {expire_next} 积分到期，可提前规划兑换",
        })

    # ---------- 4) 结论 ----------
    recs = []
    if urgency and ranked:
        budget = expire_now or available
        pickable = [i for i in ranked if i["points"] <= budget]
        if pickable:
            recs.append(
                f"先用快过期的 {budget} 积分兑换「{pickable[0]['name']}」"
                f"（{pickable[0]['points']} 积分），单位价值 {pickable[0]['valuePerPointYuan']:.4f} 元/分，为当前最优。"
            )
    if benchmark_vpp:
        recs.append(
            f"当前积分最优确定性用途约 {benchmark_vpp:.4f} 元/分（「{ranked[0]['name']}」）。"
            "低于这个水平的选择，除非积分即将过期，否则不值得。"
        )
    if lottery_out:
        if lottery_out.get("eligible") is False:
            recs.append(f"当前抽奖不可参与：{lottery_out.get('ineligibleReason') or '条件不满足'}。")
        else:
            recs.append(lottery_out["verdict"])

    return {
        "summary": {
            "availablePoint": available,
            "currentMonthExpirePoint": expire_now,
            "nextMonthExpirePoint": expire_next,
            "evaluatedItems": len(items),
            "rankedItems": len(ranked),
            "benchmarkValuePerPointYuan": round(benchmark_vpp, 6) if benchmark_vpp else None,
        },
        "redemptionRanking": ranked,
        "allItems": items,
        "lottery": lottery_out,
        "expiryUrgency": urgency,
        "recommendations": recs,
        "disclaimer": ("valuePerPointYuan 依赖现金估值：confidence=high 表示来自接口价，"
                       "low 表示用了类目兜底估值，unknown 表示无法估值。估值仅用于横向比较，不代表可套现价值。"),
    }


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def self_test() -> int:
    payload = {
        "account": {
            "availablePoint": "3200",
            "currentMouthExpirePoint": "800",
            "nextMouthExpirePoint": "1200",
        },
        "products": [
            {"spuId": 100, "spuName": "免费脆薯饼券", "catName": "优惠券", "point": "100", "price": "9"},
            {"spuId": 101, "spuName": "麦辣鸡腿堡券", "catName": "优惠券", "point": "400", "price": "24"},
            {"spuId": 102, "spuName": "复古棒球帽", "catName": "周边产品", "point": "3000", "price": "0"},
            {"spuId": 103, "spuName": "麦金卡7天", "catName": "会员卡", "point": "0", "price": "0"},
        ],
        "lottery": {
            "activityName": "周六麦金喜抽奖",
            "activityStatusText": "进行中",
            "drawPoint": "24",
            "prizes": [{"name": "积分霸王餐"}, {"name": "下单立减3元券"}, {"name": "圆筒冰淇淋4折优惠券"}],
            "drawDecision": {"resourceEligible": True},
        },
        "valueHints": {"周边产品": 30},
    }
    res = advise(payload)
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    s = res["summary"]
    print("=== 积分顾问自检 ===")
    print(f"可用积分 {s['availablePoint']} | 本月将过期 {s['currentMonthExpirePoint']} | 下月 {s['nextMonthExpirePoint']}")
    print(f"最优单位价值 {s['benchmarkValuePerPointYuan']} 元/分")
    print("\n--- 兑换价值排行 ---")
    for i in res["redemptionRanking"]:
        print(f"  {i['name']:<14} {i['points']:>5} 积分 ≈ {i['cashValueYuan']:>7} 元"
              f" → {i['valuePerPointYuan']:.4f} 元/分 [{i['confidence']}]")

    # 脆薯饼: 9元/100分 = 0.09 元/分，应排第一
    check(res["redemptionRanking"][0]["name"] == "免费脆薯饼券", "价值排行第一应为脆薯饼券")
    check(abs(res["redemptionRanking"][0]["valuePerPointYuan"] - 0.09) < 1e-9, "脆薯饼单位价值应为 0.09")
    # 麦金卡积分为 0 → 应被过滤
    check(all(i["points"] > 0 for i in res["allItems"]), "积分为 0 的项应被跳过")
    # 棒球帽无接口价 → 用 valueHints 30 元
    hat = next(i for i in res["allItems"] if i["spuId"] == "102")
    check(hat["cashValueFen"] == 3000 and hat["confidence"] == "low", "周边应使用 valueHints 估值")
    # 抽奖盈亏平衡 = 24 * 0.09 = 2.16 元 = 216 分
    check(res["lottery"]["breakEvenPrizeValueFen"] == 216, f"抽奖盈亏平衡应为 216 分，实得 {res['lottery']['breakEvenPrizeValueFen']}")
    check(len(res["expiryUrgency"]) == 2, "应识别出两条过期提醒")

    print("\n--- 抽奖机会成本 ---")
    print(" ", res["lottery"]["verdict"])
    print("\n--- 建议 ---")
    for r in res["recommendations"]:
        print("  •", r)

    if fails:
        print("\n自检失败 ❌")
        for f in fails:
            print("  -", f)
        return 1
    print("\n自检通过 ✅")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="麦麦积分价值顾问")
    ap.add_argument("--input", "-i", help="输入 JSON 文件路径（- 表示 stdin）")
    ap.add_argument("--out", "-o", help="输出 JSON 文件路径")
    ap.add_argument("--json", action="store_true", help="完整 JSON 输出到 stdout")
    ap.add_argument("--self-test", action="store_true", help="运行内置样例自检")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.input:
        ap.print_help()
        return 2

    payload = json.load(sys.stdin) if args.input == "-" else json.load(open(args.input, encoding="utf-8"))
    res = advise(payload)

    s = res["summary"]
    print(f"可用积分 {s['availablePoint']}｜本月将过期 {s['currentMonthExpirePoint']}｜评估 {s['evaluatedItems']} 项")
    if res["redemptionRanking"]:
        print("-" * 62)
        print("兑换价值排行（元/分）：")
        for i in res["redemptionRanking"][:8]:
            print(f"  {i['name']:<16} {i['points']:>6} 积分 ≈ {i['cashValueYuan']:>8} 元  "
                  f"{i['valuePerPointYuan']:.4f} 元/分")
    if res["lottery"]:
        print("-" * 62)
        print(res["lottery"]["verdict"])
    if res["recommendations"]:
        print("-" * 62)
        for r in res["recommendations"]:
            print("  •", r)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\n完整结果已写入 {args.out}", file=sys.stderr)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
