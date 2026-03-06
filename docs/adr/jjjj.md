构建Schema-Aware知识库（基础准备）

丰富元数据：不要只用原始schema。添加描述、示例数据和关系：

  * 为每张表/列添加自然语言描述（e.g., "customers表存储用户个人信息，包括id、name和email"）。
  * 定义常见joins路径（e.g., "orders表通过customer_id与customers表关联"）。
  * 创建视图（views）合并常用表组（e.g., 一个视图整合销售相关表，减少joins复杂性）。

工具推荐：用SQLAlchemy或pg_dump提取schema，然后用Pandas或自定义脚本生成JSON/YAML格式的增强元数据。存储在向量数据库如Pinecone或FAISS中，便于RAG检索。
处理规模：将schema分解为“域”（domains），如销售、库存、用户，每个域10-20表。只加载相关域。