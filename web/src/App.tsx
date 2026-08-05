import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import { OverviewPage } from "./pages/OverviewPage";
import { SearchPage } from "./pages/SearchPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { ReviewPage } from "./pages/ReviewPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<OverviewPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="cases" element={<Navigate to="/knowledge?view=queue" replace />} />
        <Route path="cases/:caseId" element={<CaseDetailPage />} />
        <Route path="documents" element={<Navigate to="/knowledge?view=ingest" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
