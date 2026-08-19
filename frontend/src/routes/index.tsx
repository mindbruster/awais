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
import { AssistantPage } from "@/pages/AssistantPage";
import { ItemsPage } from "@/pages/settings/ItemsPage";
import { AttributeOptionsPage } from "@/pages/settings/AttributeOptionsPage";
import { LocationsPage } from "@/pages/settings/LocationsPage";
import { BanksPage } from "@/pages/settings/BanksPage";
import { DesignsPage } from "@/pages/designs/DesignsPage";
import { DesignDetailPage } from "@/pages/designs/DesignDetailPage";
import { ChartOfAccountsPage } from "@/pages/ledger/ChartOfAccountsPage";
import { StatementPage } from "@/pages/ledger/StatementPage";
import { TradeAccountPage } from "@/pages/ledger/TradeAccountPage";
import { JournalPage } from "@/pages/ledger/JournalPage";
import { PositionPage } from "@/pages/ledger/PositionPage";
import { InsightsPage } from "@/pages/InsightsPage";
import { StockFormPage } from "@/pages/designs/StockFormPage";
import { BranchesPage } from "@/pages/settings/BranchesPage";
import { TransfersPage } from "@/pages/branches/TransfersPage";
import { OrdersPage } from "@/pages/orders/OrdersPage";
import { OrderDetailPage } from "@/pages/orders/OrderDetailPage";
import { MessagesPage } from "@/pages/MessagesPage";
import { ApprovalsPage } from "@/pages/ApprovalsPage";
import { OldGoldPage } from "@/pages/purchasing/OldGoldPage";
import { GoldPurchasePage, SilverPurchasePage } from "@/pages/purchasing/GoldPurchasePage";
import { SuppliersPage } from "@/pages/purchasing/SuppliersPage";
import { CashBookPage } from "@/pages/cash/CashBookPage";
import { StockPage } from "@/pages/StockPage";
import { LiveRatesPage } from "@/pages/LiveRatesPage";
import { AuditLogPage } from "@/pages/settings/AuditLogPage";
import { VendorDetailPage } from "@/pages/VendorDetailPage";
import { SupplierDetailPage } from "@/pages/purchasing/SupplierDetailPage";
import { GalleryPage } from "@/pages/GalleryPage";
import { SellersPage } from "@/pages/sales/SellersPage";
import { SellerDetailPage } from "@/pages/sales/SellerDetailPage";
import { ProfitSplitPage } from "@/pages/reports/ProfitSplitPage";
import { StonePurchasePage } from "@/pages/purchasing/StonePurchasePage";
import { StoneStockPage } from "@/pages/purchasing/StoneStockPage";
import { MaterialOutsidePage } from "@/pages/workshop/MaterialOutsidePage";
import { BillsPage } from "@/pages/purchasing/BillsPage";
import { ReconciliationPage } from "@/pages/reconciliation/ReconciliationPage";
import { OverviewPage } from "@/pages/reports/OverviewPage";
import { ModulesPage } from "@/pages/settings/ModulesPage";
import { OpeningPage } from "@/pages/settings/OpeningPage";
import { UsersPage } from "@/pages/settings/UsersPage";

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
          { path: "/settings/items", element: <ItemsPage /> },
          { path: "/settings/stone-attributes", element: <AttributeOptionsPage /> },
          { path: "/settings/locations", element: <LocationsPage /> },
          { path: "/settings/banks", element: <BanksPage /> },
          { path: "/designs", element: <DesignsPage /> },
          { path: "/designs/:id", element: <DesignDetailPage /> },
          { path: "/designs/:id/stock", element: <StockFormPage /> },
          { path: "/transfers", element: <TransfersPage /> },
          { path: "/orders", element: <OrdersPage /> },
          { path: "/orders/:id", element: <OrderDetailPage /> },
          { path: "/messages", element: <MessagesPage /> },
          { path: "/approvals", element: <ApprovalsPage /> },
          { path: "/settings/branches", element: <BranchesPage /> },
          { path: "/cash", element: <CashBookPage /> },
          { path: "/stock", element: <StockPage /> },
          { path: "/live-rates", element: <LiveRatesPage /> },
          { path: "/settings/audit-log", element: <AuditLogPage /> },
          { path: "/vendors/:id", element: <VendorDetailPage /> },
          { path: "/purchasing/suppliers/:id", element: <SupplierDetailPage /> },
          { path: "/gallery", element: <GalleryPage /> },
          { path: "/sales", element: <SellersPage /> },
          { path: "/sales/:id", element: <SellerDetailPage /> },
          { path: "/reports/profit", element: <ProfitSplitPage /> },
          { path: "/purchasing/suppliers", element: <SuppliersPage /> },
          { path: "/purchasing/gold", element: <GoldPurchasePage /> },
          { path: "/purchasing/silver", element: <SilverPurchasePage /> },
          { path: "/material-outside", element: <MaterialOutsidePage /> },
          { path: "/purchasing/bills", element: <BillsPage /> },
          { path: "/reconciliation", element: <ReconciliationPage /> },
          { path: "/overview", element: <OverviewPage /> },
          { path: "/settings/modules", element: <ModulesPage /> },
          { path: "/settings/opening", element: <OpeningPage /> },
          { path: "/settings/users", element: <UsersPage /> },
          { path: "/purchasing/old-gold", element: <OldGoldPage /> },
          { path: "/purchasing/stones", element: <StonePurchasePage /> },
          { path: "/purchasing/stone-stock", element: <StoneStockPage /> },
          { path: "/ledger/position", element: <PositionPage /> },
          { path: "/ledger/statement", element: <StatementPage /> },
          { path: "/ledger/trade-account", element: <TradeAccountPage /> },
          { path: "/ledger/journal", element: <JournalPage /> },
          { path: "/ledger/accounts", element: <ChartOfAccountsPage /> },
          { path: "/insights", element: <InsightsPage /> },
          { path: "/assistant", element: <AssistantPage /> },
        ],
      },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
