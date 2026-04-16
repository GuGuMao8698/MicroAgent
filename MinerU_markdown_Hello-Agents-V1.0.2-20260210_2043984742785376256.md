# 8.3.5 高级检索策略

RAG系统的检索能力是其核心竞争力。在实际应用中，用户的查询表述与文档中的实际内容可能存在用词差异，导致相关文档无法被检索到。为了解决这个问题，HelloAgents实现了三种互补的高级检索策略：多查询扩展（MQE）、假设文档嵌入（HyDE）和统一的扩展检索框架。

# (1) 多查询扩展 (MQE)

多查询扩展（Multi-Query Expansion）是一种通过生成语义等价的多样化查询来提高检索召回率的技术。这种方法的核心洞察是：同一个问题可以有多种不同的表述方式，而不同的表述可能匹配到不同的相关文档。例如，“如何学习Python”可以扩展为"Python入门教程"、"Python学习方法"、"Python编程指南"等多个查询。通过并行执行这些扩展查询并合并结果，系统能够覆盖更广泛的相关文档，避免因用词差异而遗漏重要信息。

MQE的优势在于它能够自动理解用户查询的多种可能含义，特别是对于模糊查询或专业术语查询效果显著。系统使用LLM生成扩展查询，确保扩展的多样性和语义相关性：

```python
def _prompt_mqe(query: str, n: int) -> List[str]:  
    '''使用LLM生成多样化的查询扩展'''  
try:  
    from ...core.11m import HelloAgentsLLM  
    11m = HelloAgentsLLM()  
    prompt = [  
        {"role": "system", "content": "你是检索查询扩展助手。生成语义等价或互补的多样化查询。使用中文，简短，避免标点。"}，  
        {"role": "user", "content": f"原始查询：{query}\n请给出{n}个不同表述的查询，每行一个。"}  
    ]  
    text = 11m.invoke_prompt)  
    lines = [ln.strip("-\t") for ln in (text or "").splitlines())]  
    outs = [ln for ln in lines if ln]  
    return outs[:n] or [query]  
except Exception:  
    return [query]
```

# (2) 假设文档嵌入 (HyDE)

假设文档嵌入（Hypothetical Document Embeddings，HyDE）是一种创新的检索技术，它的核心思想是"用答案找答案"。传统的检索方法是用问题去匹配文档，但问题和答案在语义空间中的分布往往存在差异——问题通常是疑问句，而文档内容是陈述句。HyDE通过让LLM先生成一个假设性的答案段落，然后用这个答案段落去检索真实文档，从而缩小了查询和文档之间的语义鸿沟。

这种方法的优势在于，假设答案与真实答案在语义空间中更加接近，因此能够更准确地匹配到相关文档。即使假设答案的内容不完全正确，它所包含的关键术语、概念和表述风格也能有效引导检索系统找到正确的文档。特别是对于专业领域的查询，HyDE能够生成包含领域术语的假设文档，显著提升检索精度：

```python
def _prompt_hyde(query: str) -> Optional[str]:  
    '''生成假设性文档用于改善检索'''  
try:  
    from ...core.l1m import HelloAgentsLLM  
    l1m = HelloAgentsLLM()  
    prompt = [  
        {"role": "system", "content": "根据用户问题，先写一段可能的答案性段落，用于向量检索的查询文档（不要分析过程）。"},  
        {"role": "user", "content": f"问题：{query}\n请直接写一段中等长度、客观、包含关键术语的段落。"}  
    ]  
    return l1m.invoke_prompt)  
except Exception:  
    return None
```

# (3) 扩展检索框架

HelloAgents将MQE和HyDE两种策略整合到统一的扩展检索框架中。系统通过enable_mqe和 enable_hyde参数让用户可以根据具体场景选择启用哪些策略：对于需要高召回率的场景可以同时启用两种策略，对于性能敏感的场景可以只使用基础检索。

扩展检索的核心机制是"扩展-检索-合并"三步流程。首先，系统根据原始查询生成多个扩展查询（包括MQE生成的多样化查询和HyDE生成的假设文档）；然后，对每个扩展查询并行执行向量检索，获取候选文档池；最后，通过去重和分数排序合并所有结果，返回最相关的top-k文档。这种设计的巧妙之处在于，它通过candidate_poolmultiplier参数（默认为4）扩大候选池，确保有足够的候选文档进行筛选，同时通过智能去重避免返回重复内容。

def search_vectors_expanded( store $=$ None, query: str $= \text{串}$ ， top_k:int $= 8$ rag namespace: Optional[str] $=$ None, only_rag_data: bool $=$ True, score_threshold: Optional[float] $=$ None, enable_mqe: bool $=$ False, mqe_expansions: int $= 2$ , enable_hyde: bool $=$ False, candidate_pool-multiplier: int $= 4$ -   
）->List[Ddict]: Search with query expansion using unified embedding and Qdrant. if not query: return [] #创建默认存储 if store is None: store $=$ _create_default_vector/store() #查询扩展 expansions: List[str] $=$ [query]

if enable_mqe and mqe_expansions $>0$ : expansions extend(_prompt_mqe(query, mqe_expansions))   
if enable_hyde: hyde_text $\equiv$ _prompt_hyde(query) if hyde_text: expansions.append(hyde_text) 


# 去重和修剪


```python
uniq: List[str] = []  
for e in expansions:  
    if e and e not inuniq:  
       uniq.append(e)  
expansions =uniq[:max(1,lenuniq)] 
```


分配候选池


```lisp
pool = max(top_k * candidate_poolmultiplier, 20)  
per = max(1, pool // max(1, len(expansions))) 
```


构建RAG数据过滤器


where $=$ {"memory_type": "rag_chunk"}   
if only_rag_data: where["is_rag_data"] $=$ True where["data_source"] $=$ "ragpipeline"   
if ragnamespace: where["rag namespace"] $=$ ragnamespace 


收集所有扩展查询的结果


```python
agg: Dict[str, Dict] = {}
for q in expansions:
    qv = embed_query(q)
    hits = store.search_similar(
        query_vector=qv,
        limit=per,
        score_threshold=score_threshold,
        where=where
    )
for h in hits:
    mid = h.get("metadata", {},).get("memory_id", h.get("id"))
    s = float(h.get("score", 0.0))
    if mid not in agg or s > float(agg[mid].get("score", 0.0)):
        agg[mid] = h 
```


按分数排序返回


```txt
merged = list(agg.values())
merged.sort(key= lambda x: float(x.get("score", 0.0)), reverse=True)
return merged[:top_k] 
```

实际应用中，这三种策略的组合使用效果最佳。MQE擅长处理用词多样性问题，HyDE擅长处理语义鸿沟问题，而统一框架则确保了结果的质量和多样性。对于一般查询，建议启用MQE；对于专业领域查询，建议同时启用MQE和HyDE；对于性能敏感场景，可以只使用基础检索或仅启用MQE。