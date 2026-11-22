import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Archive, CopyPlus, GitCompareArrows, RefreshCcw, Send } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { usePlan } from '@/lib/plan'
import { fmtDateTime, fmtPct, humanize } from '@/lib/format'
import type { RosterDiff, Version } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useApiMutation } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { EmptyState, ErrorState, Field, InlineError, Loading, NativeSelect, PageHeader, Spinner, ValidationBadge, VersionBadge } from '@/components/common'
import { GenerateButton } from '@/components/roster/RequireVersion'
import { ReoptimizeDialog } from '@/components/roster/ReoptimizeDialog'
import { DiffView } from '@/components/roster/DiffView'

export function VersionsPage() {
  const { versions, versionsLoading, versionId, setVersionId } = usePlan()
  const [reopt, setReopt] = useState<Version | null>(null)
  const [publishing, setPublishing] = useState<Version | null>(null)
  const [a, setA] = useState<number | null>(null)
  const [b, setB] = useState<number | null>(null)

  const clone = useApiMutation((v: Version) => api.post<Version>(`/versions/${v.id}/clone`, {}), {
    success: (n) => `Draft v${n.version_no} created`, onSuccess: (n) => setVersionId(n.id),
  })
  const archive = useApiMutation((v: Version) => api.post<Version>(`/versions/${v.id}/archive`), { success: (n) => `v${n.version_no} archived` })

  const ordered = [...versions].reverse()
  const withRoster = versions.filter((v) => !['INFEASIBLE', 'SOLVER_TIMEOUT'].includes(v.validation_status))
  const left = a ?? withRoster.find((v) => v.id !== versionId)?.id ?? null
  const right = b ?? versionId

  return (
    <>
      <PageHeader title="Roster versions"
        description="Every generation, re-optimisation and clone is kept as its own version. Only drafts are editable; publishing supersedes the previous published version."
        actions={<GenerateButton label="Generate new version" />} />
      {versionsLoading ? <Loading rows={5} /> : !versions.length ? (
        <EmptyState title="No versions for this month" description="Generate the first roster to get started." action={<GenerateButton />} />
      ) : (
        <div className="space-y-6">
          <div className="overflow-x-auto rounded-lg border bg-background">
            <Table data-testid="versions-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Version</TableHead><TableHead>Status</TableHead><TableHead>Validation</TableHead>
                  <TableHead className="text-right">Coverage</TableHead><TableHead className="text-right">Gaps</TableHead>
                  <TableHead>Origin</TableHead><TableHead>Created</TableHead><TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ordered.map((v) => {
                  const hasRoster = !['INFEASIBLE', 'SOLVER_TIMEOUT'].includes(v.validation_status)
                  return (
                    <TableRow key={v.id} className={cn(v.id === versionId && 'bg-blue-50/50')}>
                      <TableCell>
                        <button type="button" className="font-medium text-blue-700 hover:underline" onClick={() => setVersionId(v.id)}>v{v.version_no}</button>
                        {v.id === versionId && <span className="ml-2 text-xs text-muted-foreground">in focus</span>}
                      </TableCell>
                      <TableCell><VersionBadge status={v.status} /></TableCell>
                      <TableCell><ValidationBadge status={v.validation_status} /></TableCell>
                      <TableCell className="text-right tabular">{fmtPct(v.coverage_pct)}</TableCell>
                      <TableCell className="text-right tabular">
                        {v.summary ? <>{v.summary.gaps}{v.summary.hard_rule_violations > 0 && <span className="ml-1 text-red-600">+{v.summary.hard_rule_violations} rule</span>}</> : '—'}
                      </TableCell>
                      <TableCell className="text-sm">
                        {humanize(v.kind)}{v.parent_version_id && <span className="text-muted-foreground"> from v{versions.find((p) => p.id === v.parent_version_id)?.version_no ?? '?'}</span>}
                        {v.notes && <p className="max-w-56 truncate text-xs text-muted-foreground" title={v.notes}>{v.notes}</p>}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {fmtDateTime(v.created_at)} · {v.created_by}
                        {v.published_at && <p>Published {fmtDateTime(v.published_at)} by {v.published_by}</p>}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button size="xs" variant="outline" disabled={!hasRoster} onClick={() => setReopt(v)} title="Re-plan a date window"><RefreshCcw />Re-optimise</Button>
                          <Button size="xs" variant="outline" disabled={!hasRoster || clone.isPending} onClick={() => clone.mutate(v)}><CopyPlus />Clone</Button>
                          {v.status === 'DRAFT' && hasRoster && <Button size="xs" onClick={() => setPublishing(v)} data-testid={`publish-${v.version_no}`}><Send />Publish</Button>}
                          {v.status === 'DRAFT' && <Button size="xs" variant="ghost" onClick={() => archive.mutate(v)} title="Archive draft"><Archive /></Button>}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><GitCompareArrows className="size-4" />Compare versions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {withRoster.length < 2 ? <p className="text-sm text-muted-foreground">Create a second version (re-optimise or clone) to compare.</p> : (
                <>
                  <div className="flex flex-wrap items-end gap-3">
                    <Field label="Base" className="w-48">
                      <NativeSelect value={left ?? ''} onChange={(e) => setA(Number(e.target.value))} data-testid="compare-a">
                        {withRoster.map((v) => <option key={v.id} value={v.id}>v{v.version_no} ({v.status.toLowerCase()})</option>)}
                      </NativeSelect>
                    </Field>
                    <Field label="Compared with" className="w-48">
                      <NativeSelect value={right ?? ''} onChange={(e) => setB(Number(e.target.value))} data-testid="compare-b">
                        {withRoster.map((v) => <option key={v.id} value={v.id}>v{v.version_no} ({v.status.toLowerCase()})</option>)}
                      </NativeSelect>
                    </Field>
                  </div>
                  {left && right && left !== right ? <CompareResult a={left} b={right} /> : <p className="text-sm text-muted-foreground">Pick two different versions.</p>}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
      {reopt && <ReoptimizeDialog version={reopt} onClose={() => setReopt(null)} />}
      {publishing && <PublishDialog version={publishing} onClose={() => setPublishing(null)} />}
    </>
  )
}

function CompareResult({ a, b }: { a: number; b: number }) {
  const q = useQuery({ queryKey: ['diff', a, b], queryFn: () => api.get<RosterDiff>(`/versions/${a}/diff/${b}`) })
  if (q.isLoading) return <Loading rows={4} />
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />
  return <DiffView diff={q.data!} />
}

export function PublishDialog({ version, onClose }: { version: Version; onClose: () => void }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState<unknown>(null)
  const pub = useApiMutation(() => api.post<{ version: Version; superseded_version_id: number | null; comp_offs: { created: number[] } }>(
    `/versions/${version.id}/publish`, { reason: reason || null }), {
    silentError: true,
    onError: setError,
    success: (r) => `v${r.version.version_no} published${r.superseded_version_id ? ' (previous version superseded)' : ''}${r.comp_offs.created.length ? ` · ${r.comp_offs.created.length} comp-off credit(s) earned` : ''}`,
    onSuccess: onClose,
  })
  const code = error instanceof ApiError ? error.code : null
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Publish v{version.version_no}</DialogTitle>
          <DialogDescription>
            Publishing makes this the official roster and freezes it. A fully covered roster publishes directly; a partially covered one needs every gap resolved or acknowledged. Invalid rosters cannot be published.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm"><ValidationBadge status={version.validation_status} /> coverage {fmtPct(version.coverage_pct)}</div>
          <Field label="Note (optional)"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. December roster v1" /></Field>
          <InlineError error={error} />
          {(code === 'open_gaps' || code === 'not_publishable') && (
            <Link to="/conflicts" className="text-sm font-medium text-blue-700 hover:underline" onClick={onClose}>Review conflicts →</Link>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => { setError(null); pub.mutate(undefined) }} disabled={pub.isPending} data-testid="confirm-publish">
            {pub.isPending ? <Spinner /> : <Send />} Publish
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
