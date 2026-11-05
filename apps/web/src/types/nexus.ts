export type Role = 'OWNER' | 'ADMIN' | 'MANAGER' | 'MEMBER';
export type Classification = 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED';

export interface Citation {
  citation_key: string;
  document_id: string;
  document_title: string;
  version_number: number;
  page_number: number;
  section_title: string;
  excerpt: string;
  relevance_score: number;
  verified: boolean;
}

export interface AgentRun {
  id: string;
  intent: string;
  status: 'RUNNING' | 'WAITING_APPROVAL' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  current_node: string;
  step_count: number;
  max_steps: number;
  input_query: string;
  final_output?: string;
}
