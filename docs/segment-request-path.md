# Segmentation request path

How an image travels from the upload zone to the segmentation mask and back.
Companion to `case-report-request-path.md`, which picks up after `metrics` exist.

## Phase 1: select (browser only)

No application code reads the image bytes here. A `File` is a handle: name,
size and type are available at once; the bytes stay where they are.

```mermaid
%%{init: {'themeVariables': {'fontSize': '18px'}, 'sequence': {'actorFontSize': 18, 'messageFontSize': 18, 'noteFontSize': 17}}}%%
sequenceDiagram
    autonumber
    actor U as User
    participant UZ as UploadZone /<br/>ExampleGallery
    participant HP as HomePage
    participant H as useSegmentation
    participant RG as ResultsGrid

    U->>UZ: drop file, pick in dialog,<br/>or click/drag an example
    Note right of UZ: Example: urlToFile()<br/>fetches URL → File
    UZ->>HP: onFileSelect(file | [image, gt])
    HP->>HP: handleFileSelect:<br/>setMetrics(null)
    HP->>H: acceptFile(fileOrFiles)
    H->>H: split image / "_lesion" GT<br/>by filename
    H->>H: check type + size<br/>(metadata only)
    H->>H: setSelectedFile,<br/>previewUrl = createObjectURL
    H-->>UZ: re-render: selectedFile<br/>→ shows filename
    H-->>RG: previewUrl, gtMaskUrl<br/>→ preview
```

## Phase 2: submit

The user clicks **Analyse** → `HomePage.handleSubmit` → `useSegmentation.onSubmit`.

```mermaid
%%{init: {'themeVariables': {'fontSize': '18px'}, 'sequence': {'actorFontSize': 18, 'messageFontSize': 18, 'noteFontSize': 17}}}%%
sequenceDiagram
    autonumber
    participant H as useSegmentation
    participant NG as nginx
    participant EX as Express
    participant PY as FastAPI
    participant RG as ResultsGrid

    H->>NG: POST /api/segment<br/>multipart, field "image"
    Note right of NG: body ≤ 11 MB
    NG->>EX: proxy_pass /api<br/>(read timeout 70 s)
    EX->>EX: limitSegmentConcurrency<br/>(1 slot)
    EX->>EX: Multer: parse multipart,<br/>mimetype header, ≤ 10 MiB<br/>→ req.file.buffer
    EX->>PY: segmentImage: Buffer → Blob → FormData<br/>POST /infer, multipart (timeout 5 s)
    PY->>PY: _read_capped (count bytes)
    PY->>PY: PIL Image.open: first decode<br/>of the actual bytes
    PY->>PY: crop → resize → ONNX → PNG
    PY-->>EX: 200 image/png
    EX-->>NG: 200 image/png
    NG-->>H: 200 image/png
    H->>H: blob → resultUrl<br/>= createObjectURL
    H-->>RG: resultUrl → overlay
    Note over RG: onMetricsChange(metrics)<br/>→ HomePage.setMetrics
```

## Where each check happens

| # | Layer | Checks | Looks at the actual bytes? | Rejects with |
|---|---|---|---|---|
| 1 | `useSegmentation.acceptFile` | MIME type (from extension), size | No | inline error, no request sent |
| 2 | nginx | whole request ≤ 11 MB | No (counts them) | 413, JSON via `@upload_too_large` |
| 3 | Express `limitSegmentConcurrency` | one segmentation at a time | n/a | 429 |
| 4 | Express Multer | `mimetype` header, file ≤ 10 MiB | No (counts them) | 400 / 413 |
| 5 | FastAPI `_read_capped` | bytes actually received ≤ cap | No (counts them) | 413 |
| 6 | FastAPI `preprocess` (PIL) | decodes as JPEG/PNG | **Yes** | 400 "Could not process the uploaded image" |

nginx's limit (row 2) is higher than Multer's (row 4) on purpose: nginx counts the
whole multipart body, including the boundary lines and part headers (~0.2–0.4 KB
measured), while Multer counts only the file bytes. With both at 10 MiB, nginx
would reject a file Express accepts.

The type checked in rows 1 and 4 is declared by the client: the browser sets
the part's `Content-Type` from the file extension. Only row 6 reads the content.

## How errors get back to the user

- FastAPI raises `HTTPException` → body `{"detail": ...}`.
- `segmentImage` maps `detail` → `{"error": ...}` and throws `UpstreamServiceError`
  with the same status; `sendServiceError` forwards both unchanged. If the body
  isn't JSON or has no `detail`, the error is "Inference service error".
- Express-side timeout → 504 "Inference service timed out";
  any other failure (e.g. connection refused) → 503 "Inference service unavailable".
- `onSubmit` reads `error` from the JSON body and shows it. A 413 that isn't JSON
  (e.g. Cloudflare's HTML page) falls back to a generic "too large" message;
  any other status without a JSON body (e.g. an HTML 502 from nginx or
  Cloudflare) shows "Segmentation failed".
- Oversized files normally never reach `onSubmit`: `acceptFile` (row 1) rejects
  them first, so a 413 there is a backstop. It usually means the UI's
  `MAX_UPLOAD_BYTES` (`types/upload.ts`) has drifted from the server limits:
  `MAX_UPLOAD_BYTES` in `.env.config` (row 4) or nginx's `client_max_body_size`
  (row 2).
- A network failure (`fetch` throws) shows "Could not reach the server".

## Known gaps

- Dragging an example passes only `imageSrc` (`ExampleGallery.tsx:76`), so the GT
  mask is lost; clicking passes both.
