import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, MessageSquareWarning, UserCheck, UserX, Wand2 } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { ACTION_LABEL, SLOT_STYLE } from '@/lib/status'
import type { Conflict, Suggestion, Version } from '@/lib/types'
import { useApiMutation, useConflicts } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { EmptyState, ErrorState, Loading, Pill, Spinner } from '@/components/common'
import { cn } from '@/lib/utils'

/** Explains one coverage gap and offers ranked, server-computed resolutions. */
export function GapPanel({ version, slotId, date, label, onClose }: {
  version: Version; slotId: number; date: string; label: string; onClose: () => void
}) {
  const q = useConflicts(version.id, { category: 'COVERAGE', day: date })
  const conflict = q.data?.find((c) => c.brand_process_shift_id === slotId) ?? null
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-xl" data-testid="gap-panel">
        <SheetHeader>
          <SheetTitle>{label}</SheetTitle>
          <SheetDescription>{fmtDate(date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6">
          {q.isLoading ? <Loading rows={5} /> : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} /> : conflict
            ? <ConflictDetail version={version} conflict={conflict} onClose={onClose} />
            : <EmptyState icon={<CheckCircle2 className="size-6 text-emerald-600" />} title="This shift is covered"
              description="No open coverage issue exists for this shift on this day." />}
        </div>
      </SheetContent>
    </Sheet>
  )
}

export function ConflictDetail({ version, conflict, onClose }: { version: Version; conflict: Conflict; onClose?: () => void }) {
  const ex = conflict.explanation ?? {}
  const editable = version.status === 'DRAFT'
  const open = conflict.status === 'OPEN'
  const sugg = useQuery({
    queryKey: ['suggestions', conflict.id, conflict.status],
    queryFn: () => api.get<Suggestion[]>(`/conflicts/${conflict.id}/suggestions`),
    enabled: open || conflict.status === 'ACKNOWLEDGED',
  })
  const [reason, setReason] = useState('')
  const apply = useApiMutation(
    (s: Suggestion) => api.post<{ conflict: Conflict }>(`/conflicts/${conflict.id}/apply-suggestion`, { employee_id: s.employee_id, action: s.action }),
    {
      success: (r, s) => r.conflict.status === 'RESOLVED' ? `Gap resolved — ${s.name} assigned` : `${s.name} assigned; gap reduced`,
      onSuccess: (r) => { if (r.conflict.status === 'RESOLVED') onClose?.() },
    },
  )
  const ack = useApiMutation(() => api.post(`/conflicts/${conflict.id}/acknowledge`, { reason }), {
    success: 'Gap acknowledged', onSuccess: () => onClose?.(),
  })
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Pill className={conflict.type === 'UNCOVERED_SHIFT' ? SLOT_STYLE.UNCOVERED.cell : SLOT_STYLE.UNDERSTAFFED.cell}>
            {conflict.type === 'UNCOVERED_SHIFT' ? 'Uncovered' : 'Understaffed'}
          </Pill>
          {ex.gap_kind && (
            <Pill className={ex.gap_kind === 'UNAVOIDABLE' ? 'border-red-200 bg-red-50 text-red-700' : 'border-slate-200 bg-slate-50 text-slate-700'}
              title={ex.gap_kind === 'UNAVOIDABLE' ? 'Fewer eligible people can work this day than required' : 'Someone could cover, at the cost of rest, load or another shift'}>
              {ex.gap_kind === 'UNAVOIDABLE' ? 'Unavoidable with current staff' : 'Trade-off'}
            </Pill>
          )}
          <Pill className="border-slate-200 text-slate-600">{conflict.status.toLowerCase()}</Pill>
          {typeof ex.required === 'number' && <span className="text-sm text-muted-foreground tabular">{ex.staffed}/{ex.required} staffed</span>}
        </div>
        <p className="text-sm">{conflict.message}</p>
        {conflict.status === 'ACKNOWLEDGED' && (
          <p className="rounded-md bg-muted px-3 py-2 text-xs">Acknowledged by {conflict.ack_by}: “{conflict.ack_reason}”</p>
        )}
      </div>

      {!!ex.people?.length && (
        <section>
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Why eligible staff are not covering</h3>
          <ul className="divide-y rounded-md border">
            {ex.people.map((p) => (
              <li key={p.employee_id} className="flex items-start gap-2 px-3 py-2 text-sm">
                {p.can_work ? <UserCheck className="mt-0.5 size-4 text-slate-500" /> : <UserX className="mt-0.5 size-4 text-red-500" />}
                <div className="flex-1">
                  <p className="font-medium">{p.name} <span className="text-xs font-normal text-muted-foreground">({p.role.toLowerCase()})</span></p>
                  <p className="text-muted-foreground">{p.reason}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {conflict.status !== 'RESOLVED' && (
        <section>
          <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            <Wand2 className="size-3.5" />Suggested replacements
          </h3>
          {sugg.isLoading ? <Loading rows={2} /> : sugg.isError ? <ErrorState error={sugg.error} /> : !sugg.data?.length ? (
            <p className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">
              No eligible employee can take this shift. Add a trained backup (Assignments) or acknowledge the gap.
            </p>
          ) : (
            <ul className="space-y-2" data-testid="suggestions">
              {sugg.data.map((s, i) => (
                <li key={`${s.employee_id}-${s.action}`} className={cn('rounded-lg border p-3', i === 0 && 'border-blue-300 bg-blue-50/40')}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium">{s.name} <span className="font-normal text-muted-foreground">· {s.role.toLowerCase()}</span></p>
                      <p className="text-xs font-medium text-blue-700">{ACTION_LABEL[s.action] ?? s.action}</p>
                    </div>
                    <Button size="sm" disabled={!editable || apply.isPending} onClick={() => apply.mutate(s)} data-testid="apply-suggestion">
                      {apply.isPending && apply.variables === s ? <Spinner /> : null} Apply
                    </Button>
                  </div>
                  <ul className="mt-1.5 space-y-0.5 text-xs text-muted-foreground">
                    {s.reasons.map((r) => <li key={r}>• {r}</li>)}
                    {s.impact.map((r) => <li key={r} className="text-amber-700">⚠ {r}</li>)}
                  </ul>
                </li>
              ))}
            </ul>
          )}
          {!editable && <p className="mt-2 text-xs text-muted-foreground">This version is {version.status.toLowerCase()}; clone it to apply changes.</p>}
        </section>
      )}

      {open && (
        <section className="rounded-lg border p-3">
          <h3 className="mb-1 flex items-center gap-1.5 text-sm font-medium"><MessageSquareWarning className="size-4" />Accept this gap</h3>
          <p className="mb-2 text-xs text-muted-foreground">Acknowledging records who accepted reduced cover and why. Required before publishing a partially covered roster.</p>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Client informed; low volume expected" rows={2} />
          <Button size="sm" variant="outline" className="mt-2" disabled={reason.trim().length < 5 || ack.isPending} onClick={() => ack.mutate(undefined)}>
            {ack.isPending && <Spinner />} Acknowledge
          </Button>
        </section>
      )}
    </div>
  )
}
