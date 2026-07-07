import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Settings, ChevronDown } from "lucide-react";
import AppLayout from "../components/layouts/AppLayout";
import SearchBar from "../components/SearchBar";
import { DebugPanel } from "../components/debug/DebugPanel";
import UserMenu from "../components/UserMenu";
import HeroSection from "../components/home/HeroSection";
import { getLlmModels } from "../services/llmService";

const Home: React.FC = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>('gemini-2.5-flash');
  const [availableModels, setAvailableModels] = useState<{ id: string; display_name: string; provider: string; available: boolean }[]>([]);
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    getLlmModels().then(({ models, default: defaultModel }) => {
      setAvailableModels(models);
      setSelectedModel(defaultModel);
    });
  }, []);

  const handleSearch = async (query: string, uploadedTable?: string, llmModel?: string) => {
    setIsLoading(true);
    const params = new URLSearchParams();
    params.append('query', query);
    if (uploadedTable) params.append('uploaded_table', uploadedTable);
    const model = llmModel || selectedModel;
    if (model) params.append('llm_model', model);
    navigate(`/agent?${params.toString()}`);
    setIsLoading(false);
  };

  return (
    <>
      <AppLayout
        headerLeft={
          availableModels.length > 0 ? (
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
          ) : null
        }
        headerRight={
          <>
            <button
              onClick={() => setShowDebugPanel(true)}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              title="Debug"
            >
              <Settings className="w-5 h-5 text-gray-600" />
            </button>
            <UserMenu />
          </>
        }
      >
        <div className="flex items-start justify-center pt-48 pb-12">
          <div className="flex flex-col items-center space-y-8 max-w-7xl w-full px-4">
            <HeroSection />
            <SearchBar onSearch={handleSearch} isLoading={isLoading} selectedModel={selectedModel} />
          </div>
        </div>
      </AppLayout>

      {showDebugPanel && <DebugPanel onClose={() => setShowDebugPanel(false)} />}
    </>
  );
};

export default Home;
