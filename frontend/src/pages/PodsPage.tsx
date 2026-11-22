import { useState } from 'react'
import { Crown, Pencil, Plus } from 'lucide-react'
import { api } from '@/lib/api'
import type { Pod } from '@/lib/types'
import { useApiMutation, useEmployees, usePods } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState, ErrorState, Field, InlineError, Loading, NativeSelect, PageHeader, Spinner } from '@/components/common'

export function PodsPage() {
  const pods = usePods()
  const employees = useEmployees()
  const [editing, setEditing] = useState<Pod | 'new' | null>(null)
  return (
    <>
      <PageHeader title="Pods" description="Operational pods and their leads. Use the Roster page's Pod scope to see each pod's schedule and coverage."
        actions={<Button onClick={() => setEditing('new')}><Plus />Add pod</Button>} />
      {pods.isLoading ? <Loading /> : pods.isError ? <ErrorState error={pods.error} onRetry={pods.refetch} /> : !pods.data?.length ? <EmptyState title="No pods" /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {pods.data.map((p) => {
            const members = (employees.data ?? []).filter((e) => e.pod_id === p.id && e.active)
            const lead = employees.data?.find((e) => e.id === p.lead_employee_id)
            return (
              <Card key={p.id} className={p.active ? '' : 'opacity-60'}>
                <CardHeader>
                  <CardTitle>{p.name}</CardTitle>
                  <CardDescription className="flex items-center gap-1"><Crown className="size-3.5 text-amber-500" />{lead?.name ?? 'No lead assigned'}</CardDescription>
                  <CardAction><Button size="xs" variant="ghost" onClick={() => setEditing(p)}><Pencil /></Button></CardAction>
                </CardHeader>
                <CardContent>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">{members.length} members</p>
                  <ul className="space-y-0.5 text-sm">{members.map((m) => <li key={m.id}>{m.name} <span className="text-xs text-muted-foreground">{m.code}</span></li>)}</ul>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
      {editing && <PodDialog pod={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </>
  )
}

function PodDialog({ pod, onClose }: { pod: Pod | null; onClose: () => void }) {
  const employees = useEmployees()
  const [name, setName] = useState(pod?.name ?? '')
  const [lead, setLead] = useState<number | null>(pod?.lead_employee_id ?? null)
  const [active, setActive] = useState(pod?.active ?? true)
  const [error, setError] = useState<unknown>(null)
  const save = useApiMutation(() => {
    const body = { name, lead_employee_id: lead, active }
    return pod ? api.put(`/pods/${pod.id}`, body) : api.post('/pods', body)
  }, { invalidate: [['master'], ['audit']], silentError: true, onError: setError, success: 'Pod saved', onSuccess: onClose })
  const members = (employees.data ?? []).filter((e) => pod && e.pod_id === pod.id)
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{pod ? `Edit ${pod.name}` : 'Add pod'}</DialogTitle></DialogHeader>
        <div className="grid gap-3">
          <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Pod lead" hint={pod ? 'Must be a member of the pod.' : 'Add members first, then choose a lead.'}>
            <NativeSelect value={lead ?? ''} onChange={(e) => setLead(e.target.value ? Number(e.target.value) : null)} disabled={!pod}>
              <option value="">No lead</option>{members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </NativeSelect>
          </Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />Active</label>
          <InlineError error={error} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!name || save.isPending}>{save.isPending && <Spinner />}Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
