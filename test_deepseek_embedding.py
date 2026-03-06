#!/usr/bin/env python3
"""测试 DeepSeek Embedding API 连接。运行前需设置 OPENAI_API_KEY 环境变量。"""

import json
import os
import sys

try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests")
    sys.exit(1)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/embeddings"
API_KEY = os.getenv("OPENAI_API_KEY")

# 常见模型名，按优先级尝试
MODELS_TO_TRY = ["deepseek-embedding-v1", "deepseek-embedding"]


def get_deepseek_embedding(text: str, model: str = "deepseek-embedding-v1") -> list | None:
    if not API_KEY:
        print("错误: 未设置 OPENAI_API_KEY 环境变量")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    data = {"input": text, "model": model}
    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            headers=headers,
            data=json.dumps(data),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        if hasattr(e, "response") and e.response is not None:
            r = e.response
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code == 401:
                print("  请检查 API 密钥是否有效")
            elif r.status_code == 404:
                print("  请检查模型名称是否正确，可尝试 deepseek-embedding 或 deepseek-embedding-v1")
        return None


def main():
    text = "DeepSeek API 非常好用"
    print(f"测试文本: {text}")
    print(f"API 端点: {DEEPSEEK_API_URL}")
    print()

    for model in MODELS_TO_TRY:
        print(f"尝试模型: {model} ...")
        vec = get_deepseek_embedding(text, model=model)
        if vec:
            print(f"  成功! 向量维度: {len(vec)}")
            print(f"  向量前5维: {vec[:5]}")
            return
        print()

    print("所有模型均失败。")
    print("说明: api.deepseek.com 的 embeddings 接口曾多次被报告 404，"
          "可能是账户权限或接口尚未对公开 API 开放。")
    print("建议: 使用 MINE_EMBEDDING_VENDOR=openai + OpenAI API Key 进行向量化。")


if __name__ == "__main__":
    main()
