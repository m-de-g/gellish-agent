import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ApiError,
  api,
  exportDownloadUrl,
  getApiBaseUrl,
  type DictionaryAlias,
  type DictionaryConcept,
  type DictionaryRelation,
  type DictionaryTerm,
  type DocumentDetail,
  type DocumentSentence,
  type ExportCreateResponse,
  type ExportDetail,
  type ExportListItem,
  type ExportPreview,
  type Expression,
  type PromoteProvisionalsResponse,
  type ProvisionalsResponse,
  type ReviewItem,
  type SentenceIR,
  type TranslateSummary,
  type TranslationRun,
  type TranslationRunListItem,
} from './api'
import ExpressionsTable from './components/ExpressionsTable'
import ProvisionalsTable from './components/ProvisionalsTable'
import SentenceIrTable from './components/SentenceIrTable'
import { loadRecent, pushRecent, type RecentStore } from './recent'

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
          <Link to="/runs">Runs</Link>
          <Link to="/reviews">Reviews</Link>
          <Link to="/dictionary">Dictionary</Link>
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
  const [recent, setRecent] = useState<RecentStore>(loadRecent())

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
    setRecent(loadRecent())
  }, [])

  return (
    <section>
      <h2>Home</h2>
      <p>API base URL: <code>{getApiBaseUrl()}</code></p>
      <ErrorBanner message={error} />
      <LoadingText show={loading} />
      {!loading && <p>Backend health: <strong>{status}</strong></p>}

      <h3>Recent</h3>
      <div className="panel">
        <p><strong>Documents</strong></p>
        <ul>
          {recent.documents.map((id) => <li key={id}><Link to={`/documents/${id}`}>{id}</Link></li>)}
        </ul>
        <p><strong>Runs</strong></p>
        <ul>
          {recent.runs.map((id) => <li key={id}><Link to={`/runs/${id}`}>{id}</Link></li>)}
        </ul>
        <p><strong>Exports</strong></p>
        <ul>
          {recent.exports.map((id) => <li key={id}><Link to={`/exports/${id}`}>{id}</Link></li>)}
        </ul>
      </div>
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
  const [documents, setDocuments] = useState<Array<{ id: number; source: string | null; created_at: string }>>([])

  useEffect(() => {
    const run = async () => {
      try {
        const out = await api.listDocuments({ limit: 50 })
        setDocuments(out)
      } catch {
        setDocuments([])
      }
    }
    void run()
  }, [])

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    try {
      setLoading(true)
      setError(null)
      const out = await api.pasteDocument({ text, source: source || null })
      setResult(out)
      pushRecent('documents', out.id)
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
          <button onClick={() => navigate(`/documents/${result.id}`)}>Open document</button>
        </div>
      )}

      <h3>Recent documents</h3>
      <ul>
        {documents.map((doc) => (
          <li key={doc.id}>
            <Link to={`/documents/${doc.id}`}>Document {doc.id}</Link>
            {' '}source={doc.source ?? '-'} created={doc.created_at}
          </li>
        ))}
      </ul>
    </section>
  )
}

function DocumentDetailPage() {
  const params = useParams<{ documentId: string }>()
  const documentId = Number(params.documentId)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [document, setDocument] = useState<DocumentDetail | null>(null)
  const [sentences, setSentences] = useState<DocumentSentence[]>([])

  useEffect(() => {
    const run = async () => {
      if (!Number.isFinite(documentId) || documentId <= 0) return
      try {
        setLoading(true)
        setError(null)
        const [docOut, sentenceOut] = await Promise.all([
          api.getDocument(documentId),
          api.getDocumentSentences(documentId),
        ])
        setDocument(docOut)
        setSentences(sentenceOut)
        pushRecent('documents', documentId)
      } catch (err) {
        setError(parseError(err))
      } finally {
        setLoading(false)
      }
    }
    void run()
  }, [documentId])

  if (!Number.isFinite(documentId) || documentId <= 0) {
    return <p>Invalid document id.</p>
  }

  const fullText = sentences.map((sentence) => sentence.text).join('\n')

  return (
    <section>
      <h2>Document {documentId}</h2>
      <LoadingText show={loading} />
      <ErrorBanner message={error} />

      {document && (
        <div className="panel">
          <p>source: {document.source ?? '-'}</p>
          <p>mime_type: {document.mime_type ?? '-'}</p>
          <p>created_at: {document.created_at}</p>
          <p>content_hash: <code>{document.content_hash}</code></p>
          <p>
            <Link to={`/documents/${documentId}/translate?start_sentence_index=0`}>Translate this document</Link>
          </p>
          <details>
            <summary>Full text ({sentences.length} sentences)</summary>
            <pre className="json-box">{fullText}</pre>
          </details>
          <details>
            <summary>metadata_json</summary>
            <pre className="json-box">{JSON.stringify(document.metadata_json ?? {}, null, 2)}</pre>
          </details>
        </div>
      )}

      <h3>Sentences</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>sentence_id</th>
              <th>sentence_index</th>
              <th>text</th>
              <th>action</th>
            </tr>
          </thead>
          <tbody>
            {sentences.map((sentence) => (
              <tr key={sentence.id}>
                <td>{sentence.id}</td>
                <td>{sentence.sentence_index}</td>
                <td>{sentence.text}</td>
                <td>
                  <Link to={`/documents/${documentId}/translate?start_sentence_index=${sentence.sentence_index}`}>
                    Translate from here
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function TranslatePage() {
  const params = useParams<{ documentId: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const documentId = Number(params.documentId)

  const [provider, setProvider] = useState<'stub' | 'openai'>('stub')
  const [maxSentences, setMaxSentences] = useState('')
  const [startSentenceIndex, setStartSentenceIndex] = useState(searchParams.get('start_sentence_index') ?? '0')
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
      pushRecent('documents', documentId)
      pushRecent('runs', out.translation_run_id)
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

function statusFromRun(row: TranslationRunListItem): string {
  if (row.aborted_reason) return 'aborted'
  if (row.processed_sentences > 0) return 'completed'
  return 'created'
}

function RunsListPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [runId, setRunId] = useState(searchParams.get('run_id') ?? '')
  const [documentId, setDocumentId] = useState(searchParams.get('document_id') ?? '')
  const [provider, setProvider] = useState(searchParams.get('provider') ?? '')
  const [status, setStatus] = useState(searchParams.get('status') ?? '')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [items, setItems] = useState<TranslationRunListItem[]>([])

  const runSearch = async (event?: FormEvent) => {
    event?.preventDefault()
    try {
      setLoading(true)
      setError(null)
      const documentIdNumber = documentId.trim() ? Number(documentId) : undefined
      const nextParams = new URLSearchParams()
      if (runId.trim()) nextParams.set('run_id', runId.trim())
      if (documentIdNumber) nextParams.set('document_id', String(documentIdNumber))
      if (provider.trim()) nextParams.set('provider', provider.trim())
      if (status.trim()) nextParams.set('status', status.trim())
      setSearchParams(nextParams)

      const out = await api.listTranslationRuns({ limit: 100, document_id: documentIdNumber, provider: provider.trim() || undefined })
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

  const filtered = useMemo(() => {
    return items.filter((row) => {
      if (runId.trim() && row.run_id !== Number(runId)) return false
      if (status.trim() && statusFromRun(row) !== status.trim()) return false
      return true
    })
  }, [items, runId, status])

  return (
    <section>
      <h2>Runs</h2>
      <form onSubmit={runSearch} className="inline-form">
        <label>
          run_id
          <input value={runId} onChange={(e) => setRunId(e.target.value)} type="number" min={1} />
        </label>
        <label>
          document_id
          <input value={documentId} onChange={(e) => setDocumentId(e.target.value)} type="number" min={1} />
        </label>
        <label>
          provider
          <input value={provider} onChange={(e) => setProvider(e.target.value)} />
        </label>
        <label>
          status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">all</option>
            <option value="created">created</option>
            <option value="completed">completed</option>
            <option value="aborted">aborted</option>
          </select>
        </label>
        <button type="submit" disabled={loading}>Search</button>
      </form>
      <LoadingText show={loading} />
      <ErrorBanner message={error} />

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>run_id</th>
              <th>document_id</th>
              <th>provider</th>
              <th>created_at</th>
              <th>processed_sentences</th>
              <th>valid_count</th>
              <th>invalid_count</th>
              <th>aborted_reason</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => (
              <tr key={item.run_id}>
                <td><Link to={`/runs/${item.run_id}`}>{item.run_id}</Link></td>
                <td><Link to={`/documents/${item.document_id}`}>{item.document_id}</Link></td>
                <td>{item.provider ?? ''}</td>
                <td>{item.created_at}</td>
                <td>{item.processed_sentences}</td>
                <td>{item.valid_count}</td>
                <td>{item.invalid_count}</td>
                <td>{item.aborted_reason ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function matchesRunReview(item: ReviewItem, runId: number): boolean {
  const ref = item.item_ref
  return ref.startsWith(`${runId}:`) || ref.startsWith(`run:${runId}:`)
}

function RunDetailPage() {
  const params = useParams<{ runId: string }>()
  const runId = Number(params.runId)
  const [loading, setLoading] = useState(true)
  const [refreshTick, setRefreshTick] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const [runSummary, setRunSummary] = useState<TranslationRun | null>(null)
  const [sentenceIrs, setSentenceIrs] = useState<SentenceIR[]>([])
  const [expressions, setExpressions] = useState<Expression[]>([])
  const [provisionals, setProvisionals] = useState<ProvisionalsResponse | null>(null)
  const [runExports, setRunExports] = useState<ExportListItem[]>([])
  const [runReviews, setRunReviews] = useState<ReviewItem[]>([])

  const [autoGenerateMissing, setAutoGenerateMissing] = useState(true)
  const [mappingText, setMappingText] = useState('{}')
  const [promoteLoading, setPromoteLoading] = useState(false)
  const [promoteResult, setPromoteResult] = useState<PromoteProvisionalsResponse | null>(null)

  const [exportLoading, setExportLoading] = useState(false)
  const [exportResult, setExportResult] = useState<ExportCreateResponse | null>(null)
  const [reviewActionLoading, setReviewActionLoading] = useState<Record<number, boolean>>({})

  useEffect(() => {
    const run = async () => {
      if (!Number.isFinite(runId) || runId <= 0) return
      try {
        setLoading(true)
        setError(null)
        const [runOut, irsOut, exprOut, provOut, expOut, reviewsOut] = await Promise.all([
          api.getTranslationRun(runId),
          api.getSentenceIrs(runId),
          api.getExpressions(runId),
          api.getProvisionals(runId),
          api.listRunExports(runId),
          api.listReviews({ status: 'open', limit: 400 }),
        ])
        setRunSummary(runOut)
        setSentenceIrs(irsOut)
        setExpressions(exprOut)
        setProvisionals(provOut)
        setRunExports(expOut)
        setRunReviews(reviewsOut.filter((item) => matchesRunReview(item, runId)))
        pushRecent('runs', runId)
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

  const onDownloadIrJson = () => {
    const blob = new Blob([`${JSON.stringify(sentenceIrs, null, 2)}\n`], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `run-${runId}-sentence-irs.json`
    anchor.click()
    URL.revokeObjectURL(url)
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
      setRefreshTick((value) => value + 1)
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
      pushRecent('exports', out.export_id)
      setRefreshTick((value) => value + 1)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setExportLoading(false)
    }
  }

  const onCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
    } catch {
      setError('Unable to copy URL from browser clipboard API.')
    }
  }

  const onResolveReview = async (reviewId: number) => {
    try {
      setReviewActionLoading((prev) => ({ ...prev, [reviewId]: true }))
      await api.resolveReview(reviewId, { resolution: 'acknowledged', notes: 'resolved from run detail' })
      setRefreshTick((value) => value + 1)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setReviewActionLoading((prev) => ({ ...prev, [reviewId]: false }))
    }
  }

  const onDismissReview = async (reviewId: number) => {
    try {
      setReviewActionLoading((prev) => ({ ...prev, [reviewId]: true }))
      await api.dismissReview(reviewId, { reason: 'dismissed from run detail' })
      setRefreshTick((value) => value + 1)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setReviewActionLoading((prev) => ({ ...prev, [reviewId]: false }))
    }
  }

  return (
    <section>
      <h2>Run Detail {runId}</h2>
      <button onClick={() => setRefreshTick((value) => value + 1)} disabled={loading}>Refresh</button>
      <LoadingText show={loading} />
      <ErrorBanner message={error} />

      <h3>Run Summary</h3>
      {runSummary && (
        <div className="panel">
          <p>provider/model: {runSummary.provider ?? runSummary.llm_provider ?? '-'} / {runSummary.model ?? runSummary.llm_model ?? '-'}</p>
          <p>document_id: <Link to={`/documents/${runSummary.document_id}`}>{runSummary.document_id}</Link></p>
          <p>created_at: {runSummary.created_at}</p>
          <p>started_at: {runSummary.started_at ?? '-'}</p>
          <p>finished_at: {runSummary.finished_at ?? '-'}</p>
          <p>retries_total: {runSummary.retries_total}</p>
          <p>token_prompt_total: {runSummary.token_prompt_total ?? 0}</p>
          <p>token_completion_total: {runSummary.token_completion_total ?? 0}</p>
          <p>token_total: {runSummary.token_total ?? 0}</p>
          <p>aborted_reason: {runSummary.aborted_reason ?? '-'}</p>
          <button type="button" onClick={onCopyLink}>Copy link</button>
        </div>
      )}

      <h3>Sentence IRs</h3>
      <SentenceIrTable sentenceIrs={sentenceIrs} onDownloadJson={onDownloadIrJson} />

      <h3>Expressions ({expressions.length})</h3>
      <ExpressionsTable expressions={expressions} />

      <h3>Provisionals</h3>
      <p>Count: {provisionals?.provisional_uids.length ?? 0}</p>
      <ProvisionalsTable provisionals={provisionals} onSuggestMapping={setMappingText} />

      <h3>Promote provisionals</h3>
      <form onSubmit={onPromote} className="stack">
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={autoGenerateMissing}
            onChange={(event) => setAutoGenerateMissing(event.target.checked)}
          />
          auto_generate_missing
        </label>
        <label>
          mapping JSON (optional)
          <textarea value={mappingText} onChange={(event) => setMappingText(event.target.value)} rows={8} />
        </label>
        <button type="submit" disabled={promoteLoading}>Promote</button>
      </form>
      <LoadingText show={promoteLoading} label="Promoting..." />
      {promoteResult && <pre className="json-box">{JSON.stringify(promoteResult, null, 2)}</pre>}

      <h3>Reviews for this run</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>id</th>
              <th>type</th>
              <th>ref</th>
              <th>reason</th>
              <th>action</th>
            </tr>
          </thead>
          <tbody>
            {runReviews.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.item_type}</td>
                <td>{item.item_ref}</td>
                <td>{item.reason ?? ''}</td>
                <td>
                  <button
                    type="button"
                    disabled={Boolean(reviewActionLoading[item.id])}
                    onClick={() => onResolveReview(item.id)}
                  >
                    Resolve
                  </button>
                  <button
                    type="button"
                    disabled={Boolean(reviewActionLoading[item.id])}
                    onClick={() => onDismissReview(item.id)}
                  >
                    Dismiss
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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
          <input value={runId} onChange={(event) => setRunId(event.target.value)} type="number" min={1} />
        </label>
        <label>
          format
          <input value={format} onChange={(event) => setFormat(event.target.value)} />
        </label>
        <label>
          limit
          <input value={limit} onChange={(event) => setLimit(event.target.value)} type="number" min={1} max={200} />
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
        pushRecent('exports', exportId)
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

  const runIdFromMeta = typeof detail?.meta_json?.run_id === 'number' ? detail.meta_json.run_id : null
  const linkedRunId = detail?.translation_run_id ?? runIdFromMeta

  return (
    <section>
      <h2>Export Detail {exportId}</h2>
      <LoadingText show={loading} />
      <ErrorBanner message={error} />

      {detail && (
        <>
          <pre className="json-box">{JSON.stringify(detail, null, 2)}</pre>
          {linkedRunId && (
            <p>
              <Link to={`/runs/${linkedRunId}`}>Back to run {linkedRunId}</Link>
            </p>
          )}
        </>
      )}

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

type ReviewStatus = 'open' | 'resolved' | 'dismissed'

function reviewTarget(item: ReviewItem): string | null {
  const ref = item.item_ref
  if (ref.startsWith('provisional:')) {
    return `/dictionary?uid=${encodeURIComponent(ref)}`
  }

  const runSentence = ref.match(/^(\d+):(\d+)(?::\d+)?$/)
  if (runSentence) {
    return `/runs/${runSentence[1]}`
  }

  const prefixed = ref.match(/^run:(\d+):\d+(?::\d+)?$/)
  if (prefixed) {
    return `/runs/${prefixed[1]}`
  }

  return null
}

function ReviewsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<ReviewStatus>((searchParams.get('status') as ReviewStatus) || 'open')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [items, setItems] = useState<ReviewItem[]>([])
  const [actionLoading, setActionLoading] = useState<Record<number, boolean>>({})

  const fetchReviews = async (nextStatus = status) => {
    try {
      setLoading(true)
      setError(null)
      setSearchParams(new URLSearchParams({ status: nextStatus }))
      const out = await api.listReviews({ status: nextStatus, limit: 500 })
      setItems(out)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchReviews(status)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onResolve = async (reviewId: number) => {
    try {
      setActionLoading((prev) => ({ ...prev, [reviewId]: true }))
      await api.resolveReview(reviewId, { resolution: 'manual', notes: 'resolved from reviews page' })
      await fetchReviews(status)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setActionLoading((prev) => ({ ...prev, [reviewId]: false }))
    }
  }

  const onDismiss = async (reviewId: number) => {
    try {
      setActionLoading((prev) => ({ ...prev, [reviewId]: true }))
      await api.dismissReview(reviewId, { reason: 'dismissed from reviews page' })
      await fetchReviews(status)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setActionLoading((prev) => ({ ...prev, [reviewId]: false }))
    }
  }

  return (
    <section>
      <h2>Reviews</h2>
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault()
          void fetchReviews(status)
        }}
      >
        <label>
          status
          <select
            value={status}
            onChange={(event) => {
              const next = event.target.value as ReviewStatus
              setStatus(next)
            }}
          >
            <option value="open">open</option>
            <option value="resolved">resolved</option>
            <option value="dismissed">dismissed</option>
          </select>
        </label>
        <button type="submit" disabled={loading}>Refresh</button>
      </form>
      <LoadingText show={loading} />
      <ErrorBanner message={error} />

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>id</th>
              <th>type</th>
              <th>ref</th>
              <th>reason</th>
              <th>status</th>
              <th>updated_at</th>
              <th>actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const target = reviewTarget(item)
              return (
                <tr key={item.id}>
                  <td>{item.id}</td>
                  <td>{item.item_type}</td>
                  <td>{item.item_ref}</td>
                  <td>{item.reason ?? ''}</td>
                  <td>{item.status}</td>
                  <td>{item.updated_at}</td>
                  <td>
                    {target && <Link to={target}>Go to</Link>}
                    {item.status === 'open' && (
                      <>
                        <button
                          type="button"
                          disabled={Boolean(actionLoading[item.id])}
                          onClick={() => onResolve(item.id)}
                        >
                          Resolve
                        </button>
                        <button
                          type="button"
                          disabled={Boolean(actionLoading[item.id])}
                          onClick={() => onDismiss(item.id)}
                        >
                          Dismiss
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

type DictionaryTab = 'concepts' | 'relations' | 'terms' | 'aliases'

function DictionaryPage() {
  const [searchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState<DictionaryTab>('concepts')
  const [query, setQuery] = useState(searchParams.get('uid') ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [available, setAvailable] = useState<Record<DictionaryTab, boolean>>({
    concepts: true,
    relations: true,
    terms: true,
    aliases: true,
  })

  const [concepts, setConcepts] = useState<DictionaryConcept[]>([])
  const [relations, setRelations] = useState<DictionaryRelation[]>([])
  const [terms, setTerms] = useState<DictionaryTerm[]>([])
  const [aliases, setAliases] = useState<DictionaryAlias[]>([])

  useEffect(() => {
    const detect = async () => {
      const checks: Record<DictionaryTab, boolean> = {
        concepts: true,
        relations: true,
        terms: true,
        aliases: true,
      }
      try {
        await api.searchDictionaryConcepts({ q: '', limit: 1 })
      } catch (err) {
        checks.concepts = !(err instanceof ApiError && err.status === 404)
      }
      try {
        await api.searchDictionaryRelations({ q: '', limit: 1 })
      } catch (err) {
        checks.relations = !(err instanceof ApiError && err.status === 404)
      }
      try {
        await api.searchDictionaryTerms({ q: '', limit: 1 })
      } catch (err) {
        checks.terms = !(err instanceof ApiError && err.status === 404)
      }
      try {
        await api.searchDictionaryAliases({ q: '', limit: 1 })
      } catch (err) {
        checks.aliases = !(err instanceof ApiError && err.status === 404)
      }
      setAvailable(checks)

      if (!checks[activeTab]) {
        const firstAvailable = (Object.keys(checks) as DictionaryTab[]).find((key) => checks[key])
        if (firstAvailable) setActiveTab(firstAvailable)
      }
    }

    void detect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const runSearch = async (event?: FormEvent) => {
    event?.preventDefault()
    try {
      setLoading(true)
      setError(null)
      const q = query.trim()
      if (activeTab === 'concepts') setConcepts(await api.searchDictionaryConcepts({ q, limit: 100 }))
      if (activeTab === 'relations') setRelations(await api.searchDictionaryRelations({ q, limit: 100 }))
      if (activeTab === 'terms') setTerms(await api.searchDictionaryTerms({ q, limit: 100 }))
      if (activeTab === 'aliases') setAliases(await api.searchDictionaryAliases({ q, limit: 100 }))
    } catch (err) {
      setError(parseError(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void runSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  const visibleTabs = (Object.keys(available) as DictionaryTab[]).filter((key) => available[key])

  return (
    <section>
      <h2>Dictionary</h2>
      <div className="inline-form">
        {visibleTabs.map((tab) => (
          <button
            type="button"
            key={tab}
            className={tab === activeTab ? 'button-active' : ''}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <form onSubmit={runSearch} className="inline-form">
        <label>
          search
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <button type="submit" disabled={loading}>Search</button>
      </form>

      <LoadingText show={loading} />
      <ErrorBanner message={error} />

      {activeTab === 'concepts' && (
        <ul>
          {concepts.map((item) => (
            <li key={item.uid}>
              <code>{item.uid}</code> {item.pref_label} ({item.status})
            </li>
          ))}
        </ul>
      )}

      {activeTab === 'relations' && (
        <ul>
          {relations.map((item) => (
            <li key={item.uid}>
              <code>{item.uid}</code> {item.pref_label} ({item.status})
            </li>
          ))}
        </ul>
      )}

      {activeTab === 'terms' && (
        <ul>
          {terms.map((item) => (
            <li key={item.term_id}>
              {item.label} {'->'} <code>{item.concept_uid}</code> ({item.concept_pref_label})
            </li>
          ))}
        </ul>
      )}

      {activeTab === 'aliases' && (
        <ul>
          {aliases.map((item) => (
            <li key={item.old_uid}>
              <code>{item.old_uid}</code> {'->'} <code>{item.new_uid}</code>
            </li>
          ))}
        </ul>
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
        <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
        <Route path="/documents/:documentId/translate" element={<TranslatePage />} />
        <Route path="/runs" element={<RunsListPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/reviews" element={<ReviewsPage />} />
        <Route path="/dictionary" element={<DictionaryPage />} />
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
