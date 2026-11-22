import { Fragment, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { fmtDateTime, humanize } from '@/lib/format'
import { useAudit } from '@/hooks/queries'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { EmptyState, ErrorState, JsonBlock, Loading, NativeSelect, PageHeader, Pill } from '@/components/common'

const ENTITIES = ['roster_version', 'roster_entry', 'roster_conflict', 'leave', 'unavailability', 'comp_off_credit', 'comp_off_request',
  'employee', 'assignment', 'brand', 'brand_process', 'brand_process_shift', 'coverage_requirement', 'public_holiday', 'holiday_calendar', 'pod', 'process', 'shift']

export function AuditPage() {
  const [entity, setEntity] = useState('')
  const [versionId, setVersionId] = useState('')
  const [limit, setLimit] = useState(100)
  const q = useAudit({ entity_type: entity || undefined, version_id: versionId ? Number(versionId) : undefined, limit })
  const [open, setOpen] = useState<number | null>(null)
  return (
    <>
      <PageHeader title="Audit log" description="Every change: who made it (the “Acting as” name), what it was before and after, and why." />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <NativeSelect className="w-52" value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Entity type">
          <option value="">All entities</option>{ENTITIES.map((e) => <option key={e} value={e}>{humanize(e)}</option>)}
        </NativeSelect>
        <Input className="w-36" type="number" placeholder="Version id" value={versionId} onChange={(e) => setVersionId(e.target.value)} />
        <NativeSelect className="w-28" value={limit} onChange={(e) => setLimit(Number(e.target.value))} aria-label="Limit">
          {[50, 100, 250, 500].map((n) => <option key={n} value={n}>Last {n}</option>)}
        </NativeSelect>
      </div>
      {q.isLoading ? <Loading rows={10} /> : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} /> : !q.data?.length ? <EmptyState title="No audit entries" /> : (
        <div className="overflow-x-auto rounded-lg border bg-background">
          <Table data-testid="audit-table">
            <TableHeader><TableRow><TableHead className="w-6" /><TableHead>When</TableHead><TableHead>Actor</TableHead><TableHead>Action</TableHead><TableHead>Entity</TableHead><TableHead>Reason</TableHead></TableRow></TableHeader>
            <TableBody>
              {q.data.map((a) => (
                <Fragment key={a.id}>
                  <TableRow className="cursor-pointer" onClick={() => setOpen(open === a.id ? null : a.id)}>
                    <TableCell>{open === a.id ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</TableCell>
                    <TableCell className="text-xs whitespace-nowrap tabular">{fmtDateTime(a.created_at)}</TableCell>
                    <TableCell className="text-sm">{a.actor}</TableCell>
                    <TableCell><Pill className="border-slate-200 bg-slate-50 text-slate-700">{humanize(a.action)}</Pill></TableCell>
                    <TableCell className="text-sm">{humanize(a.entity_type)} #{a.entity_id}{a.version_id && a.entity_type !== 'roster_version' ? <span className="text-xs text-muted-foreground"> · version {a.version_id}</span> : null}</TableCell>
                    <TableCell className="max-w-72 truncate text-sm text-muted-foreground">{a.reason}</TableCell>
                  </TableRow>
                  {open === a.id && (
                    <TableRow>
                      <TableCell />
                      <TableCell colSpan={5}>
                        <div className="grid gap-3 py-1 md:grid-cols-2">
                          <div><p className="mb-1 text-xs font-medium text-muted-foreground">Before</p><JsonBlock value={a.before} /></div>
                          <div><p className="mb-1 text-xs font-medium text-muted-foreground">After</p><JsonBlock value={a.after} /></div>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  )
}
