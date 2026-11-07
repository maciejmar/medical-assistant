import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export type PlanStatus = 'planned' | 'completed' | 'suspended' | 'infeasible';

export interface PlanStep {
  id: number;
  position: number;
  title: string;
  description: string;
  status: PlanStatus;
  created_at: string;
  updated_at: string;
}

export interface Plan {
  include_in_context: boolean;
  steps: PlanStep[];
}

export type PlanStepInput = Pick<PlanStep, 'title' | 'description' | 'status'>;

@Injectable({ providedIn: 'root' })
export class PlanService {
  private readonly http = inject(HttpClient);

  get(patientId: number): Observable<Plan> {
    return this.http.get<Plan>(this.base(patientId));
  }

  setIncludeInContext(patientId: number, includeInContext: boolean): Observable<{ include_in_context: boolean }> {
    return this.http.put<{ include_in_context: boolean }>(`${this.base(patientId)}/settings`, {
      include_in_context: includeInContext,
    });
  }

  create(patientId: number, input: PlanStepInput): Observable<PlanStep> {
    return this.http.post<PlanStep>(`${this.base(patientId)}/steps`, input);
  }

  update(patientId: number, stepId: number, input: PlanStepInput): Observable<PlanStep> {
    return this.http.put<PlanStep>(`${this.base(patientId)}/steps/${stepId}`, input);
  }

  remove(patientId: number, stepId: number): Observable<void> {
    return this.http.delete<void>(`${this.base(patientId)}/steps/${stepId}`);
  }

  reorder(patientId: number, stepIds: number[]): Observable<PlanStep[]> {
    return this.http.put<PlanStep[]>(`${this.base(patientId)}/order`, { step_ids: stepIds });
  }

  private base(patientId: number): string {
    return `/api/patients/${patientId}/plan`;
  }
}
