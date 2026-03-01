const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || 'http://localhost:8000'

export const getApiBaseUrl = (): string => API_BASE_URL

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    let detail: unknown = null
    try {
      detail = await response.json()
    } catch {
      detail = await response.text()
    }
    throw new ApiError(`Request failed: ${response.status}`, response.status, detail)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export type HealthResponse = { status: string | boolean }

export type IngestResult = {
  id: number
  existing: boolean
}

export type TranslateRequest = {
  provider: 'stub' | 'openai'
  start_sentence_index?: number
  max_sentences?: number
  openai?: {
    model?: string
    temperature?: number
    seed?: number
  }
}

export type TranslateSummary = {
  translation_run_id: number
  sentences_processed: number
  valid_count: number
  invalid_count: number
  next_sentence_index: number | null
  is_complete: boolean
  aborted_reason: string | null
}

export type SentenceIR = {
  id: number
  translation_run_id: number
  sentence_id: number
  is_valid: boolean
  errors_json: string[] | null
  ir_json: Record<string, unknown>
  created_at: string
}

export type Expression = {
  id: number
  subject_uid: string
  relation_uid: string
  object_uid: string | null
  object_literal: string | null
  confidence: number | null
  status: string
  qualifiers_json: Record<string, unknown> | null
  provenance_json: Record<string, unknown> | null
}

export type ProvisionalsResponse = {
  run_id: number
  provisional_uids: string[]
  counts: Record<string, number>
}

export type PromoteProvisionalsRequest = {
  auto_generate_missing: boolean
  mapping: Record<
    string,
    {
      new_uid?: string | null
      pref_label?: string | null
      definition?: string | null
    }
  >
}

export type PromoteProvisionalsResponse = {
  run_id: number
  promoted: Record<string, string>
  skipped: string[]
  expressions_updated: number
  review_items_resolved: number
}

export type ExportListItem = {
  export_id: number
  run_id: number
  format: string
  kind: string
  created_at: string
  row_count: number | null
}

export type ExportCreateResponse = {
  export_id: number
  run_id: number
  created_at: string
  row_count: number
  download_url: string
}

export type ExportDetail = {
  id: number
  translation_run_id: number
  format: string
  kind: string
  storage_path: string
  sha256: string | null
  row_count: number | null
  schema_version: string | null
  created_at: string
  meta_json: Record<string, unknown> | null
}

export type ExportPreview = {
  export_id: number
  file: string
  lines: string[]
}

export const api = {
  getHealth: () => request<HealthResponse>('/health'),

  pasteDocument: (payload: { text: string; source?: string | null }) =>
    request<IngestResult>('/documents/paste', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  translateDocument: (documentId: number, payload: TranslateRequest) =>
    request<TranslateSummary>(`/translate/document/${documentId}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getSentenceIrs: (runId: number) => request<SentenceIR[]>(`/translation-runs/${runId}/sentence-irs`),

  getExpressions: (runId: number) => request<Expression[]>(`/translation-runs/${runId}/expressions`),

  getProvisionals: (runId: number) => request<ProvisionalsResponse>(`/translation-runs/${runId}/provisionals`),

  promoteProvisionals: (runId: number, payload: PromoteProvisionalsRequest) =>
    request<PromoteProvisionalsResponse>(`/translation-runs/${runId}/promote-provisionals`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  createSouffleExport: (runId: number) =>
    request<ExportCreateResponse>(`/translation-runs/${runId}/exports/souffle`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  listRunExports: (runId: number) => request<ExportListItem[]>(`/translation-runs/${runId}/exports`),

  listExports: (params: { run_id?: number; format?: string; limit?: number }) => {
    const query = new URLSearchParams()
    if (params.run_id) query.set('run_id', String(params.run_id))
    if (params.format) query.set('format', params.format)
    if (params.limit) query.set('limit', String(params.limit))
    const suffix = query.toString()
    return request<ExportListItem[]>(`/exports${suffix ? `?${suffix}` : ''}`)
  },

  getExport: (exportId: number) => request<ExportDetail>(`/exports/${exportId}`),

  getExportPreview: (exportId: number, file = 'README.txt', lines = 40) =>
    request<ExportPreview>(`/exports/${exportId}/preview?file=${encodeURIComponent(file)}&lines=${lines}`),
}

export const exportDownloadUrl = (exportId: number): string => `${API_BASE_URL}/exports/${exportId}/download`
