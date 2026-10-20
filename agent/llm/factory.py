"""LLM_BACKEND에 맞는 fast/quality LLMHandle을 만든다 (Wave 10a — 역할별 모델 분리).

- fast    : 라우팅·분류·계획·조건 판정·잡담 (저비용 소형 모델)
- quality : 최종 검토 보고 작성 (고품질 모델)

usd_per_1k_tokens는 가상 단가다 — 로컬 Ollama도 같은 잣대로 비용을 비교하기 위함.

모든 모델에 최대 생성 길이와 요청 시간 제한을 둔다. 소형 모델이 구조화 출력에서 끝나지 않는
생성을 이어 가면 검토 하나가 무한정 멈출 수 있기 때문이다 (판정 실험 중 실제로 멈춘 사례가 있었다).
"""
from .fake_chat import RuleBasedChatModel
from .handle import LLMHandle

FAST_USD_PER_1K = 0.00015
QUALITY_USD_PER_1K = 0.005
# (최대 생성 토큰, 호출 시간 제한 초) — fast는 짧은 JSON, quality는 보고서 한 편
FAST_LIMITS = (1024, 60.0)
QUALITY_LIMITS = (3072, 240.0)


def build_llms(backend: str, fast_model: str, quality_model: str) -> tuple[LLMHandle, LLMHandle]:
    if backend == "ollama":
        from langchain_ollama import ChatOllama

        def make(model: str, limits: tuple[int, float]) -> ChatOllama:
            # reasoning=False: qwen3 등 추론 모델의 <think> 출력을 끈다
            return ChatOllama(model=model, temperature=0, reasoning=False,
                              num_predict=limits[0], client_kwargs={"timeout": limits[1]})
        return (LLMHandle(f"ollama:{fast_model}", make(fast_model, FAST_LIMITS),
                          FAST_USD_PER_1K, True, timeout=FAST_LIMITS[1]),
                LLMHandle(f"ollama:{quality_model}", make(quality_model, QUALITY_LIMITS),
                          QUALITY_USD_PER_1K, True, timeout=QUALITY_LIMITS[1]))
    if backend == "openai":
        from langchain_openai import ChatOpenAI

        def make(model: str, limits: tuple[int, float]) -> ChatOpenAI:
            return ChatOpenAI(model=model, temperature=0, stream_usage=True,
                              max_tokens=limits[0], request_timeout=limits[1], max_retries=1)
        return (LLMHandle(f"openai:{fast_model}", make(fast_model, FAST_LIMITS),
                          FAST_USD_PER_1K, True, timeout=FAST_LIMITS[1]),
                LLMHandle(f"openai:{quality_model}", make(quality_model, QUALITY_LIMITS),
                          QUALITY_USD_PER_1K, True, timeout=QUALITY_LIMITS[1]))
    return (LLMHandle("fake:rule-based-fast", RuleBasedChatModel(), FAST_USD_PER_1K, False),
            LLMHandle("fake:rule-based-quality", RuleBasedChatModel(), QUALITY_USD_PER_1K,
                      False))
