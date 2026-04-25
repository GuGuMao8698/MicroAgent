# 智能分块基线

# 目标

为 `ragflow-lite` 提供更适合中文与 Markdown 文本的递归分块最小实现，作为 ingestion 阶段可演进的基础能力。该基线优先保证 chunk 边界稳定、来源可追踪和行为可解释，而不是在首版中追求自动调参或复杂质量评分。

# 技术栈

- `RecursiveCharacterChunker`（`src/ragflow_lite/infrastructure/chunkers/recursive_character.py`）：内置递归回退式分块器，按优先级依次尝试分隔符，从段落、换行到中文标点再到字符级切分。不依赖外部库，不引入自动调参循环或额外启发式评分公式。

# 默认分隔符

```python
[“\n\n”, “\n”, “。”, “！”, “？”, “.”, “!”, “?”, “ “, “”]
```

按优先级依次尝试：段落 -> 换行 -> 中文句末标点 -> 英文句末标点 -> 空格 -> 字符级回退。

# 范围与非目标

本文件只定义面向中文与 Markdown 的递归分块基线、最小可配置项以及 chunk 元数据要求。它不定义文档类型 profile 扩展机制、不定义分块质量评分公式、不定义自动调参循环，也不把离线诊断提升为主链路硬门槛。V3 不在本文件同时引入摘要树构建、检索策略或 query-time 优化能力。

# 核心契约

分块基线必须从原始文档稳定地产出一组有序 chunk。最小可配置项只有 `chunk_size`、`chunk_overlap` 和 `separators`（均为 `RecursiveCharacterChunker` 构造参数）；其中 `separators` 采用递归回退策略，优先保留段落、换行和中文常见标点边界，必要时再回退到字符级切分。相同输入文档与相同参数必须产生相同 chunk 序列，不允许在主链路中依赖运行时随机性或自动调参结果。

每个 chunk 必须携带最小来源元数据。当前实现中的元数据字段包括：

- `chunk_id`：格式为 `chunk_{document_id}_{index}`，保证全局唯一且可溯源
- `index`：chunk 在文档内的顺序编号
- `start_offset` / `end_offset`：chunk 文本在原文中的字符偏移区间（左闭右开）
- `page_start` / `page_end`（仅 PDF）：chunk 覆盖的起止页码，基于 parser 提供的 `page_spans` 计算

分块步骤只负责把文档切成稳定的原子文本单元，不负责判断这些 chunk 是否适合检索、不负责生成摘要父节点，也不负责多路候选合并。分块质量诊断可以存在，但它的角色只能是离线评估、日志指标或测试辅助，不能变成 ingestion 成败的额外阻塞条件。

# 验收口径

先失败的条件是：中文或 Markdown 文档只能按固定字符窗硬切、分块结果不携带最小来源元数据、同一输入在相同参数下产生不稳定 chunk 序列、或主链路依赖启发式评分与自动调参循环才可运行。通过后的可观察结果是：长文档能够优先沿段落和语义边界切开；每个 chunk 都能回溯到原始文档与顺序位置；相同文档重复分块得到一致结果；诊断逻辑可以单独运行而不是卡住主链路。

# 依赖与边界

本文件属于 ingestion 侧能力，服务于后续 embedding、索引落库和层级摘要构建。`RecursiveCharacterChunker` 已通过 `providers.py` 注册为默认生产分块器，`_chunk_cache_key()` 已更新为通用指纹。`RAPTOR` 只能消费这里产出的稳定 chunk，而不能反向重定义分块形状。该基线不承担 query-time 的扩展检索、去重、分数组合或内部重排职责；异步 ingestion 只是其承载环境，不改变本文件只对”如何产出稳定 chunk”负责的边界。

# 测试覆盖

当前共有 43 个测试覆盖分块器：

- 36 个算法测试：覆盖递归分隔、合并与重叠、边界条件、空输入与单 chunk、中文/英文/Markdown 场景、页码计算等
- 7 个契约测试：覆盖 `Chunker` 协议合规性、`providers.py` 注册、与 `IngestionPipeline` 的集成
