import { Navigate, createBrowserRouter } from "react-router-dom"

import { AppLayout } from "@/components/layout/AppLayout"
import { RequireAdmin, RequireAuth } from "@/components/RouteGuards"
import { BoardPage } from "@/pages/BoardPage"
import { DealPage } from "@/pages/DealPage"
import { InboxPage } from "@/pages/InboxPage"
import { LoginPage } from "@/pages/LoginPage"
import { PlaceholderPage } from "@/pages/PlaceholderPage"

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <BoardPage /> },
          { path: "deals/:dealId", element: <DealPage /> },
          { path: "contacts", element: <PlaceholderPage title="Contacts" milestone="3e" /> },
          { path: "companies", element: <PlaceholderPage title="Companies" milestone="3e" /> },
          { path: "activities", element: <PlaceholderPage title="My activities" milestone="3e" /> },
          { path: "dashboard", element: <PlaceholderPage title="Dashboard" milestone="3f" /> },
          { path: "inbox", element: <InboxPage /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: "settings", element: <PlaceholderPage title="Settings" milestone="3f" /> },
            ],
          },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
])
