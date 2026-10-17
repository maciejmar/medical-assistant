export type Role = 'ROLE_DOCTOR' | 'ROLE_ADMIN' | 'ROLE_PATIENT';

export const ROLE_LABELS: Record<Role, string> = {
  ROLE_ADMIN: 'Administrator',
  ROLE_DOCTOR: 'Użytkownik',
  ROLE_PATIENT: 'Pacjent',
};

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
  /** Fragment poniżej progu trafności – pokazany, bo żaden lepszy nie został znaleziony. */
  low_relevance?: boolean;
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

export interface PatientChatMessage extends StoredChatMessage {
  conversation_id: string;
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
  patient_accounts: number;
  patients_total: number;
  conversations_total: number;
  knowledge_base_documents: number | null;
}

export interface UserCreateInput {
  email: string;
  full_name: string;
  password: string;
  role: Role;
}

export interface LlmCallSummary {
  id: number;
  timestamp: string;
  user_id: number | null;
  user_email: string | null;
  operation: string;
  model_name: string;
  status: 'ok' | 'error';
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  duration_ms: number;
  preview: string;
}

export interface LlmCallPage {
  total: number;
  items: LlmCallSummary[];
}

export interface LlmMessage {
  role: string;
  content: string;
}

export interface LlmCallDetail extends LlmCallSummary {
  request: LlmMessage[] | { input: string[] };
  response: string;
  error: string | null;
}

export interface PatientAccount {
  user_id: number;
  email: string;
  full_name: string;
  is_active: boolean;
}

export interface Recommendation {
  id: number;
  patient_id: number;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface PatientNotification {
  id: number;
  patient_id: number;
  recipient: string;
  subject: string;
  body: string;
  status: 'sent' | 'failed';
  error: string | null;
  created_at: string;
}

export interface PatientPortal {
  first_name: string;
  last_name: string;
  birth_date: string | null;
  icd_code: string | null;
  diagnosis: string | null;
  doctor_name: string;
  doctor_email: string;
  recommendations: Recommendation[];
  notifications: PatientNotification[];
}
