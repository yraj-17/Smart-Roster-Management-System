import { fmtDate } from '@/lib/format'
import { ENTRY_STYLE, SLOT_STYLE, SHIFT_STYLE } from '@/lib/status'
import type { EntryStatus } from '@/lib/types'
import { useDay } from '@/hooks/queries'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ErrorState, Loading, Pill } from '@/components/common'
import { cn } from '@/lib/utils'

/** Who is working on a given day, on what, and which shifts are short. */
export function DayPanel({ versionId, date, onClose }: { versionId: number; date: string; onClose: () => void }) {
  const q = useDay(versionId, date)
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{fmtDate(date, { weekday: 'long', day: 'numeric', month: 'long' })}</SheetTitle>
          <SheetDescription>Who is working and where coverage is short.</SheetDescription>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-6">
          {q.isLoading ? <Loading rows={6} /> : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} /> : q.data && (
            <>
              <section>
                <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Coverage gaps ({q.data.gaps.length})</h3>
                {q.data.gaps.length === 0 ? <p className="text-sm text-emerald-700">All required shifts are staffed.</p> : (
                  <ul className="space-y-1">
                    {q.data.gaps.map((g) => (
                      <li key={g.slot_id} className="flex items-center justify-between gap-2 rounded-md border px-3 py-1.5 text-sm">
                        <span>{g.label}</span>
                        <Pill className={SLOT_STYLE[g.status].cell}>{g.staffed}/{g.required}</Pill>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section>
                <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Working ({q.data.working.length})</h3>
                <ul className="divide-y rounded-md border">
                  {q.data.working.map((w) => (
                    <li key={w.employee_id} className="px-3 py-2 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{w.name}</span>
                        <span className={cn('rounded border px-1.5 text-[10px] font-semibold', SHIFT_STYLE[w.shift])}>{w.shift}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {w.duties.map((d) => d.label + (d.duty_type === 'BACKUP' ? ' (backup)' : '')).join(' · ')}
                      </p>
                    </li>
                  ))}
                </ul>
              </section>
              <section>
                <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Not working</h3>
                {Object.entries(q.data.off).map(([status, people]) => (
                  <div key={status} className="mb-2">
                    <p className="text-xs font-medium">{ENTRY_STYLE[status as EntryStatus]?.label ?? status} ({people.length})</p>
                    <p className="text-sm text-muted-foreground">{people.map((p) => p.name).join(', ')}</p>
                  </div>
                ))}
              </section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
