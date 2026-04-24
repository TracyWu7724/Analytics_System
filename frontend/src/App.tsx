import React from "react";
import { BrowserRouter as Router, Routes, Route, useSearchParams } from "react-router-dom";
import Home from "./components/Home";
import AgentChat from "./components/AgentChat";

const AgentChatWrapper: React.FC = () => {
  const [searchParams] = useSearchParams();
  const initialQuery = searchParams.get('query') || '';
  const uploadedTable = searchParams.get('uploaded_table') || undefined;
  const llmModel = searchParams.get('llm_model') || undefined;
  return <AgentChat initialQuery={initialQuery} uploadedTable={uploadedTable} initialLlmModel={llmModel} />;
};

const App: React.FC = () => {
  return (
    <Router>
      <div className="App">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/agent" element={<AgentChatWrapper />} />
        </Routes>
      </div>
    </Router>
  );
};

export default App;
