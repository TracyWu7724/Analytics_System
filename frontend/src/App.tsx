import React from "react";
import { BrowserRouter as Router, Routes, Route, useSearchParams } from "react-router-dom";
import Home from "./components/Home";
import AgentChat from "./components/AgentChat";

const AgentChatWrapper: React.FC = () => {
  const [searchParams] = useSearchParams();
  const initialQuery = searchParams.get('query')    || '';
  const llmModel     = searchParams.get('llm_model') || undefined;
  const sessionParam = searchParams.get('session')   || undefined;

  return (
    <AgentChat
      key={sessionParam ?? 'new'}
      initialQuery={initialQuery}
      initialLlmModel={llmModel}
      sessionIdProp={sessionParam}
    />
  );
};

const App: React.FC = () => {
  return (
    <Router>
      <div className="App">
        <Routes>
          <Route path="/"      element={<Home />} />
          <Route path="/agent" element={<AgentChatWrapper />} />
        </Routes>
      </div>
    </Router>
  );
};

export default App;
