import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ApiError,
  api,
  exportDownloadUrl,
  getApiBaseUrl,
  type ExportCreateResponse,
  type ExportDetail,
  type ExportListItem,
  type ExportPreview,
  type PromoteProvisionalsResponse,
  type ProvisionalsResponse,
  type SentenceIR,
  type TranslateSummary,
} from './api'

function parseError(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail)
    return `${error.message}${detail ? ` - ${detail}` : ''}`
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Unknown error'
}

function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null
  return <div className="error-banner">{message}</div>
}

function LoadingText({ show, label = 'Loading...' }: { show: boolean; label?: string }) {
  if (!show) return null
  return <div className="loading-text">{label}</div>
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Gellish Agent UI</h1>
        <nav>
          <Link to="/">Home</Link>
          <Link to="/documents">Documents</Link>
          <Link to="/exports">Exports</Link>
        </nav>
      </header>
      <main>{children}</main>
    </div>
  )
}

function HomePage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string>('unknown')

  useEffect(() => {
    const run = async () => {
      try {
        setLoading(true)
        setError(null)
        const out = await api.getHealth()
        setStatus(String(out.status))
      } catch (err) {
        setStatus('unreachable')
        setError(parseError(err))
      } finally {
        setLoading(false)
      }
    }
    void run()
  }, [])

  return (
    <section>
      <h2>Home</h2>
      <p>API base URL: <code>{getApiBaseUrl()}</code></p>
      <ErrorBanner message={error} />
      <LoadingText show={loading} />
      {!loading && <p>Backend health: <strong>{status}</strong></p>}
      <p>
        <Link to="/documents">Go to Documents</Link>
      </p>
      <p>
        <Link to="/exports">Go to Exports</Link>
      </p>
    </section>
  )
}

function DocumentsPage() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [source, setSource] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ id: number; existing: boolean } | null>(null)

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    try {
      setLoading(true)
      setError(null)
      const out = await api.pasteDocument({ text, source: source || null })
      setResult(out)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section>
      <h2>Paste Ingest</h2>
      <form onSubmit={onSubmit} className="stack">
        <label>
          Source (optional)
          <input value={source} onChange={(e) => setSource(e.target.value)} />
        </label>
        <label>
          Text
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} required />
        </label>
        <button type="submit" disabled={loading}>Ingest text</button>
      </form>
      <LoadingText show={loading} label="Submitting document..." />
      <ErrorBanner message={error} />
      {result && (
        <div className="panel">
          <p>document_id: <strong>{result.id}</strong></p>
          <p>existing: <strong>{String(result.existing)}</strong></p>
          <button onClick={() => navigate(`/documents/${result.id}/translate`)}>Translate this document</button>
        </div>
      )}
    </section>
  )
}

function TranslatePage() {
  const params = useParams<{ documentId: string }>()
  const navigate = useNavigate()
  const documentId = Number(params.documentId)

  const [provider, setProvider] = useState<'stub' | 'openai'>('stub')
  const [maxSentences, setMaxSentences] = useState('')
  const [startSentenceIndex, setStartSentenceIndex] = useState('0')
  const [temperature, setTemperature] = useState('0')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<TranslateSummary | null>(null)

  if (!Number.isFinite(documentId) || documentId <= 0) {
    return <p>Invalid document id.</p>
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    try {
      setLoading(true)
      setError(null)
      const payload: {
        provider: 'stub' | 'openai'
        max_sentences?: number
        start_sentence_index?: number
        openai?: { temperature?: number }
      } = { provider }
      if (maxSentences.trim() !== '') payload.max_sentences = Number(maxSentences)
      if (startSentenceIndex.trim() !== '') payload.start_sentence_index = Number(startSentenceIndex)
      if (provider === 'openai' && temperature.trim() !== '') payload.openai = { temperature: Number(temperature) }

      const out = await api.translateDocument(documentId, payload)
      setResult(out)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section>
      <h2>Translate Document {documentId}</h2>
      <form onSubmit={onSubmit} className="stack">
        <label>
          Provider
          <select value={provider} onChange={(e) => setProvider(e.target.value as 'stub' | 'openai')}>
            <option value="stub">stub</option>
            <option value="openai">openai</option>
          </select>
        </label>
        <label>
          max_sentences (optional)
          <input value={maxSentences} onChange={(e) => setMaxSentences(e.target.value)} type="number" min={1} />
        </label>
        <label>
          start_sentence_index
          <input
            value={startSentenceIndex}
            onChange={(e) => setStartSentenceIndex(e.target.value)}
            type="number"
            min={0}
          />
        </label>
        {provider === 'openai' && (
          <label>
            temperature
            <input value={temperature} onChange={(e) => setTemperature(e.target.value)} type="number" min={0} max={2} step="0.1" />
          </label>
        )}
        <button type="submit" disabled={loading}>Start translation</button>
      </form>
      <LoadingText show={loading} label="Running translation..." />
      <ErrorBanner message={error} />
      {result && (
        <div className="panel">
          <p>translation_run_id: <strong>{result.translation_run_id}</strong></p>
          <p>sentences_processed: {result.sentences_processed}</p>
          <p>valid_count: {result.valid_count}</p>
          <p>invalid_count: {result.invalid_count}</p>
          <p>next_sentence_index: {String(result.next_sentence_index)}</p>
          <p>is_complete: {String(result.is_complete)}</p>
          {result.aborted_reason && <p>aborted_reason: {result.aborted_reason}</p>}
          <button onClick={() => navigate(`/runs/${result.translation_run_id}`)}>Open run detail</button>
        </div>
      )}
    </section>
  )
}

function RunDetailPage() {
  const params = useParams<{ runId: string }>()
  const runId = Number(params.runId)
  const [loading, setLoading] = useState(true)
  const [refreshTick, setRefreshTick] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const [sentenceIrs, setSentenceIrs] = useState<SentenceIR[]>([])
  const [expressions, setExpressions] = useState<
    {
      id: number
      subject_uid: string
      relation_uid: string
      object_uid: string | null
      object_literal: string | null
      status: string
      confidence: number | null
    }[]
  >([])
  const [provisionals, setProvisionals] = useState<ProvisionalsResponse | null>(null)
  const [runExports, setRunExports] = useState<ExportListItem[]>([])

  const [autoGenerateMissing, setAutoGenerateMissing] = useState(true)
  const [mappingText, setMappingText] = useState('{}')
  const [promoteLoading, setPromoteLoading] = useState(false)
  const [promoteResult, setPromoteResult] = useState<PromoteProvisionalsResponse | null>(null)

  const [exportLoading, setExportLoading] = useState(false)
  const [exportResult, setExportResult] = useState<ExportCreateResponse | null>(null)

  const prettySentenceIrs = useMemo(() => JSON.stringify(sentenceIrs, null, 2), [sentenceIrs])

  useEffect(() => {
    const run = async () => {
      if (!Number.isFinite(runId) || runId <= 0) return
      try {
        setLoading(true)
        setError(null)
        const [irsOut, exprOut, provOut, expOut] = await Promise.all([
          api.getSentenceIrs(runId),
          api.getExpressions(runId),
          api.getProvisionals(runId),
          api.listRunExports(runId),
        ])
        setSentenceIrs(irsOut)
        setExpressions(exprOut)
        setProvisionals(provOut)
        setRunExports(expOut)
      } catch (err) {
        setError(parseError(err))
      } finally {
        setLoading(false)
      }
    }
    void run()
  }, [runId, refreshTick])

  if (!Number.isFinite(runId) || runId <= 0) {
    return <p>Invalid run id.</p>
  }

  const onPromote = async (event: FormEvent) => {
    event.preventDefault()
    try {
      setPromoteLoading(true)
      setError(null)
      let mapping: Record<string, { new_uid?: string | null; pref_label?: string | null; definition?: string | null }> = {}
      if (mappingText.trim()) {
        mapping = JSON.parse(mappingText) as typeof mapping
      }
      const out = await api.promoteProvisionals(runId, {
        auto_generate_missing: autoGenerateMissing,
        mapping,
      })
      setPromoteResult(out)
      setRefreshTick((v) => v + 1)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setPromoteLoading(false)
    }
  }

  const onCreateExport = async () => {
    try {
      setExportLoading(true)
      setError(null)
      const out = await api.createSouffleExport(runId)
      setExportResult(out)
      setRefreshTick((v) => v + 1)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setExportLoading(false)
    }
  }

  return (
    <section>
      <h2>Run Detail {runId}</h2>
      <button onClick={() => setRefreshTick((v) => v + 1)} disabled={loading}>Refresh</button>
      <LoadingText show={loading} />
      <ErrorBanner message={error} />

      <h3>Sentence IRs</h3>
      <pre className="json-box">{prettySentenceIrs}</pre>

      <h3>Expressions ({expressions.length})</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>id</th>
              <th>subject_uid</th>
              <th>relation_uid</th>
              <th>object_uid</th>
              <th>object_literal</th>
              <th>status</th>
              <th>confidence</th>
            </tr>
          </thead>
          <tbody>
            {expressions.map((row) => (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td>{row.subject_uid}</td>
                <td>{row.relation_uid}</td>
                <td>{row.object_uid ?? ''}</td>
                <td>{row.object_literal ?? ''}</td>
                <td>{row.status}</td>
                <td>{row.confidence ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Provisionals</h3>
      <p>Count: {provisionals?.provisional_uids.length ?? 0}</p>
      <ul>
        {(provisionals?.provisional_uids ?? []).map((uid) => (
          <li key={uid}>{uid} ({provisionals?.counts?.[uid] ?? 0})</li>
        ))}
      </ul>

      <h3>Promote provisionals</h3>
      <form onSubmit={onPromote} className="stack">
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={autoGenerateMissing}
            onChange={(e) => setAutoGenerateMissing(e.target.checked)}
          />
          auto_generate_missing
        </label>
        <label>
          mapping JSON (optional)
          <textarea value={mappingText} onChange={(e) => setMappingText(e.target.value)} rows={8} />
        </label>
        <button type="submit" disabled={promoteLoading}>Promote</button>
      </form>
      <LoadingText show={promoteLoading} label="Promoting..." />
      {promoteResult && <pre className="json-box">{JSON.stringify(promoteResult, null, 2)}</pre>}

      <h3>Exports</h3>
      <button onClick={onCreateExport} disabled={exportLoading}>Create Souffle export</button>
      <LoadingText show={exportLoading} label="Creating export..." />
      {exportResult && <pre className="json-box">{JSON.stringify(exportResult, null, 2)}</pre>}

      <ul>
        {runExports.map((item) => (
          <li key={item.export_id}>
            #{item.export_id} | {item.format} | rows={item.row_count ?? 0} |
            {' '}<a href={exportDownloadUrl(item.export_id)}>Download</a> |
            {' '}<Link to={`/exports/${item.export_id}`}>Detail</Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ExportsPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const [runId, setRunId] = useState(searchParams.get('run_id') ?? '')
  const [format, setFormat] = useState(searchParams.get('format') ?? 'souffle')
  const [limit, setLimit] = useState(searchParams.get('limit') ?? '50')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [items, setItems] = useState<ExportListItem[]>([])

  const runSearch = async (event?: FormEvent) => {
    event?.preventDefault()
    try {
      setLoading(true)
      setError(null)
      const runIdNumber = runId.trim() ? Number(runId) : undefined
      const limitNumber = limit.trim() ? Number(limit) : undefined
      const nextParams = new URLSearchParams()
      if (runIdNumber) nextParams.set('run_id', String(runIdNumber))
      if (format.trim()) nextParams.set('format', format.trim())
      if (limitNumber) nextParams.set('limit', String(limitNumber))
      setSearchParams(nextParams)
      const out = await api.listExports({ run_id: runIdNumber, format: format.trim(), limit: limitNumber })
      setItems(out)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void runSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section>
      <h2>Export Archive Search</h2>
      <form onSubmit={runSearch} className="inline-form">
        <label>
          run_id
          <input value={runId} onChange={(e) => setRunId(e.target.value)} type="number" min={1} />
        </label>
        <label>
          format
          <input value={format} onChange={(e) => setFormat(e.target.value)} />
        </label>
        <label>
          limit
          <input value={limit} onChange={(e) => setLimit(e.target.value)} type="number" min={1} max={200} />
        </label>
        <button type="submit" disabled={loading}>Search</button>
      </form>
      <LoadingText show={loading} />
      <ErrorBanner message={error} />

      <ul>
        {items.map((item) => (
          <li key={item.export_id}>
            <Link to={`/exports/${item.export_id}`}>Export #{item.export_id}</Link>
            {' '}run={item.run_id} format={item.format} kind={item.kind} rows={item.row_count ?? 0}
          </li>
        ))}
      </ul>
    </section>
  )
}

function ExportDetailPage() {
  const params = useParams<{ exportId: string }>()
  const exportId = Number(params.exportId)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [detail, setDetail] = useState<ExportDetail | null>(null)
  const [preview, setPreview] = useState<ExportPreview | null>(null)

  useEffect(() => {
    const run = async () => {
      if (!Number.isFinite(exportId) || exportId <= 0) return
      try {
        setLoading(true)
        setError(null)
        const out = await api.getExport(exportId)
        setDetail(out)
        try {
          const previewOut = await api.getExportPreview(exportId)
          setPreview(previewOut)
        } catch {
          setPreview(null)
        }
      } catch (err) {
        setError(parseError(err))
      } finally {
        setLoading(false)
      }
    }
    void run()
  }, [exportId])

  if (!Number.isFinite(exportId) || exportId <= 0) {
    return <p>Invalid export id.</p>
  }

  return (
    <section>
      <h2>Export Detail {exportId}</h2>
      <LoadingText show={loading} />
      <ErrorBanner message={error} />

      {detail && <pre className="json-box">{JSON.stringify(detail, null, 2)}</pre>}

      <p>
        <a href={exportDownloadUrl(exportId)}>Download export</a>
      </p>

      {preview && (
        <>
          <h3>Preview: {preview.file}</h3>
          <pre className="json-box">{preview.lines.join('\n')}</pre>
        </>
      )}
    </section>
  )
}

function AppRoutes() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:documentId/translate" element={<TranslatePage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/exports" element={<ExportsPage />} />
        <Route path="/exports/:exportId" element={<ExportDetailPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
