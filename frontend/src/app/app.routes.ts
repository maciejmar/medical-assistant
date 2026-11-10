import { Routes } from '@angular/router';
import { adminGuard } from './core/admin.guard';
import { doctorGuard, guestGuard, patientGuard } from './core/doctor.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
  {
    path: 'login',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/auth/login.component').then((m) => m.LoginComponent),
  },
  {
    path: 'register',
    canActivate: [guestGuard],
    loadComponent: () =>
      import('./features/auth/register.component').then((m) => m.RegisterComponent),
  },
  {
    path: 'dashboard',
    canActivate: [doctorGuard],
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
  },
  {
    path: 'patients/:id',
    canActivate: [doctorGuard],
    loadComponent: () =>
      import('./features/patient-info/patient-info.component').then((m) => m.PatientInfoComponent),
  },
  {
    path: 'chat',
    canActivate: [doctorGuard],
    loadComponent: () => import('./features/chat/chat.component').then((m) => m.ChatComponent),
  },
  {
    path: 'kalendarz',
    canActivate: [doctorGuard],
    loadComponent: () =>
      import('./features/calendar/doctor-calendar.component').then((m) => m.DoctorCalendarComponent),
  },
  {
    path: 'kredyty',
    canActivate: [doctorGuard],
    loadComponent: () => import('./features/credits/credits.component').then((m) => m.CreditsComponent),
  },
  {
    path: 'admin',
    canActivate: [adminGuard],
    loadComponent: () =>
      import('./features/admin-panel/admin-panel.component').then((m) => m.AdminPanelComponent),
  },
  {
    path: 'admin/llm',
    canActivate: [adminGuard],
    loadComponent: () =>
      import('./features/admin-panel/llm-logs.component').then((m) => m.LlmLogsComponent),
  },
  {
    path: 'admin/testy',
    canActivate: [adminGuard],
    loadComponent: () => import('./features/admin-panel/goldset.component').then((m) => m.GoldsetComponent),
  },
  {
    path: 'admin/knowledge',
    canActivate: [adminGuard],
    loadComponent: () =>
      import('./features/admin-panel/knowledge-base.component').then(
        (m) => m.KnowledgeBaseComponent,
      ),
  },
  {
    path: 'patient',
    canActivate: [patientGuard],
    loadComponent: () =>
      import('./features/patient-portal/patient-home.component').then(
        (m) => m.PatientHomeComponent,
      ),
  },
  { path: '**', redirectTo: 'dashboard' },
];
