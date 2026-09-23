# API application

Reserved for the JewelAI V2 FastAPI application.

This directory is part of the modular-monolith repository boundary only; no API runtime is implemented in Step 2.
When the API issue is implemented, this application may orchestrate use cases and depend on reusable packages such as `packages/domain`, but domain packages must not depend on `apps/api`.

Do not add persistence, authentication, provider adapters, or deployment configuration here before their dedicated implementation decisions are accepted.
