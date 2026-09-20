/* eslint-disable react-refresh/only-export-components -- This module intentionally owns the lazy route registry and the router export. */
import {
  createBrowserRouter,
  Link,
  Navigate,
  type RouteObject,
} from 'react-router-dom'
import { lazy, Suspense, type ReactElement } from 'react'
import { AppShell } from '../components/shell/AppShell'
import { SchedulerLayout } from '../features/scheduler/SchedulerLayout'

const DashboardPage = lazy(() => import('../features/dashboard/DashboardPage').then((module) => ({ default: module.DashboardPage })))
const StudentHubPage = lazy(() => import('../features/info-hub/StudentHubPage').then((module) => ({ default: module.StudentHubPage })))
const ImportPage = lazy(() => import('../features/scheduler/pages/ImportPage').then((module) => ({ default: module.ImportPage })))
const LecturesPage = lazy(() => import('../features/scheduler/pages/LecturesPage').then((module) => ({ default: module.LecturesPage })))
const OptimizerPage = lazy(() => import('../features/scheduler/pages/OptimizerPage').then((module) => ({ default: module.OptimizerPage })))
const ResolvePage = lazy(() => import('../features/scheduler/pages/ResolvePage').then((module) => ({ default: module.ResolvePage })))
const RulesPage = lazy(() => import('../features/scheduler/pages/RulesPage').then((module) => ({ default: module.RulesPage })))
const ExportPage = lazy(() => import('../features/scheduler/pages/ExportPage').then((module) => ({ default: module.ExportPage })))
const FoundationGalleryPage = lazy(() => import('../features/foundation/FoundationGalleryPage').then((module) => ({ default: module.FoundationGalleryPage })))

function deferred(element: ReactElement) {
  return <Suspense fallback={<div aria-label="Loading Workspace" className="routeLoading" role="status"><span /></div>}>{element}</Suspense>
}

function routeFallback(body: string, title: string) {
  return (
    <section className="routeFallback">
      <h2>{title}</h2>
      <p>{body}</p>
      <Link className="routeFallback__link" to="/">
        Return to Overview
      </Link>
    </section>
  )
}

export const appRoutes: RouteObject[] = [
  {
    element: <AppShell />,
    errorElement: (
      <AppShell>
        {routeFallback('This route could not be loaded.', 'Something went wrong')}
      </AppShell>
    ),
    children: [
      { index: true, element: deferred(<DashboardPage />) },
      { path: 'students', element: deferred(<StudentHubPage />) },
      { path: 'students/:studentId', element: deferred(<StudentHubPage />) },
      {
        path: 'schedule',
        element: <SchedulerLayout />,
        children: [
          { index: true, element: <Navigate replace to="/schedule/resolve" /> },
          { path: 'lectures', element: deferred(<LecturesPage />) },
          { path: 'import', element: deferred(<ImportPage />) },
          { path: 'rules/:section?', element: deferred(<RulesPage />) },
          { path: 'optimize', element: deferred(<OptimizerPage />) },
          { path: 'resolve', element: deferred(<ResolvePage />) },
          { path: 'export', element: deferred(<ExportPage />) },
        ],
      },
      ...(import.meta.env.DEV ? [{ path: '__foundation', element: deferred(<FoundationGalleryPage />) }] : []),
      {
        path: '*',
        element: routeFallback('The requested page does not exist.', 'Page not found'),
      },
    ],
  },
]

export const router = createBrowserRouter(appRoutes)
