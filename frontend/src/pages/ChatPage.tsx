import React from 'react';
import AgentChat from '../components/AgentChat';

interface ChatPageProps {
  initialQuery?: string;
  initialLlmModel?: string;
  sessionIdProp?: string;
}

const ChatPage: React.FC<ChatPageProps> = (props) => <AgentChat {...props} />;

export default ChatPage;
