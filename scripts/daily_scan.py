#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_scan.py — 麦麦省钱助手 · 一键省钱巡检（端到端流水线）

一条命令跑完整个决策链：
    采集真实数据 → 券盘点 → 积分估值 → 活动择时 → 购物车方案优化 → 官方价格引擎真实试算 → 渲染省钱日报

用法
----
    export MCD_MCP_TOKEN=xxxx
    python daily_scan.py --city 上海市 --keyword 人民广场 --out 省钱日报.html
    python daily_scan.py --city 上海市 --keyword 人民广场 --claim          # 同时执行一键领券
    python daily_scan.py --city 上海市 --keyword 人民广场 --cart 9900004064:2,521950:1
    python daily_scan.py --self-test

说明
----
- 默认**只读**：不加 --claim 不会执行任何领券/下单等写操作。
- --cart 格式 `商品code:数量,商品code:数量`，用于生成并真实试算下单方案。
- 未指定 --cart 时，自动从该门店菜单里挑 3 个在售餐品作为演示购物车。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_client import McdMcpClient, McdMcpError  # noqa: E402
import coupon_optimizer as opt  # noqa: E402
import points_advisor as pts  # noqa: E402
import saving_report as rep  # noqa: E402


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _data(resp) -> object:
    return (resp or {}).get("data") if isinstance(resp, dict) else resp


def _ok(resp) -> bool:
    return bool(isinstance(resp, dict) and resp.get("success"))


# --------------------------------------------------------------------------- #
# 采集
# --------------------------------------------------------------------------- #
def pick_store(client: McdMcpClient, city: str, keyword: str, be_type: int = 1) -> dict | None:
    r = client.nearby_stores(city, keyword, be_type)
    if not _ok(r):
        log(f"  ! 门店搜索失败：{r.get('message')}")
        return None
    stores = _data(r) or []
    if not stores:
        log("  ! 未找到门店")
        return None
    s = stores[0]
    log(f"  ✓ 门店：{s.get('storeName')}（{s.get('storeCode')}）")
    return s


def flatten_menu(menu_resp) -> list[dict]:
    """query-meals 返回按分类分组的 [{name, meals:[{code,tags}]}]，摊平成商品列表。"""
    out: list[dict] = []
    cats = _data(menu_resp) or []
    if isinstance(cats, dict):
        cats = cats.get("categories") or cats.get("list") or []
    for cat in cats:
        if not isinstance(cat, dict):
            continue
        cat_name = cat.get("name") or ""
        for m in cat.get("meals") or []:
            if isinstance(m, dict) and m.get("code"):
                out.append({"code": str(m["code"]), "name": cat_name,
                            "tags": m.get("tags") or []})
    return out


def probe_unit_price(client: McdMcpClient, store_code: str, codes: list[str],
                     order_type: int, be_type: int, be_code: str | None) -> dict[str, int]:
    """用 calculate-price 单件试算，拿到商品的真实零售价（分）。"""
    prices: dict[str, int] = {}
    for code in codes:
        try:
            r = client.calculate_price(store_code, [{"productCode": code, "quantity": 1}],
                                       order_type=order_type, be_type=be_type, be_code=be_code)
            if _ok(r):
                p = (_data(r) or {}).get("price")
                if isinstance(p, int) and p > 0:
                    prices[code] = p
        except McdMcpError:
            continue
    return prices


def probe_item_details(client: McdMcpClient, store_code: str, codes: list[str],
                       order_type: int, be_type: int, be_code: str | None) -> dict[str, dict]:
    """一次性拿到候选商品的真实名称与零售价（名称来自 query-meal-detail，价格来自 calculate-price）。

    query-meals 只返回商品编码，没有名称也没有价格；要匹配优惠券必须拿到人可读的名称。
    """
    info: dict[str, dict] = {}
    for code in codes:
        name = ""
        try:
            d = client.call("query-meal-detail", {"storeCode": store_code, "orderType": order_type,
                                                  "beType": be_type, "code": code,
                                                  **({"beCode": be_code} if be_code else {})})
            if _ok(d):
                name = (_data(d) or {}).get("name") or ""
        except McdMcpError:
            pass
        price = None
        try:
            r = client.calculate_price(store_code, [{"productCode": code, "quantity": 1}],
                                       order_type=order_type, be_type=be_type, be_code=be_code)
            if _ok(r):
                p = (_data(r) or {}).get("price")
                if isinstance(p, int) and p > 0:
                    price = p
        except McdMcpError:
            pass
        if name or price:
            info[code] = {"name": name, "price": price}
    return info


def choose_demo_cart(candidates: list[dict], info: dict[str, dict],
                     coupon_names: list[str], limit: int = 3) -> dict[str, int]:
    """挑一个能被优惠券命中的演示购物车。

    优先选名称能与候选券对上的商品（这样方案对比才有内容），
    否则退回到价格合理的常规餐品。
    """
    scored = []
    for c in candidates:
        code = c["code"]
        d = info.get(code) or {}
        name, price = d.get("name") or "", d.get("price")
        if not name or not price:
            continue
        hit = any(opt._name_hits(name, cn) for cn in coupon_names if cn)
        scored.append({"code": code, "name": name, "price": price, "hit": hit})

    hits = [s for s in scored if s["hit"]]
    food = [s for s in scored if 500 <= s["price"] <= 6000]

    picks = list(hits[:limit])
    # 补足到 limit 件：优先补充其它常规餐品，让方案对比更有意义
    if len(picks) < limit:
        chosen = {p["code"] for p in picks}
        for cand in (food or scored):
            if len(picks) >= limit:
                break
            if cand["code"] in chosen:
                continue
            picks.append(cand)
            chosen.add(cand["code"])
    return {s["code"]: 1 for s in picks}


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run(args) -> int:
    client = McdMcpClient(token=args.token, url=args.url)
    bundle: dict = {"generatedAt": _dt.datetime.now().strftime("%Y-%m-%d %H:%M")}

    # ---- 1. 时间 ----
    log("[1/7] 获取服务端时间…")
    now = client.now()
    srv_time = ""
    if _ok(now):
        srv_time = (_data(now) or {}).get("formatted", "")
        log(f"  ✓ 服务端时间 {srv_time}（{( _data(now) or {}).get('dayOfWeek','')}）")
    bundle["serverTime"] = srv_time

    # ---- 2. 券 ----
    log("[2/7] 盘点优惠券…")
    claimable = client.available_coupons()
    bundle["claimable"] = _data(claimable) or []
    log(f"  ✓ 可领 {len(bundle['claimable'])} 张")

    if args.claim and bundle["claimable"]:
        log("  → 执行一键领券 auto-bind-coupons…")
        claimed = client.auto_bind_coupons()
        bundle["claimed"] = claimed
        log(f"  {'✓ 领券成功' if _ok(claimed) else '! 领券失败：' + str(claimed.get('message'))}")

    my = client.my_coupons(page_size=50)
    coupons = ((_data(my) or {}).get("coupons") if _ok(my) else []) or []
    bundle["coupons"] = coupons
    log(f"  ✓ 券包 {len(coupons)} 张")

    # ---- 3. 积分 ----
    log("[3/7] 积分账户与商城…")
    account = client.my_account()
    bundle["account"] = _data(account) or {}
    products = client.call("mall-points-products")
    lottery = client.call("query-lottery-info")
    advice = pts.advise({
        "account": bundle["account"],
        "products": _data(products) or [],
        "lottery": _data(lottery) or {},
    })
    bundle["pointsAdvice"] = advice
    log(f"  ✓ 可用积分 {advice['summary']['availablePoint']}，"
        f"本月将过期 {advice['summary']['currentMonthExpirePoint']}")

    # ---- 4. 活动 ----
    log("[4/7] 活动日历…")
    cal = client.campaign_calendar()
    bundle["calendar"] = _data(cal) or {}
    log(f"  ✓ 取到 {len(bundle['calendar'].get('dailyList') or [])} 天活动")

    # ---- 5. 门店 ----
    log("[5/7] 定位门店与菜单…")
    store = pick_store(client, args.city, args.keyword)
    plan_result = None
    verify_results = []

    if store:
        store_code = str(store.get("storeCode"))
        be_type, order_type, be_code = 1, 1, None
        menu = client.meals(store_code, order_type=order_type, be_type=be_type)
        items = flatten_menu(menu)
        log(f"  ✓ 菜单 {len(items)} 个餐品")

        # ---------- 6. 购物车方案 ----------
        log("[6/7] 生成下单方案并真实试算…")

        # 候选券：门店可用券优先，其次券包，最后可领券
        sc = client.store_coupons(store_code, order_type=order_type, be_type=be_type)
        store_coupons = _data(sc) if _ok(sc) else []
        candidate_coupons = store_coupons or coupons or bundle["claimable"]
        coupon_names = [opt.normalize_coupon(c)["name"] for c in candidate_coupons]
        log(f"  · 候选券 {len(candidate_coupons)} 张"
            f"（来源：{'门店可用券' if store_coupons else '券包/可领券'}）")

        # 决定购物车
        if args.cart:
            cart_spec = {}
            for pair in args.cart.split(","):
                if ":" in pair:
                    c, q = pair.split(":", 1)
                    cart_spec[c.strip()] = int(q)
            probe_codes = list(cart_spec.keys())
        else:
            # 从菜单里取样（每个分类取前几个），再挑能被券命中的
            sample: list[dict] = []
            seen: set[str] = set()
            per_cat = 3
            for it in items:
                n = sum(1 for s in sample if s["name"] == it["name"])
                if n >= per_cat or it["code"] in seen:
                    continue
                seen.add(it["code"])
                sample.append(it)
            probe_codes = [s["code"] for s in sample][:36]
            log(f"  · 取样 {len(probe_codes)} 个餐品用于比价")

        info = probe_item_details(client, store_code, probe_codes, order_type, be_type, be_code)
        log(f"  · 取得 {len(info)} 个餐品的名称与价格")

        if args.cart:
            cart_spec = {c: q for c, q in cart_spec.items() if c in info}
        else:
            cart_spec = choose_demo_cart(sample, info, coupon_names)

        prices = {c: info[c]["price"] for c in cart_spec if info.get(c, {}).get("price")}
        cart = [{"productCode": c, "name": info.get(c, {}).get("name", ""),
                 "quantity": q, "unitPrice": prices[c]}
                for c, q in cart_spec.items() if c in prices]
        if cart:
            log("  · 演示购物车：" + "、".join(f"{i['name']}×{i['quantity']}" for i in cart))

        if cart and candidate_coupons:
            # 凑单候选：菜单内已取得价格的商品
            menu_index = [{"code": c, "name": d.get("name") or "", "price": d.get("price")}
                          for c, d in info.items() if d.get("price")]
            plan_result = opt.optimize({
                "cart": cart,
                "coupons": candidate_coupons,
                "menuIndex": menu_index,
                "assumptions": {"storeCode": store_code, "orderType": order_type,
                                "beType": be_type, "beCode": be_code},
                "options": {"maxPlans": 8, "maxCouponsPerOrder": 2, "topCoupons": 6},
            })
            log(f"  ✓ 生成 {len(plan_result['plans'])} 个候选方案，"
                f"{len(plan_result['fillers'])} 条凑单建议")

            # 基准价：不用券的真实价格
            baseline_r = client.calculate_price(
                store_code, [{"productCode": c, "quantity": q} for c, q in cart_spec.items() if c in prices],
                order_type=order_type, be_type=be_type, be_code=be_code)
            if _ok(baseline_r):
                plan_result["baseline"]["payable"] = (_data(baseline_r) or {}).get(
                    "price", plan_result["baseline"]["payable"])
                plan_result["baseline"]["payableYuan"] = opt.yuan(plan_result["baseline"]["payable"])

            # 关键：用官方价格引擎逐个真实试算候选方案
            for p in plan_result["plans"][:6]:
                va = dict(p["verify"]["arguments"])
                va.update({"storeCode": store_code, "orderType": order_type, "beType": be_type})
                if be_code:
                    va["beCode"] = be_code
                try:
                    res = client.calculate_price(va.pop("storeCode"), va.pop("items"),
                                                 order_type=va.pop("orderType"),
                                                 be_type=va.pop("beType"),
                                                 be_code=va.pop("beCode", None), **va)
                    verify_results.append({"plan": p, "ok": _ok(res), "price": res})
                    if _ok(res):
                        real = (_data(res) or {}).get("price")
                        log(f"    #{p['rank']} {'+'.join(p['names'])} → 真实实付 {opt.yuan(real)} 元"
                            f"（本地估算 {opt.yuan(p['estPayable'])}）")
                    else:
                        log(f"    #{p['rank']} {'+'.join(p['names'])} → 试算被拒：{res.get('message')}")
                except McdMcpError as e:
                    verify_results.append({"plan": p, "ok": False, "error": str(e)})
                    log(f"    #{p['rank']} 试算异常：{e}")

            bundle["planResult"] = plan_result
            bundle["verifyResults"] = verify_results
        else:
            log("  ! 未生成方案（购物车或候选券为空）")
    else:
        log("  ! 跳过方案优化（未定位到门店）")

    # ---- 7. 日报 ----
    log("[7/7] 渲染省钱日报…")
    html_out = rep.render(bundle)
    out_path = args.out or "省钱日报.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    with open(os.path.splitext(out_path)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)
    print(f"✅ 日报已生成：{out_path}（{len(html_out):,} 字符）")
    return 0


# --------------------------------------------------------------------------- #
def self_test() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="上海市")
    ap.add_argument("--keyword", default="人民广场")
    ap.add_argument("--out")
    ap.add_argument("--claim", action="store_true")
    ap.add_argument("--cart")
    ap.add_argument("--token")
    ap.add_argument("--url")
    args = ap.parse_args([])
    print("daily_scan 自检：参数解析正常，模块导入正常 ✅")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="麦麦省钱助手 · 一键省钱巡检")
    ap.add_argument("--city", default="上海市", help="城市（门店搜索用）")
    ap.add_argument("--keyword", default="人民广场", help="位置关键词")
    ap.add_argument("--out", "-o", help="输出 HTML 路径")
    ap.add_argument("--claim", action="store_true", help="执行一键领券（写操作，默认关闭）")
    ap.add_argument("--cart", help="购物车 `code:qty,code:qty`")
    ap.add_argument("--token", help="MCP Token（默认读环境变量 MCD_MCP_TOKEN）")
    ap.add_argument("--url", help="MCP Server 地址（默认 https://mcp.mcd.cn）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if not (args.token or os.environ.get("MCD_MCP_TOKEN") or os.environ.get("MCDCN_MCP_TOKEN")):
        print("缺少 MCP Token：请设置环境变量 MCD_MCP_TOKEN，或用 --token 传入。", file=sys.stderr)
        return 3

    try:
        return run(args)
    except McdMcpError as e:
        print(f"MCP 错误：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
