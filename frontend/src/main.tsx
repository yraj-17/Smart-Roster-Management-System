import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { PlanProvider } from '@/lib/plan'
import { ApiError } from '@/lib/api'
import { AppShell } from '@/components/layout/AppShell'
import { EmptyState, Loading } from '@/components/common'
import './index.css'

// Route-level code splitting: each screen loads on first visit.
const DashboardPage = lazy(() => import('@/pages/DashboardPage').then((x) => ({ default: x.DashboardPage })))
const RosterPage = lazy(() => import('@/pages/RosterPage').then((x) => ({ default: x.RosterPage })))
const CoveragePage = lazy(() => import('@/pages/CoveragePage').then((x) => ({ default: x.CoveragePage })))
const ConflictsPage = lazy(() => import('@/pages/ConflictsPage').then((x) => ({ default: x.ConflictsPage })))
const VersionsPage = lazy(() => import('@/pages/VersionsPage').then((x) => ({ default: x.VersionsPage })))
const ChangesPage = lazy(() => import('@/pages/ChangesPage').then((x) => ({ default: x.ChangesPage })))
const AvailabilityPage = lazy(() => import('@/pages/AvailabilityPage').then((x) => ({ default: x.AvailabilityPage })))
const EmployeesPage = lazy(() => import('@/pages/EmployeesPage').then((x) => ({ default: x.EmployeesPage })))
const PodsPage = lazy(() => import('@/pages/PodsPage').then((x) => ({ default: x.PodsPage })))
const BrandsPage = lazy(() => import('@/pages/BrandsPage').then((x) => ({ default: x.BrandsPage })))
const AssignmentsPage = lazy(() => import('@/pages/AssignmentsPage').then((x) => ({ default: x.AssignmentsPage })))
const HolidaysPage = lazy(() => import('@/pages/HolidaysPage').then((x) => ({ default: x.HolidaysPage })))
const AuditPage = lazy(() => import('@/pages/AuditPage').then((x) => ({ default: x.AuditPage })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // Do not hammer the server on 4xx (validation / not found); retry once on network/5xx.
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <BrowserRouter>
          <PlanProvider>
            <AppShell>
              <Suspense fallback={<Loading rows={8} />}>
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/roster" element={<RosterPage />} />
                <Route path="/coverage" element={<CoveragePage />} />
                <Route path="/conflicts" element={<ConflictsPage />} />
                <Route path="/versions" element={<VersionsPage />} />
                <Route path="/changes" element={<ChangesPage />} />
                <Route path="/availability" element={<AvailabilityPage />} />
                <Route path="/employees" element={<EmployeesPage />} />
                <Route path="/pods" element={<PodsPage />} />
                <Route path="/brands" element={<BrandsPage />} />
                <Route path="/assignments" element={<AssignmentsPage />} />
                <Route path="/holidays" element={<HolidaysPage />} />
                <Route path="/audit" element={<AuditPage />} />
                <Route path="*" element={<EmptyState title="Page not found" />} />
              </Routes>
              </Suspense>
            </AppShell>
          </PlanProvider>
        </BrowserRouter>
        <Toaster richColors position="top-right" />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
