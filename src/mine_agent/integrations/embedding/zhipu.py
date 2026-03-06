"""智谱 Embedding-3 向量模型，兼容 OpenAI 格式。参考 https://docs.bigmodel.cn/guide/models/embedding/embedding-3"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mine_agent.core.embedding.base import EmbeddingService

ZHIPU_EMBED_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_EMBED_3_DIM = 2048  # embedding-3 默认
ZHIPU_EMBED_2_DIM = 1024


class ZhiPuEmbeddingService(EmbeddingService):
    """智谱 Embedding-3，OpenAI 兼容格式。支持 MINE_EMBEDDING_DIMENSIONS 自定义维度。"""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dimensions: Optional[int] = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "openai package required for ZhiPu embedding. pip install openai"
            ) from e

        self.model = model or "embedding-3"
        self.dimensions = dimensions
        api_key = api_key
        base_url = base_url or ZHIPU_EMBED_BASE_URL
        client_kwargs: Dict[str, Any] = {"api_key": api_key or "", "base_url": base_url}
        self._client = OpenAI(**client_kwargs)

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        kwargs: Dict[str, Any] = {"model": self.model, "input": texts}
        if self.dimensions is not None:
            kwargs["dimensions"] = self.dimensions
        response = self._client.embeddings.create(**kwargs)
        by_index = {item.index: item.embedding for item in response.data}
        return [by_index[i] for i in range(len(texts))]

    @property
    def dimension(self) -> int:
        if self.dimensions is not None:
            return self.dimensions
        if "embedding-2" in (self.model or ""):
            return ZHIPU_EMBED_2_DIM
        return ZHIPU_EMBED_3_DIM
