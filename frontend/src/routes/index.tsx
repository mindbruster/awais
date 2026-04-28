import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "@/store/auth";
import { DashboardLayout } from "@/components/DashboardLayout";
import { LoginPage } from "@/pages/LoginPage";
import { DashboardHome } from "@/pages/DashboardHome";
import { ProductsPage } from "@/pages/ProductsPage";
import { ProductDetailPage } from "@/pages/ProductDetailPage";
import { GoldRatesPage } from "@/pages/GoldRatesPage";
import { StonesPage } from "@/pages/StonesPage";
import { CustomersPage } from "@/pages/CustomersPage";
import { InventoryPage } from "@/pages/InventoryPage";
import { VendorsPage } from "@/pages/VendorsPage";
import { ManufacturingPage } from "@/pages/ManufacturingPage";
import { ManufacturingJobPage } from "@/pages/ManufacturingJobPage";
import { InvoicesPage } from "@/pages/InvoicesPage";
import { InvoiceDetailPage } from "@/pages/InvoiceDetailPage";
import { CustomerDetailPage } from "@/pages/CustomerDetailPage";
import { StockMovementsPage } from "@/pages/StockMovementsPage";
import { ReportsPage } from "@/pages/ReportsPage";

function ProtectedRoute() {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return <Outlet />;
}

function PublicRoute() {
  const token = useAuthStore((s) => s.token);
  if (token) return <Navigate to="/" replace />;
  return <Outlet />;
}

export const router = createBrowserRouter([
  {
    element: <PublicRoute />,
    children: [{ path: "/login", element: <LoginPage /> }],
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <DashboardLayout />,
        children: [
          { path: "/", element: <DashboardHome /> },
          { path: "/products", element: <ProductsPage /> },
          { path: "/products/:id", element: <ProductDetailPage /> },
          { path: "/customers", element: <CustomersPage /> },
          { path: "/customers/:id", element: <CustomerDetailPage /> },
          { path: "/inventory", element: <InventoryPage /> },
          { path: "/stock-movements", element: <StockMovementsPage /> },
          { path: "/vendors", element: <VendorsPage /> },
          { path: "/manufacturing", element: <ManufacturingPage /> },
          { path: "/manufacturing/:id", element: <ManufacturingJobPage /> },
          { path: "/invoices", element: <InvoicesPage /> },
          { path: "/invoices/:id", element: <InvoiceDetailPage /> },
          { path: "/reports", element: <ReportsPage /> },
          { path: "/gold-rates", element: <GoldRatesPage /> },
          { path: "/stones", element: <StonesPage /> },
        ],
      },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
