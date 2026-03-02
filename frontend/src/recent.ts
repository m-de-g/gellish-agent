export type RecentStore = {
  documents: number[]
  runs: number[]
  exports: number[]
}

const KEY = 'gellish-ui-recent-v1'
const LIMIT = 10

const EMPTY: RecentStore = {
  documents: [],
  runs: [],
  exports: [],
}

function sanitize(values: unknown): number[] {
  if (!Array.isArray(values)) return []
  return values
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0)
    .slice(0, LIMIT)
}

export function loadRecent(): RecentStore {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return EMPTY
    const parsed = JSON.parse(raw) as Partial<RecentStore>
    return {
      documents: sanitize(parsed.documents),
      runs: sanitize(parsed.runs),
      exports: sanitize(parsed.exports),
    }
  } catch {
    return EMPTY
  }
}

function saveRecent(next: RecentStore): void {
  localStorage.setItem(KEY, JSON.stringify(next))
}

export function pushRecent(kind: keyof RecentStore, id: number): RecentStore {
  const prev = loadRecent()
  const next: RecentStore = {
    ...prev,
    [kind]: [id, ...prev[kind].filter((value) => value !== id)].slice(0, LIMIT),
  }
  saveRecent(next)
  return next
}
