# JewelAI Backend

FastAPI backend implementing JewelAI architecture blocks 1-11, with image
generation isolated behind a provider-neutral gateway.

## Implemented

- Jewelry intent parsing and canonical Jewelry Specification
- versioned initial domain knowledge
- engineering enrichment and validation
- geometry-first prompt compiler
- OpenAI image adapter
- Gemini image adapter
- automatic provider routing and fallback
- Visual QA comparison and bounded correction planning
- FastAPI endpoints, Docker and CI tests

Block 9 is provider-neutral: the frontend calls only JewelAI. API keys remain
on the server. Provider model IDs and base URLs are configuration, not domain
code.

## Local setup

    cp .env.example .env
    python -m venv .venv
    . .venv/bin/activate
    pip install -e ".[dev]"
    uvicorn app.main:app --reload

Open API documentation at http://localhost:8000/docs.

## Main endpoints

- GET /v1/health
- POST /v1/specifications/interpret
- POST /v1/generations
- POST /v1/generations/from-text
- POST /v1/visual-qa/evaluate

## Secrets

Never commit .env. Configure OPENAI_API_KEY and GEMINI_API_KEY in the deployment
secret store. The committed .env.example contains names only.

## Current boundary

This first vertical slice performs provider calls synchronously. Before salon
production traffic, add durable PostgreSQL generation records, object storage,
an asynchronous job queue, authentication, per-tenant quotas, and an automated
vision inspector. The provider gateway and domain contracts are designed to
remain unchanged when those components are added.

