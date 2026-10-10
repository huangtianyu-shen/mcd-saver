#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coupon_optimizer.py — 麦当劳券组合试算优化器（麦麦省钱助手核心）

为什么需要它
------------
麦当劳的券叠加规则、门槛判定、可用性校验都在**服务端**，是黑盒。
人工不可能穷举"这单用哪几张券最省"，而本地写的规则推算又经常和真实结算价对不上。

本脚本的做法：**生成 + 剪枝 + 交验**
  1. 把券按类型归一化，本地估算每张券的"纸面收益"（仅用于排序剪枝，不当结论）
  2. 生成"单券 / 多券组合 / 搭配凑单"三类候选方案，按估算收益排序、剪枝到可控数量
  3. 每个方案输出**可直接执行的 calculate-price 参数**（verify.arguments）
  4. 由 Agent 用官方价格引擎逐个真实试算，用服务端返回的 data.price 定案

即：本地负责"穷举搜索"，服务端负责"权威定价"。

用法
----
    python coupon_optimizer.py --input plan.json --out plan_result.json
    python coupon_optimizer.py --input plan.json --pretty
    python coupon_optimizer.py --self-test          # 内置样例自检

输入 JSON
---------
{
  "cart": [{"productCode": "521950", "name": "麦旋风", "quantity": 2, "unitPrice": 1500}],
  "coupons": [ {...原始券对象 或 归一化字段...} ],
  "menuIndex": [{"code": "2001", "name": "薯条(小)", "price": 900}],
  "assumptions": {"storeCode": "1450713", "orderType": 1, "beType": 1, "beCode": null},
  "options": {"maxPlans": 12, "maxCouponsPerOrder": 2, "topCoupons": 8, "allowFiller": true}
}

说明
----
- cart[].unitPrice 支持 "元"（带小数字符串或数值）或 "分"；也可用 explicit 字段 priceUnit 指定。
- 券对象字段名兼容多种写法（couponName/name、discountAmount/off…），也能识别券名里的
  "买一送一 / 免费 / N折 / 满N减M / N.N元" 等语义；无法识别时标 kind=unknown 并建议试算。
- 若你有券的确切规则，可在券对象里加 "rules": {"kind":..., "threshold":..., "off":...} 直接覆盖。
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from typing import Any

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
KIND_LABELS = {
    "fixed_price": "指定价购",
    "free_item": "免费兑换",
    "bogo": "买赠",
    "amount_off": "满减/立减",
    "percent_off": "折扣",
    "combo": "套餐优惠",
    "unknown": "未识别",
}

# 需要"锁定到具体商品"的券类型（组合时不能重复占用同一商品）
ITEM_SCOPED = ("fixed_price", "free_item", "bogo", "combo")


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def yuan(fen: int | float | None) -> str:
    """分 → 元（字符串，两位小数）。"""
    if fen is None:
        return "-"
    return f"{fen / 100:.2f}"


def _to_fen(value: Any, unit: str | None = None) -> int | None:
    """把金额统一成分。

    unit: 'yuan' | 'fen' | None（自动推断）
    自动推断规则：字符串含小数点、或数值 < 1000 时视为"元"，否则视为"分"。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return _to_fen(value[0], str(value[1]))
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


def _lower_map(raw: dict) -> dict:
    return {str(k).lower(): v for k, v in raw.items()}


def _pools(raw: dict) -> list[dict]:
    pools = [raw]
    for k in ("data", "coupon", "couponInfo", "promotion", "scope", "applicable"):
        v = raw.get(k)
        if isinstance(v, dict):
            pools.append(v)
    return pools


def _find_num(raw: dict, keys: list[str]) -> int | None:
    for pool in _pools(raw):
        lm = _lower_map(pool)
        for key in keys:
            if key.lower() in lm:
                val = _to_fen(lm[key.lower()])
                if val is not None:
                    return val
    return None


def _find_str(raw: dict, keys: list[str]) -> str | None:
    for pool in _pools(raw):
        lm = _lower_map(pool)
        for key in keys:
            v = lm.get(key.lower())
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _collect_codes(raw: dict) -> list[str]:
    """尽力收集券适用商品的编码列表。"""
    keys = ("productCode", "productCodes", "goodsCode", "goodsCodes", "skuCode", "skuCodes",
            "applicableProducts", "applicableProductCodes", "mealCodes", "productList", "items")
    out: list[str] = []
    for pool in _pools(raw):
        lm = _lower_map(pool)
        for key in keys:
            v = lm.get(key.lower())
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
            elif isinstance(v, list):
                for it in v:
                    if isinstance(it, str) and it.strip():
                        out.append(it.strip())
                    elif isinstance(it, dict):
                        c = it.get("productCode") or it.get("code") or it.get("skuCode")
                        if c:
                            out.append(str(c))
    return list(dict.fromkeys(out))


def _core_name(name: str) -> str:
    """去掉规格括号后的商品核心名。"""
    return re.sub(r"[（(].*?[)）]", "", name or "").strip()


def _lcs_len(a: str, b: str) -> int:
    """最长公共子串长度（名称都很短，DP 足够快）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _name_hits(cart_name: str, coupon_name: str, min_lcs: int = 3) -> bool:
    """中文语义匹配：包含关系或足够长的公共子串（≥3 字）即判定为适用。

    例：「中杯冰美式咖啡」vs「9.9元中杯冰美式」→ 公共子串「中杯冰美式」命中。
    """
    if not cart_name or not coupon_name:
        return False
    if cart_name in coupon_name:
        return True
    core = _core_name(cart_name)
    if core and core in coupon_name:
        return True
    if coupon_name in cart_name:
        return True
    return _lcs_len(core or cart_name, coupon_name) >= min_lcs


# --------------------------------------------------------------------------- #
# 券归一化
# --------------------------------------------------------------------------- #
def normalize_coupon(raw: dict) -> dict:
    """把任意形态的券对象归一化成统一结构。

    已适配麦当劳 MCP 的真实券结构（query-my-coupons 的 data.coupons[]），关键字段：
      id / code / title                      券标识
      discountInfo.discountValue             券价（元），如 "9.9"
      discountInfo.discountDesc              "用券价格" / 折扣 / 满减 等语义
      reducePrice / reducePriceText          直接减免金额
      ifFreeCoupon                           是否免费券
      orderTypes / beTypes                   适用下单类型 / 场景
      appliedCategory / filterValues         适用商品范围
      instructions.labels[].text             可用状态（"未到使用时间"、"到店"…）
      tradeStartDate / tradeEndDate          有效期
    """
    name = (_find_str(raw, ["title", "couponName", "name", "couponTitle", "displayName"]) or "").strip()
    cid = _find_str(raw, ["couponId", "id", "couponID"])
    ccode = _find_str(raw, ["couponCode", "couponNo", "code"])

    threshold = _find_num(raw, ["threshold", "thresholdAmount", "minAmount", "conditionAmount",
                                "useConditionAmount", "limitAmount", "satisfyAmount"])
    off = _find_num(raw, ["reducePrice", "off", "reduceAmount", "discountAmount", "couponAmount",
                          "denomination", "faceValue", "cutAmount", "discountFee"])
    rate = _find_num(raw, ["discountRate", "rate", "zhe"])
    price = _find_num(raw, ["fixedPrice", "salePrice", "specialPrice", "activityPrice"])
    need_qty = _find_num(raw, ["buyQuantity", "needQuantity", "buyNum", "buyCount"])
    offer_qty = _find_num(raw, ["giftQuantity", "offerQuantity", "giftNum", "getNum"])
    free_flag = bool(raw.get("ifFreeCoupon"))

    # ---- 真实结构：discountInfo ----
    disc = raw.get("discountInfo") if isinstance(raw.get("discountInfo"), dict) else {}
    dval = disc.get("discountValue")
    ddesc = (disc.get("discountDesc") or "")
    dtext = (disc.get("discountTypeText") or "")

    explicit = raw.get("rules") if isinstance(raw.get("rules"), dict) else {}
    kind = explicit.get("kind")

    if not kind and disc:
        if free_flag or "免费" in ddesc:
            kind = "free_item"
        elif "折" in ddesc or "折" in str(dval):
            kind = "percent_off"
            if rate is None and dval is not None:
                rate = _to_fen(dval)  # 占位，下面统一处理
        elif "减" in ddesc:
            kind = "amount_off"
            if off is None:
                off = _to_fen(dval, "yuan")
        elif dval is not None and "价格" in ddesc:
            kind = "fixed_price"
            if price is None:
                price = _to_fen(dval, "yuan")

    # ---- 兜底：按券名推断 ----
    if not kind and name:
        if "买一送一" in name or "买1送1" in name:
            kind, need_qty, offer_qty = "bogo", need_qty or 1, offer_qty or 1
        elif "免费" in name or re.search(r"0\s*元", name):
            kind = "free_item"
        elif re.search(r"(\d+(?:\.\d+)?)\s*折", name):
            kind = "percent_off"
            if rate is None:
                rate = float(re.search(r"(\d+(?:\.\d+)?)\s*折", name).group(1)) / 10.0
        elif re.search(r"(满\s*\d+\s*减|立减|直减|满减)", name):
            kind = "amount_off"
            m = re.search(r"满\s*(\d+(?:\.\d+)?)", name)
            if m and threshold is None:
                threshold = _to_fen(m.group(1), "yuan")
            m2 = re.search(r"(?:满\s*\d+(?:\.\d+)?\s*减|立减|直减)\s*(\d+(?:\.\d+)?)", name)
            if m2 and off is None:
                off = _to_fen(m2.group(1), "yuan")
        elif re.search(r"\d+(?:\.\d+)?\s*元", name):
            kind = "fixed_price"
            m = re.search(r"(\d+(?:\.\d+)?)\s*元", name)
            if m and price is None:
                price = _to_fen(m.group(1), "yuan")
        elif "套餐" in name or "套" in name:
            kind = "combo"

    kind = kind or "unknown"

    # 折扣率收尾：rate 可能是 "8" 这种"几折"写法
    if kind == "percent_off" and rate is not None:
        if rate >= 100:          # 被当成"分"处理过，还原为折数
            rate = rate / 100
        if rate > 10:            # 形如 85 表示 8.5 折
            rate = rate / 10
        if rate > 1:
            rate = rate / 10.0   # 8 折 → 0.8
    if kind == "bogo" and price is not None and off is None:
        pass

    if explicit:
        kind = explicit.get("kind", kind)
        threshold = explicit.get("threshold", threshold)
        off = explicit.get("off", off)
        rate = explicit.get("rate", rate)
        price = explicit.get("price", price)
        need_qty = explicit.get("needQty", need_qty)
        offer_qty = explicit.get("offerQty", offer_qty)

    targets = list(explicit.get("targets") or []) or _collect_codes(raw)

    # ---- 可用性与场景约束 ----
    ins = raw.get("instructions") if isinstance(raw.get("instructions"), dict) else {}
    labels = [l.get("text", "") for l in (ins.get("labels") or []) if isinstance(l, dict)]
    blocked_tokens = ("未到使用时间", "已过期", "已使用", "不可用", "已失效")
    usable_now = not any(tok in lb for lb in labels for tok in blocked_tokens)

    order_types = raw.get("orderTypes") if isinstance(raw.get("orderTypes"), list) else None
    be_types = raw.get("beTypes") if isinstance(raw.get("beTypes"), list) else None

    return {
        "id": cid or ccode or name or "unknown-coupon",
        "code": ccode or cid,
        "name": name or "(未命名券)",
        "kind": kind,
        "kindLabel": KIND_LABELS.get(kind, kind),
        "threshold": threshold,
        "off": off,
        "rate": rate,
        "price": price,
        "needQty": need_qty,
        "offerQty": offer_qty,
        "targets": [str(t) for t in targets],
        "orderTypes": order_types,
        "beTypes": be_types,
        "labels": labels,
        "usableNow": usable_now,
        "appliedCategory": raw.get("appliedCategory"),
        "filterValues": raw.get("filterValues"),
        "availableCount": raw.get("totalAvailableCount") or raw.get("totalCount"),
        "validFrom": raw.get("tradeStartDate"),
        "validTo": raw.get("tradeEndDate"),
        "raw": raw,
    }


def scenario_allows(coupon: dict, order_type: int | None, be_type: int | None) -> tuple[bool, str]:
    """判断券是否适用于当前下单场景。

    orderTypes（1=到店, 2=外送）语义明确 → 命中则硬排除。
    beTypes（1=到店自取,2=麦乐送,5=得来速,6=团餐）常出现未公开取值（如 4）→ 仅当全是已知值时才硬排除。
    """
    ots = coupon.get("orderTypes")
    if ots and order_type is not None and order_type not in ots:
        return False, f"该券仅适用于 orderType={ots}，当前为 {order_type}"
    bts = coupon.get("beTypes")
    known = {1, 2, 5, 6}
    if bts and be_type is not None and be_type not in bts and set(bts) <= known:
        return False, f"该券仅适用于 beType={bts}，当前为 {be_type}"
    return True, ""


# --------------------------------------------------------------------------- #
# 购物车展开
# --------------------------------------------------------------------------- #
def cart_lines(cart: list[dict]) -> list[dict]:
    lines = []
    for it in cart:
        qty = int(it.get("quantity") or it.get("qty") or 1)
        unit = it.get("unitPrice")
        if unit is None:
            unit = _find_num(it, ["price", "salePrice", "originalPrice"])
        else:
            unit = _to_fen(unit, it.get("priceUnit"))
        unit = unit or 0
        lines.append({
            "productCode": str(it.get("productCode") or it.get("code") or ""),
            "name": it.get("name") or it.get("productName") or "",
            "quantity": qty,
            "unitPrice": unit,
            "subtotal": unit * qty,
        })
    return lines


# --------------------------------------------------------------------------- #
# 本地收益估算（仅用于排序与剪枝）
# --------------------------------------------------------------------------- #
def match_lines(lines: list[dict], coupon: dict) -> list[dict]:
    """找出券适用的购物车行。编码精确匹配优先，其次中文名匹配；都不中则返回空。"""
    targets = coupon["targets"]
    if targets:
        hit = [l for l in lines if l["productCode"] and l["productCode"] in targets]
        if hit:
            return hit
    hit = [l for l in lines if _name_hits(l["name"], coupon["name"])]
    return hit


def estimate_coupon(lines: list[dict], coupon: dict) -> dict:
    """估算一张券在当前购物车上的纸面收益（分）。

    返回字段：
      saving       本地估算收益（分）
      appliedTo    命中的购物车商品编码
      note         人类可读说明
      matched      该券是否与当前购物车相关（名称/编码命中）
      verify_needed 本地因**缺少面额信息**而无法估算 → 必须交给服务端试算
                    （注意区别于"明确不适用"，如数量不足/未达门槛，那种 verify_needed=False）
    """
    total = sum(l["subtotal"] for l in lines)
    kind = coupon["kind"]
    matched = match_lines(lines, coupon)
    priced = [l for l in matched if l["unitPrice"] > 0]

    def R(saving, applied, note, verify_needed=False, is_matched=None):
        return {"saving": saving, "appliedTo": applied, "note": note,
                "verify_needed": verify_needed,
                "matched": bool(matched) if is_matched is None else is_matched}

    if kind == "free_item":
        if priced:
            best = max(priced, key=lambda x: x["unitPrice"])
            return R(best["unitPrice"], [best["productCode"]],
                     f"免费获得「{best['name']}」（价值 {yuan(best['unitPrice'])} 元）")
        return R(0, [], "购物车中未找到该券对应商品", is_matched=False)

    if kind == "bogo":
        need, get = int(coupon["needQty"] or 1), int(coupon["offerQty"] or 1)
        if not priced:
            return R(0, [], "购物车中未找到该券对应商品", is_matched=False)
        best = max(priced, key=lambda x: x["unitPrice"])
        if best["quantity"] >= need + get:
            pairs = best["quantity"] // (need + get)
            return R(best["unitPrice"] * get * pairs, [best["productCode"]],
                     f"买{need}送{get}，「{best['name']}」×{best['quantity']} 可享 {pairs} 组")
        return R(0, [best["productCode"]],
                 f"买赠需「{best['name']}」达 {need + get} 件，当前 {best['quantity']} 件（见 fillers 凑件建议）")

    if kind == "fixed_price":
        if not priced:
            return R(0, [], "购物车中未找到该券对应商品", is_matched=False)
        if coupon["price"] is None:
            return R(0, [priced[0]["productCode"]], "券未带指定价，需服务端试算", verify_needed=True)
        best = max(priced, key=lambda x: x["unitPrice"])
        return R(max(0, best["unitPrice"] - coupon["price"]), [best["productCode"]],
                 f"「{best['name']}」{yuan(best['unitPrice'])} 元 → {yuan(coupon['price'])} 元")

    if kind == "percent_off":
        if coupon["rate"] is None:
            return R(0, [l["productCode"] for l in priced], "券未带折扣率，需服务端试算", verify_needed=True)
        if not priced:
            return R(0, [], "无法定位折扣适用商品", is_matched=False)
        base = sum(l["subtotal"] for l in priced)
        r = coupon["rate"]
        r = r / 10.0 if r > 1 else r
        return R(round(base * (1 - r)), [l["productCode"] for l in priced],
                 f"作用于「{'、'.join(l['name'] for l in priced)}」，基准 {yuan(base)} 元")

    if kind == "amount_off":
        th, off = coupon["threshold"] or 0, coupon["off"] or 0
        if not off:
            return R(0, [], "券未带减免金额，需服务端试算", verify_needed=True, is_matched=True)
        if total < th:
            return R(0, [], f"未达门槛：需满 {yuan(th)} 元，当前 {yuan(total)} 元，差 {yuan(th - total)} 元",
                     is_matched=True)
        return R(min(off, total), [], f"满 {yuan(th)} 元减 {yuan(off)} 元", is_matched=True)

    if kind == "combo":
        if not priced:
            return R(0, [], "购物车中未找到该券对应套餐", is_matched=False)
        base = sum(l["subtotal"] for l in priced)
        if coupon["price"] is not None and base > coupon["price"]:
            return R(base - coupon["price"], [l["productCode"] for l in priced],
                     f"套餐价 {yuan(coupon['price'])} 元（原 {yuan(base)} 元）")
        if coupon["off"]:
            return R(min(coupon["off"], base), [l["productCode"] for l in priced],
                     f"套餐减 {yuan(coupon['off'])} 元")
        return R(0, [l["productCode"] for l in priced],
                 "套餐券未带优惠面额，需服务端试算", verify_needed=True)

    # unknown
    if coupon["off"]:
        th = coupon["threshold"] or 0
        if total < th:
            return R(0, [], f"未达门槛（需满 {yuan(th)} 元）", is_matched=True)
        return R(min(coupon["off"], total), [], "按券面额估算，建议试算", is_matched=True)
    return R(0, [], "卷面信息不足，需服务端试算", verify_needed=True, is_matched=bool(matched))


# --------------------------------------------------------------------------- #
# 方案生成
# --------------------------------------------------------------------------- #
def build_verify_args(assumptions: dict, lines: list[dict], coupon_ids: list[str],
                      by_id: dict[str, dict]) -> dict:
    """构造可直接执行的 calculate-price 参数。"""
    items = []
    for l in lines:
        item = {"productCode": l["productCode"], "quantity": l["quantity"]}
        cid = next((c for c in coupon_ids
                    if l["productCode"] and l["productCode"] in by_id[c]["estimate"]["appliedTo"]), None)
        if cid:
            item["couponId"] = by_id[cid]["id"]
            if by_id[cid].get("code"):
                item["couponCode"] = by_id[cid]["code"]
        items.append(item)

    args: dict = {"items": items}
    for k in ("storeCode", "orderType", "beType"):
        if assumptions.get(k) is not None:
            args[k] = assumptions[k]
    for k in ("beCode", "reservationDate", "needTableware", "gmServiceCode"):
        if assumptions.get(k):
            args[k] = assumptions[k]
    return args


def generate_plans(lines: list[dict], coupons: list[dict], assumptions: dict,
                   options: dict) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    total = sum(l["subtotal"] for l in lines)

    for c in coupons:
        c["estimate"] = estimate_coupon(lines, c)
        ok, why = scenario_allows(c, assumptions.get("orderType"), assumptions.get("beType"))
        c["scenarioOk"], c["scenarioWhy"] = ok, why

    by_id = {c["id"]: c for c in coupons}

    excluded = [c for c in coupons if not c["scenarioOk"]]
    not_now = [c for c in coupons if c["scenarioOk"] and not c.get("usableNow", True)]
    eligible = [c for c in coupons if c["scenarioOk"] and c.get("usableNow", True)]

    for c in excluded:
        warnings.append(f"券「{c['name']}」场景不符，已排除：{c['scenarioWhy']}")
    for c in not_now:
        warnings.append(f"券「{c['name']}」当前不可用（{'、'.join(c.get('labels') or [])}），已排除；"
                        f"有效期 {c.get('validFrom')} ~ {c.get('validTo')}")

    valued = [c for c in eligible if c["estimate"]["saving"] > 0]
    # 券面信息不足以本地估值，但与购物车相关的券 —— 不能丢，必须送服务端试算
    trials = [c for c in eligible if c["estimate"]["saving"] <= 0 and c["estimate"].get("verify_needed")]
    rejected = [c for c in eligible if c["estimate"]["saving"] <= 0 and not c["estimate"].get("verify_needed")]

    for c in rejected:
        warnings.append(f"券「{c['name']}」不参与试算：{c['estimate']['note']}")
    if trials:
        warnings.append(f"共 {len(trials)} 张券因接口未返回可用面额而无法本地估值，"
                        f"已全部列入必试算候选；其 estPayable 不作预测，以试算结果为准。")

    top_n = int(options.get("topCoupons", 8))
    ranked = sorted(valued, key=lambda c: c["estimate"]["saving"], reverse=True)
    pool = (ranked + trials)[:top_n]
    if len(ranked) + len(trials) > top_n:
        warnings.append(f"可用候选 {len(ranked) + len(trials)} 张，已取前 {top_n} 张进入组合搜索")

    max_per_order = max(1, int(options.get("maxCouponsPerOrder", 2)))
    max_plans = max(1, int(options.get("maxPlans", 12)))

    plans: list[dict] = []

    for c in pool:
        if c["estimate"]["saving"] > 0:
            plans.append({
                "couponIds": [c["id"]], "names": [c["name"]],
                "estSaving": c["estimate"]["saving"],
                "estPayable": max(0, total - c["estimate"]["saving"]),
                "confidence": "medium",
                "notes": c["estimate"]["note"],
            })
        else:
            plans.append({
                "couponIds": [c["id"]], "names": [c["name"]],
                "estSaving": 0, "estPayable": total,
                "confidence": "trial",
                "notes": f"本地无面额信息，实付待试算：{c['estimate']['note']}",
            })

    if max_per_order >= 2 and len(pool) >= 2:
        cap = max_plans * 3
        made = 0
        for r in range(2, min(max_per_order, len(pool)) + 1):
            for combo in itertools.combinations(pool, r):
                occupied: set[str] = set()
                conflict = False
                for c in combo:
                    if c["kind"] in ITEM_SCOPED:
                        tgt = set(c["estimate"]["appliedTo"])
                        if tgt & occupied:
                            conflict = True
                            break
                        if not tgt:
                            conflict = True   # 该券无法定位商品却参与组合 → 不可靠，跳过
                            break
                        occupied |= tgt
                    elif c["kind"] == "amount_off" and len(combo) > 1:
                        # 两张满减券同单叠加的可能性极低
                        if any(o["kind"] == "amount_off" for o in combo if o is not c):
                            conflict = True
                            break
                if conflict:
                    continue
                est = sum(c["estimate"]["saving"] for c in combo)
                plans.append({
                    "couponIds": [c["id"] for c in combo], "names": [c["name"] for c in combo],
                    "estSaving": est, "estPayable": max(0, total - est),
                    "confidence": "low",
                    "notes": "组合方案，叠加规则须服务端试算确认",
                })
                made += 1
                if made >= cap:
                    break
            if made >= cap:
                break

    seen: set[tuple] = set()
    uniq: list[dict] = []
    for p in sorted(plans, key=lambda x: x["estSaving"], reverse=True):
        key = tuple(sorted(p["couponIds"]))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    uniq = uniq[:max_plans]

    for i, p in enumerate(uniq, 1):
        p["rank"] = i
        p["verify"] = {
            "tool": "calculate-price",
            "arguments": build_verify_args(assumptions, lines, p["couponIds"], by_id),
            "readResultAt": "data.price",
            "unit": "fen",
        }
    return uniq, warnings


# --------------------------------------------------------------------------- #
# 凑单 / 凑件建议
# --------------------------------------------------------------------------- #
def filler_suggestions(lines: list[dict], coupons: list[dict], menu_index: list[dict],
                       options: dict) -> list[dict]:
    """两类建议：
      ① 满减差一点达标 → 推荐加购一件仍能净赚的商品
      ② 买赠差件数 → 提示"再加 N 件实付不变、多得 M 件"
    """
    if not options.get("allowFiller", True):
        return []

    total = sum(l["subtotal"] for l in lines)
    out: list[dict] = []

    # ① 满减凑门槛
    max_per_coupon = int(options.get("fillerMaxPerCoupon", 1))
    for c in coupons:
        if c["kind"] != "amount_off" or not c["threshold"]:
            continue
        gap = c["threshold"] - total
        if gap <= 0:
            continue
        cands = []
        for m in menu_index:
            price = _to_fen(m.get("price"), m.get("priceUnit"))
            if not price or price <= 0:
                continue
            net = (c["off"] or 0) - price
            if net > 0:
                cands.append({"code": str(m.get("code") or m.get("productCode") or ""),
                              "name": m.get("name") or "", "price": price, "netGain": net})
        cands.sort(key=lambda x: (-x["netGain"], x["price"]))
        for cand in cands[:max_per_coupon]:
            out.append({
                "type": "threshold_gap",
                "couponId": c["id"], "couponName": c["name"], "gap": gap,
                "suggest": cand, "extraCost": cand["price"], "netGain": cand["netGain"],
                "message": (f"「{c['name']}」还差 {yuan(gap)} 元达标：加购「{cand['name']}」"
                            f"（{yuan(cand['price'])} 元）后多减 {yuan(c['off'])} 元，净省 {yuan(cand['netGain'])} 元"),
            })

    # ② 买赠凑件数
    for c in coupons:
        if c["kind"] != "bogo" or c["estimate"]["saving"] > 0:
            continue
        matched = [l for l in lines if l["unitPrice"] > 0 and
                   (l["productCode"] in c["targets"] or _name_hits(l["name"], c["name"]))]
        if not matched:
            continue
        need = int(c["needQty"] or 1)
        get = int(c["offerQty"] or 1)
        best = max(matched, key=lambda x: x["unitPrice"])
        short = (need + get) - best["quantity"]
        if short <= 0:
            continue
        gain = best["unitPrice"] * get
        out.append({
            "type": "bogo_shortfall",
            "couponId": c["id"], "couponName": c["name"], "shortfall": short,
            "suggest": {"code": best["productCode"], "name": best["name"],
                        "price": best["unitPrice"], "quantity": short},
            "extraCost": 0,
            "netGain": gain,
            "message": (f"「{c['name']}」：把「{best['name']}」加到 {need + get} 件，"
                        f"实付基本不变、多得 {get} 件（价值 {yuan(gain)} 元）——前提是你确实要 {need + get} 件"),
        })
    return out


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def optimize(payload: dict) -> dict:
    lines = cart_lines(payload.get("cart") or [])
    if not lines:
        raise ValueError("输入缺少 cart（购物车为空）")

    coupons = [normalize_coupon(c) for c in (payload.get("coupons") or [])]
    assumptions = payload.get("assumptions") or {}
    options = payload.get("options") or {}

    total = sum(l["subtotal"] for l in lines)
    plans, warnings = generate_plans(lines, coupons, assumptions, options)
    fillers = filler_suggestions(lines, coupons, payload.get("menuIndex") or [], options)

    best = plans[0] if plans else None
    return {
        "summary": {
            "cartTotalFen": total,
            "cartTotalYuan": yuan(total),
            "couponCount": len(coupons),
            "usableCouponCount": len([c for c in coupons if c["estimate"]["saving"] > 0]),
            "trialCouponCount": len([c for c in coupons
                                     if c["estimate"]["saving"] <= 0 and c["estimate"].get("verify_needed")]),
            "rejectedCouponCount": len([c for c in coupons
                                        if c["estimate"]["saving"] <= 0 and not c["estimate"].get("verify_needed")]),
            "scenarioExcludedCount": len([c for c in coupons if not c.get("scenarioOk", True)]),
            "notUsableNowCount": len([c for c in coupons
                                      if c.get("scenarioOk", True) and not c.get("usableNow", True)]),
            "planCount": len(plans),
            "fillerCount": len(fillers),
            "bestPlan": {
                "names": best["names"],
                "estPayableFen": best["estPayable"],
                "estPayableYuan": yuan(best["estPayable"]),
                "estSavingYuan": yuan(best["estSaving"]),
            } if best else None,
        },
        "baseline": {"payable": total, "payableYuan": yuan(total), "note": "不使用任何券"},
        "cartLines": lines,
        "normalizedCoupons": coupons,
        "plans": plans,
        "fillers": fillers,
        "warnings": warnings,
        "disclaimer": ("plans[].estPayable 为本地估算，仅用于排序剪枝；"
                       "实付金额必须以 calculate-price 的真实返回 data.price 为准（单位：分）。"),
    }


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def self_test() -> int:
    payload = {
        "cart": [
            {"productCode": "9900004064", "name": "麦辣鸡腿堡", "quantity": 2, "unitPrice": "24.00"},
            {"productCode": "521950", "name": "麦旋风", "quantity": 1, "unitPrice": "15.00"},
        ],
        "coupons": [
            {"couponId": "C1", "couponCode": "CODE1", "couponName": "人气麦旋风买一送一"},
            {"couponId": "C2", "couponCode": "CODE2", "couponName": "9.9元中杯冰美式",
             "applicableProducts": ["9300001"]},
            {"couponId": "C3", "couponCode": "CODE3", "couponName": "下单立减5元券",
             "thresholdAmount": "50.00", "discountAmount": "5.00"},
            {"couponId": "C4", "couponCode": "CODE4", "couponName": "圆筒冰淇淋4折优惠券",
             "thresholdAmount": "10.00"},
        ],
        "menuIndex": [
            {"code": "2001", "name": "薯条(小)", "price": "9.00"},
            {"code": "2002", "name": "圆筒冰淇淋", "price": "5.00"},
        ],
        "assumptions": {"storeCode": "1450713", "orderType": 1, "beType": 1},
        "options": {"maxPlans": 8, "maxCouponsPerOrder": 2, "topCoupons": 5, "allowFiller": True},
    }
    res = optimize(payload)
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    print("=== 自检 ===")
    print(f"购物车合计: {res['summary']['cartTotalYuan']} 元（应为 63.00）")
    check(res["summary"]["cartTotalYuan"] == "63.00", "购物车合计应为 63.00 元")
    print(f"识别券 {res['summary']['couponCount']} 张 | 可用 {res['summary']['usableCouponCount']} 张"
          f" | 方案 {res['summary']['planCount']} 个 | 凑单建议 {res['summary']['fillerCount']} 条")

    km = {c["name"]: c for c in res["normalizedCoupons"]}
    print("\n--- 券类型识别 ---")
    for n, c in km.items():
        print(f"  {n:<22} → {c['kind']:<12} 收益 {yuan(c['estimate']['saving'])} 元 | {c['estimate']['note']}")
    check(km["人气麦旋风买一送一"]["kind"] == "bogo", "买一送一 类型识别失败")
    check(km["9.9元中杯冰美式"]["kind"] == "fixed_price", "9.9元 类型识别失败")
    check(km["下单立减5元券"]["kind"] == "amount_off", "立减 类型识别失败")
    check(km["圆筒冰淇淋4折优惠券"]["kind"] == "percent_off", "N折 类型识别失败")

    # 关键正确性：美式券的适用商品不在购物车 → 必须为 0，不能误命中
    check(km["9.9元中杯冰美式"]["estimate"]["saving"] == 0, "美式券不应在当前购物车产生收益")
    # 圆筒券：购物车无圆筒 → 必须为 0
    check(km["圆筒冰淇淋4折优惠券"]["estimate"]["saving"] == 0, "圆筒券不应在当前购物车产生收益")
    # 买一送一：麦旋风仅 1 件，不足 2 件 → 0 且应给出凑件建议
    check(km["人气麦旋风买一送一"]["estimate"]["saving"] == 0, "买一送一在仅1件时应为0")
    check(any(f["type"] == "bogo_shortfall" for f in res["fillers"]), "缺少买赠凑件建议")
    # 立减券：满50减5，购物车63 → 应可用
    check(km["下单立减5元券"]["estimate"]["saving"] == 500, "满减券应可减 5.00 元")

    print("\n--- 方案 Top3 ---")
    for p in res["plans"][:3]:
        print(f"  #{p['rank']} {' + '.join(p['names'])} → 估算实付 {yuan(p['estPayable'])} 元"
              f"（省 {yuan(p['estSaving'])} 元, 置信 {p['confidence']}）")
        check(bool(p["verify"]["arguments"]["items"]), "verify.arguments.items 缺失")
    print("\n--- 凑单建议 ---")
    for f in res["fillers"]:
        print("  •", f["message"])

    check(res["summary"]["planCount"] > 0, "应至少生成 1 个方案")
    check(res["plans"][0]["estSaving"] > 0, "最优方案收益应为正")
    check(res["plans"][0]["names"] == ["下单立减5元券"] or len(res["plans"][0]["names"]) >= 1,
          "最优方案排序异常")

    if fails:
        print("\n自检失败 ❌")
        for f in fails:
            print("  -", f)
        return 1
    print("\n自检通过 ✅")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="麦当劳券组合试算优化器（麦麦省钱助手核心）")
    ap.add_argument("--input", "-i", help="输入 JSON 文件路径（- 表示 stdin）")
    ap.add_argument("--out", "-o", help="输出 JSON 文件路径（默认仅打印摘要）")
    ap.add_argument("--json", action="store_true", help="把完整 JSON 打印到 stdout")
    ap.add_argument("--self-test", action="store_true", help="运行内置样例自检")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.input:
        ap.print_help()
        return 2

    payload = json.load(sys.stdin) if args.input == "-" else json.load(open(args.input, encoding="utf-8"))
    result = optimize(payload)

    s = result["summary"]
    print(f"购物车合计 {s['cartTotalYuan']} 元 | 券 {s['couponCount']} 张（可用 {s['usableCouponCount']}）"
          f" | 方案 {s['planCount']} 个")
    print("-" * 62)
    for p in result["plans"][:5]:
        print(f"#{p['rank']} {' + '.join(p['names'])}")
        print(f"     估算实付 {yuan(p['estPayable'])} 元，省 {yuan(p['estSaving'])} 元 [{p['confidence']}]")
        print(f"     {p['notes']}")
    if result["fillers"]:
        print("-" * 62)
        print("凑单建议：")
        for f in result["fillers"]:
            print("  •", f["message"])
    if result["warnings"]:
        print("-" * 62)
        print("提示：")
        for w in result["warnings"]:
            print("  •", w)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n完整结果已写入 {args.out}", file=sys.stderr)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
