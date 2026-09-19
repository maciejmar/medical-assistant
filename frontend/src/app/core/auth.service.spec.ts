import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { AuthService } from './auth.service';
import { parseSseFrame } from './chat.service';
import { TokenResponse } from '../shared/models';

const RESPONSE: TokenResponse = {
  access_token: 'a.b.c',
  token_type: 'bearer',
  user: {
    id: 1,
    email: 'lekarz@example.com',
    full_name: 'Anna Nowak',
    role: 'ROLE_DOCTOR',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
  },
};

describe('AuthService', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
  });

  it('zapisuje sesję po zalogowaniu i ustawia role', () => {
    const service = TestBed.inject(AuthService);
    const http = TestBed.inject(HttpTestingController);

    expect(service.isAuthenticated()).toBeFalse();
    service.login('lekarz@example.com', 'haslo1234').subscribe();
    http.expectOne('/api/auth/login').flush(RESPONSE);

    expect(service.isAuthenticated()).toBeTrue();
    expect(service.isDoctor()).toBeTrue();
    expect(service.isAdmin()).toBeFalse();
    expect(service.homeRoute()).toBe('/dashboard');
    expect(localStorage.getItem('logoped.token')).toBe('a.b.c');
  });

  it('czyści sesję z wygasłym tokenem', () => {
    localStorage.setItem('logoped.token', 'a.e30.c');
    localStorage.setItem('logoped.user', JSON.stringify(RESPONSE.user));
    const service = TestBed.inject(AuthService);
    expect(service.isAuthenticated()).toBeFalse();
    expect(localStorage.getItem('logoped.token')).toBeNull();
  });
});

describe('parseSseFrame', () => {
  it('parsuje zdarzenie tokenu', () => {
    const event = parseSseFrame('event: token\ndata: {"type":"token","text":"Ala"}');
    expect(event).toEqual({ type: 'token', text: 'Ala' });
  });

  it('zwraca null dla ramki bez danych lub z błędnym JSON', () => {
    expect(parseSseFrame(': keep-alive')).toBeNull();
    expect(parseSseFrame('data: {nie json')).toBeNull();
  });
});
