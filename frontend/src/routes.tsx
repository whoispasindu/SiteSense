import type { RouteObject } from "react-router";

import { AnonymousOnly, RequireAuth, RequirePermission } from "./auth/guards";
import { AppLayout } from "./components/layout/AppLayout";
import { AuditLogPage } from "./pages/admin/AuditLogPage";
import { SitesPage } from "./pages/admin/SitesPage";
import { UsersPage } from "./pages/admin/UsersPage";
import { ChangePasswordPage } from "./pages/auth/ChangePasswordPage";
import { SignInPage } from "./pages/auth/SignInPage";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { BoqImportPage } from "./pages/projects/BoqImportPage";
import { BoqPage } from "./pages/projects/BoqPage";
import { ProjectLayout } from "./pages/projects/ProjectLayout";
import { ProjectOverview } from "./pages/projects/ProjectOverview";
import { ProjectReports } from "./pages/projects/ProjectReports";
import { ProjectSchedule } from "./pages/projects/ProjectSchedule";
import { ProjectsPage } from "./pages/projects/ProjectsPage";
import { ReportDetailPage } from "./pages/reports/ReportDetailPage";
import { ReportFormPage } from "./pages/reports/ReportFormPage";
import { SiteReportsPage } from "./pages/reports/SiteReportsPage";
import { SchedulePage } from "./pages/schedule/SchedulePage";
import { RouteErrorPage } from "./pages/RouteErrorPage";

export const routes: RouteObject[] = [
  {
    path: "/sign-in",
    element: (
      <AnonymousOnly>
        <SignInPage />
      </AnonymousOnly>
    ),
    errorElement: <RouteErrorPage />,
  },
  {
    path: "/change-password",
    element: (
      <RequireAuth>
        <ChangePasswordPage />
      </RequireAuth>
    ),
    errorElement: <RouteErrorPage />,
  },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <HomePage /> },
      {
        path: "projects",
        element: (
          <RequirePermission permission="projects:read">
            <ProjectsPage />
          </RequirePermission>
        ),
      },
      {
        path: "schedule",
        element: (
          <RequirePermission permission="schedule:read">
            <SchedulePage />
          </RequirePermission>
        ),
      },
      {
        path: "reports",
        element: (
          <RequirePermission permission="reports:read">
            <SiteReportsPage />
          </RequirePermission>
        ),
      },
      {
        path: "reports/:reportId",
        element: (
          <RequirePermission permission="reports:read">
            <ReportDetailPage />
          </RequirePermission>
        ),
      },
      {
        path: "projects/:projectId",
        element: (
          <RequirePermission permission="projects:read">
            <ProjectLayout />
          </RequirePermission>
        ),
        children: [
          { index: true, element: <ProjectOverview /> },
          { path: "boq", element: <BoqPage /> },
          {
            path: "schedule",
            element: (
              <RequirePermission permission="schedule:read">
                <ProjectSchedule />
              </RequirePermission>
            ),
          },
          {
            path: "reports",
            element: (
              <RequirePermission permission="reports:read">
                <ProjectReports />
              </RequirePermission>
            ),
          },
          {
            path: "reports/new",
            element: (
              <RequirePermission permission="reports:create">
                <ReportFormPage />
              </RequirePermission>
            ),
          },
          {
            path: "boq/import",
            element: (
              <RequirePermission permission="boq:manage">
                <BoqImportPage />
              </RequirePermission>
            ),
          },
        ],
      },
      {
        path: "admin/users",
        element: (
          <RequirePermission permission="users:manage">
            <UsersPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/sites",
        element: (
          <RequirePermission permission="sites:manage">
            <SitesPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/audit",
        element: (
          <RequirePermission permission="audit:read">
            <AuditLogPage />
          </RequirePermission>
        ),
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
