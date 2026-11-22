import type { ReactNode, SelectHTMLAttributes } from 'react'
import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { errorMessage } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { VALIDATION_STYLE, VERSION_STYLE, SLOT_STYLE } from '@/lib/status'
import type { SlotStatus, ValidationStatus, VersionStatus } from '@/lib/types'

export function PageHeader({ title, description, actions, children }: {
  title: string; description?: ReactNode; actions?: ReactNode; children?: ReactNode
}) {
  return (
    <div className="mb-5 flex flex-col gap-3 border-b pb-4 md:flex-row md:items-end md:justify-between">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Loading({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('size-4 animate-spin', className)} />
}

export function ErrorState({ error, onRetry, title = 'Could not load data' }: { error: unknown; onRetry?: () => void; title?: string }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-2 rounded-lg border border-red-200 bg-red-50/60 px-6 py-8 text-center">
      <AlertTriangle className="size-6 text-red-600" />
      <p className="font-medium text-red-900">{title}</p>
      <p className="max-w-lg text-sm text-red-800">{errorMessage(error)}</p>
      {onRetry && <Button size="sm" variant="outline" onClick={onRetry}><RefreshCw /> Retry</Button>}
    </div>
  )
}

export function EmptyState({ title, description, action, icon }: { title: string; description?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center">
      <div className="text-muted-foreground">{icon ?? <Inbox className="size-6" />}</div>
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function Pill({ className, children, title }: { className?: string; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cn('inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap', className)}>
      {children}
    </span>
  )
}

export function ValidationBadge({ status }: { status: ValidationStatus }) {
  const s = VALIDATION_STYLE[status]
  return <Pill className={s.badge} title={s.hint}>{s.label}</Pill>
}

export function VersionBadge({ status }: { status: VersionStatus }) {
  return <Pill className={VERSION_STYLE[status]}>{status.charAt(0) + status.slice(1).toLowerCase()}</Pill>
}

export function SlotDot({ status }: { status: SlotStatus }) {
  return <span className={cn('inline-block size-2.5 rounded-sm', SLOT_STYLE[status].dot)} />
}

export function SeverityBadge({ severity }: { severity: 'HARD' | 'SOFT' }) {
  return severity === 'HARD'
    ? <Pill className="border-red-200 bg-red-50 text-red-700">Hard</Pill>
    : <Pill className="border-slate-200 bg-slate-50 text-slate-600">Soft</Pill>
}

export function Field({ label, htmlFor, hint, children, className }: {
  label: string; htmlFor?: string; hint?: ReactNode; children: ReactNode; className?: string
}) {
  return (
    <div className={cn('grid gap-1.5', className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function NativeSelect({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'h-8 w-full rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  )
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'red' | 'amber' | 'green' }) {
  return (
    <div className="rounded-xl border bg-card px-4 py-3">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className={cn('mt-1 text-2xl font-semibold tabular',
        tone === 'red' && 'text-red-600', tone === 'amber' && 'text-amber-600', tone === 'green' && 'text-emerald-600')}>
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <div role="alert" className="flex gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{errorMessage(error)}</span>
    </div>
  )
}

export function JsonBlock({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>
  return <pre className="max-h-64 overflow-auto rounded-md bg-muted/60 p-2 text-[11px] leading-relaxed">{JSON.stringify(value, null, 2)}</pre>
}
