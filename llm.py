"""Provider-neutral LLM adapter. Set a provider implementation in production; no credentials live in source."""
class LLMProvider:
    def analyze(self, prompt): raise NotImplementedError
class DisabledLLM(LLMProvider):
    def analyze(self,prompt): return {'findings':[],'status':'llm_not_configured'}
