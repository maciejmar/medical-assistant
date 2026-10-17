import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { PatientPortal } from '../shared/models';

@Injectable({ providedIn: 'root' })
export class PortalService {
  private readonly http = inject(HttpClient);

  me(): Observable<PatientPortal> {
    return this.http.get<PatientPortal>('/api/portal/me');
  }
}
