import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight, CalendarCheck2, ShieldAlert, Users } from 'lucide-react'
import { usePlan } from '@/lib/plan'
import { fmtDate, fmtPct, monthLabel, parseDate } from '@/lib/format'
import { useDashboard } from '@/hooks/queries'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { buttonVariants } from '@/components/ui/button'
import { EmptyState, ErrorState, Loading, PageHeader, Pill, Stat, ValidationBadge, VersionBadge } from '@/components/common'
import { GenerateButton } from '@/components/roster/RequireVersion'

export function DashboardPage() {
  const { year, month } = usePlan()
  const q = useDashboard(year, month)
  return (
    <>
      <PageHeader title="Dashboard" description={`Staffing and coverage for ${monthLabel(year, month)}.`} />
      {q.isLoading ? <Loading rows={8} /> : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} /> : q.data && <Body d={q.data} />}
    </>
  )
}

function Body({ d }: { d: NonNullable<ReturnType<typeof useDashboard>['data']> }) {
  const c = d.counts
  const cur = d.current
  const ruleViolations = cur ? ['INTEGRITY', 'EMPLOYEE_RULE', 'SOLVER'].reduce((n, k) => n + (cur.conflicts[k]?.OPEN ?? 0), 0) : 0
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Active employees" value={c.employees} sub={`${c.pods} pods`} />
        <Stat label="Brands" value={c.brands} sub={`${c.single_resource_brands} single-resource · ${c.multi_resource_brands} multi`} />
        <Stat label="Processes" value={c.processes} sub={`${c.brand_processes} brand-process combinations`} />
        <Stat label="Pending approvals" value={d.pending_leave_requests + d.pending_comp_off_credits}
          sub={`${d.pending_leave_requests} leave · ${d.pending_comp_off_credits} comp-off`} tone={d.pending_leave_requests ? 'amber' : undefined} />
      </div>

      {!cur ? (
        <EmptyState icon={<CalendarCheck2 className="size-6" />} title="No roster for this month"
          description="Generate a roster to see coverage, conflicts and staffing for the month." action={<GenerateButton />} />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Daily coverage</CardTitle>
                <CardDescription>Staffed headcount on required shifts ÷ required headcount, per day (overstaffing never offsets a gap).</CardDescription>
                <CardAction><Link to="/coverage" className={buttonVariants({ variant: 'ghost', size: 'sm' })}>Heatmap <ArrowRight /></Link></CardAction>
              </CardHeader>
              <CardContent>
                <div className="h-56" data-testid="coverage-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={cur.daily_coverage} margin={{ left: -18, right: 8, top: 8 }}>
                      <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="date" tickFormatter={(v) => String(parseDate(v).getDate())} tick={{ fontSize: 11 }} interval={1} />
                      <YAxis domain={[80, 100]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                      <ReferenceLine y={100} stroke="var(--chart-2)" strokeDasharray="4 4" />
                      <Tooltip
                        formatter={(v: number, _n, p) => [`${v}% (${p.payload.staffed}/${p.payload.required})`, 'Coverage']}
                        labelFormatter={(l: string) => fmtDate(l, { weekday: 'short', day: 'numeric', month: 'short' })}
                      />
                      <Bar dataKey="pct" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                        {cur.daily_coverage.map((p) => (
                          <Cell key={p.date} fill={p.pct >= 100 ? 'var(--chart-2)' : p.pct >= 95 ? 'var(--chart-3)' : 'var(--chart-4)'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Roster status</CardTitle>
                <CardDescription>Version in focus for this month.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-lg font-semibold">v{cur.version.version_no}</span>
                  <VersionBadge status={cur.version.status} />
                  <ValidationBadge status={cur.version.validation_status} />
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div><p className="text-xs text-muted-foreground">Coverage</p><p className="text-xl font-semibold tabular">{fmtPct(cur.version.coverage_pct, 2)}</p></div>
                  <div><p className="text-xs text-muted-foreground">Open gaps</p><p className="text-xl font-semibold tabular text-amber-600">{cur.conflicts.COVERAGE?.OPEN ?? 0}</p></div>
                  <div><p className="text-xs text-muted-foreground">Rule violations</p><p className={`text-xl font-semibold tabular ${ruleViolations ? 'text-red-600' : ''}`}>{ruleViolations}</p></div>
                  <div><p className="text-xs text-muted-foreground">Backup duties</p><p className="text-xl font-semibold tabular">{cur.backup_duties}</p></div>
                </div>
                <div className="flex flex-wrap gap-1.5 text-xs">
                  {Object.entries(cur.entry_status_counts).map(([k, v]) => <Pill key={k} className="border-slate-200 text-slate-600">{k.replace('_', ' ').toLowerCase()} {v}</Pill>)}
                </div>
                <div className="flex gap-2 pt-1">
                  <Link to="/roster" className={buttonVariants({ size: 'sm' })}>Open roster</Link>
                  <Link to="/conflicts" className={buttonVariants({ size: 'sm', variant: 'outline' })}>Conflicts</Link>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><ShieldAlert className="size-4 text-amber-600" />Brands at risk</CardTitle>
                <CardDescription>Shift-days below minimum staffing.</CardDescription>
              </CardHeader>
              <CardContent>
                {!cur.brands_at_risk.length ? <p className="text-sm text-emerald-700">Every brand is fully covered.</p> : (
                  <ul className="space-y-2">
                    {cur.brands_at_risk.map((b) => {
                      const max = cur.brands_at_risk[0].gap_slot_days
                      return (
                        <li key={b.brand_id} className="text-sm">
                          <div className="flex justify-between"><span>{b.brand}</span><span className="tabular text-muted-foreground">{b.gap_slot_days}</span></div>
                          <div className="mt-1 h-1.5 rounded-full bg-muted"><div className="h-1.5 rounded-full bg-amber-500" style={{ width: `${(b.gap_slot_days / max) * 100}%` }} /></div>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Conflicts by category</CardTitle>
                <CardDescription>Open and acknowledged issues in the version in focus.</CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1.5 text-sm">
                  {Object.entries(cur.conflicts).sort().map(([cat, s]) => (
                    <li key={cat} className="flex items-center justify-between">
                      <span>{cat.replace('_', ' ').toLowerCase().replace(/^\w/, (x) => x.toUpperCase())}</span>
                      <span className="tabular">{s.OPEN} open{s.ACKNOWLEDGED ? <span className="text-muted-foreground"> · {s.ACKNOWLEDGED} accepted</span> : null}</span>
                    </li>
                  ))}
                  {!Object.keys(cur.conflicts).length && <li className="text-emerald-700">No issues.</li>}
                </ul>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><Users className="size-4" />Upcoming leave</CardTitle>
                <CardDescription>Approved and requested.</CardDescription>
                <CardAction><Link to="/availability" className={buttonVariants({ variant: 'ghost', size: 'sm' })}>Manage <ArrowRight /></Link></CardAction>
              </CardHeader>
              <CardContent>
                {!d.upcoming_leaves.length ? <p className="text-sm text-muted-foreground">No upcoming leave.</p> : (
                  <ul className="space-y-1.5 text-sm">
                    {d.upcoming_leaves.slice(0, 7).map((l) => (
                      <li key={l.id} className="flex items-center justify-between gap-2">
                        <span className="truncate">{l.employee}</span>
                        <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground tabular">
                          {fmtDate(l.start_date)}–{fmtDate(l.end_date)}
                          {l.status === 'REQUESTED' && <Pill className="border-amber-200 bg-amber-50 text-amber-800">pending</Pill>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
