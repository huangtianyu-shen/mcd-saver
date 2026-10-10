#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_client.py — 麦当劳中国 MCP 轻量客户端（零第三方依赖）

用途
----
WorkBuddy / Cursor / Cherry Studio 等 MCP Client 会原生暴露麦当劳的 35 个工具；
本客户端用于**脱离 IDE 独立运行**：数据管道、批量试算、参赛演示、自动化脚本。

协议
----
MCP Streamable HTTP（POST JSON-RPC 2.0 → 响应可能是 application/json 或 text/event-stream/SSE）。
鉴权：请求头 Authorization: Bearer <MCP Token>

用法
----
    # 环境变量提供 Token（推荐）
    export MCD_MCP_TOKEN=xxxx
    python mcp_client.py tools
    python mcp_client.py call available-coupons
    python mcp_client.py call query-meals --args '{"storeCode":"1450713","orderType":1,"beType":1}'
    python mcp_client.py call query-my-coupons --args '{"page":"1","pageSize":"20"}' --json

    # 或直接写进环境文件 .env（同目录）：MCD_MCP_TOKEN=xxxx
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "mcd-saver"


# --------------------------------------------------------------------------- #
# Token / 环境
# --------------------------------------------------------------------------- #
def _load_dotenv() -> None:
    """从脚本同级或工作目录的 .env 读取 MCD_MCP_TOKEN（不覆盖已有环境变量）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.getcwd(), os.path.dirname(here)):
        path = os.path.join(base, ".env")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            pass


_load_dotenv()


class McdMcpError(RuntimeError):
    """MCP 协议层错误。"""


class BusinessError(RuntimeError):
    """麦当劳业务层错误（success=false），携带 code。"""

    def __init__(self, code, message, payload=None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.payload = payload or {}


class McdMcpClient:
    """极简 MCP 客户端：initialize → notifications/initialized → tools/list|call。"""

    def __init__(self, token: str | None = None, url: str | None = None, timeout: int = 60):
        self.token = token or os.environ.get("MCD_MCP_TOKEN") or os.environ.get("MCDCN_MCP_TOKEN") or ""
        self.url = url or os.environ.get("MCD_MCP_URL") or DEFAULT_URL
        self.timeout = timeout
        self.session_id: str | None = None
        self._rid = 0
        self._initialized = False

    # -- 底层 --------------------------------------------------------------- #
    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _post(self, method: str, params=None, notify: bool = False):
        self._rid += 1
        body = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = self._rid
        if params is not None:
            body["params"] = params

        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"), headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise McdMcpError(f"HTTP {e.code}: {detail[:400]}") from None
        except OSError as e:
            raise McdMcpError(f"网络错误: {e!r}") from None

        if notify:
            return None
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str):
        """兼容纯 JSON 与 SSE（data: {...}）两种响应体。"""
        raw = (raw or "").strip()
        if not raw:
            return None
        if raw.startswith("{"):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
        return None

    # -- 会话 --------------------------------------------------------------- #
    def initialize(self) -> dict:
        if self._initialized:
            return {"session_id": self.session_id}
        resp = self._post(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": "1.0.0"},
            },
        )
        if not resp:
            raise McdMcpError("initialize 无响应；请检查 URL / Token / 网络")
        if "error" in resp:
            raise McdMcpError(f"initialize 失败: {resp['error']}")
        self._post("notifications/initialized", None, notify=True)
        self._initialized = True
        return resp.get("result", {})

    def list_tools(self) -> list[dict]:
        self.initialize()
        resp = self._post("tools/list", {})
        if not resp or "error" in resp:
            raise McdMcpError(f"tools/list 失败: {resp and resp.get('error')}")
        return (resp.get("result") or {}).get("tools", [])

    def call(self, name: str, arguments: dict | None = None, *, raise_on_business_error: bool = False) -> dict:
        """调用工具，返回 structuredContent（即麦当劳业务响应体）。

        参数
        ----
        raise_on_business_error: 为 True 时，success=false 会抛 BusinessError；
                                 默认 False，直接返回响应体，由调用方自行判断。
        """
        self.initialize()
        resp = self._post("tools/call", {"name": name, "arguments": arguments or {}})
        if not resp:
            raise McdMcpError(f"{name} 无响应")
        if "error" in resp:
            raise McdMcpError(f"{name} 协议错误: {resp['error']}")

        result = resp.get("result") or {}
        payload = result.get("structuredContent")

        if payload is None:
            # 退化路径：仅返回 content 文本时，尝试解析
            texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
            joined = "\n".join(texts)
            if not joined:
                raise McdMcpError(f"{name} 返回为空")
            try:
                payload = json.loads(joined)
            except json.JSONDecodeError:
                payload = {"success": None, "data": None, "text": joined}

        if isinstance(payload, dict) and payload.get("success") is False:
            if raise_on_business_error:
                raise BusinessError(payload.get("code"), payload.get("message", ""), payload)
        return payload

    # -- 便捷方法（省钱助手常用） -------------------------------------------- #
    def now(self) -> dict:
        return self.call("now-time-info")

    def available_coupons(self) -> dict:
        return self.call("available-coupons")

    def auto_bind_coupons(self) -> dict:
        return self.call("auto-bind-coupons")

    def my_coupons(self, page: int = 1, page_size: int = 50) -> dict:
        return self.call("query-my-coupons", {"page": str(page), "pageSize": str(page_size)})

    def my_account(self) -> dict:
        return self.call("query-my-account")

    def campaign_calendar(self, specified_date: str | None = None) -> dict:
        return self.call("campaign-calendar", {"specifiedDate": specified_date} if specified_date else {})

    def nearby_stores(self, city: str, keyword: str, be_type: int = 1) -> dict:
        return self.call(
            "query-nearby-stores",
            {"beType": be_type, "searchType": 2, "city": city, "keyword": keyword},
        )

    def meals(self, store_code: str, order_type: int = 1, be_type: int = 1, be_code: str | None = None) -> dict:
        args = {"storeCode": store_code, "orderType": order_type, "beType": be_type}
        if be_code:
            args["beCode"] = be_code
        return self.call("query-meals", args)

    def store_coupons(self, store_code: str, order_type: int = 1, be_type: int = 1, be_code: str | None = None) -> dict:
        args = {"storeCode": store_code, "orderType": order_type, "beType": be_type}
        if be_code:
            args["beCode"] = be_code
        return self.call("query-store-coupons", args)

    def calculate_price(self, store_code: str, items: list[dict], order_type: int = 1,
                        be_type: int = 1, be_code: str | None = None, **extra) -> dict:
        args = {"storeCode": store_code, "orderType": order_type, "beType": be_type, "items": items}
        if be_code:
            args["beCode"] = be_code
        args.update({k: v for k, v in extra.items() if v is not None})
        return self.call("calculate-price", args)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _out(obj, as_json: bool):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return
    sc = obj.get("structuredContent") if isinstance(obj, dict) and "structuredContent" in obj else obj
    if isinstance(sc, dict):
        ok = sc.get("success")
        print(f"[{'成功' if ok else '失败'}] code={sc.get('code')} {sc.get('message','')}")
        data = sc.get("data")
        if data is not None:
            print(json.dumps(data, ensure_ascii=False, indent=2)[:6000])
    else:
        print(json.dumps(sc, ensure_ascii=False, indent=2)[:6000])


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    cmd = argv[1]
    as_json = "--json" in argv
    args: dict = {}
    if "--args" in argv:
        try:
            args = json.loads(argv[argv.index("--args") + 1])
        except (IndexError, json.JSONDecodeError) as e:
            print(f"--args 解析失败: {e}", file=sys.stderr)
            return 2

    token = os.environ.get("MCD_MCP_TOKEN") or os.environ.get("MCDCN_MCP_TOKEN")
    if not token:
        print("未找到 MCP Token。请设置环境变量 MCD_MCP_TOKEN，或在本目录创建 .env 写入 MCD_MCP_TOKEN=xxx", file=sys.stderr)
        return 3

    client = McdMcpClient()

    try:
        if cmd == "tools":
            tools = client.list_tools()
            for t in tools:
                sch = t.get("inputSchema") or {}
                req = set(sch.get("required") or [])
                props = list((sch.get("properties") or {}).keys())
                mark = [f"{p}*" for p in props if p in req] + [p for p in props if p not in req]
                print(f"- {t['name']}({', '.join(mark)})")
            print(f"\n共 {len(tools)} 个工具")
            return 0

        if cmd == "call":
            if len(argv) < 3:
                print("用法: mcp_client.py call <tool-name> [--args JSON] [--json]", file=sys.stderr)
                return 2
            result = client.call(argv[2], args)
            _out(result, as_json)
            return 0

        if cmd == "raw":
            # 输出完整 JSON-RPC 响应，便于调试
            client.initialize()
            print(json.dumps(client._post("tools/call", {"name": argv[2], "arguments": args}), ensure_ascii=False, indent=2))
            return 0

        print(f"未知命令: {cmd}", file=sys.stderr)
        return 2

    except McdMcpError as e:
        print(f"MCP 错误: {e}", file=sys.stderr)
        return 1
    except BusinessError as e:
        print(f"业务错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
