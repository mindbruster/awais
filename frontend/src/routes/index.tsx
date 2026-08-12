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
import { InvoicesPage } from "@/pages/InvoicesPage";
import { InvoiceDetailPage } from "@/pages/InvoiceDetailPage";
import { CustomerDetailPage } from "@/pages/CustomerDetailPage";
import { StockMovementsPage } from "@/pages/StockMovementsPage";
import { ReportsPage } from "@/pages/ReportsPage";
import { DepartmentsPage } from "@/pages/settings/DepartmentsPage";
import { ItemsPage } from "@/pages/settings/ItemsPage";
import { AttributeOptionsPage } from "@/pages/settings/AttributeOptionsPage";
import { LocationsPage } from "@/pages/settings/LocationsPage";
import { BanksPage } from "@/pages/settings/BanksPage";
import { DesignsPage } from "@/pages/designs/DesignsPage";
import { DesignDetailPage } from "@/pages/designs/DesignDetailPage";
import { ChartOfAccountsPage } from "@/pages/ledger/ChartOfAccountsPage";
import { StatementPage } from "@/pages/ledger/StatementPage";
import { JournalPage } from "@/pages/ledger/JournalPage";
import { PositionPage } from "@/pages/ledger/PositionPage";
import { InsightsPage } from "@/pages/InsightsPage";
import { StockFormPage } from "@/pages/designs/StockFormPage";
import { OldGoldPage } from "@/pages/purchasing/OldGoldPage";
import { StonePurchasePage } from "@/pages/purchasing/StonePurchasePage";
import { StoneStockPage } from "@/pages/purchasing/StoneStockPage";

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
          { path: "/invoices", element: <InvoicesPage /> },
          { path: "/invoices/:id", element: <InvoiceDetailPage /> },
          { path: "/reports", element: <ReportsPage /> },
          { path: "/gold-rates", element: <GoldRatesPage /> },
          { path: "/stones", element: <StonesPage /> },
          { path: "/settings/departments", element: <DepartmentsPage /> },
          { path: "/settings/items", element: <ItemsPage /> },
          { path: "/settings/stone-attributes", element: <AttributeOptionsPage /> },
          { path: "/settings/locations", element: <LocationsPage /> },
          { path: "/settings/banks", element: <BanksPage /> },
          { path: "/designs", element: <DesignsPage /> },
          { path: "/designs/:id", element: <DesignDetailPage /> },
          { path: "/designs/:id/stock", element: <StockFormPage /> },
          { path: "/purchasing/old-gold", element: <OldGoldPage /> },
          { path: "/purchasing/stones", element: <StonePurchasePage /> },
          { path: "/purchasing/stone-stock", element: <StoneStockPage /> },
          { path: "/ledger/position", element: <PositionPage /> },
          { path: "/ledger/statement", element: <StatementPage /> },
          { path: "/ledger/journal", element: <JournalPage /> },
          { path: "/ledger/accounts", element: <ChartOfAccountsPage /> },
          { path: "/insights", element: <InsightsPage /> },
        ],
      },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
