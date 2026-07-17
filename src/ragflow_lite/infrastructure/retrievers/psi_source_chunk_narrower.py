from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ragflow_lite.domain.models import GroundedAuxiliaryQuery


@dataclass(frozen=True, slots=True)
class PsiSourceNarrowingConfig:
    max_source_chunks_without_narrowing: int = 12
    max_auxiliary_chunks: int = 8

    def __post_init__(self) -> None:
        if self.max_source_chunks_without_narrowing < 1:
            raise ValueError("max_source_chunks_without_narrowing must be positive")
        if self.max_auxiliary_chunks < 1:
            raise ValueError("max_auxiliary_chunks must be positive")


class CandidateFilteredChunkScorer(Protocol):
    def score_candidates(
        self,
        request: GroundedAuxiliaryQuery,
        candidate_chunk_ids: list[str],
        top_k: int,
    ) -> list[str]: ...


class PsiSourceChunkNarrower:
    def __init__(
        self,
        *,
        config: PsiSourceNarrowingConfig | None = None,
        candidate_filtered_scorer: CandidateFilteredChunkScorer | None = None,
    ) -> None:
        self._config = config or PsiSourceNarrowingConfig()
        self._candidate_filtered_scorer = candidate_filtered_scorer

    def narrow(
        self,
        request: GroundedAuxiliaryQuery,
        source_chunk_ids: list[str],
    ) -> tuple[list[str], str | None]:
        candidates = list(dict.fromkeys(source_chunk_ids))
        limit = self._config.max_auxiliary_chunks
        if len(candidates) <= self._config.max_source_chunks_without_narrowing:
            return candidates[:limit], None
        if self._candidate_filtered_scorer is None:
            return candidates[:limit], "narrowing_unavailable"
        try:
            scored = self._candidate_filtered_scorer.score_candidates(
                request, candidates, limit
            )
        except Exception:
            return candidates[:limit], "narrowing_unavailable"
        allowed = set(candidates)
        narrowed = [chunk_id for chunk_id in scored if chunk_id in allowed]
        return list(dict.fromkeys(narrowed))[:limit], None
