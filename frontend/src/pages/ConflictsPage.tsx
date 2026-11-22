import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowUpRight, CheckCheck, ShieldAlert, ShieldCheck } from 'lucide-react'
import { api, errorMessage } from '@/lib/api'
import { fmtDate, humanize } from '@/lib/format'
import { CONFLICT_GROUPS } from '@/lib/status'
import type { Conflict, Version } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ROSTER_KEYS, useConflicts, useEmployees } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { EmptyState, ErrorState, Loading, NativeSelect, PageHeader, Pill, SeverityBadge, Spinner } from '@/components/common'
import { ConflictDetail } from '@/components/roster/GapPanel'
import { RequireVersion } from '@/components/roster/RequireVersion'
import { VersionSummary } from '@/components/roster/VersionSummary'

export function ConflictsPage() {
  return (
    <>
      <PageHeader title="Conflicts" description="Everything the validator found, separated by what it means: hard rules that block publishing, coverage gaps to resolve or accept, and soft preferences." />
      <RequireVersion>{(v) => <ConflictsBody version={v} />}</RequireVersion>
    </>
  )
}

function ConflictsBody({ version }: { version: Version }) {
  const [status, setStatus] = useState('OPEN')
  const q = useConflicts(version.id, status === 'ALL' ? {} : { status })
  const employees = useEmployees()
  const names = useMemo(() => new Map((employees.data ?? []).map((e) => [e.id, e.name])), [employees.data])
  const [open, setOpen] = useState<Conflict | null>(null)
  const [bulk, setBulk] = useState(false)

  const grouped = useMemo(() => CONFLICT_GROUPS.map((g) => ({
    ...g, items: (q.data ?? []).filter((c) => g.categories.includes(c.category)),
  })), [q.data])
  const openGaps = (q.data ?? []).filter((c) => c.category === 'COVERAGE' && c.status === 'OPEN')

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <VersionSummary version={version} />
        <div className="flex items-center gap-2">
          <NativeSelect aria-label="Status filter" className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="OPEN">Open</option>
            <option value="ACKNOWLEDGED">Acknowledged</option>
            <option value="RESOLVED">Resolved</option>
            <option value="ALL">All</option>
          </NativeSelect>
          <Button variant="outline" size="sm" disabled={!openGaps.length} onClick={() => setBulk(true)}>
            <CheckCheck /> Acknowledge open gaps ({openGaps.length})
          </Button>
        </div>
      </div>
      {q.isLoading ? <Loading rows={8} /> : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} /> : (
        <div className="grid gap-4 xl:grid-cols-3">
          {grouped.map((g) => (
            <Card key={g.key} className={cn(g.tone === 'red' && g.items.length && 'border-red-200')} data-testid={`group-${g.key}`}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {g.tone === 'red' ? <ShieldAlert className="size-4 text-red-600" /> : g.tone === 'amber' ? <ShieldAlert className="size-4 text-amber-600" /> : <ShieldCheck className="size-4 text-slate-500" />}
                  {g.title}
                  <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-xs tabular">{g.items.length}</span>
                </CardTitle>
                <CardDescription>{g.description}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {g.items.length === 0 ? (
                  <EmptyState icon={<ShieldCheck className="size-5 text-emerald-600" />} title="Nothing here" />
                ) : (
                  <ul className="max-h-[60vh] space-y-2 overflow-auto pr-1">
                    {g.items.map((c) => (
                      <ConflictItem key={c.id} c={c} name={c.employee_id ? names.get(c.employee_id) : undefined}
                        onOpen={c.category === 'COVERAGE' ? () => setOpen(c) : undefined} />
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {open && (
        <Sheet open onOpenChange={(o) => !o && setOpen(null)}>
          <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-xl">
            <SheetHeader>
              <SheetTitle>Coverage gap</SheetTitle>
              <SheetDescription>{fmtDate(open.date, { weekday: 'long', day: 'numeric', month: 'long' })}</SheetDescription>
            </SheetHeader>
            <div className="px-4 pb-6"><ConflictDetail version={version} conflict={open} onClose={() => setOpen(null)} /></div>
          </SheetContent>
        </Sheet>
      )}
      {bulk && <BulkAcknowledge gaps={openGaps} onClose={() => setBulk(false)} />}
    </div>
  )
}

function ConflictItem({ c, name, onOpen }: { c: Conflict; name?: string; onOpen?: () => void }) {
  const dayLink = c.employee_id && c.date ? `/roster?employee=${c.employee_id}&date=${c.date}` : null
  return (
    <li className="rounded-lg border bg-background p-3 text-sm" data-testid="conflict-item">
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <SeverityBadge severity={c.severity} />
        <Pill className="border-slate-200 text-slate-600">{humanize(c.type)}</Pill>
        {c.explanation?.gap_kind && (
          <Pill className={c.explanation.gap_kind === 'UNAVOIDABLE' ? 'border-red-200 bg-red-50 text-red-700' : 'border-slate-200 text-slate-600'}>
            {c.explanation.gap_kind === 'UNAVOIDABLE' ? 'unavoidable' : 'trade-off'}
          </Pill>
        )}
        {c.status !== 'OPEN' && <Pill className="border-slate-200 bg-slate-50 text-slate-500">{c.status.toLowerCase()}</Pill>}
        {c.date && <span className="ml-auto text-xs text-muted-foreground tabular">{fmtDate(c.date)}</span>}
      </div>
      <p>{c.message}</p>
      {name && !c.message.includes(name) && <p className="text-xs text-muted-foreground">{name}</p>}
      {c.status === 'ACKNOWLEDGED' && <p className="mt-1 text-xs text-muted-foreground">Accepted by {c.ack_by}: “{c.ack_reason}”</p>}
      <div className="mt-2 flex gap-2">
        {onOpen && <Button size="xs" variant="outline" onClick={onOpen}>Resolve…</Button>}
        {dayLink && <Link className="inline-flex items-center gap-0.5 text-xs font-medium text-blue-700 hover:underline" to={dayLink}>Open day <ArrowUpRight className="size-3" /></Link>}
      </div>
    </li>
  )
}

function BulkAcknowledge({ gaps, onClose }: { gaps: Conflict[]; onClose: () => void }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  const run = async () => {
    setBusy(true)
    let ok = 0
    const failed: string[] = []
    for (const g of gaps) {
      try {
        await api.post(`/conflicts/${g.id}/acknowledge`, { reason })
        ok++
      } catch (e) {
        failed.push(errorMessage(e))
      }
    }
    await Promise.all(ROSTER_KEYS.map((k) => qc.invalidateQueries({ queryKey: k })))
    setBusy(false)
    if (failed.length) toast.error(`${failed.length} could not be acknowledged`, { description: failed[0] })
    else toast.success(`${ok} gap(s) acknowledged`)
    onClose()
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Acknowledge {gaps.length} open gap(s)</DialogTitle>
          <DialogDescription>Each gap is recorded as accepted with this reason and your name. Hard rule violations cannot be acknowledged.</DialogDescription>
        </DialogHeader>
        <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="e.g. Clients informed of reduced cover on these days" data-testid="bulk-reason" />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={reason.trim().length < 5 || busy} onClick={run} data-testid="bulk-ack">{busy && <Spinner />} Acknowledge all</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
