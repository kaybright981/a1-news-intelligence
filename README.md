# A1 News Intelligence — Starter Build

This first build contains a 179-source registry covering Nigeria (36 states + FCT), federal security/agency sources, Nigerian media, African institutions and international security sources.

## Important
- A1 = primary/official source.
- A2 = reputable independent media / rapid detection.
- State-government URLs are marked `needs_validation` until a live check confirms the current official portal.
- Social media must never be treated as automatic confirmation.

## Files
- source_registry.csv — master source database
- config.json — scoring and WhatsApp configuration
- app.py — minimal FastAPI starter API

## Production architecture
Source collectors -> normalizer -> duplicate detector -> relevance classifier -> verification engine -> priority queue -> WhatsApp Business API -> daily brief/archive.

## Verification logic
1. Official primary source can confirm a claim in its own jurisdiction.
2. High-impact claims without primary confirmation require at least two independent reputable sources.
3. Social posts are early-warning only.
4. Every alert carries status: CONFIRMED, DEVELOPING, or UNVERIFIED.
5. Store source URL, publication time, first-seen time, and verification history.

## Run locally
pip install fastapi uvicorn pydantic
uvicorn app:app --reload
