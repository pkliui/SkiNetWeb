# SkiNetWeb

A web application for automatic skin lesion segmentation using the SkiNet deep learning model.

Upload a dermoscopy image to receive a binary segmentation mask and an overlay highlighting the detected lesion region. The model is trained on the ISIC 2017 dataset.

Live at [skinet.pkliuiev.workers.dev](https://skinet.pkliuiev.workers.dev) — served via [SkiNetWeb-Proxy](https://github.com/pkliui/SkiNetWeb-Proxy).

## Stack

- **Frontend**: React / TypeScript — upload zone, example gallery, results overlay grid
- **Backend**: Node.js / TypeScript / Express — proxies image and report requests to the inference service, caches ISIC example images
- **Inference service**: Python / FastAPI / ONNX Runtime — loads the SkiNet ONNX model, returns PNG segmentation masks, and owns LLM report generation
- **Deployment**: Docker Compose on AWS EC2, Nginx as reverse proxy and static file server
- **CI/CD**: GitHub Actions

## How it works

1. User uploads a dermoscopy image (or picks one from the example gallery).
2. The frontend sends the image to the Node.js backend. See [docs/segment-request-path.md](docs/segment-request-path.md) for the full request/response trace (React state → nginx → Express → FastAPI) and where each upload check (type, size) runs.
3. The backend forwards it to the Python inference service (`POST /infer`).
4. The inference service preprocesses the image (center-crop → resize to 256 × 256 → ISIC 2017 normalisation), runs the ONNX model, and returns a PNG mask.
5. The frontend displays the original image, segmentation overlay, and metrics.
6. The optional AI report flow sends those metrics through the backend gateway to the Python service (`POST /case-report`) for LLM-backed or deterministic report generation. See [docs/case-report-request-path.md](docs/case-report-request-path.md) for the full request/response trace (React state → nginx → Express → FastAPI) and [docs/skinet-service-report-generation.md](docs/skinet-service-report-generation.md) for what runs once FastAPI has the request.



## Optional LLM reporting

SkiNetWeb includes an AI Segmentation Report workflow that turns segmentation metrics into a grounded engineering summary. It is designed for explainability and operations demos: the UI shows prompt grounding, quality checks, safety controls, and whether the response came from a live LLM or the deterministic local fallback.

[Mistral](https://mistral.ai) is the default provider, with [OpenRouter](https://openrouter.ai) kept as a fallback. Both are reached over the same OpenAI-shaped `/chat/completions` API, so neither needs a vendor SDK — only the env vars differ. The service resolves Mistral first and falls back to OpenRouter only when `MISTRAL_API_KEY`/`MISTRAL_MODEL` are absent; clearing the Mistral vars is all it takes to revert an environment.

Each provider needs its key *and* its model — there is no code-level default model, so the pair is required together:

```bash
# default provider
MISTRAL_API_KEY=<key>
MISTRAL_MODEL=mistral-medium-2604   # Mistral Medium 3.5

# optional
MISTRAL_BASE_URL=https://api.mistral.ai/v1

# fallback provider
OPENROUTER_API_KEY=<key>
OPENROUTER_MODEL=openai/gpt-oss-20b:free

# optional
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

Timeout/retry/output-size knobs (attempt timeout, silence timeout, connect
timeout, total budget, max retries, max output tokens, status-check timeout)
are **not** environment variables — they're fixed constants in
`skinet-service/reporting/client.py` (`DEFAULT_*`) and
`skinet-service/reporting/status.py`. See "Timeouts" below for the current
values and where to change them.

Structured outputs (strict `json_schema` response format vs. the default
"any valid JSON object" mode) is not an env var either — it's a fixed,
per-provider constant in `skinet-service/reporting/provider.py`: on for
Mistral (`mistral-medium-2604` is verified to honour it), off for OpenRouter
(it routes to an arbitrary, caller-chosen model, so strict-schema support
can't be assumed).

If neither provider is fully configured, `/api/case-report` still returns a deterministic report from the same metrics. The browser contract remains stable while the Python AI service owns prompt orchestration, schema validation, fallback behavior, and telemetry fields.

### Timeouts

`/api/case-report` waits on an LLM, so several layers each impose a deadline. They are ordered deliberately:

| Layer | Budget | Set in |
|---|---|---|
| Cloudflare Worker (production only) | 100s, hard | external (`SkiNetWeb-Proxy`) |
| nginx `proxy_read_timeout` | 70s | `nginx/default.conf` |
| Express abort | 50s | `CASE_REPORT_TIMEOUT_MS` default in `skinetweb-server/src/config.ts` |
| Python total budget | 40s | `DEFAULT_TOTAL_BUDGET_SECONDS` in `skinet-service/reporting/client.py` |
| Python per attempt (wall-clock) | 25s | `DEFAULT_ATTEMPT_TIMEOUT_SECONDS` in `skinet-service/reporting/client.py` |
| Python per attempt (silence) | 15s | `DEFAULT_SILENCE_TIMEOUT_SECONDS` in `skinet-service/reporting/client.py` |
| Python connect | 5s | `DEFAULT_CONNECT_TIMEOUT_SECONDS` in `skinet-service/reporting/client.py` |

None of these are environment variables — each is a fixed constant in code,
changed by editing the file and redeploying. There is no `.env` override for
any of them; `docker-compose*.yml` does not reference any of these vars.

**The rule: each layer's budget must exceed the layer it calls, and the innermost layer that can produce a useful degraded response must give up first.** Only the Python service can answer a slow LLM with a deterministic report; every layer above it can only return an error. So it must run out of time while Express is still listening.

Two things this guards against, both of which were live bugs:

- A retry loop needs a *total* budget, not just a per-attempt one. `DEFAULT_ATTEMPT_TIMEOUT_SECONDS` bounds one attempt, so with retries the real worst case was `25s × 3` plus backoff — which is what the caller waits for. `DEFAULT_TOTAL_BUDGET_SECONDS` caps the whole thing, and attempts that cannot finish inside it are skipped.
- The request is bounded by two different mechanisms, on purpose. `DEFAULT_SILENCE_TIMEOUT_SECONDS` is passed to httpx, which measures the gap between bytes rather than wall-clock elapsed — a slow-streaming response can exceed it without ever tripping it, since each new byte resets the clock. `DEFAULT_ATTEMPT_TIMEOUT_SECONDS` is enforced separately by `asyncio.wait_for` around the whole call, and is the only one of the two that bounds total elapsed time; it exists specifically to catch that gap. `DEFAULT_SILENCE_TIMEOUT_SECONDS` is kept shorter than `DEFAULT_ATTEMPT_TIMEOUT_SECONDS` so httpx's more specific error (which phase — connect, read, or waiting for a pooled connection — was in progress) reaches the log before the generic timeout from `wait_for` would.

If you raise `DEFAULT_TOTAL_BUDGET_SECONDS`, raise every layer above it too, or the outer layer will cut off the fallback and the user will see a 504 instead of a report.

To confirm that a live LLM generated the report, inspect `promptTrace` in the `/api/case-report` response or the badge in the UI. A live response has `"mode": "llm"` and `provider` set to the provider that served it (`mistral` or `openrouter`); fallback responses have `"mode": "deterministic-fallback"` and include `fallbackReason`.

Example direct check:

```bash
curl -s http://localhost:5000/api/case-report \
  -H 'Content-Type: application/json' \
  -d '{"fileName":"case.png","imageType":"image/png","imageSizeBytes":1234,"metrics":{"predAreaPct":12.5,"dice":0.8,"iou":0.67}}'
```

## Development

```bash
docker compose -f docker-compose.dev.yml up --build
```

The app is available at `http://localhost:8002` (Nginx entry point).

## Release flow

See [docs/release-flow.md](docs/release-flow.md).
