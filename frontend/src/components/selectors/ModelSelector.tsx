// src/components/selectors/ModelSelector.tsx
import { ChevronDown } from "lucide-react";

export type LlmModel = {
  id: string;
  display_name: string;
  provider: string;
  available: boolean;
};

type ModelSelectorProps = {
  selectedModel: string;
  availableModels: LlmModel[];
  onModelChange: (model: string) => void;
};

export default function ModelSelector({
  selectedModel,
  availableModels,
  onModelChange,
}: ModelSelectorProps) {
  if (availableModels.length === 0) {
    return null;
  }

  return (
    <div className="relative">
      <select
        value={selectedModel}
        onChange={(event) => onModelChange(event.target.value)}
        className="appearance-none pl-3 pr-8 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-700 cursor-pointer hover:border-gray-300 focus:outline-none"
      >
        {availableModels.map((model) => (
          <option key={model.id} value={model.id} disabled={!model.available}>
            {model.display_name}
            {!model.available ? " (no key)" : ""}
          </option>
        ))}
      </select>

      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
    </div>
  );
}