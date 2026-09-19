export type Role = 'ROLE_DOCTOR' | 'ROLE_ADMIN';

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface PatientInput {
  first_name: string;
  last_name: string;
  birth_date: string | null;
  icd_code: string | null;
  diagnosis: string | null;
  description: string | null;
}

export interface Patient extends PatientInput {
  id: number;
  created_at: string;
  updated_at: string;
}

export type NoteSource = 'typed' | 'dictated';

export interface PatientNote {
  id: number;
  patient_id: number;
  content: string;
  source: NoteSource;
  created_at: string;
}

export interface RecentNote {
  note_id: number;
  patient_id: number;
  patient_name: string;
  snippet: string;
  source: NoteSource;
  created_at: string;
}

export interface ChatSource {
  index: number;
  title: string;
  category: string;
  audience: string;
  icd10: string;
  icd11: string;
  snippet: string;
  score: number;
}

export interface TokenCounter {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export type ChatEvent =
  | { type: 'meta'; conversation_id: string }
  | { type: 'status'; stage: string }
  | { type: 'sources'; sources: ChatSource[] }
  | { type: 'token'; text: string }
  | ({ type: 'usage' } & TokenCounter)
  | { type: 'error'; message: string }
  | { type: 'done' };

export interface StoredChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  sources: ChatSource[] | null;
  total_tokens: number;
  created_at: string;
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  message_count: number;
  updated_at: string;
}

export interface UsageBucket extends TokenCounter {
  requests: number;
}

export interface UsageReport {
  days: number;
  totals: UsageBucket;
  by_day: (UsageBucket & { date: string })[];
  by_user: (UsageBucket & { user_id: number | null; label: string })[];
  by_model: (UsageBucket & { model_name: string })[];
  by_operation: (UsageBucket & { operation: string })[];
}

export interface SystemStats {
  users_total: number;
  users_active: number;
  doctors: number;
  admins: number;
  patients_total: number;
  conversations_total: number;
  knowledge_base_documents: number | null;
}
