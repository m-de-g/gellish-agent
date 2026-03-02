import { useMemo, useState } from 'react'
import type { ProvisionalsResponse } from '../api'

type Props = {
  provisionals: ProvisionalsResponse | null
  onSuggestMapping: (mappingJson: string) => void
}

type SortBy = 'uid' | 'count'

function slugBase(uid: string): string {
  const tail = uid.split(':').pop() ?? uid
  const base = tail.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return base || 'concept'
}

function hashShort(text: string): string {
  let hash = 0
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) >>> 0
  }
  return hash.toString(16).slice(0, 8)
}

function titleizeSlug(base: string): string {
  return base
    .split('-')
    .filter(Boolean)
    .map((token) => token[0].toUpperCase() + token.slice(1))
    .join(' ')
}

export default function ProvisionalsTable({ provisionals, onSuggestMapping }: Props) {
  const [sortBy, setSortBy] = useState<SortBy>('count')
  const [descending, setDescending] = useState(true)

  const rows = useMemo(() => {
    const items = (provisionals?.provisional_uids ?? []).map((uid) => ({
      uid,
      count: provisionals?.counts?.[uid] ?? 0,
    }))

    items.sort((a, b) => {
      if (sortBy === 'count') {
        return descending ? b.count - a.count : a.count - b.count
      }
      return descending ? b.uid.localeCompare(a.uid) : a.uid.localeCompare(b.uid)
    })
    return items
  }, [descending, provisionals, sortBy])

  const suggest = () => {
    const mapping: Record<string, { new_uid: string; pref_label: string; definition: null }> = {}
    for (const uid of provisionals?.provisional_uids ?? []) {
      const base = slugBase(uid)
      mapping[uid] = {
        new_uid: `concept:${base}-${hashShort(uid)}`,
        pref_label: titleizeSlug(base),
        definition: null,
      }
    }
    onSuggestMapping(JSON.stringify(mapping, null, 2))
  }

  return (
    <section>
      <div className="inline-form">
        <label>
          sort
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortBy)}>
            <option value="count">count</option>
            <option value="uid">uid</option>
          </select>
        </label>
        <label className="checkbox-row">
          <input type="checkbox" checked={descending} onChange={(e) => setDescending(e.target.checked)} />
          descending
        </label>
        <button type="button" onClick={suggest}>Suggest mapping JSON</button>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>uid</th>
              <th>count</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.uid}>
                <td>{row.uid}</td>
                <td>{row.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
