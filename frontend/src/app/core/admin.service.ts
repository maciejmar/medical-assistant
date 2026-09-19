import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { Role, SystemStats, UsageReport, User } from '../shared/models';

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

  updateUser(id: number, patch: { is_active?: boolean; role?: Role }): Observable<User> {
    return this.http.patch<User>(`/api/admin/users/${id}`, patch);
  }

  deleteUser(id: number): Observable<void> {
    return this.http.delete<void>(`/api/admin/users/${id}`);
  }
}
