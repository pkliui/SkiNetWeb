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
2. The frontend sends the image to the Node.js backend.
3. The backend forwards it to the Python inference service (`POST /infer`).
4. The inference service preprocesses the image (center-crop → resize to 256 × 256 → ISIC 2017 normalisation), runs the ONNX model, and returns a PNG mask.
5. The frontend displays the original image, segmentation overlay, and metrics.
6. The optional AI report flow sends those metrics through the backend gateway to the Python service (`POST /case-report`) for LLM-backed or deterministic report generation.



## Optional LLM reporting

SkiNetWeb includes an AI Segmentation Report workflow that turns segmentation metrics into a grounded engineering summary. It is designed for explainability and operations demos: the UI shows prompt grounding, quality checks, safety controls, and whether the response came from a live LLM or the deterministic local fallback.

Configure one of these in the `skinet-service` environment to enable live generation:

```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT=<deployment-name>
AZURE_OPENAI_API_VERSION=2024-02-15-preview

# or OpenAI-compatible fallback
OPENAI_API_KEY=<key>
OPENAI_MODEL=gpt-4o-mini

# optional operational tuning
LLM_TIMEOUT_SECONDS=20
LLM_MAX_RETRIES=2
LLM_MAX_OUTPUT_TOKENS=700
```

If no LLM credentials are present, `/api/case-report` still returns a deterministic report from the same metrics. The browser contract remains stable while the Python AI service owns prompt orchestration, schema validation, fallback behavior, and telemetry fields.

## Development

```bash
docker compose -f docker-compose.dev.yml up --build
```

The app is available at `http://localhost:8002` (Nginx entry point).

## Release flow

See [docs/release-flow.md](docs/release-flow.md).
