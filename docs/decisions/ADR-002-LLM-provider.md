# ADR-002: Multi-Provider LLM Abstraction with Google Gemini Primary & Deterministic Offline Fallback

- **Status:** Accepted
- **Date:** 2026-11-05

## Context
LLM model identifiers, SDKs, embedding dimensions, and tool-calling schemas evolve rapidly. For example, Google's `text-embedding-004` was shut down on January 13, 2026 in favor of `gemini-embedding-001` and `gemini-embedding-2`, and `gemini-2.5-pro` transitions to `gemini-3.8-flash` on December 1, 2026. Furthermore, automated CI/CD pipelines and local sandbox environments must be able to execute deterministic unit, integration, security, and evaluation tests when live external API keys or outbound network access are unavailable.

## Options Considered
1. **Direct Google GenAI SDK calls hardcoded inside business logic**.
2. **Heavyweight third-party abstraction wrapper only**.
3. **Custom `LLMProviderContract` interface (`packages/llm_core`) with `GeminiProvider`, `OpenAIProvider`, and `DeterministicGroundedProvider`**.

## Decision
Implement Option 3 in `packages/llm_core/provider.py`.

## Technical Justification
- Decouples chat models (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-2.5-flash`, `gpt-4o`) from embedding models (`gemini-embedding-001`, `text-embedding-3-small`).
- Normalizes token accounting, cost calculation, structured JSON output validation, and error handling across providers.
- When live API credentials are absent, clearly reports `provider_mode: "deterministic_grounded_test_double"` in status/observability responses while computing real deterministic feature-hashed L2-normalized embeddings and evidence-synthesized grounded answers from actual retrieved chunks—never returning hardcoded fake strings.

## Trade-offs & Consequences
- Maintaining provider adapters requires updating model pricing tables when vendors adjust rates.
