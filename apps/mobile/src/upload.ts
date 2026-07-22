// The native UploadPort: how the shared api-client PUTs a media file's bytes.
//
// The shared `putAndComplete` contract (packages/api-client) is platform-free:
// it asks this port for a file's content type and to PUT the bytes to a URL
// (our own API locally, a presigned S3 URL in prod). On web that port wraps a
// browser `File`; on native we hand it a local content URI (from the camera,
// library, mic, or a document) and stream it straight off disk with
// expo-file-system, so a large video never has to sit in JS memory as a Blob.
import * as FileSystem from "expo-file-system";
import { ApiError, type UploadPort } from "@futureroots/api-client";

/** A file staged for upload on native: a local content URI plus its MIME type. */
export interface MobileUpload {
  uri: string;
  contentType: string;
}

export const mobileUpload: UploadPort<MobileUpload> = {
  contentType: (file) => file.contentType,
  put: async (url, file, headers) => {
    // BINARY_CONTENT streams the raw bytes as the request body with a PUT,
    // exactly matching the presigned-URL / local-media contract (no multipart).
    const result = await FileSystem.uploadAsync(url, file.uri, {
      httpMethod: "PUT",
      uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
      headers,
    });
    // uploadAsync resolves (rather than throwing) on non-2xx, so surface an
    // ApiError the same way the JSON request path does.
    if (result.status < 200 || result.status >= 300) {
      throw new ApiError(
        result.status,
        "We couldn't add that just now. Please check your connection and try again."
      );
    }
  },
};
