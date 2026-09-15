import "dotenv/config";

import cors from "cors";
import express, { type ErrorRequestHandler } from "express";

import { PORT } from "./config.js";
import { initCacheInBackground } from "./cache/isicCache.js";
import { inferenceRouter } from "./routes/inference.js";
import { isicRouter } from "./routes/isicRoutes.js";

const app = express();

app.use(cors());
app.use(express.json({ limit: "1mb" }));

app.use(inferenceRouter);
app.use(isicRouter);

const errorHandler: ErrorRequestHandler = (err, _req, res, next) => {
  if (res.headersSent) {
    next(err);
    return;
  }

  res.status(500).json({ error: "Internal server error" });
};

app.use(errorHandler);

app.listen(PORT, () => {
  console.log(`Backend is running on port ${PORT}`);
  initCacheInBackground();
});
