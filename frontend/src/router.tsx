import { Navigate, createBrowserRouter } from "react-router-dom"

import { PageError, RootError } from "@/components/ErrorScreens"
import { AppLayout } from "@/components/layout/AppLayout"
import { RequireAdmin, RequireAuth } from "@/components/RouteGuards"
import { PageLoading } from "@/components/PageLoading"
import { LoginPage } from "@/pages/LoginPage"

// Each page is its own file, downloaded the first time someone opens it, so the first visit
// (often the sign-in page) doesn't wait for the whole app.
const page = <K extends string>(load: () => Promise<Record<K, React.ComponentType>>, name: K) => ({
  lazy: async () => ({ Component: (await load())[name] }),
})

export const router = createBrowserRouter([
  {
    // an error that takes the whole app down, including in the sign-in pages
    errorElement: <RootError />,
    HydrateFallback: PageLoading,
    children: [
      { path: "/login", element: <LoginPage /> },
      {
        path: "/forgot-password",
        ...page(() => import("@/pages/PasswordResetPages"), "ForgotPasswordPage"),
      },
      {
        path: "/reset-password",
        ...page(() => import("@/pages/PasswordResetPages"), "ResetPasswordPage"),
      },
      {
        element: <RequireAuth />,
        children: [
          {
            element: <AppLayout />,
            children: [
              {
                // a page's error stays inside the layout, so the navigation still works
                errorElement: <PageError />,
                children: [
                  { index: true, ...page(() => import("@/pages/BoardPage"), "BoardPage") },
                  { path: "deals/:dealId", ...page(() => import("@/pages/DealPage"), "DealPage") },
                  {
                    path: "contacts",
                    ...page(() => import("@/pages/ContactsPage"), "ContactsPage"),
                  },
                  {
                    path: "contacts/:contactId",
                    ...page(() => import("@/pages/ContactPage"), "ContactPage"),
                  },
                  {
                    path: "companies",
                    ...page(() => import("@/pages/CompaniesPage"), "CompaniesPage"),
                  },
                  {
                    path: "companies/:companyId",
                    ...page(() => import("@/pages/CompanyPage"), "CompanyPage"),
                  },
                  {
                    path: "activities",
                    ...page(() => import("@/pages/ActivitiesPage"), "ActivitiesPage"),
                  },
                  {
                    path: "dashboard",
                    ...page(() => import("@/pages/DashboardPage"), "DashboardPage"),
                  },
                  { path: "inbox", ...page(() => import("@/pages/InboxPage"), "InboxPage") },
                  { path: "account", ...page(() => import("@/pages/AccountPage"), "AccountPage") },
                  { path: "trash", ...page(() => import("@/pages/TrashPage"), "TrashPage") },
                  {
                    element: <RequireAdmin />,
                    children: [
                      {
                        path: "settings",
                        ...page(() => import("@/pages/SettingsPage"), "SettingsPage"),
                      },
                      { path: "usage", ...page(() => import("@/pages/UsagePage"), "UsagePage") },
                    ],
                  },
                  { path: "*", element: <Navigate to="/" replace /> },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
])
