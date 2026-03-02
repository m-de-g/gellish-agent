import { useMemo, useState } from 'react'
import type { Expression } from '../api'

type Props = {
  expressions: Expression[]
}

function escapeCsv(value: unknown): string {
  const text = String(value ?? '')
  if (text.includes('"') || text.includes(',') || text.includes('\n')) {
    return `"${text.replace(/"/g, '""')}"`
  }
  return text
}

export default function ExpressionsTable({ expressions }: Props) {
  const [search, setSearch] = useState('')
  const [relationUid, setRelationUid] = useState('')

  const relationOptions = useMemo(
    () => Array.from(new Set(expressions.map((row) => row.relation_uid))).sort(),
    [expressions],
  )

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return expressions.filter((row) => {
      if (relationUid && row.relation_uid !== relationUid) return false
      if (!needle) return true
      return [row.subject_uid, row.relation_uid, row.object_uid ?? '', row.object_literal ?? '']
        .join(' ')
        .toLowerCase()
        .includes(needle)
    })
  }, [expressions, relationUid, search])

  const onExportCsv = () => {
    const header = ['id', 'subject_uid', 'relation_uid', 'object_uid', 'object_literal', 'status', 'confidence']
    const lines = [header.join(',')]
    for (const row of filtered) {
      lines.push(
        [
          row.id,
          row.subject_uid,
          row.relation_uid,
          row.object_uid ?? '',
          row.object_literal ?? '',
          row.status,
          row.confidence ?? '',
        ]
          .map(escapeCsv)
          .join(','),
      )
    }
    const blob = new Blob([`${lines.join('\n')}\n`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'expressions.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section>
      <div className="inline-form">
        <label>
          search
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="subject/relation/object"
          />
        </label>
        <label>
          relation_uid
          <select value={relationUid} onChange={(e) => setRelationUid(e.target.value)}>
            <option value="">all</option>
            {relationOptions.map((uid) => (
              <option key={uid} value={uid}>{uid}</option>
            ))}
          </select>
        </label>
        <button type="button" onClick={onExportCsv}>Export expressions CSV</button>
      </div>

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
            {filtered.map((row) => (
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
    </section>
  )
}
