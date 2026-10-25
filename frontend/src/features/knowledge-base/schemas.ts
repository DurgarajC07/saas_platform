import { z } from 'zod'

// ── Constants that mirror backend frozensets ──────────────────────────────────
export const KB_STATUSES = ['pending', 'processing', 'completed', 'failed'] as const
export const KB_FILE_TYPES = ['pdf', 'docx', 'txt', 'md', 'csv', 'url', 'youtube'] as const

export type KbStatus = (typeof KB_STATUSES)[number]
export type KbFileType = (typeof KB_FILE_TYPES)[number]

// ── Response interfaces ───────────────────────────────────────────────────────
export interface KbDocumentResponse {
  id: string
  agentId: string
  orgId: string
  fileName: string
  fileType: string
  fileSizeBytes: number | null
  sourceUrl: string | null
  status: KbStatus
  errorMessage: string | null
  chunkCount: number | null
  createdAt: string
  updatedAt: string
}

export interface KbDocumentListResponse {
  documents: KbDocumentResponse[]
  total: number
}

export interface KbUploadResponse {
  docId: string
  fileName: string
  fileType: string
  status: string
  taskId: string
  qdrantCollection: string
}

export interface KbDeleteDocResponse {
  docId: string
  chunksDeleted: number
  message: string
}

// ── URL/YouTube ingestion mini-form ───────────────────────────────────────────
export const urlIngestSchema = z.object({
  url: z.string().url('Enter a valid URL'),
})

export type UrlIngestInput = z.infer<typeof urlIngestSchema>
