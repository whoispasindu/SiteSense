import type { RouteObject } from "react-router";

import { AnonymousOnly, RequireAuth, RequirePermission } from "./auth/guards";
import { AppLayout } from "./components/layout/AppLayout";
import { AuditLogPage } from "./pages/admin/AuditLogPage";
import { HolidaysPage } from "./pages/admin/HolidaysPage";
import { VariationLimitsPage } from "./pages/admin/VariationLimitsPage";
import { ClientVariationPage, ClientVariationsPage } from "./pages/client/ClientVariationsPage";
import { CostPage } from "./pages/cost/CostPage";
import { SitesPage } from "./pages/admin/SitesPage";
import { UsersPage } from "./pages/admin/UsersPage";
import { ChangePasswordPage } from "./pages/auth/ChangePasswordPage";
import { SignInPage } from "./pages/auth/SignInPage";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { BoqImportPage } from "./pages/projects/BoqImportPage";
import { BoqPage } from "./pages/projects/BoqPage";
import { ProjectLayout } from "./pages/projects/ProjectLayout";
import { ProjectClaims } from "./pages/projects/ProjectClaims";
import { ProjectOverview } from "./pages/projects/ProjectOverview";
import { ProjectReports } from "./pages/projects/ProjectReports";
import { ProjectSchedule } from "./pages/projects/ProjectSchedule";
import { ProjectsPage } from "./pages/projects/ProjectsPage";
import { ProjectVariations } from "./pages/projects/ProjectVariations";
import { ReportDetailPage } from "./pages/reports/ReportDetailPage";
import { ReportFormPage } from "./pages/reports/ReportFormPage";
import { SiteReportsPage } from "./pages/reports/SiteReportsPage";
import { MaterialsPage } from "./pages/materials/MaterialsPage";
import { RequestDetailPage } from "./pages/materials/RequestDetailPage";
import { RequestFormPage } from "./pages/materials/RequestFormPage";
import { PurchaseOrderDetailPage } from "./pages/procurement/PurchaseOrderDetailPage";
import { PurchaseOrdersPage } from "./pages/procurement/PurchaseOrdersPage";
import { SuppliersPage } from "./pages/procurement/SuppliersPage";
import { SchedulePage } from "./pages/schedule/SchedulePage";
import { RouteErrorPage } from "./pages/RouteErrorPage";
import { VariationDetailPage } from "./pages/variations/VariationDetailPage";

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
        path: "materials",
        element: (
          <RequirePermission permission="materials:read">
            <MaterialsPage />
          </RequirePermission>
        ),
      },
      {
        path: "materials/new",
        element: (
          <RequirePermission permission="materials:request">
            <RequestFormPage />
          </RequirePermission>
        ),
      },
      {
        path: "materials/:requestId",
        element: (
          <RequirePermission permission="materials:read">
            <RequestDetailPage />
          </RequirePermission>
        ),
      },
      {
        path: "purchase-orders",
        element: (
          <RequirePermission permission="materials:read">
            <PurchaseOrdersPage />
          </RequirePermission>
        ),
      },
      {
        path: "purchase-orders/:orderId",
        element: (
          <RequirePermission permission="materials:read">
            <PurchaseOrderDetailPage />
          </RequirePermission>
        ),
      },
      {
        path: "suppliers",
        element: (
          <RequirePermission permission="suppliers:manage">
            <SuppliersPage />
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
        path: "cost",
        element: (
          <RequirePermission permission="cost:read">
            <CostPage />
          </RequirePermission>
        ),
      },
      {
        path: "variations/:variationId",
        element: (
          <RequirePermission permission="variations:manage">
            <VariationDetailPage />
          </RequirePermission>
        ),
      },
      {
        path: "client/variations",
        element: (
          <RequirePermission permission="client:portal">
            <ClientVariationsPage />
          </RequirePermission>
        ),
      },
      {
        path: "client/variations/:variationId",
        element: (
          <RequirePermission permission="client:portal">
            <ClientVariationPage />
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
            path: "claims",
            element: (
              <RequirePermission permission="cost:read">
                <ProjectClaims />
              </RequirePermission>
            ),
          },
          {
            path: "variations",
            element: (
              <RequirePermission permission="variations:manage">
                <ProjectVariations />
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
        path: "admin/holidays",
        element: (
          <RequirePermission permission="holidays:manage">
            <HolidaysPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/variation-limits",
        element: (
          <RequirePermission permission="variation_limits:manage">
            <VariationLimitsPage />
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
