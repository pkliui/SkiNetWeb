import express from "express";
import cors from "cors";
import multer from "multer";

const PORT = process.env.PORT || 5000;
const INFERENCE_URL = process.env.INFERENCE_URL || "http://skinet-service:5001";

const app = express();
app.use(cors());

const upload = multer({ storage: multer.memoryStorage() });

app.post("/api/segment", upload.single("image"), async (req, res) => {
  if (!req.file) {
    res.status(400).json({ error: "No image file provided" });
    return;
  }

  try {
    const formData = new FormData();
    const blob = new Blob([new Uint8Array(req.file.buffer)], { type: req.file.mimetype });
    formData.append("image", blob, req.file.originalname);

    const inferenceRes = await fetch(`${INFERENCE_URL}/infer`, {
      method: "POST",
      body: formData,
    });

    if (!inferenceRes.ok) {
      res.status(502).json({ error: "Inference service error" });
      return;
    }

    const maskBuffer = Buffer.from(await inferenceRes.arrayBuffer());
    res.set("Content-Type", "image/png");
    res.send(maskBuffer);
  } catch {
    res.status(503).json({ error: "Inference service unavailable" });
  }
});

app.listen(PORT, () => {
  console.log(`Backend is running on port ${PORT}`);
});
