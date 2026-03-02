import { useMemo, useState } from 'react'
import type { SentenceIR } from '../api'

type Props = {
  sentenceIrs: SentenceIR[]
  onDownloadJson: () => void
}

type ValidFilter = 'all' | 'valid' | 'invalid'

function extractSentenceText(ir: SentenceIR): string {
  const direct = ir.ir_json?.sentence_text
  if (typeof direct === 'string') return direct
  const fallback = ir.ir_json?.text
  if (typeof fallback === 'string') return fallback
  return ''
}

export default function SentenceIrTable({ sentenceIrs, onDownloadJson }: Props) {
  const [validFilter, setValidFilter] = useState<ValidFilter>('all')
  const [search, setSearch] = useState('')
  const [openRows, setOpenRows] = useState<Record<number, boolean>>({})

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return sentenceIrs.filter((row) => {
      if (validFilter === 'valid' && !row.is_valid) return false
      if (validFilter === 'invalid' && row.is_valid) return false
      if (!needle) return true

      const sentenceText = extractSentenceText(row).toLowerCase()
      if (sentenceText.includes(needle)) return true
      return JSON.stringify(row.ir_json).toLowerCase().includes(needle)
    })
  }, [sentenceIrs, search, validFilter])

  const toggleOpen = (id: number) => {
    setOpenRows((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  return (
    <section>
      <div className="inline-form">
        <label>
          validity
          <select value={validFilter} onChange={(e) => setValidFilter(e.target.value as ValidFilter)}>
            <option value="all">all</option>
            <option value="invalid">only invalid</option>
            <option value="valid">only valid</option>
          </select>
        </label>
        <label>
          search
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="sentence_text or JSON"
          />
        </label>
        <button type="button" onClick={onDownloadJson}>Download IR JSON</button>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>sentence_id</th>
              <th>is_valid</th>
              <th>created_at</th>
              <th>error_count</th>
              <th>details</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => {
              const isOpen = Boolean(openRows[row.id])
              return (
                <tr key={row.id}>
                  <td>{row.sentence_id}</td>
                  <td>{String(row.is_valid)}</td>
                  <td>{row.created_at}</td>
                  <td>{row.errors_json?.length ?? 0}</td>
                  <td>
                    <button type="button" onClick={() => toggleOpen(row.id)}>{isOpen ? 'Hide' : 'Show'}</button>
                    {isOpen && (
                      <div className="panel">
                        <strong>ir_json</strong>
                        <pre className="json-box">{JSON.stringify(row.ir_json, null, 2)}</pre>
                        <strong>errors_json</strong>
                        <pre className="json-box">{JSON.stringify(row.errors_json ?? [], null, 2)}</pre>
                      </div>
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
