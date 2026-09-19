import { Routes } from '@angular/router';
import { adminGuard } from './core/admin.guard';
import { doctorGuard, guestGuard } from './core/doctor.guard';

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
    path: 'admin',
    canActivate: [adminGuard],
    loadComponent: () =>
      import('./features/admin-panel/admin-panel.component').then((m) => m.AdminPanelComponent),
  },
  { path: '**', redirectTo: 'dashboard' },
];
