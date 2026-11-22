import { AlertTriangle } from 'lucide-react'
import { fmtPct } from '@/lib/format'
import { VALIDATION_STYLE } from '@/lib/status'
import type { Version } from '@/lib/types'
import { ValidationBadge, VersionBadge } from '@/components/common'

/** One-line status of the version in focus. */
export function VersionSummary({ version }: { version: Version }) {
  const s = version.summary
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <span className="font-medium">v{version.version_no}</span>
      <VersionBadge status={version.status} />
      <ValidationBadge status={version.validation_status} />
      <span className="text-muted-foreground">Coverage <b className="text-foreground tabular">{fmtPct(version.coverage_pct)}</b></span>
      {s && (
        <span className="text-muted-foreground tabular">
          {s.gaps} gap{s.gaps === 1 ? '' : 's'} ({s.uncovered} uncovered, {s.understaffed} understaffed)
          {s.hard_rule_violations > 0 && <b className="ml-1 text-red-600">· {s.hard_rule_violations} rule violation(s)</b>}
        </span>
      )}
    </div>
  )
}

export function VersionAlert({ version }: { version: Version }) {
  if (!['INVALID', 'INFEASIBLE', 'SOLVER_TIMEOUT'].includes(version.validation_status)) return null
  return (
    <div role="alert" className="mb-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span><b>{VALIDATION_STYLE[version.validation_status].label}.</b> {VALIDATION_STYLE[version.validation_status].hint} See Conflicts for details.</span>
    </div>
  )
}
