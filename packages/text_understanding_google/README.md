# Google text understanding

This package is the narrow Google Generative Language adapter for Text Intake v1. It makes one
bounded `generateContent` call and validates the structured result as the existing untrusted
`ParserCandidate` contract. The runtime API then applies the existing deterministic
`ParserProposal`, revision/CAS, and Rules Engine boundaries.

The adapter cannot mutate design state, confirm or lock fields, select questions, compile prompts,
or generate images. It sends the API key only in `x-goog-api-key`; errors never include provider
responses, prompts, or credentials. CI uses mocked HTTP transports and makes no paid calls.
