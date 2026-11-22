import { Navigate, createBrowserRouter } from "react-router-dom"

import { AppLayout } from "@/components/layout/AppLayout"
import { RequireAdmin, RequireAuth } from "@/components/RouteGuards"
import { AccountPage } from "@/pages/AccountPage"
import { ActivitiesPage } from "@/pages/ActivitiesPage"
import { BoardPage } from "@/pages/BoardPage"
import { CompaniesPage } from "@/pages/CompaniesPage"
import { CompanyPage } from "@/pages/CompanyPage"
import { DashboardPage } from "@/pages/DashboardPage"
import { ContactPage } from "@/pages/ContactPage"
import { ContactsPage } from "@/pages/ContactsPage"
import { DealPage } from "@/pages/DealPage"
import { InboxPage } from "@/pages/InboxPage"
import { SettingsPage } from "@/pages/SettingsPage"
import { TrashPage } from "@/pages/TrashPage"
import { UsagePage } from "@/pages/UsagePage"
import { LoginPage } from "@/pages/LoginPage"
import { ForgotPasswordPage, ResetPasswordPage } from "@/pages/PasswordResetPages"

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/forgot-password", element: <ForgotPasswordPage /> },
  { path: "/reset-password", element: <ResetPasswordPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <BoardPage /> },
          { path: "deals/:dealId", element: <DealPage /> },
          { path: "contacts", element: <ContactsPage /> },
          { path: "contacts/:contactId", element: <ContactPage /> },
          { path: "companies", element: <CompaniesPage /> },
          { path: "companies/:companyId", element: <CompanyPage /> },
          { path: "activities", element: <ActivitiesPage /> },
          { path: "dashboard", element: <DashboardPage /> },
          { path: "inbox", element: <InboxPage /> },
          { path: "account", element: <AccountPage /> },
          { path: "trash", element: <TrashPage /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: "settings", element: <SettingsPage /> },
              { path: "usage", element: <UsagePage /> },
            ],
          },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
])
