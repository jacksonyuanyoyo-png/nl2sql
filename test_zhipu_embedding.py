#!/usr/bin/env python3
"""测试智谱 ZhiPu Embedding-3 API 连接。运行前需设置 ZHIPU_API_KEY 环境变量。"""

import json
import os
import sys

try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests")
    sys.exit(1)

ZHIPU_API_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
API_KEY = os.getenv("ZHIPU_API_KEY")


def get_zhipu_embedding(
    text: str,
    model: str = "embedding-3",
    dimensions: int | None = None,
) -> list[float] | None:
    """请求智谱 embedding，返回向量或 None。"""
    if not API_KEY:
        print("错误: 未设置 ZHIPU_API_KEY 环境变量")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    data: dict = {"model": model, "input": text}
    if dimensions is not None:
        data["dimensions"] = dimensions

    try:
        response = requests.post(
            ZHIPU_API_URL,
            headers=headers,
            data=json.dumps(data),
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        return body["data"][0]["embedding"]
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        if hasattr(e, "response") and e.response is not None:
            r = e.response
            print(f"  HTTP {r.status_code}: {r.text[:400]}")
            if r.status_code == 401:
                print("  请检查 API 密钥是否有效（从 open.bigmodel.cn 获取）")
            elif r.status_code == 429:
                if "余额不足" in r.text or "1113" in r.text:
                    print("  智谱账户余额不足，请在 open.bigmodel.cn 充值")
                else:
                    print("  请求过于频繁，请稍后重试")
        return None


def main():
    text = "智谱 Embedding-3 API 非常好用"
    print(f"测试文本: {text}")
    print(f"API 端点: {ZHIPU_API_URL}")
    print(f"模型: embedding-3")
    print()

    if not API_KEY:
        print("请先设置环境变量: export ZHIPU_API_KEY='your-api-key'")
        sys.exit(1)

    print("请求中 ...")
    vec = get_zhipu_embedding(text)
    if vec:
        print(f"成功! 向量维度: {len(vec)}")
        print(f"向量前 5 维: {vec[:5]}")
    else:
        print("请求失败，请检查 API Key 和网络。")
        sys.exit(1)


if __name__ == "__main__":
    main()
