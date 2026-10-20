"""LLM_BACKEND에 맞는 fast/quality LLMHandle을 만든다 (Wave 10a — 역할별 모델 분리).

- fast    : 라우팅·분류·계획·조건 판정·잡담 (저비용 소형 모델)
- quality : 최종 검토 보고 작성 (고품질 모델)

usd_per_1k_tokens는 가상 단가다 — 로컬 Ollama도 같은 잣대로 비용을 비교하기 위함.
"""
from .fake_chat import RuleBasedChatModel
from .handle import LLMHandle

FAST_USD_PER_1K = 0.00015
QUALITY_USD_PER_1K = 0.005


def build_llms(backend: str, fast_model: str, quality_model: str) -> tuple[LLMHandle, LLMHandle]:
    if backend == "ollama":
        from langchain_ollama import ChatOllama

        def make(model: str) -> ChatOllama:
            # reasoning=False: qwen3 등 추론 모델의 <think> 출력을 끈다
            return ChatOllama(model=model, temperature=0, reasoning=False)
        return (LLMHandle(f"ollama:{fast_model}", make(fast_model), FAST_USD_PER_1K, True),
                LLMHandle(f"ollama:{quality_model}", make(quality_model),
                          QUALITY_USD_PER_1K, True))
    if backend == "openai":
        from langchain_openai import ChatOpenAI

        def make(model: str) -> ChatOpenAI:
            return ChatOpenAI(model=model, temperature=0, stream_usage=True)
        return (LLMHandle(f"openai:{fast_model}", make(fast_model), FAST_USD_PER_1K, True),
                LLMHandle(f"openai:{quality_model}", make(quality_model),
                          QUALITY_USD_PER_1K, True))
    return (LLMHandle("fake:rule-based-fast", RuleBasedChatModel(), FAST_USD_PER_1K, False),
            LLMHandle("fake:rule-based-quality", RuleBasedChatModel(), QUALITY_USD_PER_1K,
                      False))
