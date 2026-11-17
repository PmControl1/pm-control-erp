// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Shared upload routine for the file manager.
 *
 * Extracted from ``UploadDialog`` so the same ``doUpload`` path can drive
 * both the dialog and the page-level drag-and-drop drop zone. Routes each
 * upload to the endpoint that owns its kind so files land in the right
 * pipeline instead of all becoming generic documents:
 *   - BIM models (RVT / IFC / ...) -> POST /api/v1/bim_hub/upload-cad/
 *   - DWG / DXF drawings           -> POST /api/v1/dwg_takeoff/drawings/upload/
 *   - site photos                  -> POST /api/v1/documents/photos/upload/
 *   - everything else              -> POST /api/v1/documents/upload/
 * With no folder chosen (the only choice on a new project), a model or a
 * drawing still goes to the pipeline that can open it, by its extension; if
 * that pipeline refuses it, it is kept as a document, as it always was.
 * A batch sends a few files at a time, and when the server says "too many
 * uploads" (429), every file waits as long as it asks and then goes again,
 * so a dropped folder arrives whole instead of losing what came past the
 * server's per-minute limit.
 * Large document uploads take the resumable chunked client; the dedicated
 * BIM/DWG/photo endpoints stream server-side. Progress rolls up into the
 * same FloatingQueuePanel used everywhere else.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { uuid } from '@/shared/lib/browser';
import { extractErrorMessageFromBody } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import { fileManagerKeys } from './hooks';
import { uploadResumable, RESUMABLE_THRESHOLD_BYTES } from './resumableUpload';
import type { FileKind } from './types';
// Name-only mesh check (three.js-free) so recognising a 3D file here does not
// pull the BIM viewer's loader graph into the file-manager bundle.
import { isMeshImportFile } from '@/features/bim/meshImport/formats';
import { BIM_MODEL_EXTENSIONS, HANDOFF_EXTENSIONS } from '@/features/bim/uploadFormats';

/** Map FileKind -> documents-module category. Used only by the documents
 * pipeline (the kinds that don't have a dedicated endpoint). */
function categoryForKind(kind: FileKind | null): string {
  if (kind === 'photo') return 'photo';
  if (kind === 'sheet') return 'drawing';
  return 'other';
}

const MODEL_EXTENSIONS = new Set<string>(BIM_MODEL_EXTENSIONS);
const DRAWING_EXTENSIONS = new Set<string>(HANDOFF_EXTENSIONS);

/** The pipeline a file belongs to when nobody chose a folder: ``.ifc`` and
 *  ``.rvt`` are models, ``.dwg`` and ``.dxf`` drawings, the rest documents
 *  (``null``). An IFC stored as a plain document has no viewer, no elements
 *  and no quantities, which is what a dropped model used to get. */
export function kindForUnfiledFile(name: string): FileKind | null {
  const dot = name.lastIndexOf('.');
  if (dot < 0) return null;
  const ext = name.slice(dot).toLowerCase();
  if (MODEL_EXTENSIONS.has(ext)) return 'bim_model';
  if (DRAWING_EXTENSIONS.has(ext)) return 'dwg_drawing';
  return null;
}

/** A refusal that says something about this file, as opposed to "try again
 *  later" (429) or the server failing (5xx). */
function refusedForWhatItIs(status: number): boolean {
  return status >= 400 && status < 500 && status !== 429;
}

/** Uploads of one batch in flight at once. A dropped folder used to start
 *  every upload at the same moment, so all of them raced the server's
 *  per-minute limit together and the ones past it were refused. */
export const PARALLEL_UPLOADS = 3;

/** How many times one file waits out "too many uploads" before giving up. */
export const THROTTLE_RETRIES = 5;

const DEFAULT_RETRY_AFTER_S = 60;
const MAX_RETRY_AFTER_S = 300;

/** How long a 429's ``Retry-After`` asks to wait, in ms: seconds or an HTTP
 *  date, a minute when it says nothing, five minutes at most. */
export function retryAfterMs(header: string | null, now = Date.now()): number {
  const value = header?.trim();
  if (value) {
    if (/^\d+$/.test(value)) return Math.min(Number(value), MAX_RETRY_AFTER_S) * 1000;
    const at = Date.parse(value);
    if (!Number.isNaN(at)) return Math.min(Math.max(at - now, 0), MAX_RETRY_AFTER_S * 1000);
  }
  return DEFAULT_RETRY_AFTER_S * 1000;
}

/** When the server last said "too many uploads", the moment it said to come
 *  back. Shared by every upload, so they all wait instead of each one being
 *  refused to find out. */
let throttledUntil = 0;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Run ``jobs`` with at most ``limit`` going at once, in order. */
async function runWithLimit(jobs: Array<() => Promise<void>>, limit: number): Promise<void> {
  let next = 0;
  const worker = async () => {
    while (next < jobs.length) {
      const job = jobs[next++]!;
      try {
        await job();
      } catch {
        // Each job reports its own failure on its queue row; the next one
        // still goes.
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, jobs.length) }, worker));
}

export interface UseFileUploadResult {
  /** Upload the given files into the pipeline for ``kind``. ``onDone`` runs
   *  once the batch has been queued (not once each transfer finishes). */
  doUpload: (files: FileList | File[], kind: FileKind | null, onDone?: () => void) => Promise<void>;
  uploading: boolean;
}

export function useFileUpload(projectId: string | null | undefined): UseFileUploadResult {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const addQueueTask = useUploadQueueStore((s) => s.addTask);
  const updateQueueTask = useUploadQueueStore((s) => s.updateTask);
  const [uploading, setUploading] = useState(false);

  // Resolve where a kind's upload should go. ``bim_model`` and
  // ``dwg_drawing`` have their own ingest endpoints (and their own storage +
  // conversion pipelines); site photos go to the photo pipeline so a real
  // ProjectPhoto is created; everything else stays on the documents endpoint.
  const directUploadUrl = useCallback(
    (kind: FileKind | null): string | null => {
      if (kind === 'bim_model') {
        return `/api/v1/bim_hub/upload-cad/?project_id=${projectId}`;
      }
      if (kind === 'dwg_drawing') {
        return `/api/v1/dwg_takeoff/drawings/upload/?project_id=${projectId}`;
      }
      if (kind === 'photo') {
        return `/api/v1/documents/photos/upload/?project_id=${projectId}`;
      }
      return null;
    },
    [projectId],
  );

  const doUpload = useCallback(
    async (files: FileList | File[], kind: FileKind | null, onDone?: () => void) => {
      if (!projectId) {
        addToast({
          type: 'error',
          title: t('files.upload_no_project', { defaultValue: 'No active project' }),
        });
        return;
      }

      const validFiles = Array.from(files);
      if (validFiles.length === 0) return;

      const token = useAuthStore.getState().accessToken;
      const cat = categoryForKind(kind);
      const documentsUrl = `/api/v1/documents/upload/?project_id=${projectId}&category=${cat}`;
      setUploading(true);

      // Count 3D mesh files in the batch so we can nudge the user toward the
      // BIM Hub 3D uploader (which actually views/measures them) after queuing.
      let meshCount = 0;
      const jobs: Array<() => Promise<void>> = [];

      for (const file of validFiles) {
        // Common 3D mesh formats (OBJ/STL/glTF/GLB/DAE/FBX/PLY/3DS/…) are not
        // server-convertible CAD: the raw-CAD ingest endpoint would reject
        // them (400). Keep them on the documents pipeline so they are stored
        // safely as a file, and point the user to the BIM Hub 3D uploader to
        // actually view and measure them.
        const isMesh = isMeshImportFile(file.name);
        if (isMesh) meshCount += 1;
        // A folder someone chose is kept; with none, the extension decides.
        const fileKind = kind ?? kindForUnfiledFile(file.name);
        const routedByName = kind === null && fileKind !== null;
        // Non-null for BIM/DWG/photo -> upload goes straight to that module's
        // ingest endpoint (single-shot, server-streamed) instead of the
        // documents pipeline / resumable client.
        const fileDirectUrl = isMesh ? null : directUploadUrl(fileKind);
        const taskId = uuid();
        const uploadingMessage = t('files.uploading', { defaultValue: 'Uploading…' });
        addQueueTask({
          id: taskId,
          type: 'file_upload',
          filename: file.name,
          status: 'queued',
          progress: 0,
          message: t('files.upload_waiting', { defaultValue: 'Waiting to upload…' }),
        });

        // Run a few at a time in the background; progress shows up in the
        // global FloatingQueuePanel, same as DocumentsPage.
        jobs.push(async () => {
          updateQueueTask(taskId, { status: 'processing', message: uploadingMessage, startedAt: Date.now() });
          const markDone = (message?: string) => {
            updateQueueTask(taskId, {
              status: 'completed',
              progress: 100,
              message: message ?? t('files.uploaded', { defaultValue: 'Uploaded' }),
              completedAt: Date.now(),
            });
            queryClient.invalidateQueries({ queryKey: [fileManagerKeys.tree, projectId] });
            queryClient.invalidateQueries({ queryKey: [fileManagerKeys.list, projectId] });
            if (fileKind === 'photo') {
              queryClient.invalidateQueries({
                predicate: (q) =>
                  q.queryKey.some(
                    (k) => typeof k === 'string' && k.toLowerCase().includes('photo'),
                  ),
              });
            }
          };
          const markError = (detail: string) => {
            updateQueueTask(taskId, {
              status: 'error',
              error: detail,
              completedAt: Date.now(),
            });
          };

          /** Large document files take the resumable, chunked path: real
           *  progress and per-chunk retry. */
          const sendResumable = async (doneMessage?: string) => {
            try {
              updateQueueTask(taskId, {
                message: t('files.uploading_chunked', {
                  defaultValue: 'Uploading large file…',
                }),
              });
              await uploadResumable(file, {
                projectId,
                category: cat,
                onProgress: (percent) => updateQueueTask(taskId, { progress: percent }),
              });
              markDone(doneMessage);
            } catch (err) {
              markError(
                err instanceof Error
                  ? err.message
                  : t('files.upload_resume_failed', {
                      defaultValue: 'Upload interrupted. Try again to resume.',
                    }),
              );
            }
          };

          /** One multipart POST, with progress estimated while it runs. */
          const post = async (url: string): Promise<Response> => {
            const formData = new FormData();
            formData.append('file', file);

            const headers: Record<string, string> = { 'X-DDC-Client': 'OE/1.0' };
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const estimatedMs = Math.max(2000, (file.size / (1024 * 1024)) * 500);
            const progressTimer = setInterval(() => {
              const task = useUploadQueueStore.getState().tasks.find((tk) => tk.id === taskId);
              if (task && task.status === 'processing' && task.progress < 90) {
                updateQueueTask(taskId, { progress: task.progress + 5 });
              }
            }, estimatedMs / 18);
            try {
              return await fetch(url, { method: 'POST', headers, body: formData });
            } finally {
              clearInterval(progressTimer);
            }
          };

          /** ``post``, after waiting out any "too many uploads" the server has
           *  answered, and again after each new one, up to THROTTLE_RETRIES. */
          const sendOnce = async (url: string): Promise<Response> => {
            for (let attempt = 0; ; attempt += 1) {
              const wait = throttledUntil - Date.now();
              if (wait > 0) {
                updateQueueTask(taskId, {
                  message: t('files.upload_throttled', {
                    defaultValue: 'The server asked to wait; sending again in {{seconds}} s',
                    seconds: Math.ceil(wait / 1000),
                  }),
                });
                await sleep(wait);
                updateQueueTask(taskId, { message: uploadingMessage });
              }
              const res = await post(url);
              if (res.status !== 429 || attempt >= THROTTLE_RETRIES) return res;
              throttledUntil = Math.max(throttledUntil, Date.now() + retryAfterMs(res.headers.get('Retry-After')));
            }
          };

          const reasonFrom = async (res: Response): Promise<string> => {
            try {
              const body = await res.json();
              return extractErrorMessageFromBody(body) ?? file.name;
            } catch {
              return file.name;
            }
          };

          // Small documents keep the single-shot multipart upload.
          // BIM/DWG/photo always take the single-shot path to their own
          // endpoint (which streams server-side regardless).
          if (!fileDirectUrl && file.size >= RESUMABLE_THRESHOLD_BYTES) {
            await sendResumable();
            return;
          }

          try {
            const res = await sendOnce(fileDirectUrl ?? documentsUrl);
            if (res.ok) {
              markDone();
              return;
            }
            const reason = await reasonFrom(res);
            if (!(routedByName && refusedForWhatItIs(res.status))) {
              markError(reason);
              return;
            }
            // Nobody asked for a model or a drawing, so a refusal there must
            // not lose the file: keep it as a document, as before, and say why.
            const keptAsDocument = t('files.kept_as_document', {
              defaultValue: 'Kept as a document: {{reason}}',
              reason,
            });
            if (file.size >= RESUMABLE_THRESHOLD_BYTES) {
              await sendResumable(keptAsDocument);
              return;
            }
            const asDocument = await sendOnce(documentsUrl);
            if (asDocument.ok) markDone(keptAsDocument);
            else markError(await reasonFrom(asDocument));
          } catch (err) {
            markError(err instanceof Error ? err.message : 'Upload failed');
          }
        });
      }

      void runWithLimit(jobs, PARALLEL_UPLOADS);

      addToast({
        type: 'info',
        title: t('files.upload_queued', {
          defaultValue: '{{count}} file(s) queued',
          count: validFiles.length,
        }),
      });

      // 3D mesh files are stored here as documents, but the place to actually
      // view and measure them is the BIM Hub 3D uploader (it reads OBJ/STL/
      // glTF/… in the browser). Surface that once per batch, not per file.
      if (meshCount > 0) {
        addToast({
          type: 'info',
          title: t('files.mesh_saved_title', {
            defaultValue: '3D mesh saved',
          }),
          message: t('files.mesh_saved_hint', {
            defaultValue:
              'Open the BIM Hub 3D uploader and drop the file there to view, measure and extract geometry quantities.',
          }),
        });
      }

      setUploading(false);
      onDone?.();
    },
    [projectId, directUploadUrl, addToast, addQueueTask, updateQueueTask, queryClient, t],
  );

  return { doUpload, uploading };
}
