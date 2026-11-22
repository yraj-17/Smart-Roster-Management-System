import { useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  CalendarDays, ChevronLeft, ChevronRight, ClipboardList, GitCompareArrows, Grid3x3, History, LayoutDashboard,
  Menu, PlaneTakeoff, ShieldAlert, Store, Sun, Users, UsersRound, Workflow, Link2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePlan } from '@/lib/plan'
import { getActor, setActor } from '@/lib/api'
import { monthLabel } from '@/lib/format'
import { VALIDATION_STYLE } from '@/lib/status'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { NativeSelect } from '@/components/common'

const NAV: { section: string; items: { to: string; label: string; icon: typeof LayoutDashboard }[] }[] = [
  { section: 'Overview', items: [{ to: '/', label: 'Dashboard', icon: LayoutDashboard }] },
  {
    section: 'Rostering', items: [
      { to: '/roster', label: 'Roster', icon: CalendarDays },
      { to: '/coverage', label: 'Coverage', icon: Grid3x3 },
      { to: '/conflicts', label: 'Conflicts', icon: ShieldAlert },
      { to: '/versions', label: 'Versions', icon: GitCompareArrows },
      { to: '/changes', label: 'Change management', icon: Workflow },
    ],
  },
  { section: 'Availability', items: [{ to: '/availability', label: 'Leave & comp-offs', icon: PlaneTakeoff }] },
  {
    section: 'Setup', items: [
      { to: '/employees', label: 'Employees', icon: Users },
      { to: '/pods', label: 'Pods', icon: UsersRound },
      { to: '/brands', label: 'Brands & processes', icon: Store },
      { to: '/assignments', label: 'Assignments', icon: Link2 },
      { to: '/holidays', label: 'Holidays', icon: Sun },
    ],
  },
  { section: 'Governance', items: [{ to: '/audit', label: 'Audit log', icon: History }] },
]

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-5 px-3 py-4" aria-label="Main">
      {NAV.map((g) => (
        <div key={g.section}>
          <p className="px-2 pb-1.5 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">{g.section}</p>
          <ul className="space-y-0.5">
            {g.items.map((it) => (
              <li key={it.to}>
                <NavLink
                  to={it.to}
                  end={it.to === '/'}
                  onClick={onNavigate}
                  className={({ isActive }) => cn(
                    'flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-slate-300 transition-colors hover:bg-white/5 hover:text-white',
                    isActive && 'bg-white/10 font-medium text-white',
                  )}
                >
                  <it.icon className="size-4 shrink-0" />
                  {it.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}

function Brand() {
  return (
    <div className="flex h-14 items-center gap-2 border-b border-white/10 px-5">
      <div className="grid size-7 place-items-center rounded-md bg-blue-500 text-white"><ClipboardList className="size-4" /></div>
      <div className="leading-tight">
        <p className="text-sm font-semibold text-white">Smart Roster</p>
        <p className="text-[11px] text-slate-400">Operations planning</p>
      </div>
    </div>
  )
}

function MonthPicker() {
  const { year, month, setMonth } = usePlan()
  const shift = (d: number) => {
    const dt = new Date(year, month - 1 + d, 1)
    setMonth(dt.getFullYear(), dt.getMonth() + 1)
  }
  return (
    <div className="flex items-center rounded-lg border bg-background">
      <Button variant="ghost" size="icon-sm" onClick={() => shift(-1)} aria-label="Previous month"><ChevronLeft /></Button>
      <span className="min-w-32 text-center text-sm font-medium tabular" data-testid="month-label">{monthLabel(year, month)}</span>
      <Button variant="ghost" size="icon-sm" onClick={() => shift(1)} aria-label="Next month"><ChevronRight /></Button>
    </div>
  )
}

function VersionPicker() {
  const { versions, versionId, setVersionId, versionsLoading } = usePlan()
  if (versionsLoading) return <span className="text-xs text-muted-foreground">Loading versions…</span>
  if (!versions.length) return <span className="text-xs text-muted-foreground">No roster yet</span>
  return (
    <NativeSelect
      aria-label="Roster version"
      data-testid="version-picker"
      className="h-8 w-auto max-w-[calc(100vw-2rem)] md:max-w-72"
      value={versionId ?? ''}
      onChange={(e) => setVersionId(Number(e.target.value))}
    >
      {[...versions].reverse().map((v) => (
        <option key={v.id} value={v.id}>
          v{v.version_no} · {v.status.toLowerCase()} · {VALIDATION_STYLE[v.validation_status].label.toLowerCase()}
        </option>
      ))}
    </NativeSelect>
  )
}

function ActorInput() {
  const [name, setName] = useState(getActor())
  return (
    <label className="hidden items-center gap-1.5 text-xs text-muted-foreground lg:flex" title="Recorded in the audit log for every change">
      Acting as
      <input
        className="h-7 w-28 rounded-md border bg-background px-2 text-xs text-foreground"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => setActor(name.trim() || 'ops.manager')}
      />
    </label>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  const monthScoped = !['/employees', '/pods', '/brands', '/assignments', '/holidays', '/audit'].includes(loc.pathname)
  return (
    <div className="min-h-screen bg-slate-50/60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 bg-slate-900 lg:block">
        <Brand />
        <Nav />
      </aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-64 bg-slate-900 p-0 text-white" showCloseButton={false}>
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Brand />
          <Nav onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex min-h-14 flex-wrap items-center gap-2 border-b bg-background/95 px-4 py-2 backdrop-blur md:gap-3 md:px-6">
          <Button variant="ghost" size="icon-sm" className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open navigation">
            <Menu />
          </Button>
          {monthScoped && <MonthPicker />}
          {monthScoped && <VersionPicker />}
          <div className="ml-auto"><ActorInput /></div>
        </header>
        <main className="mx-auto max-w-[1600px] px-4 py-5 md:px-6">{children}</main>
      </div>
    </div>
  )
}
