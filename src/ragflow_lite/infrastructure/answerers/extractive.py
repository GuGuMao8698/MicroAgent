"""本地抽取式回答器。

V0 阶段先不接生成模型，而是从召回片段中挑选最相关句子拼接回答，
用于验证检索到回答的闭环是否打通。
"""

from __future__ import annotations

import re

from ragflow_lite.domain.models import AnswerResult, RetrievedChunk
from ragflow_lite.infrastructure.embedders.hash_embedder import tokenize

FALLBACK_ANSWER = "当前已索引内容中没有足够信息回答这个问题。"
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？.!?])\s+|\n+")


class ExtractiveAnswerer:
    """根据召回片段生成最小可用回答。"""

    def answer(self, query: str, contexts: list[RetrievedChunk]) -> AnswerResult:
        """从前几个召回片段中选出与查询 token 重叠最多的句子。"""
        if not contexts:
            return AnswerResult(
                answer=FALLBACK_ANSWER, contexts=[], metadata={"strategy": "fallback"}
            )

        query_tokens = set(tokenize(query))
        best_sentence = ""
        best_overlap = -1

        for context in contexts[:3]:
            # 只看最靠前的少量 context，保持 V0 行为简单且可解释。
            sentences = [
                sentence.strip()
                for sentence in SENTENCE_SPLIT_PATTERN.split(context.text)
                if sentence.strip()
            ]
            for sentence in sentences:
                overlap = len(query_tokens & set(tokenize(sentence)))
                if overlap > best_overlap:
                    best_sentence = sentence
                    best_overlap = overlap

        # 如果没有找到更细粒度的匹配句子，就回退到首个片段全文。
        if not best_sentence:
            best_sentence = contexts[0].text.strip()

        return AnswerResult(
            answer=f"根据已索引文档，{best_sentence}",
            contexts=contexts,
            metadata={"strategy": "extractive"},
        )
