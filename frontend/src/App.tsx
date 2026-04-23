import React from "react";
import { BrowserRouter as Router, Routes, Route, useSearchParams } from "react-router-dom";
import Home from "./components/Home";
import Chat from "./components/Chat";
import RagQA from "./components/RagQA";

const ChatWrapper: React.FC = () => {
  const [searchParams] = useSearchParams();
  const initialQuery = searchParams.get('query') || '';
  const uploadedTable = searchParams.get('uploaded_table') || undefined;

  return <Chat initialQuery={initialQuery} uploadedTable={uploadedTable} />;
};

const App: React.FC = () => {
  return (
    <Router>
      <div className="App">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/chat" element={<ChatWrapper />} />
          <Route path="/rag-qa" element={<RagQA />} />
          <Route path="/text2sql" element={<Home />} />
        </Routes>
      </div>
    </Router>
  );
};

export default App; 
