// src/hooks/useLlmModels.ts
import { useEffect, useState } from "react";
import { getLlmModels } from "../services/llmService";
import type { LlmModel } from "../components/selectors/ModelSelector";

export function useLlmModels() {
  const [selectedModel, setSelectedModel] = useState<string>("gpt-4o");
  const [availableModels, setAvailableModels] = useState<LlmModel[]>([]);

  useEffect(() => {
    getLlmModels().then(({ models, default: defaultModel }) => {
      setAvailableModels(models);
      setSelectedModel(defaultModel);
    });
  }, []);

  return {
    selectedModel,
    setSelectedModel,
    availableModels,
  };
}