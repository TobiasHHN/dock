// Routing (Task 2.1). Öffentliche Seiten: Anmeldung und Registrierung; alles andere hinter RequireAuth (AppShell).
import { Navigate, Route, Routes } from "react-router-dom";
import { LoginPage, SignupPage } from "./auth/AuthPages";
import { DocumentPage } from "./documents/DocumentView";
import { Home } from "./home/Home";
import { TableEditorPage } from "./tables/TableEditor";
import { RequireAuth } from "./layout/AppShell";
import { InboxTasksPage } from "./inbox/TaskList";
import { InboxRequestsPage } from "./inbox/MyRequests";
import { RunPage, WorkflowPage } from "./layout/Placeholders";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Home />} />
        <Route path="/documents/:id" element={<DocumentPage />} />
        <Route path="/tables/:id" element={<TableEditorPage />} />
        <Route path="/workflows/:id" element={<WorkflowPage />} />
        <Route path="/runs/:id" element={<RunPage />} />
        <Route path="/inbox/tasks" element={<InboxTasksPage />} />
        <Route path="/inbox/requests" element={<InboxRequestsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
