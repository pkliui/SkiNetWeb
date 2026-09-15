import { promises as fsp } from "fs";

/**
 * Determines whether a filesystem path is accessible.
 *
 * This utility provides a Promise-based wrapper around Node.js filesystem
 * access checks and converts filesystem failures into a boolean result.
 *
 * The function does not expose underlying filesystem errors. Any failure to
 * access the path (for example, missing path, permission issues, or invalid
 * filesystem state) is treated as an inaccessible path and returns `false`.
 *
 * This helper is intended for application flow decisions where callers only
 * need to know whether a resource is available and do not require filesystem
 * error details.
 *
 * @param filePath
 * Path to check for accessibility.
 *
 * @returns
 * Resolves to `true` when the path is accessible, otherwise `false`.
 */
export async function fileExists(filePath: string): Promise<boolean> {
  try {
    await fsp.access(filePath);
    return true;
  } catch {
    return false;
  }
}
