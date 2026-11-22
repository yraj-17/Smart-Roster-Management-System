import type { ReactNode } from 'react'
import { CalendarPlus, Sparkles } from 'lucide-react'
import { api } from '@/lib/api'
import { usePlan } from '@/lib/plan'
import { monthLabel } from '@/lib/format'
import { VALIDATION_STYLE } from '@/lib/status'
import type { Version } from '@/lib/types'
import { useApiMutation } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { EmptyState, Loading, Spinner } from '@/components/common'

export function GenerateButton({ variant = 'default', label = 'Generate roster' }: { variant?: 'default' | 'outline'; label?: string }) {
  const { year, month, setVersionId } = usePlan()
  const gen = useApiMutation(() => api.post<Version>(`/roster-plans/${year}/${month}/generate`, { notes: null }), {
    success: (v) => `Generated v${v.version_no}: ${VALIDATION_STYLE[v.validation_status].label.toLowerCase()}, ${v.coverage_pct ?? 0}% coverage`,
    onSuccess: (v) => setVersionId(v.id),
  })
  return (
    <Button variant={variant} onClick={() => gen.mutate(undefined)} disabled={gen.isPending} data-testid="generate-roster">
      {gen.isPending ? <Spinner /> : <Sparkles />} {gen.isPending ? 'Solving…' : label}
    </Button>
  )
}

/** Renders children with the selected version, or an empty/loading state. */
export function RequireVersion({ children }: { children: (v: Version) => ReactNode }) {
  const { version, versionsLoading, year, month } = usePlan()
  if (versionsLoading) return <Loading rows={8} />
  if (!version) {
    return (
      <EmptyState
        icon={<CalendarPlus className="size-6" />}
        title={`No roster for ${monthLabel(year, month)} yet`}
        description="Generate one: the solver plans every employee's days and duties against brand calendars, coverage minimums, leave and rest rules, and explains any gap it cannot fill."
        action={<GenerateButton />}
      />
    )
  }
  return <>{children(version)}</>
}
