#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简 MCP stdio 客户端：跟 `concat --mcp headless` 对话。

只用标准库，不需要装 mcp SDK。
    from concat_client import Concat
    c = Concat()
    c.call("project_create", {"location": "/root", "name": "p", "width": 1080, "height": 1920})
    c.close()

注意：`call()` 返回 structuredContent（一般已反序列化成 dict/list）。
"""
import json
import os
import subprocess


class Concat:
    def __init__(self, mode="headless", binary="concat"):
        env = dict(os.environ)
        env.pop("DISPLAY", None)          # 无显示器环境下必须清掉
        self.p = subprocess.Popen(
            [binary, "--mcp", mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, env=env)
        self.id = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "probe", "version": "1"}})

    def rpc(self, method, params=None):
        self.id += 1
        msg = {"jsonrpc": "2.0", "id": self.id, "method": method}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("MCP 断开")
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("id") == self.id:
                if "error" in d:
                    raise RuntimeError(f"{method} 失败: {d['error']}")
                return d["result"]

    def call(self, tool, args=None):
        r = self.rpc("tools/call", {"name": tool, "arguments": args or {}})
        if r.get("isError"):
            txt = "".join(c.get("text", "") for c in r.get("content", []))
            raise RuntimeError(f"{tool}: {txt}")
        if "structuredContent" in r:
            return r["structuredContent"]
        txt = "".join(c.get("text", "") for c in r.get("content", []))
        try:
            return json.loads(txt)
        except Exception:
            return txt

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
        except Exception:
            pass


def brief(x, n=600):
    s = json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x
    return s[:n] + ("..." if len(s) > n else "")
