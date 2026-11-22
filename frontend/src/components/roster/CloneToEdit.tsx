import { CopyPlus } from 'lucide-react'
import { api } from '@/lib/api'
import { usePlan } from '@/lib/plan'
import type { Version } from '@/lib/types'
import { useApiMutation } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Spinner } from '@/components/common'

/** Published/superseded versions are immutable; editing means cloning into a draft. */
export function CloneToEdit({ version, onDone }: { version: Version; onDone?: () => void }) {
  const { setVersionId } = usePlan()
  const clone = useApiMutation(() => api.post<Version>(`/versions/${version.id}/clone`, { reason: 'Edit after publish' }), {
    success: (v) => `Draft v${v.version_no} created from v${version.version_no}`,
    onSuccess: (v) => { setVersionId(v.id); onDone?.() },
  })
  return (
    <Alert>
      <AlertTitle>v{version.version_no} is {version.status.toLowerCase()} and read-only</AlertTitle>
      <AlertDescription>
        <p>Published history is never changed. Clone it into a new draft to make edits.</p>
        <Button size="sm" className="mt-2" onClick={() => clone.mutate(undefined)} disabled={clone.isPending}>
          {clone.isPending ? <Spinner /> : <CopyPlus />} Clone to new draft
        </Button>
      </AlertDescription>
    </Alert>
  )
}
