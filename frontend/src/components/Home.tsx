import React, { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { BookOpen, Database } from "lucide-react";
import Sidebar from "./Sidebar";
import SearchBar from "./SearchBar";

const NAV_ITEMS = [
  { label: "RAG Q&A",     path: "/rag-qa",   Icon: BookOpen },
  { label: "Text to SQL", path: "/text2sql", Icon: Database },
];

const Home: React.FC = () => {
  const [hasOutput, setHasOutput] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const handleSearch = async (query: string, uploadedTable?: string) => {
    setIsLoading(true);
    console.log("Navigating to chat with query:", query, "uploaded table:", uploadedTable);
    
    // Navigate to chat page with the query and uploaded table as URL parameters
    const params = new URLSearchParams();
    params.append('query', query);
    if (uploadedTable) {
      params.append('uploaded_table', uploadedTable);
    }
    navigate(`/chat?${params.toString()}`);
    
    setIsLoading(false);
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0 }
  };

  return (
    <div className="flex min-h-screen bg-white text-gray-900">
      <Sidebar />
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
                    Text-to-SQL for Analytics and Insights
                    
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
          <SearchBar onSearch={handleSearch} isLoading={isLoading} />

          {/* Mode Navigation Buttons */}
          <div className="flex items-center gap-3 flex-wrap justify-center">
            {NAV_ITEMS.map(({ label, path, Icon }) => {
              const isActive =
                location.pathname === path ||
                (path === "/text2sql" && (location.pathname === "/" || location.pathname === "/chat"));
              return (
                <button
                  key={path}
                  onClick={() => navigate(path)}
                  className={`inline-flex items-center gap-2 px-5 py-2 rounded-full text-sm font-medium border-2 transition-all duration-200 ${
                    isActive
                      ? "text-white border-transparent shadow-md"
                      : "text-gray-600 bg-white border-gray-200 hover:border-blue-300 hover:text-blue-700"
                  }`}
                  style={isActive ? { backgroundColor: "#113D73", borderColor: "#113D73" } : {}}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Home; 
