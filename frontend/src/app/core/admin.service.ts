import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  LlmCallDetail,
  LlmCallPage,
  Role,
  SystemStats,
  UsageReport,
  User,
  UserCreateInput,
} from '../shared/models';

export interface LlmCallFilter {
  operation?: string;
  status_filter?: string;
  limit: number;
  offset: number;
}

@Injectable({ providedIn: 'root' })
export class AdminService {
  private readonly http = inject(HttpClient);

  usage(days: number): Observable<UsageReport> {
    return this.http.get<UsageReport>('/api/admin/usage', { params: { days } });
  }

  stats(): Observable<SystemStats> {
    return this.http.get<SystemStats>('/api/admin/stats');
  }

  users(): Observable<User[]> {
    return this.http.get<User[]>('/api/admin/users');
  }

  createUser(input: UserCreateInput): Observable<User> {
    return this.http.post<User>('/api/admin/users', input);
  }

  updateUser(
    id: number,
    patch: { is_active?: boolean; role?: Role; full_name?: string; password?: string },
  ): Observable<User> {
    return this.http.patch<User>(`/api/admin/users/${id}`, patch);
  }

  deleteUser(id: number): Observable<void> {
    return this.http.delete<void>(`/api/admin/users/${id}`);
  }

  llmCalls(filter: LlmCallFilter): Observable<LlmCallPage> {
    const params: Record<string, string | number> = { limit: filter.limit, offset: filter.offset };
    if (filter.operation) {
      params['operation'] = filter.operation;
    }
    if (filter.status_filter) {
      params['status_filter'] = filter.status_filter;
    }
    return this.http.get<LlmCallPage>('/api/admin/llm-calls', { params });
  }

  llmCall(id: number): Observable<LlmCallDetail> {
    return this.http.get<LlmCallDetail>(`/api/admin/llm-calls/${id}`);
  }
}
