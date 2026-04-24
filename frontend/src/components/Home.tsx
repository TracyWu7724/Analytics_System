import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Settings, ChevronDown } from "lucide-react";
import Sidebar from "./Sidebar";
import SearchBar from "./SearchBar";
import { DebugPanel } from "./DebugPanel";
import UserMenu from "./UserMenu";
import { ApiService } from "../services/api";

const Home: React.FC = () => {
  const [hasOutput, setHasOutput] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
const [selectedModel, setSelectedModel] = useState<string>('gemini-2.5-flash');
  const [availableModels, setAvailableModels] = useState<{ id: string; display_name: string; provider: string; available: boolean }[]>([]);
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    ApiService.getLlmModels().then(({ models, default: defaultModel }) => {
      setAvailableModels(models);
      setSelectedModel(defaultModel);
    });
  }, []);

  const handleSearch = async (query: string, uploadedTable?: string, llmModel?: string) => {
    setIsLoading(true);
    const params = new URLSearchParams();
    params.append('query', query);
    if (uploadedTable) {
      params.append('uploaded_table', uploadedTable);
    }
    const model = llmModel || selectedModel;
    if (model) {
      params.append('llm_model', model);
    }
    navigate(`/agent?${params.toString()}`);
    setIsLoading(false);
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0 }
  };

  return (
    <div className="flex min-h-screen bg-white text-gray-900">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <header className="bg-white px-6 py-4 flex items-center">
          {/* Model selector — left */}
          {availableModels.length > 0 && (
            <div className="relative">
              <select
                value={selectedModel}
                onChange={e => setSelectedModel(e.target.value)}
                className="appearance-none pl-3 pr-8 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-700 cursor-pointer hover:border-gray-300 focus:outline-none"
              >
                {availableModels.map(m => (
                  <option key={m.id} value={m.id} disabled={!m.available}>
                    {m.display_name}{!m.available ? ' (no key)' : ''}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
            </div>
          )}

          {/* Right controls */}
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => setShowDebugPanel(true)}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              title="Debug"
            >
              <Settings className="w-5 h-5 text-gray-600" />
            </button>
            <UserMenu />
          </div>
        </header>

        <div className="flex-1 flex items-start justify-center pt-48 pb-12 overflow-y-auto">
          <div className="flex flex-col items-center space-y-8 max-w-7xl w-full px-4">
            {/* Title Section */}
            <div className="text-center space-y-4">
              <AnimatePresence>
                {!hasOutput && (
                  <>
                    <motion.span
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="shimmer inline-block px-4 py-1.5 mb-6 text-sm md:text-base font-medium tracking-wider border-[3px] rounded-full shadow-glow"
                      style={{
                        borderColor: 'rgba(17, 61, 115, 0.2)',
                        backgroundColor: 'rgba(17, 61, 115, 0.05)'
                      }}
                    >
                      <svg className="w-4 h-4 inline mr-2" fill="#3070A6" viewBox="0 0 24 24">
                        <path d="M12 2L15.09 8.26L22 9L17 14L18.18 21L12 17.77L5.82 21L7 14L2 9L8.91 8.26L12 2Z"/>
                      </svg>
                      AI Powered
                    </motion.span>
                    <motion.h1
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="text-2xl md:text-4xl lg:text-5xl font-bold mb-4 md:mb-6 tracking-tight text-gray-900" style={{ color: '#113D73' }}
                    >
                      Multi-Agent System for Analytics and Insights
                    </motion.h1>
                    <motion.p
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      variants={itemVariants}
                      className="text-base md:text-lg text-gray-600 mb-8 md:mb-10 max-w-2xl mx-auto"
                    >
                    </motion.p>
                  </>
                )}
              </AnimatePresence>
            </div>

            {/* Search Bar */}
            <SearchBar onSearch={handleSearch} isLoading={isLoading} selectedModel={selectedModel} />
          </div>
        </div>
      </div>

      {showDebugPanel && <DebugPanel onClose={() => setShowDebugPanel(false)} />}
    </div>
  );
};

export default Home; 
