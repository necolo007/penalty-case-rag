import { Navigate } from "react-router-dom";

/** 已合并至案例知识库；保留文件避免外部书签断裂。 */
export function CasesPage() {
  return <Navigate to="/knowledge?view=queue" replace />;
}
