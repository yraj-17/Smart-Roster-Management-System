import { useEffect, useState } from 'react'
import { FileUp, Plus, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import type { Holiday } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useApiMutation, useCalendars, useHolidays } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState, ErrorState, Field, InlineError, Loading, NativeSelect, PageHeader, Pill, Spinner } from '@/components/common'

const KEYS = [['master'], ['versions'], ['version'], ['roster'], ['conflicts'], ['dashboard'], ['audit']]

export function HolidaysPage() {
  const cals = useCalendars()
  const [calId, setCalId] = useState<number | null>(null)
  const [year, setYear] = useState(2026)
  useEffect(() => { if (!calId && cals.data?.length) setCalId(cals.data.find((c) => c.is_default)?.id ?? cals.data[0].id) }, [cals.data, calId])
  const hol = useHolidays(calId, year)
  const [importing, setImporting] = useState(false)
  const [newCal, setNewCal] = useState('')
  const [h, setH] = useState({ date: '', name: '', kind: 'NATIONAL' })
  const add = useApiMutation(() => api.post(`/holiday-calendars/${calId}/holidays`, h), {
    invalidate: KEYS, success: 'Holiday added — affected rosters flagged for re-check', onSuccess: () => setH({ date: '', name: '', kind: 'NATIONAL' }),
  })
  const del = useApiMutation((x: Holiday) => api.del(`/holidays/${x.id}`), { invalidate: KEYS, success: 'Holiday removed — affected rosters flagged for re-check' })
  const createCal = useApiMutation(() => api.post<{ id: number }>('/holiday-calendars', { name: newCal, region: null, is_default: false }), {
    invalidate: [['master'], ['audit']], success: 'Calendar created', onSuccess: (c) => { setCalId(c.id); setNewCal('') },
  })
  const makeDefault = useApiMutation((id: number) => {
    const c = cals.data!.find((x) => x.id === id)!
    return api.put(`/holiday-calendars/${id}`, { name: c.name, region: c.region, is_default: true })
  }, { invalidate: KEYS, success: 'Default calendar changed' })

  return (
    <>
      <PageHeader title="Public holidays" description="Brands use their calendar to decide whether a process operates; employees use theirs to decide whose holiday it is. Editing a holiday flags that month's rosters for re-validation." />
      <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="space-y-2">
          {cals.isLoading ? <Loading rows={2} /> : (cals.data ?? []).map((c) => (
            <button key={c.id} type="button" onClick={() => setCalId(c.id)}
              className={cn('flex w-full items-center justify-between rounded-lg border bg-background px-3 py-2 text-left text-sm', calId === c.id && 'border-blue-500 ring-1 ring-blue-500')}>
              <span><span className="font-medium">{c.name}</span><span className="block text-xs text-muted-foreground">{c.region}</span></span>
              {c.is_default ? <Pill className="border-blue-200 bg-blue-50 text-blue-700">default</Pill>
                : <span role="button" tabIndex={0} className="text-xs text-blue-700 hover:underline" onClick={(e) => { e.stopPropagation(); makeDefault.mutate(c.id) }}>make default</span>}
            </button>
          ))}
          <div className="flex gap-2 pt-1">
            <Input placeholder="New calendar name" value={newCal} onChange={(e) => setNewCal(e.target.value)} />
            <Button size="sm" variant="outline" disabled={!newCal || createCal.isPending} onClick={() => createCal.mutate(undefined)}><Plus /></Button>
          </div>
        </div>
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Year"><NativeSelect className="w-24" value={year} onChange={(e) => setYear(Number(e.target.value))}>{[2025, 2026, 2027].map((y) => <option key={y}>{y}</option>)}</NativeSelect></Field>
            <Field label="Date"><Input type="date" value={h.date} onChange={(e) => setH({ ...h, date: e.target.value })} /></Field>
            <Field label="Name"><Input value={h.name} onChange={(e) => setH({ ...h, name: e.target.value })} /></Field>
            <Field label="Kind"><NativeSelect className="w-32" value={h.kind} onChange={(e) => setH({ ...h, kind: e.target.value })}>{['NATIONAL', 'REGIONAL', 'OPTIONAL'].map((k) => <option key={k} value={k}>{k.toLowerCase()}</option>)}</NativeSelect></Field>
            <Button disabled={!calId || !h.date || !h.name || add.isPending} onClick={() => add.mutate(undefined)}><Plus />Add</Button>
            <Button variant="outline" disabled={!calId} onClick={() => setImporting(true)}><FileUp />Import CSV</Button>
          </div>
          {hol.isLoading ? <Loading /> : hol.isError ? <ErrorState error={hol.error} /> : !hol.data?.length ? <EmptyState title={`No holidays in ${year}`} /> : (
            <div className="overflow-x-auto rounded-lg border bg-background">
              <Table>
                <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Name</TableHead><TableHead>Kind</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
                <TableBody>
                  {hol.data.map((x) => (
                    <TableRow key={x.id}>
                      <TableCell className="tabular">{fmtDate(x.date, { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })}</TableCell>
                      <TableCell className="font-medium">{x.name}</TableCell>
                      <TableCell>{x.kind.toLowerCase()}</TableCell>
                      <TableCell className="text-right"><Button size="xs" variant="ghost" onClick={() => del.mutate(x)}><Trash2 /></Button></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      </div>
      {importing && calId && <ImportDialog calId={calId} onClose={() => setImporting(false)} />}
    </>
  )
}

function ImportDialog({ calId, onClose }: { calId: number; onClose: () => void }) {
  const [text, setText] = useState('date,name,kind\n')
  const [error, setError] = useState<unknown>(null)
  const run = useApiMutation(() => api.postText<{ created: number; updated: number }>(`/holiday-calendars/${calId}/holidays/import`, text), {
    invalidate: KEYS, silentError: true, onError: setError, success: (r) => `Imported: ${r.created} created, ${r.updated} updated`, onSuccess: onClose,
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Import holidays</DialogTitle><DialogDescription>CSV lines: <code>YYYY-MM-DD,Name,KIND</code>. Existing dates are updated. Any invalid line aborts the whole import.</DialogDescription></DialogHeader>
        <Textarea rows={8} className="font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} />
        <InlineError error={error} />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => run.mutate(undefined)} disabled={run.isPending}>{run.isPending && <Spinner />}Import</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
