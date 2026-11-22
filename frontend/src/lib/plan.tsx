// Which month and roster version the manager is working on (shared by every page).
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Version } from './types'

interface PlanState {
  year: number
  month: number
  versionId: number | null
  version: Version | null
  versions: Version[]
  versionsLoading: boolean
  setMonth: (year: number, month: number) => void
  setVersionId: (id: number | null) => void
}

const Ctx = createContext<PlanState | null>(null)
const KEY = 'roster.plan'

function initial(): { year: number; month: number; picks: Record<string, number> } {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (saved?.year && saved?.month) return { picks: {}, ...saved }
  } catch {
    /* ignore */
  }
  // Operations plan ahead: default to next month.
  const d = new Date()
  const next = new Date(d.getFullYear(), d.getMonth() + 1, 1)
  return { year: next.getFullYear(), month: next.getMonth() + 1, picks: {} }
}

export function PlanProvider({ children }: { children: ReactNode }) {
  const init = useMemo(initial, [])
  const [year, setYear] = useState(init.year)
  const [month, setMonthState] = useState(init.month)
  const [picks, setPicks] = useState<Record<string, number>>(init.picks)

  const versionsQ = useQuery({
    queryKey: ['versions', year, month],
    queryFn: () => api.get<Version[]>(`/roster-plans/${year}/${month}/versions`),
  })
  const versions = useMemo(() => versionsQ.data ?? [], [versionsQ.data])
  const key = `${year}-${month}`

  // Default: the published version, else the newest draft that has a roster.
  const fallback = useMemo(() => {
    const pub = versions.find((v) => v.status === 'PUBLISHED')
    if (pub) return pub.id
    const drafts = versions.filter((v) => v.status === 'DRAFT' && !['INFEASIBLE', 'SOLVER_TIMEOUT'].includes(v.validation_status))
    return drafts.length ? drafts[drafts.length - 1].id : versions.length ? versions[versions.length - 1].id : null
  }, [versions])
  const picked = picks[key]
  const versionId = picked && versions.some((v) => v.id === picked) ? picked : fallback
  const version = versions.find((v) => v.id === versionId) ?? null

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ year, month, picks }))
    } catch {
      /* ignore */
    }
  }, [year, month, picks])

  const value: PlanState = {
    year, month, versionId, version, versions, versionsLoading: versionsQ.isLoading,
    setMonth: (y, m) => { setYear(y); setMonthState(m) },
    setVersionId: (id) => setPicks((p) => {
      const n = { ...p }
      if (id === null) delete n[key]
      else n[key] = id
      return n
    }),
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function usePlan() {
  const v = useContext(Ctx)
  if (!v) throw new Error('usePlan outside PlanProvider')
  return v
}
