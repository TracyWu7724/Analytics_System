import React from "react";
import { BrowserRouter as Router, Routes, Route, useSearchParams } from "react-router-dom";
import Home from "./pages/Home";
import ChatPage from "./pages/ChatPage";
import DatabasePage from "./pages/DatabasePage";
import HistoryPage from "./pages/HistoryPage";

const ChatPageWrapper: React.FC = () => {
  const [searchParams] = useSearchParams();
  const initialQuery = searchParams.get("query") || "";
  const llmModel     = searchParams.get("llm_model") || undefined;
  const sessionParam = searchParams.get("session")   || undefined;

  return (
    <ChatPage
      key={sessionParam ?? "new"}
      initialQuery={initialQuery}
      initialLlmModel={llmModel}
      sessionIdProp={sessionParam}
    />
  );
};

const App: React.FC = () => (
  <Router>
    <Routes>
      <Route path="/"          element={<Home />} />
      <Route path="/agent"     element={<ChatPageWrapper />} />
      <Route path="/database"  element={<DatabasePage />} />
      <Route path="/history"   element={<HistoryPage />} />
    </Routes>
  </Router>
);

export default App;
